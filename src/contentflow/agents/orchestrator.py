"""Orchestrator Agent：LangGraph StateGraph 驅動的 AI 文章生產流程

架構升級：Pipeline 順序呼叫 → Agent StateGraph 條件分支

  research → strategy → write → seo_check
                                     ↓ seo_gate
                     "pass"(≥85) → factcheck
                     "retry"(<85,<3次) → seo_qa → seo_check
                     "force_output"(≥3次) → force_output_marker → factcheck
                                     ↓
                               factcheck → budget_guard → END

品質閘門：SEO ≥ 85 才通過，最多重試 3 輪
預算守衛：LLM 呼叫 ≤ 15，成本 ≤ $2.00
決策日誌：每步驟記錄 step / decision / reason / confidence → AgentDecisionLog
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
from typing_extensions import TypedDict

from loguru import logger

try:
    import agentops
except ImportError:  # pragma: no cover - exercised by environments without AgentOps
    agentops = None

from ..config import settings
from ..llm_client import reset_cost_tracker, get_cost_summary


def _init_agentops() -> bool:
    """初始化 AgentOps（若未設定 API Key 則靜默跳過）。"""
    if agentops is None:
        logger.info("[AgentOps] 套件未安裝，略過可觀測性追蹤")
        return False

    key = settings.agentops_api_key
    if not key:
        return False
    try:
        agentops.init(
            api_key=key,
            default_tags=["contentflow", "langgraph"],
            instrument_llm_calls=True,
        )
        logger.info("[AgentOps] 初始化成功")
        return True
    except Exception as e:
        logger.warning(f"[AgentOps] 初始化失敗（繼續執行）：{e}")
        return False


_agentops_enabled: bool = _init_agentops()
from ..models import ArticleTask, ArticleStatus
from ..project_context import load_project_context, project_uses_pubmed
from .research_agent import run_research_agent
from .strategy_agent import run_strategy_agent
from .writing_agent import run_writing_agent
from .seo_qa_agent import run_seo_qa_agent
from .seo_check_agent import run_seo_check_agent
from .factcheck_agent import run_factcheck_agent
from .budget_guard import budget_guard_node, budget_gate


class PipelineState(TypedDict, total=False):
    """LangGraph StateGraph 狀態定義（用 TypedDict 避免字典鍵分散問題）"""
    task: Any
    project_context: Any
    article_type: str
    use_pubmed: bool
    strategy_context: Optional[dict]
    research_report: Any
    draft: Any
    seo_score: int
    best_seo_score: int
    best_draft: Any
    seo_retry_count: int
    _seo_checks: list
    agent_decisions: list
    total_cost: float
    total_llm_calls: int
    _budget_exceeded: bool
    run_id: str
    article_id: Optional[int]
    primary_kw: str
    secondary_kws: list


SEO_PASS_THRESHOLD = 85
SEO_MAX_RETRIES = 3

# 随流量偵測用的預算上限（不再用於成本模擬）
_LLM_CALL_COST_EST = 0.0  # 改用真實 token 計算，規則不再時使用此常數


# ── 決策日誌 helper ──────────────────────────────────────────────────────

def _append_decision(
    state: dict,
    step: str,
    decision: str,
    reason: str,
    confidence: str = "heuristic",
) -> list:
    decisions = list(state.get("agent_decisions") or [])
    decisions.append({
        "step": step,
        "decision": decision,
        "reason": reason,
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    return decisions


def _persist_decisions(
    article_id: Optional[int],
    run_id: str,
    decisions: list,
) -> None:
    """將決策日誌寫入 DB（best-effort，失敗不影響主流程）"""
    if not decisions:
        return
    try:
        from ..db import SessionLocal
        from ..models.database import AgentDecisionLog
        session = SessionLocal()
        try:
            for d in decisions:
                session.add(AgentDecisionLog(
                    article_id=article_id,
                    run_id=run_id,
                    step=d.get("step", ""),
                    decision=d.get("decision", ""),
                    reason=d.get("reason", ""),
                    confidence=d.get("confidence", ""),
                ))
            session.commit()
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"[Orchestrator] AgentDecisionLog 寫入失敗：{e}")


# ── 節點函式（Nodes）─────────────────────────────────────────────────────

async def research_node(state: dict) -> dict:
    """Research Agent 節點"""
    task = state["task"]
    ctx = state["project_context"]
    logger.info(f"[Graph/research] 啟動研究：{task.title}")
    report = await run_research_agent(
        article_title=task.title,
        search_keywords=task.keywords or [task.title],
        serp_gl=ctx.serp_gl,
        serp_hl=ctx.serp_hl,
        use_pubmed=state.get("use_pubmed", True),
    )
    pubmed_count = sum(len(r.articles) for r in report.pubmed_results)
    decisions = _append_decision(
        state, "research",
        f"研究完成（{pubmed_count} 篇文獻，{len(report.suggested_keywords)} 個建議關鍵字）",
        "Research Agent",
        "data",
    )
    return {
        "research_report": report,
        "agent_decisions": decisions,
        "total_llm_calls": state.get("total_llm_calls", 0) + 1,
    }


async def strategy_node(state: dict) -> dict:
    """Strategy Agent 節點"""
    report = state["research_report"]
    task = state["task"]
    ctx = state["project_context"]
    if state.get("strategy_context"):
        logger.info("[Graph/strategy] 使用人工策略指引")
        decisions = _append_decision(
            state, "strategy", "使用人工提供的策略指引，跳過 LLM", "human override", "rule"
        )
        return {"agent_decisions": decisions}
    logger.info("[Graph/strategy] AI 策略分析")
    strategy_report = await run_strategy_agent(
        keyword=task.keywords[0] if task.keywords else task.title,
        secondary_keywords=task.keywords[1:] if len(task.keywords) > 1 else [],
        serp=report.serp_analysis,
        paa_questions=report.paa_questions,
        project_id=ctx.project_id,
    )
    strategy_context = strategy_report.to_strategy_context()
    decisions = _append_decision(
        state, "strategy",
        (
            f"格式={strategy_context.get('format_type', 'unknown')}，"
            f"寫作架構={strategy_context.get('writing_architecture', '')[:40]}"
        ),
        "根據 SERP 分析",
        "data",
    )
    return {
        "strategy_context": strategy_context,
        "agent_decisions": decisions,
        "total_llm_calls": state.get("total_llm_calls", 0) + 1,
        "total_cost": state.get("total_cost", 0.0) + _LLM_CALL_COST_EST,
    }


async def writing_node(state: dict) -> dict:
    """Writing Agent 節點"""
    report = state["research_report"]
    strategy_context = state.get("strategy_context")
    task = state["task"]
    ctx = state["project_context"]
    logger.info("[Graph/write] AI 撰文")
    task.status = ArticleStatus.WRITING
    primary_kw = task.keywords[0] if task.keywords else task.title
    secondary_kws = task.keywords[1:] if len(task.keywords) > 1 else []
    draft = await run_writing_agent(
        report=report,
        strategy_context=strategy_context,
        target_word_count=task.target_word_count,
        project_id=ctx.project_id,
    )
    decisions = _append_decision(
        state, "writing",
        f"撰文完成（{len(draft.content_markdown)} 字）",
        "根據策略指引三階段生成",
        "data",
    )
    return {
        "draft": draft,
        "primary_kw": primary_kw,
        "secondary_kws": secondary_kws,
        "agent_decisions": decisions,
        "total_llm_calls": state.get("total_llm_calls", 0) + 3,
        "total_cost": state.get("total_cost", 0.0) + _LLM_CALL_COST_EST * 3,
    }


async def seo_check_node(state: dict) -> dict:
    """SEO Check 節點"""
    draft = state["draft"]
    primary_kw = state.get("primary_kw", "")
    secondary_kws = state.get("secondary_kws", [])
    seo_result = run_seo_check_agent(
        draft=draft,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
    )
    score = seo_result["score"]
    prev_score = state.get("seo_score", 0)
    decisions = _append_decision(
        state, "seo_check",
        f"SEO 評分 {score}/100",
        f"前次分數={prev_score}，重試次數={state.get('seo_retry_count', 0)}",
        "rule",
    )
    # 追蹤歷史最佳草稿：若此次分數更高則更新，否則保留前次最佳
    best_score = state.get("best_seo_score", 0)
    if score > best_score:
        return {
            "seo_score": score,
            "best_seo_score": score,
            "best_draft": draft,
            "_seo_checks": seo_result.get("checks", []),
            "agent_decisions": decisions,
        }
    return {
        "seo_score": score,
        "_seo_checks": seo_result.get("checks", []),
        "agent_decisions": decisions,
    }


async def seo_qa_node(state: dict) -> dict:
    """SEO QA 修正節點"""
    # 優先使用歷史最佳草稿作為修正基底，避免從退步版本繼續修改
    draft = state.get("best_draft") or state["draft"]
    report = state["research_report"]
    primary_kw = state.get("primary_kw", "")
    secondary_kws = state.get("secondary_kws", [])
    ctx = state["project_context"]
    checks = state.get("_seo_checks", [])
    failed_checks = [c for c in checks if not c.get("passed", True)]
    retry_count = state.get("seo_retry_count", 0) + 1
    current_calls = state.get("total_llm_calls", 0)
    from .budget_guard import DEFAULT_BUDGET
    if current_calls >= DEFAULT_BUDGET.max_llm_calls_per_article:
        logger.warning(
            f"[Graph/seo_qa] 預算已達 {current_calls} 次呼叫上限，跳過 QA 修正"
        )
        decisions = _append_decision(
            state, f"seo_qa_retry_{retry_count}",
            "跳過 SEO QA：LLM 呼叫次數已達上限",
            f"calls={current_calls} >= {DEFAULT_BUDGET.max_llm_calls_per_article}",
            "rule",
        )
        return {
            "seo_retry_count": retry_count,
            "agent_decisions": decisions,
        }
    logger.info(f"[Graph/seo_qa] 第 {retry_count} 輪修正（{len(failed_checks)} 項失敗）")
    draft = await run_seo_qa_agent(
        draft=draft,
        report=report,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
        failed_checks=failed_checks,
        project_id=ctx.project_id,
    )
    decisions = _append_decision(
        state, f"seo_qa_retry_{retry_count}",
        f"SEO QA 第 {retry_count} 輪修正（修正 {len(failed_checks)} 項）",
        f"score={state.get('seo_score', 0)} < {SEO_PASS_THRESHOLD}",
        "rule",
    )
    return {
        "draft": draft,
        "seo_retry_count": retry_count,
        "agent_decisions": decisions,
        "total_llm_calls": state.get("total_llm_calls", 0) + 1,
        "total_cost": state.get("total_cost", 0.0) + _LLM_CALL_COST_EST,
    }


async def force_output_marker_node(state: dict) -> dict:
    """force_output 路徑：標記草稿需人工審核並繼續"""
    # 使用歷史最佳草稿作為最終輸出，而非最後一次（可能退步的）版本
    best_score = state.get("best_seo_score", state.get("seo_score", 0))
    retries = state.get("seo_retry_count", 0)
    decisions = _append_decision(
        state, "seo_gate",
        f"SEO 分數最高 {best_score} 低於閾值 {SEO_PASS_THRESHOLD}，已達 {retries} 次重試上限，強制輸出",
        "needs_human_review: seo_below_threshold",
        "rule",
    )
    draft = state.get("best_draft") or state.get("draft")
    if draft and hasattr(draft, "status"):
        if draft.status == ArticleStatus.APPROVED:
            draft.status = ArticleStatus.REVIEW_REQUIRED
    return {"agent_decisions": decisions, "draft": draft, "seo_score": best_score}


async def factcheck_node(state: dict) -> dict:
    """FactCheck 節點"""
    draft = state["draft"]
    report = state["research_report"]
    ctx = state["project_context"]
    article_type = state.get("article_type", "educational")
    task = state["task"]
    logger.info("[Graph/factcheck] 事實查核")
    task.status = ArticleStatus.FACT_CHECKING
    draft = await run_factcheck_agent(
        draft=draft,
        report=report,
        project_id=ctx.project_id,
        article_type=article_type,
    )
    review_count = sum(1 for i in (draft.fact_check_items or []) if i.needs_review)
    decisions = _append_decision(
        state, "factcheck",
        f"事實查核完成（需審核 {review_count} 項）",
        "FactCheck Agent：比對 PubMed 文獻",
        "data",
    )
    return {
        "draft": draft,
        "agent_decisions": decisions,
        "total_llm_calls": state.get("total_llm_calls", 0) + 1,
        "total_cost": state.get("total_cost", 0.0) + _LLM_CALL_COST_EST,
    }


# ── 條件邊 ────────────────────────────────────────────────────────────────

def seo_gate(state: dict) -> str:
    """SEO 品質閘門 — "pass" / "retry" / "force_output" """
    score = state.get("seo_score", 0)
    retries = state.get("seo_retry_count", 0)
    if score >= SEO_PASS_THRESHOLD:
        logger.info(f"[Graph/seo_gate] PASS（{score} >= {SEO_PASS_THRESHOLD}）")
        return "pass"
    if retries < SEO_MAX_RETRIES:
        logger.info(f"[Graph/seo_gate] RETRY（{score} < {SEO_PASS_THRESHOLD}，第 {retries + 1} 次）")
        return "retry"
    logger.warning(
        f"[Graph/seo_gate] FORCE OUTPUT（{score} < {SEO_PASS_THRESHOLD}，已重試 {retries} 次）"
    )
    return "force_output"


# ── Graph 建構 ────────────────────────────────────────────────────────────

def _build_graph():
    """建構並編譯 LangGraph StateGraph（LangGraph 未安裝時返回 None）"""
    try:
        from langgraph.graph import StateGraph, END
        graph = StateGraph(PipelineState)
        graph.add_node("research", research_node)
        graph.add_node("strategy", strategy_node)
        graph.add_node("write", writing_node)
        graph.add_node("seo_check", seo_check_node)
        graph.add_node("seo_qa", seo_qa_node)
        graph.add_node("force_output_marker", force_output_marker_node)
        graph.add_node("factcheck", factcheck_node)
        graph.add_node("budget_guard", budget_guard_node)
        graph.set_entry_point("research")
        graph.add_edge("research", "strategy")
        graph.add_edge("strategy", "write")
        graph.add_edge("write", "seo_check")
        graph.add_conditional_edges(
            "seo_check",
            seo_gate,
            {"pass": "factcheck", "retry": "seo_qa", "force_output": "force_output_marker"},
        )
        graph.add_edge("seo_qa", "seo_check")
        graph.add_edge("force_output_marker", "factcheck")
        graph.add_edge("factcheck", "budget_guard")
        graph.add_conditional_edges(
            "budget_guard", budget_gate, {"ok": END, "over_budget": END}
        )
        return graph.compile()
    except ImportError:
        logger.warning("[Orchestrator] LangGraph 未安裝，將使用 fallback pipeline")
        return None
    except Exception as e:
        logger.error(f"[Orchestrator] LangGraph 建構失敗：{e}")
        return None


_agent = None


def _get_agent():
    global _agent
    if _agent is None:
        _agent = _build_graph()
    return _agent


# ── Pipeline Checkpoint helper ──────────────────────────────────────────────

def _checkpoint(
    run_id: str,
    project_id: int | None,
    article_id: int | None,
    current_step: str,
    status: str,
    error: str | None = None,
    llm_calls: int = 0,
    cost: float = 0.0,
    seo_score: int | None = None,
) -> None:
    """將 pipeline 進度寫入 PipelineRun 表（best-effort）。"""
    try:
        from ..db import SessionLocal
        from ..models.database import PipelineRun
        with SessionLocal() as session:
            pr = session.query(PipelineRun).filter(PipelineRun.run_id == run_id).first()
            if pr:
                pr.current_step = current_step
                pr.status = status
                if error:
                    pr.error_message = error[:500]
                if llm_calls:
                    pr.total_llm_calls = llm_calls
                if cost:
                    pr.total_cost = cost
                if seo_score is not None:
                    pr.seo_score = seo_score
                if status in ("completed", "failed"):
                    pr.finished_at = datetime.now(timezone.utc)
            else:
                # 首次 checkpoint（非 strategic_agent 觸發的 run）
                session.add(PipelineRun(
                    run_id=run_id,
                    project_id=project_id,
                    article_id=article_id,
                    trigger="manual",
                    current_step=current_step,
                    status=status,
                    error_message=error[:500] if error else None,
                    total_llm_calls=llm_calls,
                    total_cost=cost,
                    seo_score=seo_score,
                ))
            session.commit()
    except Exception as e:
        logger.warning(f"[Orchestrator] checkpoint 寫入失敗：{e}")


def _schedule_reflection(run_id: str, project_id: int | None, article_id: int | None) -> None:
    """排程 post-pipeline 反思（fire-and-forget，不阻塞 pipeline 回傳）。"""
    import asyncio

    if not project_id:
        return

    async def _do_reflect():
        try:
            from .reflective_agent import reflect_on_pipeline
            await reflect_on_pipeline(run_id, project_id, article_id)
        except Exception as e:
            logger.warning(f"[Orchestrator] post-pipeline 反思失敗：{e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_do_reflect())
        else:
            asyncio.run(_do_reflect())
    except RuntimeError:
        logger.debug("[Orchestrator] 無可用 event loop，跳過反思")


# ── 內部連結建議（best-effort）───────────────────────────────────────────

def _add_internal_links(draft, task, ctx) -> None:
    """取已發布文章清單 → suggest_internal_links → 寫入 draft（失敗靜默）"""
    try:
        from ..db import SessionLocal
        from ..models.database import Article as _ArticleModel
        from .seo_check_agent import suggest_internal_links
        session = SessionLocal()
        try:
            _published = session.query(_ArticleModel).filter(
                _ArticleModel.project_id == ctx.project_id,
                _ArticleModel.status == "published",
                _ArticleModel.publish_url.isnot(None),
                _ArticleModel.publish_url != "",
            ).all()
            _existing = [
                {
                    "title": a.title,
                    "url": a.publish_url,
                    "primary_keyword": a.primary_keyword,
                    "secondary_keywords": a.secondary_keywords or "",
                }
                for a in _published
            ]
            primary_kw = task.keywords[0] if task.keywords else task.title
            if _existing:
                draft.internal_link_suggestions = suggest_internal_links(
                    draft.content_markdown, primary_kw, _existing
                )
                logger.info(
                    f"[Orchestrator] 內部連結建議：{len(draft.internal_link_suggestions)} 條"
                )
        finally:
            session.close()
    except Exception as e:
        logger.warning(f"[Orchestrator] 無法生成內部連結建議：{e}")


# ── 公開介面 ─────────────────────────────────────────────────────────────

async def run_orchestrator(
    task: ArticleTask,
    project_id: int | None = None,
    project_slug: str | None = None,
    article_type: str = "educational",
    strategy_context: dict | None = None,
    use_pubmed: bool | None = None,
    article_id: int | None = None,
    run_id: str | None = None,
) -> ArticleTask:
    """
    端到端文章生產流程（LangGraph StateGraph 版）。

    Args:
        task:              文章任務（含標題、關鍵字等）
        project_id:        專案 DB ID（擇一提供）
        project_slug:      專案 slug（擇一提供）
        article_type:      "educational" | "product"
        strategy_context:  人工策略指引（若為 None 則 AI 自動生成）
        use_pubmed:        是否啟用 PubMed 查詢
        article_id:        對應的 Article DB ID（供決策日誌寫入）

    Returns:
        更新後的 ArticleTask（含 research_report + draft）
    """
    t0 = time.time()
    run_id = run_id or str(uuid.uuid4())
    logger.info(f"[Orchestrator] 啟動：「{task.title}」run_id={run_id[:8]}")

    agent = _get_agent()

    if agent is None:
        raise ImportError(
            "LangGraph 未安裝或建構失敗，無法執行 pipeline。"
            "請執行: pip install langgraph"
        )

    ctx = load_project_context(project_id=project_id, project_slug=project_slug)
    if use_pubmed is None:
        use_pubmed = project_uses_pubmed(ctx)

    # 開始計算真實 token 用量和成本
    reset_cost_tracker()

    task.status = ArticleStatus.RESEARCHING

    initial_state: dict = {
        "task": task,
        "project_context": ctx,
        "article_type": article_type,
        "use_pubmed": use_pubmed,
        "strategy_context": strategy_context,
        "research_report": None,
        "draft": None,
        "seo_score": 0,
        "best_seo_score": 0,
        "best_draft": None,
        "seo_retry_count": 0,
        "_seo_checks": [],
        "agent_decisions": [],
        "total_cost": 0.0,
        "total_llm_calls": 0,
        "_budget_exceeded": False,
        "run_id": run_id,
        "article_id": article_id,
        "primary_kw": task.keywords[0] if task.keywords else task.title,
        "secondary_kws": task.keywords[1:] if len(task.keywords) > 1 else [],
    }

    # Pipeline checkpoint：記錄啟動
    _checkpoint(run_id, project_id, article_id, "research", "running")

    # AgentOps trace（若未設定 API Key 則 session 為 None，不影響主流程）
    _ao_session = None
    if _agentops_enabled:
        try:
            _ao_session = agentops.start_session(
                tags=["contentflow", task.title[:50]],
            )
        except Exception:
            pass

    try:
        final_state: dict = await agent.ainvoke(initial_state)
    except Exception as e:
        logger.exception(f"[Orchestrator] Graph 執行失敗：{e}")
        _checkpoint(run_id, project_id, article_id, "failed", "failed", error=str(e))
        if _ao_session:
            try:
                agentops.end_session("Fail", session=_ao_session)
            except Exception:
                pass
        raise

    draft = final_state.get("draft")
    decisions = final_state.get("agent_decisions", [])

    if draft:
        draft.seo_score = final_state.get("seo_score", 0)
        task.draft = draft
        task.status = draft.status
        _add_internal_links(draft, task, ctx)
        # Hero image 生成（best-effort，失敗不阻塞文章儲存）
        try:
            from .hero_image_agent import run_hero_image_agent
            draft = await run_hero_image_agent(draft, article_type)
            task.draft = draft
            logger.info(f"[Orchestrator] Hero image: {draft.hero_image_url or '未生成'}")
        except Exception as _hi_err:
            logger.warning(f"[Orchestrator] Hero image 生成失敗（不影響文章）：{_hi_err}")
        # 段落配圖 alt text / SEO 檔名（best-effort，失敗不阻塞文章儲存）
        try:
            from .image_agent import run_image_agent
            draft = await run_image_agent(draft)
            task.draft = draft
            logger.info(f"[Orchestrator] 段落配圖 alt text 產生完成（{len(draft.image_prompts)} 項 prompt）")
        except Exception as _img_err:
            logger.warning(f"[Orchestrator] 段落配圖生成失敗（不影響文章）：{_img_err}")
    else:
        task.status = ArticleStatus.ERROR

    task.updated_at = datetime.now(timezone.utc)
    _persist_decisions(article_id, run_id, decisions)

    elapsed = time.time() - t0
    # 取得真實 LLM token 用量和成本（隶 ContextVar 累積）
    usage = get_cost_summary()
    calls = usage["calls"] or final_state.get("total_llm_calls", 0)
    cost = usage["total_cost"] or final_state.get("total_cost", 0.0)

    # Pipeline checkpoint：記錄完成
    _checkpoint(
        run_id, project_id, article_id, "completed",
        "completed" if task.status != ArticleStatus.FAILED else "failed",
        llm_calls=calls, cost=cost,
        seo_score=final_state.get("seo_score"),
    )

    # AgentOps：結束 session
    if _ao_session:
        try:
            ao_status = "Success" if task.status != ArticleStatus.FAILED else "Fail"
            agentops.end_session(ao_status, session=_ao_session)
        except Exception:
            pass

    # Reflective Loop：post-pipeline 反思（best-effort，非同步不阻塞）
    _schedule_reflection(run_id, project_id, article_id)
    review_count = sum(1 for i in (draft.fact_check_items or []) if i.needs_review) if draft else 0

    logger.info(
        f"[Orchestrator] 完成！耗時 {elapsed:.1f}s | "
        f"狀態: {task.status.value} | "
        f"LLM calls: {calls} | cost: ${cost:.4f} | "
        f"prompt_tokens: {usage['prompt_tokens']} out: {usage['completion_tokens']} | "
        f"需審核: {review_count} 項 | 決策日誌: {len(decisions)} 條"
    )
    return task
