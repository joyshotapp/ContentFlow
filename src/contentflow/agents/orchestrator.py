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
from typing import Optional

from loguru import logger

from ..config import settings
from ..models import ArticleTask, ArticleStatus
from ..project_context import load_project_context, project_uses_pubmed
from .research_agent import run_research_agent
from .strategy_agent import run_strategy_agent
from .writing_agent import run_writing_agent
from .seo_qa_agent import run_seo_qa_agent
from .seo_check_agent import run_seo_check_agent
from .factcheck_agent import run_factcheck_agent
from .budget_guard import budget_guard_node, budget_gate


SEO_PASS_THRESHOLD = 85
SEO_MAX_RETRIES = 3

# gpt-4o-mini 每次呼叫的估算成本（USD）；用於 total_cost 累積
_LLM_CALL_COST_EST = 0.08


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
            f"字數={strategy_context.get('target_word_count', 0)}"
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
    return {
        "seo_score": score,
        "_seo_checks": seo_result.get("checks", []),
        "agent_decisions": decisions,
    }


async def seo_qa_node(state: dict) -> dict:
    """SEO QA 修正節點"""
    draft = state["draft"]
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
    score = state.get("seo_score", 0)
    retries = state.get("seo_retry_count", 0)
    decisions = _append_decision(
        state, "seo_gate",
        f"SEO 分數 {score} 低於閾值 {SEO_PASS_THRESHOLD}，已達 {retries} 次重試上限，強制輸出",
        "needs_human_review: seo_below_threshold",
        "rule",
    )
    draft = state.get("draft")
    if draft and hasattr(draft, "status"):
        if draft.status == ArticleStatus.APPROVED:
            draft.status = ArticleStatus.REVIEW_REQUIRED
    return {"agent_decisions": decisions}


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
        graph = StateGraph(dict)
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
) -> ArticleTask:
    """
    端到端文章生產流程（LangGraph StateGraph 版）。

    與舊版保持相同對外介面。若 LangGraph 未安裝，自動 fallback 到線性 pipeline。

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
    run_id = str(uuid.uuid4())
    logger.info(f"[Orchestrator] 啟動：「{task.title}」run_id={run_id[:8]}")

    agent = _get_agent()

    if agent is None:
        return await _run_legacy_pipeline(
            task, project_id, project_slug, article_type, strategy_context, use_pubmed
        )

    ctx = load_project_context(project_id=project_id, project_slug=project_slug)
    if use_pubmed is None:
        use_pubmed = project_uses_pubmed(ctx)

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

    try:
        final_state: dict = await agent.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"[Orchestrator] Graph 執行失敗，fallback 到 legacy pipeline：{e}")
        return await _run_legacy_pipeline(
            task, project_id, project_slug, article_type, strategy_context, use_pubmed
        )

    draft = final_state.get("draft")
    decisions = final_state.get("agent_decisions", [])

    if draft:
        draft.seo_score = final_state.get("seo_score", 0)
        task.draft = draft
        task.status = draft.status
        _add_internal_links(draft, task, ctx)
    else:
        task.status = ArticleStatus.ERROR

    task.updated_at = datetime.now(timezone.utc)
    _persist_decisions(article_id, run_id, decisions)

    elapsed = time.time() - t0
    calls = final_state.get("total_llm_calls", 0)
    cost = final_state.get("total_cost", 0.0)
    review_count = sum(1 for i in (draft.fact_check_items or []) if i.needs_review) if draft else 0

    logger.info(
        f"[Orchestrator] 完成！耗時 {elapsed:.1f}s | "
        f"狀態: {task.status.value} | "
        f"LLM calls: {calls} | cost: ${cost:.3f} | "
        f"需審核: {review_count} 項 | 決策日誌: {len(decisions)} 條"
    )
    return task


# ── Legacy Pipeline（Fallback）──────────────────────────────────────────

async def _run_legacy_pipeline(
    task: ArticleTask,
    project_id: int | None,
    project_slug: str | None,
    article_type: str,
    strategy_context: dict | None,
    use_pubmed: bool | None,
) -> ArticleTask:
    """LangGraph 不可用時的 fallback 線性 pipeline（保留舊版行為）"""
    logger.info("[Orchestrator] 使用 Legacy Pipeline")
    t0 = time.time()

    ctx = load_project_context(project_id=project_id, project_slug=project_slug)
    use_pubmed = project_uses_pubmed(ctx) if use_pubmed is None else use_pubmed
    task.status = ArticleStatus.RESEARCHING

    primary_kw = task.keywords[0] if task.keywords else task.title
    secondary_kws = task.keywords[1:] if len(task.keywords) > 1 else []

    logger.info("[Legacy] Step 1/5: 選題研究")
    report = await run_research_agent(
        article_title=task.title,
        search_keywords=task.keywords or [task.title],
        serp_gl=ctx.serp_gl,
        serp_hl=ctx.serp_hl,
        use_pubmed=use_pubmed,
    )
    task.research_report = report

    if not strategy_context:
        logger.info("[Legacy] Step 2/5: AI 策略分析")
        strategy_report = await run_strategy_agent(
            keyword=primary_kw,
            secondary_keywords=secondary_kws,
            serp=report.serp_analysis,
            paa_questions=report.paa_questions,
            project_id=ctx.project_id,
        )
        strategy_context = strategy_report.to_strategy_context()
    else:
        logger.info("[Legacy] Step 2/5: 使用人工策略指引")

    logger.info("[Legacy] Step 3/5: AI 撰文")
    task.status = ArticleStatus.WRITING
    draft = await run_writing_agent(
        report=report,
        strategy_context=strategy_context,
        target_word_count=task.target_word_count,
        project_id=ctx.project_id,
    )

    logger.info("[Legacy] Step 4/5: SEO 品質優化")
    pre_seo = run_seo_check_agent(
        draft=draft, primary_keyword=primary_kw, secondary_keywords=secondary_kws
    )
    failed_checks = [c for c in pre_seo["checks"] if not c["passed"]]
    logger.info(f"[Legacy] SEO 初檢：{pre_seo['score']}/100（{len(failed_checks)} 項待修）")

    draft = await run_seo_qa_agent(
        draft=draft,
        report=report,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
        failed_checks=failed_checks,
        project_id=ctx.project_id,
    )

    seo_result = run_seo_check_agent(
        draft=draft, primary_keyword=primary_kw, secondary_keywords=secondary_kws
    )
    logger.info(f"[Legacy] SEO 複檢：{pre_seo['score']} → {seo_result['score']}/100")

    _add_internal_links(draft, task, ctx)

    logger.info("[Legacy] Step 5/5: 事實查核")
    task.status = ArticleStatus.FACT_CHECKING
    draft = await run_factcheck_agent(
        draft=draft, report=report,
        project_id=ctx.project_id, article_type=article_type
    )

    task.draft = draft
    task.status = draft.status
    task.updated_at = datetime.now(timezone.utc)

    elapsed = time.time() - t0
    review_count = sum(1 for i in (draft.fact_check_items or []) if i.needs_review)
    logger.info(
        f"[Legacy] 完成！耗時 {elapsed:.1f}s | "
        f"狀態: {task.status.value} | 需審核: {review_count} 項"
    )
    return task
