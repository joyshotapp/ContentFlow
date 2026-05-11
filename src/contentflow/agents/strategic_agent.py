"""Strategic Agent — 強化版 B 的「大腦」層

每日被 Scheduler 喚醒，收集全專案數據，透過 LLM 決策產出結構化「執行計畫」：
- 該產哪些新文章（依日曆排程）
- 該 Refresh 哪些舊文章（依排名數據）
- 哪些文章需要人工審閱提醒

Strategic Agent 不執行 pipeline —— 它只做決策。
Tactical Pipeline（orchestrator.py）負責執行。

架構對應：
  Strategic Agent → 決定「做什麼」
  Tactical Pipeline → 決定「怎麼做」
  Reflective Loop → 決定「學到什麼」
"""

from __future__ import annotations

import json
from datetime import datetime, date, timezone, timedelta
from statistics import median
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from ..config import settings
from ..db import SessionLocal
from ..models.database import (
    Article,
    ActionOutcomeEvaluation,
    ContentCalendar,
    KnowledgeEntry,
    Project,
    ReflectionLog,
    SEORanking,
    StrategicPlan,
    ActionOutcome,
    TopicCluster,
    ClusterMember,
)
from .strategic_controls import (
    _attach_action_controls,
    _can_execute_action,
    _parse_business_goal_profile,
    _score_action_business_utility,
)
from .strategic_context import collect_project_context_impl
from .strategic_execution import execute_strategic_plan_impl, run_strategic_agent_impl
from .strategic_outcomes import _build_action_outcome_stats
from ..project_integrations import (
    build_forgebase_publisher,
    build_native_publish_url,
    build_wordpress_publisher,
    resolve_publish_platform,
)
from ..utils.topic_hygiene import is_viable_topic


def _normalize_url_path(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    path = (parsed.path or url).strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path.lstrip('/')}"
    return path.rstrip("/") or "/"


def _candidate_article_paths(article: Article) -> list[str]:
    paths: list[str] = []
    publish_path = _normalize_url_path(article.publish_url or "")
    if publish_path:
        paths.append(publish_path)
    if article.slug:
        slug = article.slug.strip("/")
        paths.extend([f"/blog/{slug}", f"/{slug}"])
    seen: set[str] = set()
    unique_paths: list[str] = []
    for path in paths:
        if path and path not in seen:
            unique_paths.append(path)
            seen.add(path)
    return unique_paths


def _build_article_gsc_feedback(article: Article, ranking_rows: list[Any]) -> dict[str, Any] | None:
    candidate_paths = _candidate_article_paths(article)
    if not candidate_paths:
        return None

    matched_rows = [
        row for row in ranking_rows
        if _normalize_url_path(getattr(row, "landing_page", "") or "") in candidate_paths
    ]
    if not matched_rows:
        return None

    latest_date = max((row.tracked_date for row in matched_rows if row.tracked_date), default=None)
    if latest_date is None:
        return None

    latest_rows = [row for row in matched_rows if row.tracked_date == latest_date]
    if not latest_rows:
        return None

    impressions = sum(int(row.impressions or 0) for row in latest_rows)
    clicks = sum(int(row.clicks or 0) for row in latest_rows)
    positions = [float(row.position) for row in latest_rows if row.position is not None]
    ctr = round((clicks / impressions), 4) if impressions > 0 else 0.0
    avg_position = round(sum(positions) / len(positions), 1) if positions else None

    low_ctr_queries: list[dict[str, Any]] = []
    for row in sorted(latest_rows, key=lambda item: (item.impressions or 0, -(item.clicks or 0)), reverse=True):
        row_impressions = int(row.impressions or 0)
        row_clicks = int(row.clicks or 0)
        row_ctr = float(row.ctr or 0.0)
        if row_impressions < 20:
            continue
        if row_ctr >= 0.03 and row_clicks > 0:
            continue
        low_ctr_queries.append({
            "query": row.keyword,
            "impressions": row_impressions,
            "clicks": row_clicks,
            "ctr": round(row_ctr, 4),
            "position": round(float(row.position), 1) if row.position is not None else None,
        })

    return {
        "article_id": article.id,
        "title": article.title,
        "publish_path": _normalize_url_path(article.publish_url or ""),
        "tracked_date": latest_date.isoformat(),
        "position": avg_position,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "low_ctr_queries": low_ctr_queries[:5],
    }


