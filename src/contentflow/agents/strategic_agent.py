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
from typing import Any

from loguru import logger

from ..config import settings
from ..db import SessionLocal
from ..models.database import (
    Article,
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


def _calculate_generate_capacity(context: dict[str, Any]) -> dict[str, Any]:
    """依 backlog、待審稿壓力與歷史成效決定今日 generate 配額。"""
    backlog = len(context.get("calendar_items", []))
    reviewing = int(context.get("article_stats", {}).get("reviewing", 0) or 0)
    ranking_changes = context.get("ranking_changes_top10", [])
    outcome_stats = context.get("action_outcome_stats", {}) or {}
    generate_stats = outcome_stats.get("generate", {}) or {}
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
    success_rate = improved_generate / total_generate if total_generate else None
    decline_rate = declined_generate / total_generate if total_generate else None

    if total_generate >= 4 and decline_rate is not None and success_rate is not None:
        if decline_rate >= 0.5:
            quota = max(0, quota - 2)
            signals.append("generate_decline_rate_high")
        elif decline_rate >= 0.34 or success_rate < 0.25:
            quota = max(0, quota - 1)
            signals.append("generate_performance_soften")
        elif success_rate >= 0.6 and decline_rate <= 0.2 and reviewing <= 2 and backlog > quota:
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


# ── 數據收集 ──────────────────────────────────────────────────

def _collect_project_context(project_id: int, session) -> dict[str, Any]:
    """收集 Strategic Agent 做決策所需的全部數據快照。"""
    today = date.today()
    week_ago = today - timedelta(days=7)
    current_month = today.month
    current_week = (today.day - 1) // 7 + 1

    # 1. 日曆中待執行的 planned 文章
    planned_calendar = (
        session.query(ContentCalendar)
        .filter(
            ContentCalendar.project_id == project_id,
            ContentCalendar.status == "planned",
            ContentCalendar.month <= current_month,
        )
        .all()
    )
    calendar_items = [
        {
            "calendar_id": c.id,
            "title": c.title,
            "keywords": c.keywords,
            "month": c.month,
            "week": c.week,
            "article_id": c.article_id,
        }
        for c in planned_calendar
    ]

    # 1b. 自動補充日曆：若 planned 排程 < 最低閾值，從關鍵字庫選高優先詞建立條目
    #     條件：未有對應文章（無 published/planned 文章）+ 有搜尋量
    MIN_CALENDAR_BUFFER = 5
    if len(calendar_items) < MIN_CALENDAR_BUFFER:
        from ..models.database import Keyword, Article as _Article
        existing_kws = {
            kw for kw in (
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
        # 排序：搜尋量 desc + trend_direction = 'rising' 優先 + difficulty asc
        candidate_keywords = (
            session.query(Keyword)
            .filter(
                Keyword.project_id == project_id,
                Keyword.search_volume > 0,
            )
            .order_by(
                Keyword.search_volume.desc(),
            )
            .limit(50)
            .all()
        )
        needed = MIN_CALENDAR_BUFFER - len(calendar_items)
        added = 0
        for kw_obj in candidate_keywords:
            if added >= needed:
                break
            if kw_obj.keyword in existing_kws:
                continue
            # 建立 Article + ContentCalendar
            new_art = _Article(
                project_id=project_id,
                title=kw_obj.keyword,
                primary_keyword=kw_obj.keyword,
                status="planned",
            )
            session.add(new_art)
            session.flush()
            new_cal = ContentCalendar(
                project_id=project_id,
                title=kw_obj.keyword,
                keywords=kw_obj.keyword,
                month=current_month,
                week=current_week,
                status="planned",
                article_id=new_art.id,
            )
            session.add(new_cal)
            session.flush()
            calendar_items.append({
                "calendar_id": new_cal.id,
                "title": kw_obj.keyword,
                "keywords": kw_obj.keyword,
                "month": current_month,
                "week": current_week,
                "article_id": new_art.id,
            })
            existing_kws.add(kw_obj.keyword)
            added += 1
        if added > 0:
            session.commit()
            logger.info(
                f"[StrategicAgent] 自動補充日曆：從關鍵字庫新增 {added} 個待產出排程，"
                f"總 planned backlog = {len(calendar_items)}"
            )

    # 2. 排名數據（近 7 天 vs 前 7 天比對）
    two_weeks_ago = today - timedelta(days=14)
    recent_rankings = (
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
            SEORanking.project_id == project_id,
            SEORanking.tracked_date >= two_weeks_ago,
        )
        .all()
    )

    # 分群：本週 vs 上週
    rank_current: dict[str, list[float]] = {}
    rank_previous: dict[str, list[float]] = {}
    for r in recent_rankings:
        kw = r.keyword
        pos = r.position
        if pos is None:
            continue
        if r.tracked_date and r.tracked_date >= week_ago:
            rank_current.setdefault(kw, []).append(pos)
        else:
            rank_previous.setdefault(kw, []).append(pos)

    # 計算排名變化
    ranking_changes = []
    for kw in set(list(rank_current.keys()) + list(rank_previous.keys())):
        curr_avg = sum(rank_current.get(kw, [99])) / max(len(rank_current.get(kw, [99])), 1)
        prev_avg = sum(rank_previous.get(kw, [99])) / max(len(rank_previous.get(kw, [99])), 1)
        delta = curr_avg - prev_avg  # 正值 = 排名下滑（數字變大）
        ranking_changes.append({
            "keyword": kw,
            "current_position": round(curr_avg, 1),
            "previous_position": round(prev_avg, 1),
            "delta": round(delta, 1),
        })
    ranking_changes.sort(key=lambda x: x["delta"], reverse=True)

    # 3. 排名分群（A-F，§8.3）
    rank_groups = {"A": [], "B": [], "C": [], "D": [], "E": [], "F": []}
    articles_with_rank = (
        session.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.status == "published",
        )
        .all()
    )
    for art in articles_with_rank:
        # 取該文章最近一次排名
        latest_rank = (
            session.query(SEORanking)
            .filter(
                SEORanking.project_id == project_id,
                SEORanking.landing_page.contains(art.slug) if art.slug else False,
            )
            .order_by(SEORanking.tracked_date.desc())
            .first()
        )
        pos = latest_rank.position if latest_rank else None
        info = {"article_id": art.id, "title": art.title, "position": pos}
        if pos is None:
            rank_groups["F"].append(info)
        elif pos <= 3:
            rank_groups["A"].append(info)
        elif pos <= 10:
            rank_groups["B"].append(info)
        elif pos <= 20:
            rank_groups["C"].append(info)
        elif pos <= 50:
            rank_groups["D"].append(info)
        else:
            rank_groups["E"].append(info)

    # 4. Refresh 候選（KnowledgeEntry category=refresh_priority）
    refresh_candidates = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.category == "refresh_priority",
            KnowledgeEntry.is_active == True,  # noqa: E712
        )
        .all()
    )
    refresh_items = [
        {"pattern": k.pattern, "metadata": k.metadata_json}
        for k in refresh_candidates
    ]

    # 5. 上次反思摘要（最近一次 ReflectionLog 的 session_summary）
    last_reflection = (
        session.query(ReflectionLog)
        .filter(ReflectionLog.project_id == project_id)
        .order_by(ReflectionLog.created_at.desc())
        .first()
    )
    last_summary = last_reflection.session_summary if last_reflection else ""

    # 6. 文章狀態統計
    reviewing_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status.in_(["reviewing", "review_required"]))
        .count()
    )
    planned_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "planned")
        .count()
    )
    published_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "published")
        .count()
    )

    # 7. 過去動作的成效回饋（ActionOutcome — 因果學習資料）
    recent_outcomes = (
        session.query(ActionOutcome)
        .filter(
            ActionOutcome.project_id == project_id,
            ActionOutcome.success_flag.isnot(None),
            ActionOutcome.success_flag != "too_early",
        )
        .order_by(ActionOutcome.action_date.desc())
        .limit(20)
        .all()
    )
    outcome_summary = []
    for o in recent_outcomes:
        outcome_summary.append({
            "action_type": o.action_type,
            "keyword": o.primary_keyword,
            "action_date": o.action_date.isoformat() if o.action_date else None,
            "baseline_rank": o.baseline_rank,
            "rank_after_28d": o.rank_after_28d,
            "rank_delta": o.rank_delta,
            "success": o.success_flag,
            "confidence": o.learning_confidence,
        })

    # 8. 成效統計摘要（按 action_type 分組）
    outcome_stats = {}
    for o in recent_outcomes:
        at = o.action_type
        if at not in outcome_stats:
            outcome_stats[at] = {"total": 0, "improved": 0, "declined": 0, "stable": 0}
        outcome_stats[at]["total"] += 1
        if o.success_flag in outcome_stats[at]:
            outcome_stats[at][o.success_flag] += 1

    # 9. 關鍵字自蝕偵測（CannibalizationDetector）
    from .analytics_agent import CannibalizationDetector
    cannib_pairs = CannibalizationDetector(session).detect(project_id)
    cannibalization_summary = [
        {
            "keyword": p.keyword,
            "competing_titles": p.article_titles[:3],
            "suggestion": p.suggestion,
        }
        for p in cannib_pairs[:5]
    ]

    # 10. 叢集缺口（直接查 DB，不重新執行 AI 分群）
    cluster_gaps_raw = (
        session.query(ClusterMember.keyword, TopicCluster.pillar_keyword)
        .join(TopicCluster, ClusterMember.cluster_id == TopicCluster.id)
        .filter(
            TopicCluster.project_id == project_id,
            ClusterMember.article_id == None,  # noqa: E711
        )
        .all()
    )
    cluster_gaps_summary = [
        {"pillar": row.pillar_keyword, "missing_keyword": row.keyword}
        for row in cluster_gaps_raw[:10]
    ]

    # 11. 關鍵字趨勢方向（rising/declining）
    from ..models.database import Keyword
    trending_keywords = (
        session.query(Keyword.keyword, Keyword.trend_direction, Keyword.trends_score)
        .filter(
            Keyword.project_id == project_id,
            Keyword.trend_direction.isnot(None),
            Keyword.trend_direction != "stable",
        )
        .order_by(Keyword.trends_score.desc())
        .limit(10)
        .all()
    )
    keyword_trends_summary = [
        {"keyword": r.keyword, "direction": r.trend_direction, "score": r.trends_score}
        for r in trending_keywords
    ]

    context_snapshot = {
        "today": today.isoformat(),
        "calendar_items": calendar_items,
        "ranking_changes_top10": ranking_changes[:10],
        "rank_groups_summary": {
            k: {"count": len(v), "articles": v[:3]}
            for k, v in rank_groups.items()
        },
        "refresh_candidates": refresh_items[:10],
        "last_session_summary": last_summary,
        "article_stats": {
            "planned": planned_count,
            "reviewing": reviewing_count,
            "published": published_count,
        },
        "action_outcome_history": outcome_summary[:10],
        "action_outcome_stats": outcome_stats,
        "cannibalization_risks": cannibalization_summary,
        "cluster_gaps": cluster_gaps_summary,
        "keyword_trends": keyword_trends_summary,
    }
    context_snapshot["generate_capacity"] = _calculate_generate_capacity(context_snapshot)
    return context_snapshot


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
- 如果 `cannibalization_risks` 不為空，發送 alert 告知哪些關鍵字有自蝕風險
- 如果 `cluster_gaps` 不為空，優先將高价値缺口關鍵字納入 generate 計劃- 如果 `keyword_trends` 中有 direction="up" 的關鍵字且尚無文章，納入 generate 候選
## 因果學習（重要）：
- 數據中包含 `action_outcome_history`，記錄過去動作的實際成效
- `action_outcome_stats` 顯示各類動作（generate/refresh）的成功率統計
- **優先安排成功率高的動作類型**
- 如果某類動作 declined 比例高，降低其優先級並在 summary 中說明原因
- 如果沒有 outcome 數據（系統初期），按照基本規則決策即可

