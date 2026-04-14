"""APScheduler 排程系統（CF-02-01）

內嵌於 FastAPI 服務，在 startup/shutdown 事件中啟動/停止。
所有 job 執行結果寫入 SchedulerLog，失敗自動指數退避重試最多 3 次，
達上限後發送 Slack 通知。

使用方式（api.py 已整合）：
  from contentflow.scheduler import scheduler, schedule_all_jobs
  在 @app.on_event("startup") 呼叫 schedule_all_jobs()
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Callable, Awaitable

# 跨 process 排程鎖（多 worker 部署時只讓一個 worker 啟動排程）
_scheduler_lock_fd = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import SchedulerLog
from sqlalchemy import func

# ── 全域 scheduler 實例 ───────────────────────────────────────

scheduler = AsyncIOScheduler(
    timezone=settings.scheduler_timezone,
    job_defaults={"misfire_grace_time": 60 * 10},  # 10 分鐘內的 misfire 仍執行
)

# ── SchedulerLog 寫入 helper ──────────────────────────────────

def _write_log(
    job_id: str,
    job_name: str,
    status: str,
    started_at: datetime,
    retry_count: int = 0,
    error_message: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    """同步寫入 SchedulerLog（在 async job 中以 thread-safe 方式呼叫）。"""
    with SessionLocal() as session:
        log = SchedulerLog(
            job_id=job_id,
            job_name=job_name,
            status=status,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            retry_count=retry_count,
            error_message=error_message,
            duration_seconds=duration_seconds,
        )
        session.add(log)
        session.commit()


async def _send_failure_alert(job_name: str, error: str) -> None:
    """排程任務超過最大重試次數時發 Slack 通知。"""
    import httpx
    if not settings.slack_webhook_url:
        return
    msg = f"🚨 ContentFlow Scheduler 失敗\n任務：{job_name}\n錯誤：{error[:200]}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.slack_webhook_url, json={"text": msg})
    except Exception as exc:
        logger.warning(f"[Scheduler] Slack 通知失敗：{exc}")


# ── Retry wrapper ─────────────────────────────────────────────

def with_retry(max_retries: int = 3, base_delay: int = 300):
    """指數退避重試裝飾器（5min → 15min → 45min）。"""

    def decorator(fn: Callable[..., Awaitable]):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            job_name = fn.__name__
            started_at = datetime.now(timezone.utc)
            t0 = time.monotonic()

            for attempt in range(max_retries + 1):
                try:
                    await fn(*args, **kwargs)
                    duration = time.monotonic() - t0
                    _write_log(
                        job_id=job_name,
                        job_name=job_name,
                        status="success",
                        started_at=started_at,
                        retry_count=attempt,
                        duration_seconds=duration,
                    )
                    logger.info(f"[Scheduler] ✅ {job_name} 完成（{duration:.1f}s）")
                    return
                except Exception as exc:
                    error_msg = str(exc)
                    logger.warning(f"[Scheduler] {job_name} 第 {attempt + 1} 次失敗：{error_msg}")
                    if attempt < max_retries:
                        delay = base_delay * (3 ** attempt)  # 5min, 15min, 45min
                        logger.info(f"[Scheduler] {job_name} {delay // 60}min 後重試")
                        await asyncio.sleep(delay)
                    else:
                        duration = time.monotonic() - t0
                        _write_log(
                            job_id=job_name,
                            job_name=job_name,
                            status="failed",
                            started_at=started_at,
                            retry_count=attempt,
                            error_message=error_msg,
                            duration_seconds=duration,
                        )
                        logger.error(f"[Scheduler] ❌ {job_name} 超過最大重試次數")
                        await _send_failure_alert(job_name, error_msg)

        return wrapper
    return decorator


# ── 排程任務定義 ──────────────────────────────────────────────
# 各 tool 模組尚未實作時為 placeholder，接上後直接呼叫即可。

def _to_gsc_site_url(brand_url: str) -> str:
    """將品牌 URL 轉換為 GSC API 接受的 site_url 格式。

    GSC Domain Property（sc-domain:）覆蓋所有子網域與 http/https；
    URL-prefix property 只覆蓋特定前綴，使用 Domain Property 更準確。

    Examples:
        "https://goodbone.com.tw"  → "sc-domain:goodbone.com.tw"
        "https://www.example.com/" → "sc-domain:example.com"
        "sc-domain:already.com"    → "sc-domain:already.com"（原樣回傳）
    """
    if brand_url.startswith("sc-domain:"):
        return brand_url
    from urllib.parse import urlparse
    parsed = urlparse(brand_url)
    hostname = parsed.hostname or brand_url
    # 移除 www. 前綴（Domain Property 不含 www）
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return f"sc-domain:{hostname}"


@with_retry(max_retries=3)
async def sync_gsc_all_projects() -> None:
    """每日 03:00 — 同步全專案 GSC 排名數據。"""
    from contentflow.tools.gsc import GSCClient
    from contentflow.db import SessionLocal
    from contentflow.models.database import Project

    client = GSCClient()
    with SessionLocal() as session:
        projects = session.query(Project).all()
    for project in projects:
        if project.brand_url:
            site_url = _to_gsc_site_url(project.brand_url)
            await client.sync_to_db(project_id=project.id, site_url=site_url)
    logger.info(f"[GSCSync] 已同步 {len(projects)} 個專案")


@with_retry(max_retries=3)
async def sync_ga4_all_projects() -> None:
    """每日 03:30 — 同步全專案 GA4 頁面指標，持久化到 GAPageMetric。"""
    from datetime import date
    from contentflow.tools.ga4 import GA4Client
    from contentflow.models.database import Project, GAPageMetric

    with SessionLocal() as session:
        projects = session.query(Project).filter(Project.ga4_property_id != "").all()
        project_data = [(p.id, p.ga4_property_id) for p in projects]

    if not project_data:
        logger.info("[GA4Sync] 無已設定 GA4 Property ID 的專案")
        return

    today = date.today()
    client = GA4Client()
    total_rows = 0

    for project_id, property_id in project_data:
        try:
            metrics = await client.get_page_metrics(property_id=property_id)
            with SessionLocal() as session:
                # 同一天的數據先刪除（避免重複）
                session.query(GAPageMetric).filter(
                    GAPageMetric.project_id == project_id,
                    GAPageMetric.tracked_date == today,
                ).delete()
                for m in metrics:
                    session.add(GAPageMetric(
                        project_id=project_id,
                        page_path=m.page_path,
                        active_users=m.active_users,
                        sessions=m.sessions,
                        avg_engagement_time_sec=m.avg_engagement_time_sec,
                        bounce_rate=m.bounce_rate,
                        conversions=m.conversions,
                        tracked_date=today,
                    ))
                session.commit()
                total_rows += len(metrics)
            logger.info(f"[GA4Sync] project={project_id} 同步 {len(metrics)} 筆頁面指標")
        except Exception as exc:
            logger.warning(f"[GA4Sync] project={project_id} 失敗：{exc}")

    logger.info(f"[GA4Sync] 全部完成，共 {total_rows} 筆")


@with_retry(max_retries=2)
async def run_competitor_serp_check() -> None:
    """每週一 04:00 — 追蹤競品 SERP 排名變化，寫入 CompetitorSnapshot。"""
    import asyncio
    from datetime import date
    from contentflow.tools.serp import search_serp
    from contentflow.models.database import Competitor, SEORanking, CompetitorSnapshot, Project

    today = date.today()

    with SessionLocal() as session:
        competitors = session.query(Competitor).all()
        comp_data = [(c.id, c.project_id, c.brand_name, c.website) for c in competitors]

        # 取得每個專案的主要追蹤關鍵字（最多 5 個/專案）
        project_keywords: dict[int, list[str]] = {}
        for _cid, pid, _bname, _website in comp_data:
            if pid not in project_keywords:
                kws = (
                    session.query(SEORanking.keyword)
                    .filter(SEORanking.project_id == pid)
                    .group_by(SEORanking.keyword)
                    .limit(5)
                    .all()
                )
                project_keywords[pid] = [k[0] for k in kws if k[0]]

        projects = {p.id: p.brand_url for p in session.query(Project).all()}

    snapshots_added = 0
    for comp_id, project_id, brand_name, website in comp_data:
        keywords = project_keywords.get(project_id, [])
        if not keywords or not website:
            continue

        comp_domain = website.replace("https://", "").replace("http://", "").strip("/")
        our_domain = (projects.get(project_id) or "").replace("https://", "").replace("http://", "").strip("/")

        for keyword in keywords:
            try:
                analysis = await search_serp(keyword, num_results=20, gl="tw", hl="zh-tw")

                comp_position: float | None = None
                comp_url = ""
                our_position: float | None = None

                for r in analysis.top_results:
                    if comp_domain and comp_domain in r.url:
                        comp_position = float(r.position)
                        comp_url = r.url
                    if our_domain and our_domain in r.url:
                        our_position = float(r.position)

                with SessionLocal() as session:
                    session.add(CompetitorSnapshot(
                        project_id=project_id,
                        competitor_id=comp_id,
                        keyword=keyword,
                        position=comp_position,
                        url=comp_url,
                        our_position=our_position,
                        tracked_date=today,
                    ))
                    session.commit()
                    snapshots_added += 1

                await asyncio.sleep(1)  # 避免 SERP API 過度請求
            except Exception as exc:
                logger.warning(f"[CompetitorSERP] kw='{keyword}' comp='{brand_name}' 失敗：{exc}")

    logger.info(f"[CompetitorSERP] 完成，新增 {snapshots_added} 筆競品快照")


@with_retry(max_retries=2)
async def run_attribution_engine() -> None:
    """每週一 05:00 — 文章表現歸因分析，計算 A-F 等級和推薦動作。"""
    from contentflow.agents.analytics_agent import AttributionEngine
    from contentflow.models.database import Project, Article

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    total_analyzed = 0
    for project_id in project_ids:
        try:
            with SessionLocal() as session:
                engine = AttributionEngine(session)
                performances = engine.get_project_performance(project_id)
                # 把 eeat_score (used as a stand-in for performance grade) 回寫到文章
                for perf in performances:
                    article = session.get(Article, perf.article_id)
                    if article:
                        # Store grade as numeric: A=95, B=80, C=60, D=40, F=20
                        grade_map = {"A": 95, "B": 80, "C": 60, "D": 40, "F": 20}
                        article.eeat_score = grade_map.get(perf.performance_grade, 50)
                        session.commit()
                total_analyzed += len(performances)
                logger.info(f"[Attribution] project={project_id}，分析 {len(performances)} 篇文章")
        except Exception as exc:
            logger.warning(f"[Attribution] project={project_id} 失敗：{exc}")

    logger.info(f"[Attribution] 完成，共分析 {total_analyzed} 篇文章")


@with_retry(max_retries=2)
async def check_refresh_triggers() -> None:
    """每週二 04:00 — 檢查 Content Refresh 觸發條件，回寫 last_refresh_date 建議。"""
    from contentflow.agents.analytics_agent import RefreshTriggerChecker, CannibalizationDetector
    from contentflow.models.database import Project, Article, KnowledgeEntry

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    total_refresh = 0
    total_cannibal = 0

    for project_id in project_ids:
        try:
            with SessionLocal() as session:
                # Refresh 觸發
                checker = RefreshTriggerChecker(session)
                recommendations = checker.check_project(project_id)
                for rec in recommendations:
                    # 標記需要 refresh 的文章（寫入 KnowledgeEntry 作為待辦）
                    existing = session.query(KnowledgeEntry).filter(
                        KnowledgeEntry.project_id == project_id,
                        KnowledgeEntry.category == "refresh_priority",
                        KnowledgeEntry.pattern.contains(f"article_id:{rec.article_id}"),
                    ).first()
                    if not existing:
                        import json as _json
                        session.add(KnowledgeEntry(
                            project_id=project_id,
                            category="refresh_priority",
                            pattern=f"article_id:{rec.article_id} — {rec.trigger_reason}",
                            evidence_count=1,
                            confidence_level="unverified",
                            metadata_json=_json.dumps({
                                "article_id": rec.article_id,
                                "title": rec.article_title,
                                "priority": rec.priority,
                                "current_rank": rec.current_rank,
                            }),
                        ))
                session.commit()
                total_refresh += len(recommendations)

                # 自蝕偵測
                cannibal = CannibalizationDetector(session)
                pairs = cannibal.detect(project_id)
                for pair in pairs:
                    existing = session.query(KnowledgeEntry).filter(
                        KnowledgeEntry.project_id == project_id,
                        KnowledgeEntry.category == "cannibalization",
                        KnowledgeEntry.pattern.contains(pair.keyword),
                    ).first()
                    if not existing:
                        import json as _json
                        session.add(KnowledgeEntry(
                            project_id=project_id,
                            category="cannibalization",
                            pattern=f"關鍵字「{pair.keyword}」有 {len(pair.article_ids)} 篇文章互競 — {pair.suggestion}",
                            evidence_count=len(pair.article_ids),
                            confidence_level="verified",
                            metadata_json=_json.dumps({
                                "keyword": pair.keyword,
                                "article_ids": pair.article_ids,
                                "urls": pair.article_urls,
                            }),
                        ))
                session.commit()
                total_cannibal += len(pairs)

                logger.info(f"[RefreshCheck] project={project_id}：{len(recommendations)} Refresh 建議，{len(pairs)} 自蝕偵測")
        except Exception as exc:
            logger.warning(f"[RefreshCheck] project={project_id} 失敗：{exc}")

    logger.info(f"[RefreshCheck] 完成：{total_refresh} Refresh 建議，{total_cannibal} 自蝕")


@with_retry(max_retries=1)
async def run_l1_pattern_analysis() -> None:
    """每月 1 號 06:00 — L1 成功模式學習，分析文章屬性 vs 排名。"""
    from contentflow.agents.learning_agent import analyze_success_patterns
    from contentflow.models.database import Project

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    total_patterns = 0
    for project_id in project_ids:
        try:
            with SessionLocal() as session:
                report = analyze_success_patterns(project_id, session)
                total_patterns += len(report.patterns)
                logger.info(f"[L1Learn] project={project_id}，發現 {len(report.patterns)} 個成功模式，分析 {report.analyzed_articles} 篇文章")
        except Exception as exc:
            logger.warning(f"[L1Learn] project={project_id} 失敗：{exc}")

    logger.info(f"[L1Learn] 完成，共發現 {total_patterns} 個模式")


@with_retry(max_retries=1)
async def run_l2_roi_analysis() -> None:
    """每月 1 號 07:00 — L2 ROI 分析，找出高/低 ROI 關鍵字，更新策略建議。"""
    from contentflow.agents.learning_agent import optimize_content_strategy
    from contentflow.models.database import Project

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    for project_id in project_ids:
        try:
            with SessionLocal() as session:
                update = optimize_content_strategy(project_id, session)
                high = len(update.high_roi_keywords) if update.high_roi_keywords else 0
                low = len(update.low_roi_keywords) if update.low_roi_keywords else 0
                logger.info(f"[L2Learn] project={project_id}，高 ROI={high}，低 ROI={low}")
        except Exception as exc:
            logger.warning(f"[L2Learn] project={project_id} 失敗：{exc}")

    logger.info("[L2Learn] L2 ROI 分析完成")


@with_retry(max_retries=2)
async def run_auto_pipeline() -> None:
    """每日 08:00 — 三層架構入口：Strategic Agent 規劃 → Tactical Pipeline 執行。

    流程：
    1. 對每個專案呼叫 Strategic Agent 產出當日計畫
    2. 依計畫執行 generate / refresh / alert actions
    3. Pipeline 完成後自動觸發 Reflective Loop（在 orchestrator 內建）
    """
    from contentflow.models.database import Project
    from contentflow.agents.strategic_agent import run_strategic_agent, execute_strategic_plan

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    if not project_ids:
        logger.info("[AutoPipeline] 無專案")
        return

    for project_id in project_ids:
        try:
            # Strategic Agent：決定今天要做什麼
            plan = await run_strategic_agent(project_id)
            logger.info(
                f"[AutoPipeline] project={project_id} 計畫：{plan.total_count} 項 action"
            )

            if plan.total_count > 0 and plan.status == "pending":
                # Tactical Pipeline：按計畫執行
                await execute_strategic_plan(plan.id)
        except Exception as exc:
            logger.error(f"[AutoPipeline] project={project_id} 失敗：{exc}")

    logger.info("[AutoPipeline] 三層架構每日執行完成")


@with_retry(max_retries=1)
async def run_weekly_reflection() -> None:
    """每週日 08:00 — 週級反思：L1/L2 跨文章學習，更新知識庫與寫作規範。"""
    from contentflow.models.database import Project
    from contentflow.agents.reflective_agent import reflect_weekly

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    for project_id in project_ids:
        try:
            await reflect_weekly(project_id)
            logger.info(f"[WeeklyReflection] project={project_id} 完成")
        except Exception as exc:
            logger.warning(f"[WeeklyReflection] project={project_id} 失敗：{exc}")

    logger.info("[WeeklyReflection] 全部專案週級反思完成")


@with_retry(max_retries=1)
async def send_weekly_report() -> None:
    """每週日 09:00 — 彙整週報 KPI 並推送 Slack 通知。

    彙整最近 7 天的 GSC、文章發布量、SEO 分數均值，
    使用 Slack Webhook 傳送摘要（需設定 SLACK_WEBHOOK_URL）。
    """
    from contentflow.models.database import Article, SEORanking
    import httpx

    slack_url = getattr(settings, "slack_webhook_url", None)
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    with SessionLocal() as session:
        # Articles published this week
        published_this_week = (
            session.query(Article)
            .filter(Article.status == "published", Article.updated_at >= week_ago)
            .count()
        )
        # Average SEO score
        avg_seo_q = (
            session.query(func.avg(SEORanking.position).label("avg_pos"),
                          func.sum(SEORanking.clicks).label("total_clicks"),
                          func.sum(SEORanking.impressions).label("total_imp"))
            .filter(SEORanking.tracked_date >= week_ago.date())
            .first()
        )
        avg_pos = round(float(avg_seo_q.avg_pos), 1) if avg_seo_q and avg_seo_q.avg_pos else None
        total_clicks = int(avg_seo_q.total_clicks or 0) if avg_seo_q else 0
        total_imp = int(avg_seo_q.total_impressions or 0) if avg_seo_q else 0

        planned_count = session.query(Article).filter(Article.status == "planned").count()
        writing_count = session.query(Article).filter(Article.status == "writing").count()

    report_lines = [
        f"*📊 ContentFlow 週報 — {now.strftime('%Y/%m/%d')}*",
        "",
        f"• 本週發布文章：*{published_this_week}* 篇",
        f"• GSC 點擊數（7天）：*{total_clicks:,}*",
        f"• GSC 曝光數（7天）：*{total_imp:,}*",
        f"• 平均排名：*{avg_pos or '—'}*",
        f"• 待撰寫：{writing_count} 篇 | 待規劃：{planned_count} 篇",
        "",
        f"🔗 <{settings.admin_url}/admin/reports|查看完整報告>",
    ]
    report_text = "\n".join(report_lines)
    logger.info(f"[WeeklyReport] {report_text}")

    if slack_url:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(slack_url, json={"text": report_text})
                if resp.status_code == 200:
                    logger.info("[WeeklyReport] ✅ Slack 通知已發送")
                else:
                    logger.warning(f"[WeeklyReport] Slack 回應異常: {resp.status_code}")
        except Exception as e:
            logger.error(f"[WeeklyReport] Slack 發送失敗: {e}")
    else:
        logger.info("[WeeklyReport] 未設定 SLACK_WEBHOOK_URL，跳過推播")


@with_retry(max_retries=2)
async def backfill_action_outcomes() -> None:
    """每日 04:00 — 回填 ActionOutcome 的 7d / 14d / 28d GSC 數據。

    掃描所有未完成的 ActionOutcome，根據距離 action_date 的天數
    查詢 GSC 排名數據回填，並在 28d 完成後判定 success_flag。
    """
    from datetime import date
    from contentflow.models.database import ActionOutcome, SEORanking

    today = date.today()

    with SessionLocal() as session:
        # 找出所有 checked_28d_at 為 NULL（尚未完成 28 天追蹤）的 outcome
        pending = (
            session.query(ActionOutcome)
            .filter(ActionOutcome.checked_28d_at.is_(None))
            .all()
        )

        if not pending:
            logger.info("[OutcomeBackfill] 無待回填的 ActionOutcome")
            return

        filled_count = 0
        for outcome in pending:
            days_since = (today - outcome.action_date).days
            kw = outcome.primary_keyword
            project_id = outcome.project_id

            # 查詢指定時間窗口的 GSC 平均排名
            def _avg_gsc(target_date):
                """取 target_date ±2 天窗口的 GSC 平均數據。"""
                window_start = target_date - timedelta(days=2)
                window_end = target_date + timedelta(days=2)
                rows = (
                    session.query(
                        func.avg(SEORanking.position),
                        func.sum(SEORanking.impressions),
                        func.sum(SEORanking.clicks),
                        func.avg(SEORanking.ctr),
                    )
                    .filter(
                        SEORanking.project_id == project_id,
                        SEORanking.keyword == kw,
                        SEORanking.tracked_date >= window_start,
                        SEORanking.tracked_date <= window_end,
                    )
                    .first()
                )
                if rows and rows[0] is not None:
                    return {
                        "rank": round(float(rows[0]), 1),
                        "impressions": int(rows[1] or 0),
                        "clicks": int(rows[2] or 0),
                        "ctr": round(float(rows[3] or 0), 4),
                    }
                return None

            now_ts = datetime.now(timezone.utc)

            # 7 天回填
            if days_since >= 7 and outcome.checked_7d_at is None:
                data = _avg_gsc(outcome.action_date + timedelta(days=7))
                if data:
                    outcome.rank_after_7d = data["rank"]
                    outcome.impressions_after_7d = data["impressions"]
                    outcome.clicks_after_7d = data["clicks"]
                    outcome.ctr_after_7d = data["ctr"]
                    outcome.checked_7d_at = now_ts
                    filled_count += 1

            # 14 天回填
            if days_since >= 14 and outcome.checked_14d_at is None:
                data = _avg_gsc(outcome.action_date + timedelta(days=14))
                if data:
                    outcome.rank_after_14d = data["rank"]
                    outcome.impressions_after_14d = data["impressions"]
                    outcome.clicks_after_14d = data["clicks"]
                    outcome.ctr_after_14d = data["ctr"]
                    outcome.checked_14d_at = now_ts
                    filled_count += 1

            # 28 天回填 + 成效判定
            if days_since >= 28 and outcome.checked_28d_at is None:
                data = _avg_gsc(outcome.action_date + timedelta(days=28))
                if data:
                    outcome.rank_after_28d = data["rank"]
                    outcome.impressions_after_28d = data["impressions"]
                    outcome.clicks_after_28d = data["clicks"]
                    outcome.ctr_after_28d = data["ctr"]
                    outcome.checked_28d_at = now_ts

                    # 成效判定
                    if outcome.baseline_rank is not None:
                        delta = data["rank"] - outcome.baseline_rank
                        outcome.rank_delta = round(delta, 1)
                        if delta <= -3:
                            outcome.success_flag = "improved"
                            outcome.learning_confidence = "high"
                        elif delta <= 0:
                            outcome.success_flag = "improved"
                            outcome.learning_confidence = "medium"
                        elif delta <= 3:
                            outcome.success_flag = "stable"
                            outcome.learning_confidence = "medium"
                        else:
                            outcome.success_flag = "declined"
                            outcome.learning_confidence = "high"
                    else:
                        # 新文章：有排名就算成功
                        if data["rank"] <= 50:
                            outcome.success_flag = "improved"
                            outcome.learning_confidence = "medium"
                        else:
                            outcome.success_flag = "stable"
                            outcome.learning_confidence = "low"

                    filled_count += 1

        session.commit()

    logger.info(f"[OutcomeBackfill] 回填完成：{filled_count} 筆更新，{len(pending)} 筆追蹤中")


def record_action_outcome(
    *,
    project_id: int,
    article_id: int,
    run_id: str | None = None,
    strategic_plan_id: int | None = None,
    action_type: str,
    primary_keyword: str,
) -> None:
    """在 pipeline 完成後記錄一筆 ActionOutcome，同時抓取當前 GSC baseline。

    由 strategic_agent._execute_generate / _execute_refresh 呼叫。
    """
    from datetime import date
    from contentflow.models.database import ActionOutcome, SEORanking

    today = date.today()
    with SessionLocal() as session:
        # 取得當前 GSC 基線（最近 7 天平均）
        week_ago = today - timedelta(days=7)
        baseline = (
            session.query(
                func.avg(SEORanking.position),
                func.sum(SEORanking.impressions),
                func.sum(SEORanking.clicks),
                func.avg(SEORanking.ctr),
            )
            .filter(
                SEORanking.project_id == project_id,
                SEORanking.keyword == primary_keyword,
                SEORanking.tracked_date >= week_ago,
            )
            .first()
        )

        outcome = ActionOutcome(
            project_id=project_id,
            article_id=article_id,
            run_id=run_id,
            strategic_plan_id=strategic_plan_id,
            action_type=action_type,
            action_date=today,
            primary_keyword=primary_keyword,
            baseline_rank=round(float(baseline[0]), 1) if baseline and baseline[0] else None,
            baseline_impressions=int(baseline[1] or 0) if baseline else None,
            baseline_clicks=int(baseline[2] or 0) if baseline else None,
            baseline_ctr=round(float(baseline[3] or 0), 4) if baseline else None,
            success_flag="too_early",
        )
        session.add(outcome)
        session.commit()
        logger.info(
            f"[ActionOutcome] 記錄 {action_type} kw='{primary_keyword}' "
            f"baseline_rank={outcome.baseline_rank}"
        )


async def check_ranking_drops() -> None:
    """每週三 06:00 — 核心演算法更新偵測：比對排名 7天 vs 前7天，退步 ≥5 名發送 Slack 警報。

    Section 18：演算法應對 SOP
    - 若發現批量關鍵字退步（≥5 個關鍵字退步 ≥5 名），視為 Core Update 訊號
    - 自動推送 Slack 預警，並建議執行 Content Refresh
    """
    from contentflow.models.database import SEORanking
    import httpx

    slack_url = getattr(settings, "slack_webhook_url", None)
    now = datetime.now(timezone.utc)
    cutoff_curr = (now - timedelta(days=7)).date()
    cutoff_prev = (now - timedelta(days=14)).date()

    with SessionLocal() as session:
        curr_ranks = {
            row.keyword: float(row.avg_pos)
            for row in session.query(
                SEORanking.keyword,
                func.avg(SEORanking.position).label("avg_pos"),
            ).filter(SEORanking.tracked_date >= cutoff_curr).group_by(SEORanking.keyword).all()
            if row.avg_pos
        }

        prev_ranks = {
            row.keyword: float(row.avg_pos)
            for row in session.query(
                SEORanking.keyword,
                func.avg(SEORanking.position).label("avg_pos"),
            ).filter(
                SEORanking.tracked_date >= cutoff_prev,
                SEORanking.tracked_date < cutoff_curr,
            ).group_by(SEORanking.keyword).all()
            if row.avg_pos
        }

    drops = []
    for kw, curr in curr_ranks.items():
        if kw in prev_ranks:
            delta = curr - prev_ranks[kw]
            if delta >= 5:
                drops.append((kw, round(prev_ranks[kw], 1), round(curr, 1), round(delta, 1)))

    drops.sort(key=lambda x: x[3], reverse=True)
    logger.info(f"[RankDrop] 偵測到 {len(drops)} 個關鍵字排名退步 ≥5 名")

    if len(drops) >= 5:
        # 批量退步 → 疑似 Core Update
        lines = [
            f"*⚠️ ContentFlow — 排名異動預警 {now.strftime('%Y/%m/%d')}*",
            f"偵測到 *{len(drops)} 個*關鍵字在過去 7 天內排名退步 ≥5 名，可能受 Google Core Update 影響。",
            "",
        ]
        for kw, prev, curr, delta in drops[:8]:
            lines.append(f"• `{kw}` #{prev} → #{curr} (*↓{delta}*)")
        lines.extend([
            "",
            "建議動作：",
            "1. 確認 Google Search Central 是否公告 Core Update",
            "2. 至競品追蹤頁面比對競品排名",
            "3. 對退步幅度最大的文章執行 Content Refresh",
        ])
        alert_text = "\n".join(lines)
        logger.warning(f"[RankDrop] Core Update 疑似訊號！{alert_text}")
        if slack_url:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(slack_url, json={"text": alert_text})
                    logger.info("[RankDrop] ✅ 排名異動 Slack 警報已發送")
            except Exception as e:
                logger.error(f"[RankDrop] Slack 發送失敗: {e}")
    elif drops:
        logger.info(f"[RankDrop] 退步關鍵字 < 5 個（{len(drops)}），非批量退步，不發送警報")


# ── 排程設定進入點 ────────────────────────────────────────────

def schedule_all_jobs() -> None:
    """註冊全部排程任務。由 site_app startup 呼叫。"""
    global _scheduler_lock_fd

    if not settings.scheduler_enabled:
        logger.info("[Scheduler] SCHEDULER_ENABLED=false，跳過排程初始化")
        return

    # 多 worker 部署：用檔案鎖確保只有一個 process 啟動排程
    try:
        _scheduler_lock_fd = open("/tmp/contentflow_scheduler.lock", "w")
        fcntl.flock(_scheduler_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _scheduler_lock_fd.write(str(os.getpid()))
        _scheduler_lock_fd.flush()
    except (IOError, OSError):
        logger.info("[Scheduler] 另一個 worker 已持有排程鎖，跳過")
        return

    scheduler.add_job(sync_gsc_all_projects,      CronTrigger(hour=3,  minute=0),                              id="gsc_sync",        replace_existing=True)
    scheduler.add_job(sync_ga4_all_projects,       CronTrigger(hour=3,  minute=30),                             id="ga4_sync",        replace_existing=True)
    scheduler.add_job(backfill_action_outcomes,     CronTrigger(hour=4,  minute=0),                              id="outcome_backfill", replace_existing=True)
    scheduler.add_job(run_competitor_serp_check,   CronTrigger(day_of_week="mon", hour=4, minute=30),           id="competitor_serp", replace_existing=True)
    scheduler.add_job(run_attribution_engine,      CronTrigger(day_of_week="mon", hour=5, minute=0),            id="attribution",     replace_existing=True)
    scheduler.add_job(check_refresh_triggers,      CronTrigger(day_of_week="tue", hour=4, minute=0),            id="refresh_check",   replace_existing=True)
    scheduler.add_job(run_l1_pattern_analysis,     CronTrigger(day=1,   hour=6,  minute=0),                     id="l1_learn",        replace_existing=True)
    scheduler.add_job(run_l2_roi_analysis,         CronTrigger(day=1,   hour=7,  minute=0),                     id="l2_learn",        replace_existing=True)
    scheduler.add_job(run_auto_pipeline,           CronTrigger(hour=8,  minute=0),                              id="auto_pipeline",   replace_existing=True)
    scheduler.add_job(run_weekly_reflection,        CronTrigger(day_of_week="sun", hour=8, minute=0),            id="weekly_reflection", replace_existing=True)
    scheduler.add_job(send_weekly_report,          CronTrigger(day_of_week="sun", hour=9, minute=0),            id="weekly_report",   replace_existing=True)
    scheduler.add_job(check_ranking_drops,         CronTrigger(day_of_week="wed", hour=6, minute=0),            id="ranking_drops",   replace_existing=True)

    scheduler.start()
    logger.info(f"[Scheduler] 已啟動 {len(scheduler.get_jobs())} 個排程任務")