def _summarize_gsc_feedback_opportunities(
    articles: list[Article],
    ranking_rows: list[Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    meta_opportunities: list[dict[str, Any]] = []
    query_opportunities: list[dict[str, Any]] = []

    for article in articles:
        feedback = _build_article_gsc_feedback(article, ranking_rows)
        if not feedback:
            continue

        position = feedback.get("position")
        impressions = int(feedback.get("impressions", 0) or 0)
        ctr = float(feedback.get("ctr", 0.0) or 0.0)
        query_gaps = feedback.get("low_ctr_queries", []) or []

        if position is not None and position <= 12 and impressions >= 50 and ctr < 0.03:
            meta_opportunities.append({
                "article_id": feedback["article_id"],
                "title": feedback["title"],
                "position": position,
                "impressions": impressions,
                "clicks": feedback["clicks"],
                "ctr": ctr,
                "gsc_queries": query_gaps[:3],
                "reason": (
                    f"GSC 顯示排名 P{position} 但 CTR 僅 {round(ctr * 100, 2)}%，"
                    f"近 28 天曝光 {impressions}，適合優先優化 meta"
                ),
            })

        if query_gaps:
            query_opportunities.append({
                "article_id": feedback["article_id"],
                "title": feedback["title"],
                "position": position,
                "impressions": impressions,
                "clicks": feedback["clicks"],
                "ctr": ctr,
                "gsc_queries": query_gaps[:3],
                "reason": (
                    "GSC 查詢詞顯示高曝光低 CTR，適合把這些搜尋意圖補進 refresh 內容"
                ),
            })

    meta_opportunities.sort(key=lambda item: (item["impressions"], -item["ctr"]), reverse=True)
    query_opportunities.sort(key=lambda item: (len(item["gsc_queries"]), item["impressions"]), reverse=True)
    return meta_opportunities[:5], query_opportunities[:5]


def _load_article_gsc_feedback(session, article: Article, lookback_days: int = 14) -> dict[str, Any] | None:
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = (
        session.query(
            SEORanking.keyword,
            SEORanking.position,
            SEORanking.impressions,
            SEORanking.clicks,
            SEORanking.ctr,
            SEORanking.landing_page,
            SEORanking.tracked_date,
        )
        .filter(
            SEORanking.project_id == article.project_id,
            SEORanking.tracked_date >= cutoff,
        )
        .all()
    )
    return _build_article_gsc_feedback(article, rows)


def _merge_action_gsc_queries(
    feedback: dict[str, Any] | None,
    action_queries: list[dict[str, Any]] | None,
    *,
    article: Article,
) -> dict[str, Any] | None:
    if not action_queries:
        return feedback
    merged = dict(feedback or {})
    merged.setdefault("article_id", article.id)
    merged.setdefault("title", article.title)
    merged.setdefault("position", None)
    merged.setdefault("impressions", 0)
    merged.setdefault("clicks", 0)
    merged.setdefault("ctr", 0.0)
    merged["low_ctr_queries"] = action_queries[:5]
    return merged


def _build_gsc_feedback_summary(feedback: dict[str, Any] | None) -> str:
    if not feedback:
        return ""

    parts = []
    position = feedback.get("position")
    impressions = int(feedback.get("impressions", 0) or 0)
    clicks = int(feedback.get("clicks", 0) or 0)
    ctr = float(feedback.get("ctr", 0.0) or 0.0)
    if position is not None:
        parts.append(
            f"GSC 最新快照：排名 P{position}、曝光 {impressions}、點擊 {clicks}、CTR {round(ctr * 100, 2)}%"
        )

    low_ctr_queries = feedback.get("low_ctr_queries", []) or []
    if low_ctr_queries:
        query_lines = []
        for item in low_ctr_queries[:3]:
            query_lines.append(
                f"{item.get('query', '')}（曝光 {int(item.get('impressions', 0) or 0)}、CTR {round(float(item.get('ctr', 0.0) or 0.0) * 100, 2)}%）"
            )
        parts.append("高曝光低 CTR 查詢詞：" + "；".join(query_lines))

    return "\n".join(parts)


def _configured_generate_ceiling() -> int:
    candidates: list[int] = []
    for raw_value in (
        getattr(settings, "strategic_daily_generate_limit", None),
        getattr(settings, "max_articles_per_run", None),
    ):
        try:
            if raw_value is None:
                continue
            parsed = int(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            candidates.append(parsed)
    return min(candidates) if candidates else 5


def _clamp_score(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _calculate_generate_capacity(context: dict[str, Any]) -> dict[str, Any]:
    """依 backlog、待審稿壓力與歷史成效決定今日 generate 配額。"""
    backlog = len(context.get("calendar_items", []))
    reviewing = int(context.get("article_stats", {}).get("reviewing", 0) or 0)
    ranking_changes = context.get("ranking_changes_top10", [])
    outcome_stats = context.get("action_outcome_stats", {}) or {}
    action_policy_scores = context.get("action_policy_scores", {}) or {}
    generate_stats = outcome_stats.get("generate", {}) or {}
    generate_policy = action_policy_scores.get("generate", {}) or {}
    ceiling = _configured_generate_ceiling()
    signals: list[str] = []

    if backlog <= 0:
        return {
            "quota": 0,
            "ceiling": ceiling,
            "backlog": 0,
            "reviewing": reviewing,
            "signals": ["no_planned_backlog"],
        }

    if backlog >= max(ceiling * 4, 20):
        quota = ceiling
        signals.append("very_large_backlog")
    elif backlog >= max(ceiling * 2, 8):
        quota = min(ceiling, 4)
        signals.append("large_backlog")
    elif backlog >= 4:
        quota = min(ceiling, 3)
        signals.append("medium_backlog")
    elif backlog >= 2:
        quota = min(ceiling, 2)
        signals.append("small_backlog")
    else:
        quota = 1
        signals.append("single_backlog_item")

    if reviewing >= 8:
        quota = max(0, quota - 2)
        signals.append("review_backlog_critical")
    elif reviewing >= 5:
        quota = max(0, quota - 1)
        signals.append("review_backlog_high")
    elif reviewing >= 3:
        quota = max(0, quota - 1)
        signals.append("review_backlog_building")

    total_generate = int(generate_stats.get("total", 0) or 0)
    improved_generate = int(generate_stats.get("improved", 0) or 0)
    declined_generate = int(generate_stats.get("declined", 0) or 0)
    success_rate = generate_policy.get("weighted_improved_rate")
    decline_rate = generate_policy.get("weighted_declined_rate")
    policy_score = generate_policy.get("policy_score")
    recommendation = generate_policy.get("recommendation")

    if success_rate is None:
        success_rate = improved_generate / total_generate if total_generate else None
    if decline_rate is None:
        decline_rate = declined_generate / total_generate if total_generate else None

    if total_generate >= 4 and decline_rate is not None and success_rate is not None:
        if decline_rate >= 0.5 or (policy_score is not None and policy_score <= -0.2):
            quota = max(0, quota - 2)
            signals.append("generate_decline_rate_high" if decline_rate >= 0.5 else "generate_policy_deprioritize")
        elif decline_rate >= 0.34 or success_rate < 0.25 or (policy_score is not None and policy_score < 0.05):
            quota = max(0, quota - 1)
            signals.append("generate_performance_soften")
        elif (
            recommendation == "scale" or
            (policy_score is not None and policy_score >= 0.35)
        ) and success_rate >= 0.55 and decline_rate <= 0.2 and reviewing <= 2 and backlog > quota:
            quota = min(ceiling, quota + 1)
            signals.append("generate_performance_strong")

    severe_rank_drops = sum(1 for rc in ranking_changes if (rc.get("delta") or 0) >= 8)
    if severe_rank_drops >= 3 and quota > 0:
        quota = max(0, quota - 1)
        signals.append("refresh_pressure_high")

    quota = min(quota, backlog, ceiling)
    return {
        "quota": quota,
        "ceiling": ceiling,
        "backlog": backlog,
        "reviewing": reviewing,
        "generate_outcome_total": total_generate,
        "generate_success_rate": round(success_rate, 3) if success_rate is not None else None,
        "generate_decline_rate": round(decline_rate, 3) if decline_rate is not None else None,
        "generate_policy_score": round(float(policy_score), 3) if policy_score is not None else None,
        "generate_policy_recommendation": recommendation,
        "signals": signals,
    }


def _ensure_generate_capacity(context: dict[str, Any]) -> dict[str, Any]:
    existing = context.get("generate_capacity")
    if isinstance(existing, dict) and "quota" in existing:
        return existing
    capacity = _calculate_generate_capacity(context)
    context["generate_capacity"] = capacity
    return capacity


def _normalize_plan_result(plan_result: dict[str, Any], context_snapshot: dict[str, Any]) -> dict[str, Any]:
    """將 LLM 計畫收斂到系統實際可執行的 generate 配額內。"""
    normalized = dict(plan_result or {})
    capacity = _ensure_generate_capacity(context_snapshot)
    quota = int(capacity.get("quota", 0) or 0)
    allowed_calendar_ids = {
        item.get("calendar_id")
        for item in context_snapshot.get("calendar_items", [])
        if item.get("calendar_id") is not None
    }

    actions = normalized.get("actions", []) or []
    kept_actions: list[dict[str, Any]] = []
    skipped_generate = 0
    generate_count = 0

    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("action") != "generate":
            kept_actions.append(action)
            continue

        calendar_id = action.get("calendar_id")
        if calendar_id not in allowed_calendar_ids:
            skipped_generate += 1
            continue
        if generate_count >= quota:
            skipped_generate += 1
            continue

        kept_actions.append(action)
        generate_count += 1

    if skipped_generate > 0:
        kept_actions.append({
            "action": "alert",
            "message": (
                f"系統自動產能控制已將 generate 收斂為 {quota} 篇，"
                f"本次略過 {skipped_generate} 個超額或無效 generate action"
            ),
            "priority": 0,
        })

    normalized["actions"] = kept_actions
    summary = (normalized.get("summary") or "").strip()
    capacity_note = f"系統動態 generate 配額：{quota} 篇"
    normalized["summary"] = f"{summary}｜{capacity_note}" if summary else capacity_note
    return normalized


def _find_calendar_item(context_snapshot: dict[str, Any], calendar_id: Any) -> dict[str, Any] | None:
    for item in context_snapshot.get("calendar_items", []) or []:
        if item.get("calendar_id") == calendar_id:
            return item
    return None


def _find_ranking_change(context_snapshot: dict[str, Any], keyword: str) -> dict[str, Any] | None:
    for item in context_snapshot.get("ranking_changes_top10", []) or []:
        if item.get("keyword") == keyword:
            return item
    return None


def _find_gsc_meta_opportunity(context_snapshot: dict[str, Any], article_id: Any) -> dict[str, Any] | None:
    for item in context_snapshot.get("gsc_meta_opportunities", []) or []:
        if item.get("article_id") == article_id:
            return item
    return None


def _find_gsc_query_opportunity(
    context_snapshot: dict[str, Any],
    *,
    article_id: Any = None,
    keyword: str = "",
) -> dict[str, Any] | None:
    for item in context_snapshot.get("gsc_query_opportunities", []) or []:
        if article_id is not None and item.get("article_id") == article_id:
            return item
        if keyword and any(query.get("query") == keyword for query in item.get("gsc_queries", []) or []):
            return item
    return None


def _build_expected_outcome(action_type: str) -> str:
    if action_type == "generate":
        return "完成新文章產出並進入審閱或發布流程"
    if action_type == "refresh":
        return "在 28 天內改善排名或補齊高曝光查詢詞的點擊表現"
    if action_type == "optimize_meta":
        return "在不重寫全文的前提下提升 SERP CTR"
    return "提醒管理者處理風險或瓶頸"


def _build_action_evidence(action: dict[str, Any], context_snapshot: dict[str, Any]) -> dict[str, Any]:
    existing = action.get("evidence")
    if isinstance(existing, dict) and existing:
        return existing

    action_type = action.get("action", "")
    evidence: dict[str, Any] = {
        "summary": action.get("reason") or action.get("message") or "系統依據當前快照產生此 action",
        "primary_signals": [],
        "thresholds_triggered": [],
        "counter_signals": [],
        "expected_outcome": _build_expected_outcome(action_type),
        "confidence": "medium",
    }

    if action_type == "generate":
        item = _find_calendar_item(context_snapshot, action.get("calendar_id"))
        capacity = context_snapshot.get("generate_capacity", {}) or {}
        if item:
            evidence["summary"] = f"日曆項目「{item.get('title') or item.get('keywords') or '未命名題目'}」已排程且在有效 backlog 內"
            evidence["primary_signals"].append({"label": "日曆項目", "value": item.get("title") or item.get("keywords") or "—"})
        backlog = capacity.get("backlog")
        quota = capacity.get("quota")
        if backlog is not None and quota is not None:
            evidence["primary_signals"].append({"label": "產能配額", "value": f"backlog {backlog} / quota {quota}"})
        for signal in capacity.get("signals", [])[:3]:
            evidence["thresholds_triggered"].append(signal)
        evidence["confidence"] = "high" if item else "medium"

    elif action_type == "refresh":
        keyword = action.get("keyword", "")
        article_id = action.get("article_id")
        ranking_change = _find_ranking_change(context_snapshot, keyword)
        query_gap = _find_gsc_query_opportunity(context_snapshot, article_id=article_id, keyword=keyword)
        if ranking_change:
            evidence["primary_signals"].append({
                "label": "排名變化",
                "value": f"P{ranking_change.get('previous_position')} -> P{ranking_change.get('current_position')} (delta {ranking_change.get('delta')})",
            })
            if (ranking_change.get("delta") or 0) >= 5:
                evidence["thresholds_triggered"].append("排名下滑 >= 5 位")
        if query_gap:
            queries = query_gap.get("gsc_queries", []) or []
            if queries:
                top_query = queries[0]
                evidence["primary_signals"].append({
                    "label": "GSC 查詢詞缺口",
                    "value": f"{top_query.get('query')} / CTR {round(float(top_query.get('ctr', 0.0) or 0.0) * 100, 2)}% / 曝光 {int(top_query.get('impressions', 0) or 0)}",
                })
                evidence["thresholds_triggered"].append("存在高曝光低 CTR query gap")
        if not ranking_change:
            evidence["counter_signals"].append("未找到明確的排名下滑紀錄")
        evidence["confidence"] = "high" if ranking_change and query_gap else "medium"

    elif action_type == "optimize_meta":
        article_id = action.get("article_id")
        meta_gap = _find_gsc_meta_opportunity(context_snapshot, article_id)
        if meta_gap:
            position = meta_gap.get("position")
            impressions = int(meta_gap.get("impressions", 0) or 0)
            ctr = round(float(meta_gap.get("ctr", 0.0) or 0.0) * 100, 2)
            evidence["summary"] = meta_gap.get("reason") or evidence["summary"]
            evidence["primary_signals"].extend([
                {"label": "平均排名", "value": f"P{position}" if position is not None else "—"},
                {"label": "曝光與 CTR", "value": f"曝光 {impressions} / CTR {ctr}%"},
            ])
            evidence["thresholds_triggered"].extend([
                "排名在 P1-P12 內",
                "CTR 低於預期門檻",
                "曝光量足以支撐 meta 測試",
            ])
            queries = meta_gap.get("gsc_queries", []) or []
            if queries:
                evidence["primary_signals"].append({
                    "label": "代表查詢詞",
                    "value": ", ".join(query.get("query", "") for query in queries[:3] if query.get("query")),
                })
            evidence["confidence"] = "high"
        else:
            evidence["counter_signals"].append("缺少 article-level GSC meta opportunity")

    elif action_type == "alert":
        reviewing = int(context_snapshot.get("article_stats", {}).get("reviewing", 0) or 0)
        if reviewing:
            evidence["primary_signals"].append({"label": "待審閱文章", "value": str(reviewing)})
            if reviewing >= 5:
                evidence["thresholds_triggered"].append("review backlog >= 5")
        if context_snapshot.get("cannibalization_risks"):
            evidence["counter_signals"].append("存在關鍵字自蝕風險，需要人工判斷")
        evidence["confidence"] = "medium"

    if not evidence["primary_signals"]:
        evidence["primary_signals"].append({"label": "系統訊號", "value": evidence["summary"]})

    evidence["thresholds_triggered"] = list(dict.fromkeys(evidence["thresholds_triggered"]))
    evidence["counter_signals"] = list(dict.fromkeys(evidence["counter_signals"]))
    return evidence


def _attach_action_evidence(plan_result: dict[str, Any], context_snapshot: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(plan_result or {})
    enriched_actions: list[dict[str, Any]] = []
    for raw_action in enriched.get("actions", []) or []:
        if not isinstance(raw_action, dict):
            continue
        action = dict(raw_action)
        action["evidence"] = _build_action_evidence(action, context_snapshot)
        enriched_actions.append(action)
    enriched["actions"] = enriched_actions
    return enriched


def _summarize_planning_recommendations(planning_plan: Any) -> list[dict[str, Any]]:
    recommendations = getattr(planning_plan, "recommendations", []) or []
    summary: list[dict[str, Any]] = []
    for rec in recommendations[:10]:
        summary.append({
            "action": getattr(rec, "action", ""),
            "priority": getattr(rec, "priority", ""),
            "keyword": getattr(rec, "keyword", ""),
            "article_id": getattr(rec, "article_id", None),
            "reason": getattr(rec, "reason", ""),
        })
    return summary


# ── 數據收集 ──────────────────────────────────────────────────

def _detect_seasonal_opportunities(
    session,
    project_id: int,
    existing_kws: set | None = None,
) -> list[dict]:
    """
    偵測季節性高峰提前佈局機會。

    條件：
    - trend_direction == "up"（熱度上升中）
    - trends_score >= 60（有足夠搜尋量訊號）
    - 尚未有 published/planned/draft 文章對應此關鍵字

    提前佈局邏輯：文章從開始製作到上線平均需要 4-6 週，因此需提前規劃。

    Returns:
        list of {keyword, trends_score, note}
    """
    from ..models.database import Keyword, Article as _Article

    if existing_kws is None:
        existing_kws = {
            kw[0] for kw in (
                session.query(_Article.primary_keyword)
                .filter(
                    _Article.project_id == project_id,
                    _Article.status.in_(["published", "planned", "draft", "review_required", "approved"]),
                    _Article.primary_keyword.isnot(None),
                )
                .all()
            )
            if kw[0]
        }

    rising_keywords = (
        session.query(Keyword)
        .filter(
            Keyword.project_id == project_id,
            Keyword.trend_direction == "up",
            Keyword.trends_score >= 60,
        )
        .order_by(Keyword.trends_score.desc())
        .limit(20)
        .all()
    )

    opportunities = []
    for kw_obj in rising_keywords:
        if kw_obj.keyword in existing_kws:
            continue
        # trends_score 越高越緊迫（≥ 80 = 高優先）
        urgency = "高優先" if (kw_obj.trends_score or 0) >= 80 else "建議佈局"
        opportunities.append({
            "keyword": kw_obj.keyword,
            "trends_score": kw_obj.trends_score,
            "search_volume": kw_obj.search_volume,
            "note": f"季節高峰提前佈局（{urgency}，熱度分數 {kw_obj.trends_score}，建議提前 4–6 週產出文章）",
        })

    return opportunities[:10]


def _collect_project_context(project_id: int, session) -> dict[str, Any]:
    """收集 Strategic Agent 做決策所需的全部數據快照。"""
    return collect_project_context_impl(
        project_id,
        session,
        parse_business_goal_profile=_parse_business_goal_profile,
        is_viable_topic=is_viable_topic,
        normalize_url_path=_normalize_url_path,
        candidate_article_paths=_candidate_article_paths,
        summarize_gsc_feedback_opportunities=_summarize_gsc_feedback_opportunities,
        build_action_outcome_stats=_build_action_outcome_stats,
        detect_seasonal_opportunities=_detect_seasonal_opportunities,
        calculate_generate_capacity=_calculate_generate_capacity,
        logger=logger,
    )


# ── LLM 決策 ─────────────────────────────────────────────────

STRATEGIC_SYSTEM_PROMPT_TEMPLATE = """你是 ContentFlow 的 Strategic Agent，負責決定「今天要做什麼」。

你不執行任何操作 — 你只輸出一份結構化的**執行計畫**，由 Tactical Pipeline 去執行。

## 你可以規劃的 action 類型：
1. **generate** — 啟動 AI Pipeline 產出新文章
   - 需指定 calendar_id（從待執行日曆中選）
    - 今日系統自動核定上限為 __GENERATE_LIMIT__ 篇，不可超出
2. **refresh** — 對已發布文章觸發 Content Refresh
   - 需指定 article_id + 原因
   - 優先處理排名 4-20 的文章（§8.3 群組 B/C，ROI 最高）
3. **alert** — 標記需要人工注意的事項
   - 排名大幅下滑、未收錄、待審閱文章堆積等
4. **optimize_meta** — 重寫指定文章的 meta title / description
   - 需指定 article_id
   - 適用情境：CTR 明顯低於同排名水準（CTR < 2% 且排名 B/C 群）

## 決策原則：
- 排名 B 群（4-10）的 Refresh ROI 最高，優先安排
- 排名 C 群（11-20）是重點優化目標
- 新文章優先產出日曆上已排程且已到期的
- generate 必須服從系統動態產能配額 __GENERATE_LIMIT__，不可自行放大
- refresh 仍控制在 2 個以內
- 如果有很多待審閱文章（≥5），提醒人工優先處理
- 參考上次執行摘要，避免重複工作
- `planning_recommendations` 是規則引擎算出的 deterministic 建議，優先參考
- `gsc_meta_opportunities` 是 GSC 已確認的高曝光低 CTR 文章，優先安排 optimize_meta
- `gsc_query_opportunities` 是 GSC 已確認的 query-level 缺口；若安排 refresh，優先參考其中的 `gsc_queries`
- 如果 `cannibalization_risks` 不為空，發送 alert 告知哪些關鍵字有自蝕風險
- 如果 `cluster_gaps` 不為空，優先將高价値缺口關鍵字納入 generate 計劃- 如果 `keyword_trends` 中有 direction="up" 的關鍵字且尚無文章，納入 generate 候選
- 如果 `seasonal_opportunities` 不為空，**立即將高優先項目納入 generate 計畫**，並在 reason 中標注「季節高峰提前佈局」；urgency="高優先" 的項目須排在其他 generate 之前
## 因果學習（重要）：
- 數據中包含 `action_outcome_history`，記錄過去動作的實際成效
- `action_outcome_stats` 顯示各類動作（generate/refresh）的成功率統計
- `action_policy_scores` 是 confidence / traffic / rank 變化加權後，並相對於同專案控制基準修正的 deterministic policy score
- **優先安排成功率高的動作類型**
- 如果 `action_policy_scores` 的 recommendation = `scale`，可提高該 action 類型優先級
- 如果 `action_policy_scores` 的 recommendation = `deprioritize`，降低該 action 類型優先級並在 summary 說明
- 如果某類動作 declined 比例高，降低其優先級並在 summary 中說明原因
- 如果沒有 outcome 數據（系統初期），按照基本規則決策即可

## 輸出格式（嚴格 JSON）：
```json
{
  "actions": [
    {"action": "generate", "calendar_id": 7, "reason": "日曆排程已到期", "priority": 1},
            {"action": "refresh", "article_id": 3, "reason": "排名從 8 掉到 15，屬於 B→C 群", "priority": 2, "gsc_queries": [{"query": "膝蓋骨刺症狀", "impressions": 120, "ctr": 0.011}]},
    {"action": "alert", "message": "有 6 篇文章待審閱，建議今日優先處理", "priority": 0},
        {"action": "optimize_meta", "article_id": 5, "reason": "CTR 1.2% 但排名 P5，活化 meta 可提升點擊率", "priority": 3, "gsc_queries": [{"query": "膝蓋骨刺復健", "impressions": 88, "ctr": 0.009}]}
  ],
  "summary": "今日計畫：產出 1 篇新文、Refresh 1 篇排名下滑文章。6 篇待審閱需儘快處理。",
  "outcome_insight": "過去 refresh 動作成功率 75%，generate 成功率 60%，本次優先安排 refresh。"
}
```

只輸出 JSON，不要其他文字。"""


def _build_strategic_system_prompt(generate_limit: int) -> str:
    return STRATEGIC_SYSTEM_PROMPT_TEMPLATE.replace(
        "__GENERATE_LIMIT__",
        str(generate_limit),
    )


async def _call_strategic_llm(context_snapshot: dict) -> dict:
    """呼叫 LLM 產出執行計畫，自帶 provider failover。"""
    from ..llm_client import achat

    capacity = _ensure_generate_capacity(context_snapshot)
    generate_limit = int(capacity.get("quota", 0) or 0)
    user_msg = f"以下是今日的專案數據，請產出今日執行計畫：\n\n```json\n{json.dumps(context_snapshot, ensure_ascii=False, indent=2)}\n```"

    content = await achat(
        messages=[
            {"role": "system", "content": _build_strategic_system_prompt(generate_limit)},
            {"role": "user", "content": user_msg},
        ],
        model=settings.llm_lite_model or "gpt-4o-mini",
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return json.loads(content or "{}")


# ── 公開介面 ──────────────────────────────────────────────────

async def run_strategic_agent(project_id: int) -> StrategicPlan:
    """
    Strategic Agent 主入口：收集數據 → LLM 決策 → 寫入 StrategicPlan。

    Returns:
        StrategicPlan ORM 實例（已 commit 到 DB）
    """
    return await run_strategic_agent_impl(
        project_id,
        session_factory=SessionLocal,
        logger=logger,
        collect_project_context=_collect_project_context,
        summarize_planning_recommendations=_summarize_planning_recommendations,
        call_strategic_llm=_call_strategic_llm,
        fallback_plan=_fallback_plan,
        normalize_plan_result=_normalize_plan_result,
        attach_action_evidence=_attach_action_evidence,
        attach_action_controls=_attach_action_controls,
    )


def _fallback_plan(context: dict) -> dict:
    """LLM 不可用時的 fallback：純規則產出計畫。"""
    actions = []
    capacity = _ensure_generate_capacity(context)
    generate_limit = int(capacity.get("quota", 0) or 0)
    calendar_items = context.get("calendar_items", [])

    # 到期日曆 → generate
    for item in calendar_items[:generate_limit]:
        actions.append({
            "action": "generate",
            "calendar_id": item["calendar_id"],
            "reason": "日曆排程已到期（fallback 規則）",
            "priority": 1,
        })

    if len(calendar_items) > generate_limit:
        actions.append({
            "action": "alert",
            "message": (
                f"仍有 {len(calendar_items)} 筆待產出日曆項目，"
                f"今日系統自動核定僅產出 {generate_limit} 筆"
            ),
            "priority": 0,
        })

    for rec in context.get("planning_recommendations", []):
        if rec.get("action") == "refresh" and rec.get("article_id"):
            actions.append({
                "action": "refresh",
                "article_id": rec["article_id"],
                "reason": rec.get("reason", "Planning Agent refresh 建議"),
                "priority": 2,
            })
        elif rec.get("action") == "merge" and rec.get("keyword"):
            actions.append({
                "action": "alert",
                "message": f"Planning Agent 建議處理關鍵字自蝕：{rec['keyword']}",
                "priority": 0,
            })

    # 排名下滑 > 5 位 → refresh
    for rc in context.get("ranking_changes_top10", []):
        if rc["delta"] >= 5:
            actions.append({
                "action": "refresh",
                "keyword": rc["keyword"],
                "reason": f"排名下滑 {rc['delta']} 位（{rc['previous_position']} → {rc['current_position']}）",
                "priority": 2,
            })

    for item in context.get("gsc_query_opportunities", [])[:2]:
        actions.append({
            "action": "refresh",
            "article_id": item["article_id"],
            "reason": item.get("reason", "GSC 查詢詞缺口補強"),
            "priority": 2,
            "gsc_queries": item.get("gsc_queries", []),
        })

    for item in context.get("gsc_meta_opportunities", [])[:2]:
        actions.append({
            "action": "optimize_meta",
            "article_id": item["article_id"],
            "reason": item.get("reason", "GSC 高曝光低 CTR"),
            "priority": 3,
            "gsc_queries": item.get("gsc_queries", []),
        })
    # 待審閱堆積 → alert
    reviewing = context.get("article_stats", {}).get("reviewing", 0)
    if reviewing >= 5:
        actions.append({
            "action": "alert",
            "message": f"有 {reviewing} 篇文章待審閱，請優先處理",
            "priority": 0,
        })
    return {
        "actions": actions,
        "summary": f"Fallback 規則計畫：{len(actions)} 項 action",
    }


# ── 計畫執行器（被 Scheduler 呼叫）──────────────────────────

async def execute_strategic_plan(plan_id: int) -> None:
    """依序執行 StrategicPlan 中的 actions。"""
    await execute_strategic_plan_impl(
        plan_id,
        session_factory=SessionLocal,
        logger=logger,
        can_execute_action=_can_execute_action,
        execute_generate=_execute_generate,
        execute_refresh=_execute_refresh,
        execute_alert=_execute_alert,
        execute_optimize_meta=_execute_optimize_meta,
        execute_inject_internal_links=_execute_inject_internal_links,
    )


async def _submit_url_to_indexing(url: str) -> None:
    """Submit URL to Google Indexing API to accelerate Googlebot crawl (best-effort)."""
    try:
        import httpx
        svc_file = settings.google_service_account_file
        if not svc_file:
            return
        import google.oauth2.service_account as _sa
        import google.auth.transport.requests as _gtr
        creds = _sa.Credentials.from_service_account_file(
            svc_file, scopes=["https://www.googleapis.com/auth/indexing"]
        )
        creds.refresh(_gtr.Request())
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={"Authorization": f"Bearer {creds.token}", "Content-Type": "application/json"},
                json={"url": url, "type": "URL_UPDATED"},
            )
            if resp.status_code == 200:
                logger.info(f"[IndexingAPI] ✅ 提交成功：{url}")
            else:
                logger.warning(f"[IndexingAPI] 失敗 {resp.status_code}：{resp.text[:200]}")
    except Exception as e:
        logger.debug(f"[IndexingAPI] 略過（non-fatal）：{e}")


async def _execute_generate(action: dict, project_id: int, *, plan_id: int | None = None) -> None:
    """執行 generate action：從日曆條目啟動 pipeline。"""
    import uuid
    from .orchestrator import run_orchestrator
    from ..models import ArticleTask
    from ..models.database import ContentCalendar, Article, PipelineRun

    calendar_id = action.get("calendar_id")
    if not calendar_id:
        logger.warning("[StrategicExecutor/generate] 缺少 calendar_id")
        return

    with SessionLocal() as session:
        cal = session.get(ContentCalendar, calendar_id)
        if not cal:
            logger.warning(f"[StrategicExecutor/generate] Calendar #{calendar_id} 不存在")
            return
        if cal.status != "planned":
            logger.info(f"[StrategicExecutor/generate] Calendar #{calendar_id} 狀態={cal.status}，跳過")
            return

        # 建立或取得對應 Article
        if cal.article_id:
            article = session.get(Article, cal.article_id)
        else:
            article = Article(
                project_id=project_id,
                title=cal.title,
                primary_keyword=cal.keywords.split(",")[0].strip() if cal.keywords else cal.title,
                secondary_keywords=cal.keywords,
                status="planned",
                article_type=cal.article_type or "educational",
            )
            session.add(article)
            session.flush()
            cal.article_id = article.id
            session.commit()

        art_id = article.id
        art_title = article.title
        art_kw = article.primary_keyword or article.title

        # 記錄 PipelineRun
        run_id = str(uuid.uuid4())
        pipeline_run = PipelineRun(
            run_id=run_id,
            project_id=project_id,
            article_id=art_id,
            calendar_id=calendar_id,
            strategic_plan_id=plan_id,
            trigger="strategic_agent",
            current_step="pending",
            status="running",
        )
        session.add(pipeline_run)
        session.commit()
        pr_id = pipeline_run.id

    task = ArticleTask(
        task_id=run_id,
        title=art_title,
        keywords=[art_kw],
        target_word_count=1200,
    )
    logger.info(f"[StrategicExecutor/generate] 啟動 pipeline：'{art_title}' run_id={run_id[:8]}")

    try:
        result = await run_orchestrator(task, project_id=project_id, article_id=art_id, run_id=run_id)

        # 回寫結果
        pub_url: str | None = None
        _pub_platform: str | None = None
        _pub_article_id: int = art_id
        _pub_draft = None
        _pub_slug: str = ""
        with SessionLocal() as session:
            article = session.get(Article, art_id)
            project = session.get(Project, project_id)
            if article and result.draft:
                article.draft_content = result.draft.content_markdown
                article.meta_title = result.draft.meta_title
                article.meta_description = result.draft.meta_description
                article.slug = result.draft.slug
                article.faq_schema_json = result.draft.faq_schema_json
                article.article_schema_json = result.draft.article_schema_json
                article.seo_score = result.draft.seo_score or None
                # 持久化內部連結建議
                if result.draft.internal_link_suggestions:
                    import json as _json
                    article.suggested_internal_links = _json.dumps(
                        result.draft.internal_link_suggestions, ensure_ascii=False
                    )
                # Slug 唯一性保障：避免多篇文章搶佔同一 URL
                proposed_slug = article.slug
                if proposed_slug:
                    suffix = 2
                    candidate = proposed_slug
                    while session.query(Article).filter(
                        Article.slug == candidate, Article.id != art_id
                    ).first():
                        candidate = f"{proposed_slug}-{suffix}"
                        suffix += 1
                    article.slug = candidate
                # 發布政策（L2-1）：
                #   auto_publish_enabled=True 且 seo_score >= min_score → 立即發布
                #     - 原生 blog（無 WordPress/ForgeBase 設定）：DB 直接標記 published
                #     - WordPress：create post as "publish" 直接上線
                #     - ForgeBase：create brief → page → publish 三步驟
                #   有排程時間 → approved（等待 04:05 排程 job）
                #   否則 → review_required（人工審核）
                now_utc = datetime.now(timezone.utc)
                auto_pub = (
                    project
                    and project.auto_publish_enabled
                    and (article.seo_score or 0) >= (project.auto_publish_min_score or 85)
                )
                if auto_pub and article.slug:
                    _pub_platform = resolve_publish_platform(
                        db=session,
                        project_id=project.id if project else article.project_id,
                    )
                    _pub_article_id = art_id
                    _pub_draft = result.draft
                    _pub_slug = article.slug
                    _pub_project_id = project.id if project else article.project_id
                elif auto_pub:
                    # slug 尚未生成（罕見），fallback 到排程器
                    article.status = "approved"
                    article.scheduled_publish_at = article.scheduled_publish_at or now_utc
                    _pub_platform = None
                elif article.scheduled_publish_at:
                    article.status = "approved"
                    _pub_platform = None
                else:
                    article.status = result.status or "review_required"
                    _pub_platform = None
                article.updated_at = now_utc

            cal = session.get(ContentCalendar, calendar_id)
            if cal:
                cal.status = "completed"

            pr = session.get(PipelineRun, pr_id)
            if pr:
                pr.current_step = "completed"
                pr.status = "completed"
                pr.seo_score = result.draft.seo_score if result.draft else None
                pr.finished_at = datetime.now(timezone.utc)

            session.commit()

        # 實際執行自動發布（session 已 commit 後再執行，避免 DB 鎖定）
        if _pub_platform == "native":
            # 原生 FastAPI blog：DB 直接標記已發布即可（/blog/{slug} 從 DB 讀取）
            pub_url = build_native_publish_url(_pub_slug, project_id=_pub_project_id)
            with SessionLocal() as s2:
                _art = s2.get(Article, _pub_article_id)
                if _art:
                    _art.status = "published"
                    _art.published_at = now_utc
                    _art.publish_date = now_utc.strftime("%Y-%m-%d")
                    _art.publish_url = pub_url
                    s2.commit()
            logger.info(f"[StrategicExecutor] 原生發布完成：{pub_url}")

        elif _pub_platform == "wordpress":
            try:
                from contentflow.models.schemas import ArticleDraft as _Draft
                wp_draft = _Draft(
                    title=_pub_draft.title,
                    meta_title=_pub_draft.meta_title or _pub_draft.title,
                    meta_description=_pub_draft.meta_description or "",
                    content_markdown=_pub_draft.content_markdown,
                    slug=_pub_draft.slug or "",
                    faq_schema_json=_pub_draft.faq_schema_json or "",
                    article_schema_json=_pub_draft.article_schema_json or "",
                )
                wp_pub = build_wordpress_publisher(project_id=_pub_project_id)
                # 直接以 publish 狀態建立（不走 draft → publish 兩步）
                wp_result = await wp_pub._create_post(wp_draft, status="publish")
                if wp_result.success:
                    pub_url = wp_result.publish_url or ""
                    with SessionLocal() as s2:
                        _art = s2.get(Article, _pub_article_id)
                        if _art:
                            _art.status = "published"
                            _art.published_at = now_utc
                            _art.publish_date = now_utc.strftime("%Y-%m-%d")
                            _art.publish_url = pub_url
                            _art.wp_post_id = str(wp_result.post_id or "")
                            s2.commit()
                    logger.info(f"[StrategicExecutor] WordPress 發布完成：{pub_url}")
                else:
                    logger.error(f"[StrategicExecutor] WordPress 發布失敗：{wp_result.error}")
                    with SessionLocal() as s2:
                        _art = s2.get(Article, _pub_article_id)
                        if _art:
                            _art.status = "review_required"
                            s2.commit()
            except Exception as _wp_err:
                logger.error(f"[StrategicExecutor] WordPress 自動發布異常：{_wp_err}")
                with SessionLocal() as s2:
                    _art = s2.get(Article, _pub_article_id)
                    if _art:
                        _art.status = "review_required"
                        s2.commit()

        elif _pub_platform == "forgebase":
            try:
                fb_pub = build_forgebase_publisher(project_id=_pub_project_id)
                # Step 1+2: create brief → page（草稿）
                fb_result = await fb_pub.publish_draft(
                    _pub_draft, primary_keyword=_pub_draft.title
                )
                if fb_result.success and fb_result.post_id:
                    # Step 3: 立即發布
                    fb_published = await fb_pub.publish_page(fb_result.post_id)
                    pub_url = (fb_published.publish_url or "") if fb_published.success else ""
                    with SessionLocal() as s2:
                        _art = s2.get(Article, _pub_article_id)
                        if _art:
                            _art.status = "published" if fb_published.success else "review_required"
                            if fb_published.success:
                                _art.published_at = now_utc
                                _art.publish_date = now_utc.strftime("%Y-%m-%d")
                                _art.publish_url = pub_url
                                _art.forgebase_id = fb_result.post_id
                            s2.commit()
                    if fb_published.success:
                        logger.info(f"[StrategicExecutor] ForgeBase 發布完成：{pub_url}")
                    else:
                        logger.error(f"[StrategicExecutor] ForgeBase publish_page 失敗：{fb_published.error}")
                else:
                    logger.error(f"[StrategicExecutor] ForgeBase publish_draft 失敗：{fb_result.error}")
                    with SessionLocal() as s2:
                        _art = s2.get(Article, _pub_article_id)
                        if _art:
                            _art.status = "review_required"
                            s2.commit()
            except Exception as _fb_err:
                logger.error(f"[StrategicExecutor] ForgeBase 自動發布異常：{_fb_err}")
                with SessionLocal() as s2:
                    _art = s2.get(Article, _pub_article_id)
                    if _art:
                        _art.status = "review_required"
                        s2.commit()

        # Google Indexing API：加速 Googlebot 首次收錄（best-effort）
        if pub_url:
            try:
                import asyncio as _asyncio
                _asyncio.create_task(_submit_url_to_indexing(pub_url))
            except RuntimeError:
                # 沒有 running loop（測試環境）：改用 ensure_future
                import asyncio as _asyncio
                _asyncio.ensure_future(_submit_url_to_indexing(pub_url))

        # 記錄 ActionOutcome（因果追蹤基線）
        from ..scheduler import record_action_outcome
        record_action_outcome(
            project_id=project_id,
            article_id=art_id,
            run_id=run_id,
            strategic_plan_id=plan_id,
            action_type="generate",
            primary_keyword=art_kw,
        )

        logger.info(f"[StrategicExecutor/generate] ✅ '{art_title}' 完成")
    except Exception as e:
        with SessionLocal() as session:
            pr = session.get(PipelineRun, pr_id)
            if pr:
                pr.status = "failed"
                pr.error_message = str(e)[:500]
                pr.finished_at = datetime.now(timezone.utc)
                session.commit()
        raise


async def _execute_refresh(action: dict, project_id: int, *, plan_id: int | None = None) -> None:
    """執行 refresh action：對指定文章觸發 Content Refresh。"""
    from .refresh_agent import run_refresh_pipeline

    article_id = action.get("article_id")
    keyword = action.get("keyword")

    if not article_id and not keyword:
        logger.warning("[StrategicExecutor/refresh] 缺少 article_id 或 keyword")
        return

    with SessionLocal() as session:
        if article_id:
            article = session.get(Article, article_id)
        elif keyword:
            article = (
                session.query(Article)
                .filter(
                    Article.project_id == project_id,
                    Article.status == "published",
                    Article.primary_keyword.contains(keyword),
                )
                .first()
            )
        else:
            article = None

        if not article:
            logger.warning(f"[StrategicExecutor/refresh] 找不到目標文章 id={article_id} kw={keyword}")
            return

        if not article.draft_content:
            logger.warning(f"[StrategicExecutor/refresh] 文章 #{article.id} 無草稿，跳過 refresh")
            return

        art_title = article.title

    reason = action.get("reason", "Strategic Agent 決策")
    logger.info(f"[StrategicExecutor/refresh] Refresh：'{art_title}' 原因={reason}")

    try:
        if article.wp_post_id:
            platform = "wordpress"
            post_id = article.wp_post_id
        elif article.publish_url:
            platform = "url"
            post_id = None
        else:
            platform = "forgebase"
            post_id = article.forgebase_id or article.slug or str(article.id)

        with SessionLocal() as session:
            art = session.get(Article, article.id)
            if not art:
                logger.warning(f"[StrategicExecutor/refresh] 找不到文章 #{article.id}")
                return
            gsc_feedback = _merge_action_gsc_queries(
                _load_article_gsc_feedback(session, art),
                action.get("gsc_queries"),
                article=art,
            )

            refresh_result = await run_refresh_pipeline(
                article=art,
                keyword=art.primary_keyword or art.title,
                session=session,
                serp_summary=_build_gsc_feedback_summary(gsc_feedback),
                platform=platform,
                post_id=post_id,
                generate_content=True,
                publish=True,
                gsc_context=gsc_feedback,
            )

            diff_result = refresh_result.get("plan")
        logger.info(
            f"[StrategicExecutor/refresh] '{art_title}' "
            f"新鮮度={getattr(diff_result, 'overall_freshness_score', None)}，"
            f"建議={getattr(diff_result, 'recommendation', None)}"
        )

        if diff_result and getattr(diff_result, "recommendation", None) in ("patch", "rewrite"):
            with SessionLocal() as session:
                art = session.get(Article, article.id)
                if art:
                    art.last_refresh_date = datetime.now(timezone.utc)
                    session.commit()

            # 記錄 ActionOutcome（因果追蹤基線）
            from ..scheduler import record_action_outcome
            record_action_outcome(
                project_id=project_id,
                article_id=article.id,
                strategic_plan_id=plan_id,
                action_type="refresh",
                primary_keyword=article.primary_keyword or article.title,
            )

    except Exception as e:
        logger.error(f"[StrategicExecutor/refresh] '{art_title}' 失敗：{e}")


async def _execute_alert(action: dict, project_id: int) -> None:
    """執行 alert action：發送 Slack 通知。"""
    import httpx

    message = action.get("message", "Strategic Agent 警報")
    slack_url = settings.slack_webhook_url
    if not slack_url:
        logger.info(f"[StrategicExecutor/alert] （無 Slack）{message}")
        return

    text = f"🧠 *Strategic Agent 提醒*\n{message}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(slack_url, json={"text": text})
        logger.info("[StrategicExecutor/alert] Slack 通知已發送")
    except Exception as e:
        logger.warning(f"[StrategicExecutor/alert] Slack 發送失敗：{e}")


async def _execute_optimize_meta(action: dict, project_id: int) -> None:
    """執行 optimize_meta action：用 SEO QA Agent 重寫 meta title/description 並回寫平台。"""
    from ..agents.seo_qa_agent import run_seo_qa_agent
    from ..models.database import Article
    from ..models.schemas import ArticleDraft, ResearchReport

    article_id = action.get("article_id")
    if not article_id:
        logger.warning("[StrategicExecutor/optimize_meta] 缺少 article_id")
        return

    with SessionLocal() as session:
        article = session.get(Article, article_id)
        if not article:
            logger.warning(f"[StrategicExecutor/optimize_meta] 找不到文章 #{article_id}")
            return
        if not article.draft_content:
            logger.warning(f"[StrategicExecutor/optimize_meta] 文章 #{article_id} 無草稿，跳過")
            return
        art_title = article.title
        art_kw = article.primary_keyword or article.title
        draft_content = article.draft_content
        art_wp_id = article.wp_post_id
        art_fb_id = article.forgebase_id
        art_pub_url = article.publish_url or ""
        gsc_feedback = _merge_action_gsc_queries(
            _load_article_gsc_feedback(session, article),
            action.get("gsc_queries"),
            article=article,
        )

    logger.info(f"[StrategicExecutor/optimize_meta] 文章：'{art_title}' 原因={action.get('reason', '')}")

    try:
        # 組裝一個最小 ArticleDraft 讓 SEO QA Agent 處理
        draft_obj = ArticleDraft(
            title=art_title,
            content_markdown=draft_content,
            meta_title=article.meta_title or "",
            meta_description=article.meta_description or "",
        )
        suggested_keywords = [art_kw]
        failed_checks: list[dict[str, Any]] = []
        if gsc_feedback:
            low_ctr_queries = gsc_feedback.get("low_ctr_queries", []) or []
            suggested_keywords.extend(
                query.get("query", "") for query in low_ctr_queries if query.get("query")
            )
            position = gsc_feedback.get("position")
            impressions = int(gsc_feedback.get("impressions", 0) or 0)
            ctr = float(gsc_feedback.get("ctr", 0.0) or 0.0)
            if position is not None and impressions >= 50 and ctr < 0.03:
                failed_checks.append({
                    "name": "gsc_ctr_gap",
                    "detail": (
                        f"GSC 顯示排名 P{position}、曝光 {impressions}、CTR {round(ctr * 100, 2)}% 偏低，"
                        "請讓 meta 與首段更直接回應搜尋意圖"
                    ),
                    "passed": False,
                })
            for query in low_ctr_queries[:3]:
                failed_checks.append({
                    "name": "gsc_query_gap",
                    "detail": (
                        f"查詢詞「{query.get('query', '')}」曝光 {int(query.get('impressions', 0) or 0)}、"
                        f"CTR {round(float(query.get('ctr', 0.0) or 0.0) * 100, 2)}% 偏低"
                    ),
                    "passed": False,
                })

        empty_report = ResearchReport(
            article_title=art_title,
            keywords=[art_kw],
            suggested_keywords=[kw for kw in suggested_keywords if kw][:10],
        )
        optimized = await run_seo_qa_agent(
            draft=draft_obj,
            report=empty_report,
            primary_keyword=art_kw,
            secondary_keywords=[kw for kw in suggested_keywords if kw and kw != art_kw][:5],
            failed_checks=failed_checks,
            project_id=project_id,
        )
        new_title = optimized.meta_title
        new_desc = optimized.meta_description

        if not new_title and not new_desc:
            logger.info(f"[StrategicExecutor/optimize_meta] '{art_title}' QA 未給出優化建議，跳過")
            return
        # 回寫 DB
        with SessionLocal() as session:
            art = session.get(Article, article_id)
            if art:
                if new_title:
                    art.meta_title = new_title
                if new_desc:
                    art.meta_description = new_desc
                art.updated_at = datetime.now(timezone.utc)
                session.commit()

        # 回寫平台（若已發布）
        if art_pub_url:
            draft_obj = ArticleDraft(
                title=art_title,
                content_markdown=draft_content,
                meta_title=new_title or "",
                meta_description=new_desc or "",
            )
            with SessionLocal() as session:
                if art_wp_id:
                    pub = build_wordpress_publisher(db=session, project_id=article.project_id)
                elif art_fb_id:
                    pub = build_forgebase_publisher(db=session, project_id=article.project_id)
                else:
                    pub = None
            if art_wp_id and pub is not None:
                await pub.update_post(art_wp_id, draft_obj)
                logger.info(f"[StrategicExecutor/optimize_meta] '{art_title}' WP meta 已回寫")
            elif art_fb_id and pub is not None:
                await pub.update_post(art_fb_id, draft_obj)
                logger.info(f"[StrategicExecutor/optimize_meta] '{art_title}' ForgeBase meta 已回寫")

    except Exception as e:
        logger.error(f"[StrategicExecutor/optimize_meta] '{art_title}' 失敗：{e}")


async def _execute_inject_internal_links(action: dict, project_id: int) -> None:
    """執行 inject_internal_links action：
    讀取 Article.suggested_internal_links，將建議連結注入 Markdown 內文，
    再透過 publisher 更新已發布文章。
    """
    import json as _json
    import re as _re
    from ..models.database import Article

    article_id = action.get("article_id")
    if not article_id:
        logger.warning("[StrategicExecutor/inject_links] 缺少 article_id")
        return

    with SessionLocal() as session:
        article = session.get(Article, article_id)
        if not article:
            logger.warning(f"[StrategicExecutor/inject_links] 文章 #{article_id} 不存在")
            return
        if not article.draft_content:
            logger.warning(f"[StrategicExecutor/inject_links] 文章 #{article_id} 無草稿")
            return

        raw_links = article.suggested_internal_links or "[]"
        suggestions: list[dict] = _json.loads(raw_links)
        if not suggestions:
            logger.info(f"[StrategicExecutor/inject_links] 文章 #{article_id} 無建議連結，跳過")
            return

        art_title = article.title
        art_wp_id = article.wp_post_id
        art_fb_id = article.forgebase_id
        draft_content = article.draft_content
        art_meta_title = article.meta_title
        art_meta_desc = article.meta_description

    logger.info(
        f"[StrategicExecutor/inject_links] '{art_title}'：注入 {len(suggestions)} 條建議連結"
    )

    # 將建議連結逐一注入：在 Markdown 中找到 anchor_text 第一次出現處並替換為 [anchor_text](target_url)
    modified = draft_content
    injected = 0
    for link in suggestions:
        anchor = link.get("anchor_text", "").strip()
        url = link.get("target_url", "").strip()
        if not anchor or not url:
            continue
        # 確保不替換已經是連結的部分
        pattern = rf"(?<!\[)(?<!\()({_re.escape(anchor)})(?!\])(?!\))"
        replacement = f"[{anchor}]({url})"
        new_content, count = _re.subn(pattern, replacement, modified, count=1)
        if count:
            modified = new_content
            injected += 1

    if not injected:
        logger.info(f"[StrategicExecutor/inject_links] '{art_title}'：無法在內文中找到錨文字，跳過")
        return

    # 回寫 DB
    with SessionLocal() as session:
        art = session.get(Article, article_id)
        if art:
            art.draft_content = modified
            art.updated_at = datetime.now(timezone.utc)
            session.commit()

    # 回寫平台（若已發布）
    from ..models.schemas import ArticleDraft
    draft_obj = ArticleDraft(
        title=art_title,
        content_markdown=modified,
        meta_title=art_meta_title,
        meta_description=art_meta_desc,
    )
    try:
        with SessionLocal() as session:
            if art_wp_id:
                publisher = build_wordpress_publisher(db=session, project_id=article.project_id)
            elif art_fb_id:
                publisher = build_forgebase_publisher(db=session, project_id=article.project_id)
            else:
                publisher = None
        if art_wp_id and publisher is not None:
            await publisher.update_post(art_wp_id, draft_obj)
            logger.info(f"[StrategicExecutor/inject_links] '{art_title}' WP 已更新（注入 {injected} 條連結）")
        elif art_fb_id and publisher is not None:
            await publisher.update_post(art_fb_id, draft_obj)
            logger.info(f"[StrategicExecutor/inject_links] '{art_title}' ForgeBase 已更新（注入 {injected} 條連結）")
        else:
            logger.info(
                f"[StrategicExecutor/inject_links] '{art_title}'：尚未發布（無 wp/forgebase id），"
                "連結已寫入草稿，待發布時生效"
            )
    except Exception as e:
        logger.error(f"[StrategicExecutor/inject_links] '{art_title}' 平台回寫失敗：{e}")
