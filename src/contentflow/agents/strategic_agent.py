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

    return {
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


# ── LLM 決策 ─────────────────────────────────────────────────

STRATEGIC_SYSTEM_PROMPT = """你是 ContentFlow 的 Strategic Agent，負責決定「今天要做什麼」。

你不執行任何操作 — 你只輸出一份結構化的**執行計畫**，由 Tactical Pipeline 去執行。

## 你可以規劃的 action 類型：
1. **generate** — 啟動 AI Pipeline 產出新文章
   - 需指定 calendar_id（從待執行日曆中選）
   - 每日最多 2 篇（避免成本失控）
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
- 每日控制在 2 個 generate + 2 個 refresh 以內
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


async def _call_strategic_llm(context_snapshot: dict) -> dict:
    """呼叫 LLM 產出執行計畫，自帶 provider failover。"""
    from ..llm_client import achat

    user_msg = f"以下是今日的專案數據，請產出今日執行計畫：\n\n```json\n{json.dumps(context_snapshot, ensure_ascii=False, indent=2)}\n```"

    content = await achat(
        messages=[
            {"role": "system", "content": STRATEGIC_SYSTEM_PROMPT},
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
    # 到期日曆 → generate
    for item in context.get("calendar_items", [])[:2]:
        actions.append({
            "action": "generate",
            "calendar_id": item["calendar_id"],
            "reason": "日曆排程已到期（fallback 規則）",
            "priority": 1,
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
                # 發布政策（L2-1）：
                #   auto_publish_enabled=True 且 seo_score >= min_score → 直接發布
                #   有排程時間 → approved（等待排程 job）
                #   否則 → reviewing（人工審核）
                auto_pub = (
                    project
                    and project.auto_publish_enabled
                    and (article.seo_score or 0) >= (project.auto_publish_min_score or 85)
                )
                if auto_pub:
                    article.status = "approved"   # check_scheduled_publishes 會立即偵測並發布
                    article.scheduled_publish_at = article.scheduled_publish_at or datetime.now(timezone.utc)
                elif article.scheduled_publish_at:
                    article.status = "approved"
                else:
                    article.status = result.status or "reviewing"
                article.updated_at = datetime.now(timezone.utc)

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
