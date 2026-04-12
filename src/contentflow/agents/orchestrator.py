"""Orchestrator Agent：自動化文章生產全流程

依序執行：Research → Strategy → Writing → SEO QA → FactCheck → SEO Score
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
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


async def run_orchestrator(
    task: ArticleTask,
    project_id: int | None = None,
    project_slug: str | None = None,
    article_type: str = "educational",
    strategy_context: dict | None = None,
    use_pubmed: bool | None = None,
) -> ArticleTask:
    """
    端到端文章生產流程。

    Args:
        task: 文章任務（含標題、關鍵字等）
        project_id / project_slug: 專案識別
        article_type: "educational" | "product"（影響禁用詞嚴格度）
        strategy_context: 人工策略指引（若為 None 則自動生成）
        use_pubmed: 是否啟用 PubMed 查詢

    Returns:
        更新後的 ArticleTask（含 research_report + draft）
    """
    t0 = time.time()
    logger.info(f"[Orchestrator] 啟動：「{task.title}」（{task.task_id}）")

    ctx = load_project_context(project_id=project_id, project_slug=project_slug)
    use_pubmed = project_uses_pubmed(ctx) if use_pubmed is None else use_pubmed
    task.status = ArticleStatus.RESEARCHING

    # ── Step 1: Research ─────────────────────────────────
    logger.info("[Orchestrator] Step 1/5: 選題研究")
    report = await run_research_agent(
        article_title=task.title,
        search_keywords=task.keywords or [task.title],
        serp_gl=ctx.serp_gl,
        serp_hl=ctx.serp_hl,
        use_pubmed=use_pubmed,
    )
    task.research_report = report
    pubmed_count = sum(len(r.articles) for r in report.pubmed_results)
    logger.info(f"[Orchestrator] 研究完成：{pubmed_count} 篇文獻, {len(report.suggested_keywords)} 個建議關鍵字")

    # ── Step 2: Strategy（若無人工指引）────────────────────
    if not strategy_context:
        logger.info("[Orchestrator] Step 2/5: AI 策略分析")
        strategy_report = await run_strategy_agent(
            keyword=task.keywords[0] if task.keywords else task.title,
            secondary_keywords=task.keywords[1:] if len(task.keywords) > 1 else [],
            serp=report.serp_analysis,
            paa_questions=report.paa_questions,
            project_id=ctx.project_id,
        )
        strategy_context = strategy_report.to_strategy_context()
    else:
        logger.info("[Orchestrator] Step 2/5: 使用人工策略指引")

    # ── Step 3: Writing ──────────────────────────────────
    logger.info("[Orchestrator] Step 3/5: AI 撰文")
    task.status = ArticleStatus.WRITING

    primary_kw = task.keywords[0] if task.keywords else task.title
    secondary_kws = task.keywords[1:] if len(task.keywords) > 1 else []

    draft = await run_writing_agent(
        report=report,
        strategy_context=strategy_context,
        target_word_count=task.target_word_count,
        project_id=ctx.project_id,
    )
    logger.info(f"[Orchestrator] 撰文完成：{len(draft.content_markdown)} 字")

    # ── Step 4: SEO QA ───────────────────────────────────
    logger.info("[Orchestrator] Step 4/5: SEO 品質優化")

    # 4a — 先做 SEO Check，找出失敗項目
    pre_seo = run_seo_check_agent(
        draft=draft,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
    )
    failed_checks = [c for c in pre_seo["checks"] if not c["passed"]]
    logger.info(f"[Orchestrator] SEO 初檢：{pre_seo['score']}/100（{len(failed_checks)} 項待修）")

    # 4b — 把 failed_checks 交給 SEO QA 做針對性修正
    draft = await run_seo_qa_agent(
        draft=draft,
        report=report,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
        failed_checks=failed_checks,
        project_id=ctx.project_id,
    )

    # 4c — 修正後重新評分
    seo_result = run_seo_check_agent(
        draft=draft,
        primary_keyword=primary_kw,
        secondary_keywords=secondary_kws,
    )
    logger.info(
        f"[Orchestrator] SEO 複檢：{pre_seo['score']} → {seo_result['score']}/100"
    )

    # ── 內部連結建議 ─────────────────────────────────────────
    try:
        from ..db import get_db
        from ..models.database import Article as _ArticleModel
        from .seo_check_agent import suggest_internal_links

        _session = get_db()
        _published = _session.query(_ArticleModel).filter(
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
        if _existing:
            draft.internal_link_suggestions = suggest_internal_links(
                draft.content_markdown, primary_kw, _existing
            )
            logger.info(f"[Orchestrator] 內部連結建議：{len(draft.internal_link_suggestions)} 條")
    except Exception as _e:
        logger.warning(f"[Orchestrator] 無法生成內部連結建議：{_e}")

    # ── Step 5: FactCheck ────────────────────────────────
    logger.info("[Orchestrator] Step 5/5: 事實查核")
    task.status = ArticleStatus.FACT_CHECKING
    draft = await run_factcheck_agent(
        draft=draft,
        report=report,
        project_id=ctx.project_id,
        article_type=article_type,
    )

    task.draft = draft
    task.status = draft.status  # APPROVED or REVIEW_REQUIRED
    task.updated_at = datetime.now(timezone.utc)

    elapsed = time.time() - t0
    review_count = sum(1 for i in (draft.fact_check_items or []) if i.needs_review)
    logger.info(
        f"[Orchestrator] 完成！耗時 {elapsed:.1f}s | "
        f"狀態: {task.status.value} | "
        f"需審核: {review_count} 項"
    )
    return task