## 輸出格式（嚴格 JSON）：
```json
{
  "actions": [
    {"action": "generate", "calendar_id": 7, "reason": "日曆排程已到期", "priority": 1},
      {"action": "refresh", "article_id": 3, "reason": "排名從 8 掉到 15，屬於 B→C 群", "priority": 2},
    {"action": "alert", "message": "有 6 篇文章待審閱，建議今日優先處理", "priority": 0},
    {"action": "optimize_meta", "article_id": 5, "reason": "CTR 1.2% 但排名 P5，活化 meta 可提升點擊率", "priority": 3}
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
    today = date.today()
    logger.info(f"[StrategicAgent] 啟動 project={project_id} date={today}")

    with SessionLocal() as session:
        # 檢查今天是否已有計畫（避免重複執行）
        existing = (
            session.query(StrategicPlan)
            .filter(
                StrategicPlan.project_id == project_id,
                StrategicPlan.plan_date == today,
                StrategicPlan.plan_type == "daily",
            )
            .first()
        )
        if existing and existing.status != "pending":
            logger.info(f"[StrategicAgent] 今日計畫已存在且狀態={existing.status}，跳過")
            return existing

        # 收集數據
        context_snapshot = _collect_project_context(project_id, session)

    # LLM 決策
    try:
        plan_result = await _call_strategic_llm(context_snapshot)
    except Exception as e:
        logger.error(f"[StrategicAgent] LLM 決策失敗：{e}")
        # Fallback：只排日曆中到期的 planned 文章
        plan_result = _fallback_plan(context_snapshot)

    plan_result = _normalize_plan_result(plan_result, context_snapshot)
    actions = plan_result.get("actions", [])
    summary = plan_result.get("summary", "")

    # 寫入 DB
    with SessionLocal() as session:
        plan = StrategicPlan(
            project_id=project_id,
            plan_date=today,
            plan_type="daily",
            actions_json=json.dumps(actions, ensure_ascii=False),
            summary=summary,
            context_snapshot=json.dumps(context_snapshot, ensure_ascii=False),
            total_count=len(actions),
            executed_count=0,
            status="pending",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        logger.info(
            f"[StrategicAgent] 計畫產出完成：{len(actions)} 項 action | {summary[:80]}"
        )
        return plan


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

    # 排名下滑 > 5 位 → refresh
    for rc in context.get("ranking_changes_top10", []):
        if rc["delta"] >= 5:
            actions.append({
                "action": "refresh",
                "keyword": rc["keyword"],
                "reason": f"排名下滑 {rc['delta']} 位（{rc['previous_position']} → {rc['current_position']}）",
                "priority": 2,
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
    """依序執行 StrategicPlan 中的 actions。

    - generate → 呼叫 run_orchestrator
    - refresh → 呼叫 refresh_agent
    - alert → 發 Slack 通知
    """
    from .orchestrator import run_orchestrator
    from ..models import ArticleTask

    with SessionLocal() as session:
        plan = session.get(StrategicPlan, plan_id)
        if not plan:
            logger.error(f"[StrategicExecutor] Plan #{plan_id} 不存在")
            return
        plan.status = "executing"
        session.commit()

        actions = json.loads(plan.actions_json or "[]")
        project_id = plan.project_id

    executed = 0
    for action in sorted(actions, key=lambda a: a.get("priority", 99)):
        action_type = action.get("action")
        try:
            if action_type == "generate":
                await _execute_generate(action, project_id, plan_id=plan_id)
                executed += 1
            elif action_type == "refresh":
                await _execute_refresh(action, project_id, plan_id=plan_id)
                executed += 1
            elif action_type == "alert":
                await _execute_alert(action, project_id)
                executed += 1
            elif action_type == "optimize_meta":
                await _execute_optimize_meta(action, project_id)
                executed += 1
            elif action_type == "inject_internal_links":
                await _execute_inject_internal_links(action, project_id)
                executed += 1
            else:
                logger.warning(f"[StrategicExecutor] 未知 action 類型：{action_type}")
        except Exception as e:
            logger.error(f"[StrategicExecutor] action={action_type} 失敗：{e}")

    with SessionLocal() as session:
        plan = session.get(StrategicPlan, plan_id)
        if plan:
            plan.executed_count = executed
            plan.status = "completed"
            session.commit()

    logger.info(f"[StrategicExecutor] Plan #{plan_id} 完成，{executed}/{len(actions)} 項")


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

    task = ArticleTask(task_id=run_id, title=art_title, keywords=[art_kw])
    logger.info(f"[StrategicExecutor/generate] 啟動 pipeline：'{art_title}' run_id={run_id[:8]}")

    try:
        result = await run_orchestrator(task, project_id=project_id, article_id=art_id)

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
                    # 決定發布平台：WordPress > ForgeBase > 原生 blog
                    wp_configured = bool(
                        settings.wordpress_site_url
                        and settings.wordpress_username
                        and settings.wordpress_app_password
                    )
                    fb_configured = bool(
                        settings.forgebase_api_base_url
                        and settings.forgebase_api_token
                    )
                    _pub_platform = (
                        "wordpress" if wp_configured
                        else "forgebase" if fb_configured
                        else "native"
                    )
                    _pub_article_id = art_id
                    _pub_draft = result.draft
                    _pub_slug = article.slug
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
            site_root = settings.site_url.rstrip("/")
            pub_url = f"{site_root}/blog/{_pub_slug}"
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
                from ..publishers.wordpress import WordPressPublisher
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
                wp_pub = WordPressPublisher()
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
                from ..publishers.forgebase import ForgeBasePublisher
                fb_pub = ForgeBasePublisher()
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
    from .refresh_agent import RefreshDiffAnalyzer

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
        analyzer = RefreshDiffAnalyzer()
        diff_result = await analyzer.analyze(
            current_content=article.draft_content,
            keyword=article.primary_keyword or article.title,
        )
        logger.info(
            f"[StrategicExecutor/refresh] '{art_title}' "
            f"新鮮度={diff_result.freshness_score}，建議={diff_result.recommendation}"
        )

        if diff_result.recommendation in ("patch", "rewrite"):
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

    logger.info(f"[StrategicExecutor/optimize_meta] 文章：'{art_title}' 原因={action.get('reason', '')}")

    try:
        # 組裝一個最小 ArticleDraft 讓 SEO QA Agent 處理
        draft_obj = ArticleDraft(
            title=art_title,
            content_markdown=draft_content,
            meta_title="",
            meta_description="",
        )
        empty_report = ResearchReport(
            topic=art_kw,
            suggested_keywords=[art_kw],
            summary="",
        )
        optimized = await run_seo_qa_agent(
            draft=draft_obj,
            report=empty_report,
            primary_keyword=art_kw,
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
            if art_wp_id:
                from ..publishers.wordpress import WordPressPublisher
                pub = WordPressPublisher()
                await pub.update_post(art_wp_id, draft_obj)
                logger.info(f"[StrategicExecutor/optimize_meta] '{art_title}' WP meta 已回寫")
            elif art_fb_id:
                from ..publishers.forgebase import ForgeBasePublisher
                pub = ForgeBasePublisher()
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
        if art_wp_id:
            from ..publishers.wordpress import WordPressPublisher
            await WordPressPublisher().update_post(art_wp_id, draft_obj)
            logger.info(f"[StrategicExecutor/inject_links] '{art_title}' WP 已更新（注入 {injected} 條連結）")
        elif art_fb_id:
            from ..publishers.forgebase import ForgeBasePublisher
            await ForgeBasePublisher().update_post(art_fb_id, draft_obj)
            logger.info(f"[StrategicExecutor/inject_links] '{art_title}' ForgeBase 已更新（注入 {injected} 條連結）")
        else:
            logger.info(
                f"[StrategicExecutor/inject_links] '{art_title}'：尚未發布（無 wp/forgebase id），"
                "連結已寫入草稿，待發布時生效"
            )
    except Exception as e:
        logger.error(f"[StrategicExecutor/inject_links] '{art_title}' 平台回寫失敗：{e}")
