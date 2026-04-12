"""Planning Agent：AI 選題決策引擎

依據歸因分析數據自動推薦：新文 / Content Refresh / 合併 / 重寫
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from ..models.database import Article, Keyword
from .analytics_agent import (
    ArticlePerformance,
    AttributionEngine,
    CannibalizationDetector,
    CannibalizationPair,
    RefreshRecommendation,
    RefreshTriggerChecker,
)
from .cluster_agent import ClusterGap, detect_cluster_gaps


# ── 資料結構 ──────────────────────────────────────────────────────────────

@dataclass
class ContentRecommendation:
    """單條內容推薦"""
    action: str                     # new_article / refresh / rewrite / merge / deprioritize
    priority: str                   # high / medium / low
    keyword: str
    reason: str
    article_id: Optional[int] = None    # 對既有文章的動作才有
    article_title: str = ""
    expected_impact: str = ""           # 預估影響（文字描述）


@dataclass
class ContentPlan:
    """整個 project 的內容計畫輸出"""
    project_id: int
    recommendations: list[ContentRecommendation] = field(default_factory=list)
    cannibalization_issues: list[CannibalizationPair] = field(default_factory=list)
    summary: str = ""


# ── 主函式 ────────────────────────────────────────────────────────────────

async def generate_content_plan(
    project_id: int,
    session: Session,
) -> ContentPlan:
    """
    基於數據自動推薦內容計劃

    推薦邏輯（按優先序）：
    1. Cannibalization → 合併建議（高優先）
    2. 排名下滑 > 5 位（高優先 Refresh）
    3. 關鍵字缺口：有搜尋量但無對應文章
    4. P11-P20 近首頁 → Content Refresh（中優先）
    5. CTR 低於位置平均 → 標題優化
    6. 發布 > 6 個月 + P10–P30 → Refresh
    7. 表現差文章 → rewrite / deprioritize（低優先）
    """
    plan = ContentPlan(project_id=project_id)

    # 取得所有文章的映射（供後續查 keyword）
    art_map: dict[int, Article] = {
        a.id: a
        for a in session.query(Article).filter(Article.project_id == project_id).all()
    }

    # ── Cannibalization ──────────────────────────────────────────────────
    detector = CannibalizationDetector(session)
    plan.cannibalization_issues = detector.detect(project_id)

    for pair in plan.cannibalization_issues:
        plan.recommendations.append(ContentRecommendation(
            action="merge",
            priority="high",
            keyword=pair.keyword,
            reason=pair.suggestion,
            article_id=pair.article_ids[0] if pair.article_ids else None,
            article_title=pair.article_titles[0] if pair.article_titles else "",
            expected_impact="消除關鍵字競爭，集中排名信號，預期排名提升 5–10 位",
        ))

    # ── Refresh Triggers ─────────────────────────────────────────────────
    trigger_checker = RefreshTriggerChecker(session)
    refresh_recs: list[RefreshRecommendation] = trigger_checker.check_project(project_id)

    for rr in refresh_recs:
        # 避免與 cannibalization 推薦重複
        already_listed = any(
            r.article_id == rr.article_id
            for r in plan.recommendations
            if r.article_id is not None
        )
        if already_listed:
            continue
        kw = ""
        art = art_map.get(rr.article_id)
        if art:
            kw = art.primary_keyword or ""
        plan.recommendations.append(ContentRecommendation(
            action="refresh",
            priority=rr.priority,
            keyword=kw,
            reason=rr.trigger_reason,
            article_id=rr.article_id,
            article_title=rr.article_title,
            expected_impact="排名有機會進入第一頁",
        ))

    # ── 關鍵字缺口：有搜尋量但無文章 ──────────────────────────────────
    covered_keywords: set[str] = {
        a.primary_keyword.lower()
        for a in art_map.values()
        if a.primary_keyword
    }

    all_keywords = (
        session.query(Keyword)
        .filter(
            Keyword.project_id == project_id,
            Keyword.search_volume > 0,
        )
        .all()
    )

    for kw in all_keywords:
        if kw.keyword.lower() not in covered_keywords:
            priority = "high" if kw.search_volume >= 1000 else "medium"
            plan.recommendations.append(ContentRecommendation(
                action="new_article",
                priority=priority,
                keyword=kw.keyword,
                reason=f"搜尋量 {kw.search_volume:.0f}，尚無對應文章",
                expected_impact=f"預計覆蓋 {kw.search_volume:.0f} 次/月搜尋量",
            ))

    # ── 表現差的文章 → rewrite / deprioritize ──────────────────────────
    engine = AttributionEngine(session)
    performances: list[ArticlePerformance] = engine.get_project_performance(project_id)

    for perf in performances:
        if perf.recommended_action not in ("rewrite", "deprioritize"):
            continue
        already_listed = any(
            r.article_id == perf.article_id
            for r in plan.recommendations
            if r.article_id is not None
        )
        if already_listed:
            continue
        art = art_map.get(perf.article_id)
        plan.recommendations.append(ContentRecommendation(
            action=perf.recommended_action,
            priority="low",
            keyword=perf.target_keyword,
            reason=perf.action_reason,
            article_id=perf.article_id,
            article_title=art.title if art else "",
            expected_impact="提升整體 portfolio 品質",
        ))

    # ── 排序：high → medium → low ─────────────────────────────────────
    priority_order = {"high": 0, "medium": 1, "low": 2}
    plan.recommendations.sort(key=lambda r: priority_order.get(r.priority, 3))

    # ── Cluster Gaps：Topic Cluster 內缺少的關鍵字 ─────────────────────
    try:
        cluster_gaps: list[ClusterGap] = await detect_cluster_gaps(project_id, session)
        for gap in cluster_gaps:
            already_listed = any(
                r.keyword.lower() == gap.missing_keyword.lower()
                for r in plan.recommendations
            )
            if already_listed:
                continue
            plan.recommendations.append(ContentRecommendation(
                action="new_article",
                priority=gap.priority,
                keyword=gap.missing_keyword,
                reason=(
                    f"Topic Cluster「{gap.cluster_pillar}」缺口，"
                    f"搜尋量 {gap.estimated_volume:.0f}"
                ),
                expected_impact=(
                    f"補齊主題群覆蓋，強化「{gap.cluster_pillar}」主題權威"
                ),
            ))
    except Exception as e:
        logger.warning(f"[PlanningAgent] detect_cluster_gaps 失敗（非致命）：{e}")

    # ── 再次排序（cluster gaps 加入後）──────────────────────────────────
    plan.recommendations.sort(key=lambda r: priority_order.get(r.priority, 3))

    # ── 摘要 ─────────────────────────────────────────────────────────────
    n_new = sum(1 for r in plan.recommendations if r.action == "new_article")
    n_refresh = sum(1 for r in plan.recommendations if r.action in ("refresh", "rewrite"))
    n_merge = sum(1 for r in plan.recommendations if r.action == "merge")
    n_deprio = sum(1 for r in plan.recommendations if r.action == "deprioritize")
    plan.summary = (
        f"共 {len(plan.recommendations)} 條推薦："
        f"{n_new} 新文 / {n_refresh} 更新 / {n_merge} 合併 / {n_deprio} 降優先"
    )
    logger.info(f"[PlanningAgent] project={project_id}，{plan.summary}")
    return plan
