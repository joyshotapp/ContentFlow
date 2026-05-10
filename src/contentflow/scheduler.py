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
import json
import os
import re
import time
import traceback
from datetime import datetime, timezone, timedelta
from functools import wraps
from pathlib import Path
from statistics import median
from typing import Callable, Awaitable

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

# 跨 process 排程鎖（多 worker 部署時只讓一個 worker 啟動排程）
_scheduler_lock_fd = None

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
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


def _scheduler_heartbeat_path() -> Path:
    return Path(settings.scheduler_heartbeat_path)


def _write_scheduler_heartbeat(reason: str) -> None:
    """更新 scheduler heartbeat，供跨 container 健康檢查使用。"""
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "reason": reason,
    }
    heartbeat_path = _scheduler_heartbeat_path()
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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


async def _scheduler_heartbeat_job() -> None:
    _write_scheduler_heartbeat("tick")


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


def _normalize_url_path(url: str) -> str:
    if not url:
        return ""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = (parsed.path or url).strip()
    if not path:
        return ""
    if not path.startswith("/"):
        path = f"/{path.lstrip('/')}"
    return path.rstrip("/") or "/"


def _get_gsc_snapshot(
    session,
    project_id: int,
    keyword: str,
    target_date,
    *,
    landing_page: str | None = None,
    window_days: int = 2,
):
    from contentflow.models.database import SEORanking

    window_start = target_date - timedelta(days=window_days)
    window_end = target_date + timedelta(days=window_days)
    rows = (
        session.query(SEORanking)
        .filter(
            SEORanking.project_id == project_id,
            SEORanking.keyword == keyword,
            SEORanking.tracked_date >= window_start,
            SEORanking.tracked_date <= window_end,
        )
        .all()
    )
    if not rows:
        return None

    target_path = _normalize_url_path(landing_page or "")
    if target_path:
        path_rows = [row for row in rows if _normalize_url_path(row.landing_page or "") == target_path]
        if path_rows:
            rows = path_rows

    latest_date = max((row.tracked_date for row in rows if row.tracked_date), default=None)
    if latest_date is None:
        return None

    latest_rows = [row for row in rows if row.tracked_date == latest_date]
    positions = [float(row.position) for row in latest_rows if row.position is not None]
    impressions = sum(int(row.impressions or 0) for row in latest_rows)
    clicks = sum(int(row.clicks or 0) for row in latest_rows)
    ctr = round((clicks / impressions), 4) if impressions > 0 else 0.0

    return {
        "rank": round(sum(positions) / len(positions), 1) if positions else None,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "tracked_date": latest_date,
    }


def _classify_outcome_success(outcome, snapshot: dict[str, object]) -> tuple[str, str, float | None]:
    rank = snapshot.get("rank")
    if rank is None:
        return "stable", "low", None

    if outcome.baseline_rank is None:
        if rank <= 50:
            return "improved", "medium", None
        return "stable", "low", None

    rank_delta = round(float(rank) - float(outcome.baseline_rank), 1)
    click_delta = int(snapshot.get("clicks", 0) or 0) - int(outcome.baseline_clicks or 0)
    ctr_delta = round(float(snapshot.get("ctr", 0.0) or 0.0) - float(outcome.baseline_ctr or 0.0), 4)

    if rank_delta <= -3:
        return "improved", "high", rank_delta
    if rank_delta <= 0 and (click_delta > 0 or ctr_delta >= 0.01):
        return "improved", "medium", rank_delta
    if rank_delta <= 3 and (click_delta >= 0 or ctr_delta >= 0.0):
        return "stable", "medium", rank_delta
    return "declined", "high", rank_delta


def _evaluation_weight(outcome) -> float:
    confidence_weight = {
        "low": 0.75,
        "medium": 1.0,
        "high": 1.25,
    }.get((outcome.learning_confidence or "low").lower(), 0.75)
    traffic_reference = max(
        int(outcome.baseline_impressions or 0),
        int(outcome.impressions_after_28d or 0),
    )
    traffic_weight = 1.0 + min(0.35, traffic_reference / 800.0)
    rank_delta = abs(float(outcome.rank_delta or 0.0))
    rank_weight = 1.0 + min(rank_delta, 10.0) * 0.03
    return round(confidence_weight * traffic_weight * rank_weight, 4)


def _evaluation_clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _outcome_effects(outcome) -> dict[str, float | None]:
    rank_delta = float(outcome.rank_delta) if outcome.rank_delta is not None else None

    baseline_clicks_raw = getattr(outcome, "baseline_clicks", None)
    after_clicks_raw = getattr(outcome, "clicks_after_28d", None)
    if baseline_clicks_raw is None and after_clicks_raw is None:
        click_delta = None
    else:
        click_delta = int(after_clicks_raw or 0) - int(baseline_clicks_raw or 0)

    baseline_ctr_raw = getattr(outcome, "baseline_ctr", None)
    after_ctr_raw = getattr(outcome, "ctr_after_28d", None)
    if baseline_ctr_raw is None and after_ctr_raw is None:
        ctr_delta = None
    else:
        ctr_delta = round(float(after_ctr_raw or 0.0) - float(baseline_ctr_raw or 0.0), 4)

    return {
        "rank_delta": rank_delta,
        "click_delta": click_delta,
        "ctr_delta": ctr_delta,
    }


def _control_baseline(outcomes) -> dict[str, float]:
    rank_deltas: list[float] = []
    click_deltas: list[float] = []
    ctr_deltas: list[float] = []

    for outcome in outcomes:
        effects = _outcome_effects(outcome)
        if effects["rank_delta"] is not None:
            rank_deltas.append(float(effects["rank_delta"]))
        if effects["click_delta"] is not None:
            click_deltas.append(float(effects["click_delta"]))
        if effects["ctr_delta"] is not None:
            ctr_deltas.append(float(effects["ctr_delta"]))

    return {
        "rank_delta_median": round(float(median(rank_deltas)), 3) if rank_deltas else 0.0,
        "click_delta_median": round(float(median(click_deltas)), 3) if click_deltas else 0.0,
        "ctr_delta_median": round(float(median(ctr_deltas)), 4) if ctr_deltas else 0.0,
    }


def _build_outcome_evaluation_snapshot(outcome, reference_outcomes) -> dict[str, float | None]:
    effects = _outcome_effects(outcome)
    baseline = _control_baseline(reference_outcomes)

    rank_advantage = 0.0 if effects["rank_delta"] is None else baseline["rank_delta_median"] - float(effects["rank_delta"])
    click_advantage = 0.0 if effects["click_delta"] is None else float(effects["click_delta"]) - baseline["click_delta_median"]
    ctr_advantage = 0.0 if effects["ctr_delta"] is None else float(effects["ctr_delta"]) - baseline["ctr_delta_median"]

    rank_component = _evaluation_clamp(rank_advantage / 5.0)
    click_component = _evaluation_clamp(click_advantage / 10.0)
    ctr_component = _evaluation_clamp(ctr_advantage / 0.015)
    control_adjustment = (rank_component * 0.35) + (click_component * 0.15) + (ctr_component * 0.2)

    return {
        "outcome_weight": _evaluation_weight(outcome),
        "rank_delta": round(float(effects["rank_delta"]), 3) if effects["rank_delta"] is not None else None,
        "click_delta": round(float(effects["click_delta"]), 3) if effects["click_delta"] is not None else None,
        "ctr_delta": round(float(effects["ctr_delta"]), 4) if effects["ctr_delta"] is not None else None,
        "control_rank_delta_median": baseline["rank_delta_median"],
        "control_click_delta_median": baseline["click_delta_median"],
        "control_ctr_delta_median": baseline["ctr_delta_median"],
        "rank_advantage_vs_baseline": round(rank_advantage, 3),
        "click_advantage_vs_baseline": round(click_advantage, 3),
        "ctr_advantage_vs_baseline": round(ctr_advantage, 4),
        "control_adjustment": round(control_adjustment, 3),
    }


# ── Retry wrapper ─────────────────────────────────────────────

def with_retry(max_retries: int = 3, base_delay: int = 300):
    """指數退避重試裝飾器（5min → 15min → 45min）。"""

    def decorator(fn: Callable[..., Awaitable]):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            job_name = fn.__name__
            started_at = datetime.now(timezone.utc)
            t0 = time.monotonic()

            _write_scheduler_heartbeat(f"job_start:{job_name}")

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
                    _write_scheduler_heartbeat(f"job_success:{job_name}")
                    logger.info(f"[Scheduler] ✅ {job_name} 完成（{duration:.1f}s）")
                    return
                except Exception as exc:
                    error_msg = str(exc)
                    tb = traceback.format_exc()
                    # 前幾次失敗用 exception() 記錄完整 traceback，方便 debug
                    logger.exception(f"[Scheduler] {job_name} 第 {attempt + 1} 次失敗：{error_msg}")
                    if attempt < max_retries:
                        delay = base_delay * (3 ** attempt)  # 5min, 15min, 45min
                        logger.info(f"[Scheduler] {job_name} {delay // 60}min 後重試")
                        await asyncio.sleep(delay)
                    else:
                        duration = time.monotonic() - t0
                        # 將 traceback 截短後存入 DB（Text 欄位上限約 50KB）
                        _write_log(
                            job_id=job_name,
                            job_name=job_name,
                            status="failed",
                            started_at=started_at,
                            retry_count=attempt,
                            error_message=(error_msg + "\n\n" + tb)[:4000],
                            duration_seconds=duration,
                        )
                        _write_scheduler_heartbeat(f"job_failed:{job_name}")
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

                    # CompetitorThreatDetector：偵測競品威脅並寫入知識庫
                    try:
                        from contentflow.agents.refresh_agent import CompetitorThreatDetector
                        from contentflow.models.database import KnowledgeEntry
                        import json as _json_ct
                        threat_detector = CompetitorThreatDetector()
                        threat_report = threat_detector.detect(
                            project_id, keyword, session, brand_url=our_domain
                        )
                        if threat_report.threats:
                            existing_threat = session.query(KnowledgeEntry).filter(
                                KnowledgeEntry.project_id == project_id,
                                KnowledgeEntry.category == "competitor_threat",
                                KnowledgeEntry.pattern.contains(keyword),
                            ).first()
                            if not existing_threat:
                                session.add(KnowledgeEntry(
                                    project_id=project_id,
                                    category="competitor_threat",
                                    pattern=f"關鍵字「{keyword}」有 {len(threat_report.threats)} 個競品威脅（排名快速上升）",
                                    evidence_count=len(threat_report.threats),
                                    confidence_level="verified",
                                    metadata_json=_json_ct.dumps({
                                        "keyword": keyword,
                                        "threats": threat_report.threats,
                                        "defense_suggestions": threat_report.defense_suggestions,
                                    }),
                                ))
                                session.commit()
                    except Exception as _ct_err:
                        logger.warning(f"[CompetitorSERP] CompetitorThreatDetector 失敗 kw='{keyword}'：{_ct_err}")

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
                for perf in performances:
                    article = session.get(Article, perf.article_id)
                    if article:
                        article.performance_grade = perf.performance_grade
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

                # Featured Snippet 偵測（取排名前 5 關鍵字）
                try:
                    from contentflow.agents.refresh_agent import FeaturedSnippetDetector
                    from contentflow.models.database import SEORanking
                    from sqlalchemy import func as _sqlfunc
                    snippet_detector = FeaturedSnippetDetector()
                    top_kws = (
                        session.query(SEORanking.keyword)
                        .filter(SEORanking.project_id == project_id, SEORanking.position <= 10)
                        .group_by(SEORanking.keyword)
                        .order_by(_sqlfunc.avg(SEORanking.position))
                        .limit(5)
                        .all()
                    )
                    for (kw,) in top_kws:
                        threat = snippet_detector.detect(project_id, kw, session)
                        if threat.featured_snippet_seized:
                            existing_fs = session.query(KnowledgeEntry).filter(
                                KnowledgeEntry.project_id == project_id,
                                KnowledgeEntry.category == "featured_snippet_lost",
                                KnowledgeEntry.pattern.contains(kw),
                            ).first()
                            if not existing_fs:
                                import json as _json2
                                session.add(KnowledgeEntry(
                                    project_id=project_id,
                                    category="featured_snippet_lost",
                                    pattern=f"關鍵字「{kw}」的 Featured Snippet 可能被競品搶走",
                                    evidence_count=1,
                                    confidence_level="unverified",
                                    metadata_json=_json2.dumps({
                                        "keyword": kw,
                                        "suggestions": threat.featured_snippet_suggestions,
                                    }),
                                ))
                    session.commit()
                except Exception as _fs_err:
                    logger.warning(f"[RefreshCheck] FeaturedSnippet 偵測失敗 project={project_id}：{_fs_err}")

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
    import httpx
    from contentflow.models.database import Project
    from contentflow.agents.reflective_agent import reflect_weekly

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    total_wr_updates = 0
    total_kb_updates = 0
    failed_projects = []

    for project_id in project_ids:
        try:
            log = await reflect_weekly(project_id)
            if log:
                total_wr_updates += log.writing_rule_updates or 0
                total_kb_updates += log.knowledge_updates or 0
            logger.info(f"[WeeklyReflection] project={project_id} 完成 WR+{log.writing_rule_updates if log else 0}")
        except Exception as exc:
            logger.warning(f"[WeeklyReflection] project={project_id} 失敗：{exc}")
            failed_projects.append(project_id)

    logger.info(
        f"[WeeklyReflection] 全部完成 WR+{total_wr_updates} KB+{total_kb_updates}"
        f" 失敗專案={failed_projects}"
    )

    # ── WritingRule 更新觀察：若本週完全無規範更新，發 Slack 警告 ──
    slack_url = getattr(settings, "slack_webhook_url", None)
    if slack_url and total_wr_updates == 0 and project_ids:
        try:
            msg = (
                "⚠️ *[ContentFlow 學習閉環警告]*\n"
                "本週週級反思完成，但 *0 條寫作規範* 被更新。\n"
                "可能原因：LLM 反思未輸出 `writing_rule_updates` 陣列，或反思品質不足。\n"
                f"請至 <{settings.admin_url}/admin/reflections|反思日誌> 確認 prompt 輸出。"
            )
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(slack_url, json={"text": msg})
            logger.warning("[WeeklyReflection] WritingRule 0 更新 — Slack 警告已發送")
        except Exception as e:
            logger.error(f"[WeeklyReflection] Slack 警告發送失敗：{e}")


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
        total_imp = int(avg_seo_q.total_imp or 0) if avg_seo_q else 0

        planned_count = session.query(Article).filter(Article.status == "planned").count()
        writing_count = session.query(Article).filter(Article.status == "writing").count()

        # 本週反思 WritingRule 更新計數
        from contentflow.models.database import ReflectionLog
        wr_total = (
            session.query(func.sum(ReflectionLog.writing_rule_updates))
            .filter(ReflectionLog.created_at >= week_ago)
            .scalar()
        ) or 0

    report_lines = [
        f"*📊 ContentFlow 週報 — {now.strftime('%Y/%m/%d')}*",
        "",
        f"• 本週發布文章：*{published_this_week}* 篇",
        f"• GSC 點擊數（7天）：*{total_clicks:,}*",
        f"• GSC 曝光數（7天）：*{total_imp:,}*",
        f"• 平均排名：*{avg_pos or '—'}*",
        f"• 待撰寫：{writing_count} 篇 | 待規劃：{planned_count} 篇",
        f"• 寫作規範本週更新：*{wr_total}* 條{'  ⚠️ 學習閉環無更新' if wr_total == 0 else ''}",
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
    from contentflow.models.database import ActionOutcome, ActionOutcomeEvaluation, Article

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
            article = session.get(Article, outcome.article_id)
            landing_page = article.publish_url if article else None

            now_ts = datetime.now(timezone.utc)

            # 7 天回填
            if days_since >= 7 and outcome.checked_7d_at is None:
                data = _get_gsc_snapshot(
                    session,
                    project_id,
                    kw,
                    outcome.action_date + timedelta(days=7),
                    landing_page=landing_page,
                )
                if data:
                    outcome.rank_after_7d = data["rank"]
                    outcome.impressions_after_7d = data["impressions"]
                    outcome.clicks_after_7d = data["clicks"]
                    outcome.ctr_after_7d = data["ctr"]
                    outcome.checked_7d_at = now_ts
                    filled_count += 1

            # 14 天回填
            if days_since >= 14 and outcome.checked_14d_at is None:
                data = _get_gsc_snapshot(
                    session,
                    project_id,
                    kw,
                    outcome.action_date + timedelta(days=14),
                    landing_page=landing_page,
                )
                if data:
                    outcome.rank_after_14d = data["rank"]
                    outcome.impressions_after_14d = data["impressions"]
                    outcome.clicks_after_14d = data["clicks"]
                    outcome.ctr_after_14d = data["ctr"]
                    outcome.checked_14d_at = now_ts
                    filled_count += 1

            # 28 天回填 + 成效判定
            if days_since >= 28 and outcome.checked_28d_at is None:
                data = _get_gsc_snapshot(
                    session,
                    project_id,
                    kw,
                    outcome.action_date + timedelta(days=28),
                    landing_page=landing_page,
                )
                if data:
                    outcome.rank_after_28d = data["rank"]
                    outcome.impressions_after_28d = data["impressions"]
                    outcome.clicks_after_28d = data["clicks"]
                    outcome.ctr_after_28d = data["ctr"]
                    outcome.checked_28d_at = now_ts

                    outcome.success_flag, outcome.learning_confidence, outcome.rank_delta = (
                        _classify_outcome_success(outcome, data)
                    )

                    evaluated_outcomes = (
                        session.query(ActionOutcome)
                        .filter(
                            ActionOutcome.project_id == project_id,
                            ActionOutcome.checked_28d_at.isnot(None),
                            ActionOutcome.success_flag.isnot(None),
                            ActionOutcome.success_flag != "too_early",
                        )
                        .all()
                    )
                    evaluation_snapshot = _build_outcome_evaluation_snapshot(outcome, evaluated_outcomes)
                    evaluation = (
                        session.query(ActionOutcomeEvaluation)
                        .filter(ActionOutcomeEvaluation.action_outcome_id == outcome.id)
                        .first()
                    )
                    if evaluation is None:
                        evaluation = ActionOutcomeEvaluation(
                            action_outcome_id=outcome.id,
                            project_id=outcome.project_id,
                            article_id=outcome.article_id,
                            action_type=outcome.action_type,
                            evaluation_window_days=28,
                        )
                        session.add(evaluation)

                    evaluation.outcome_weight = evaluation_snapshot["outcome_weight"]
                    evaluation.rank_delta = evaluation_snapshot["rank_delta"]
                    evaluation.click_delta = evaluation_snapshot["click_delta"]
                    evaluation.ctr_delta = evaluation_snapshot["ctr_delta"]
                    evaluation.control_rank_delta_median = evaluation_snapshot["control_rank_delta_median"]
                    evaluation.control_click_delta_median = evaluation_snapshot["control_click_delta_median"]
                    evaluation.control_ctr_delta_median = evaluation_snapshot["control_ctr_delta_median"]
                    evaluation.rank_advantage_vs_baseline = evaluation_snapshot["rank_advantage_vs_baseline"]
                    evaluation.click_advantage_vs_baseline = evaluation_snapshot["click_advantage_vs_baseline"]
                    evaluation.ctr_advantage_vs_baseline = evaluation_snapshot["ctr_advantage_vs_baseline"]
                    evaluation.control_adjustment = evaluation_snapshot["control_adjustment"]
                    evaluation.evaluated_at = now_ts

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
    from contentflow.models.database import ActionOutcome, Article

    today = date.today()
    with SessionLocal() as session:
        article = session.get(Article, article_id)
        baseline = _get_gsc_snapshot(
            session,
            project_id,
            primary_keyword,
            today,
            landing_page=article.publish_url if article else None,
        )

        outcome = ActionOutcome(
            project_id=project_id,
            article_id=article_id,
            run_id=run_id,
            strategic_plan_id=strategic_plan_id,
            action_type=action_type,
            action_date=today,
            primary_keyword=primary_keyword,
            baseline_rank=baseline.get("rank") if baseline else None,
            baseline_impressions=int(baseline.get("impressions", 0) or 0) if baseline else None,
            baseline_clicks=int(baseline.get("clicks", 0) or 0) if baseline else None,
            baseline_ctr=float(baseline.get("ctr", 0.0) or 0.0) if baseline else None,
            success_flag="too_early",
        )
        session.add(outcome)
        session.commit()
        logger.info(
            f"[ActionOutcome] 記錄 {action_type} kw='{primary_keyword}' "
            f"baseline_rank={outcome.baseline_rank}"
        )


@with_retry(max_retries=2)
async def check_ranking_drops() -> None:
    """每週三 06:00 — 核心演算法更新偵測：比對排名 7天 vs 前7天，退步 ≥5 名發送 Slack 警報。

    Section 18：演算法應對 SOP
    - 若發現批量關鍵字退步（≥5 個關鍵字退步 ≥5 名），視為 Core Update 訊號
    - 自動推送 Slack 預警，並建議執行 Content Refresh
    """
    from contentflow.models.database import SEORanking, Project
    import httpx

    slack_url = getattr(settings, "slack_webhook_url", None)
    now = datetime.now(timezone.utc)
    cutoff_curr = (now - timedelta(days=7)).date()
    cutoff_prev = (now - timedelta(days=14)).date()

    with SessionLocal() as session:
        project_ids = [p.id for p in session.query(Project).all()]

    all_drops: list[tuple] = []
    for project_id in project_ids:
        with SessionLocal() as session:
            curr_ranks = {
                row.keyword: float(row.avg_pos)
                for row in session.query(
                    SEORanking.keyword,
                    func.avg(SEORanking.position).label("avg_pos"),
                ).filter(
                    SEORanking.project_id == project_id,
                    SEORanking.tracked_date >= cutoff_curr,
                ).group_by(SEORanking.keyword).all()
                if row.avg_pos
            }

            prev_ranks = {
                row.keyword: float(row.avg_pos)
                for row in session.query(
                    SEORanking.keyword,
                    func.avg(SEORanking.position).label("avg_pos"),
                ).filter(
                    SEORanking.project_id == project_id,
                    SEORanking.tracked_date >= cutoff_prev,
                    SEORanking.tracked_date < cutoff_curr,
                ).group_by(SEORanking.keyword).all()
                if row.avg_pos
            }

        drops_for_project = []
        for kw, curr in curr_ranks.items():
            if kw in prev_ranks:
                delta = curr - prev_ranks[kw]
                if delta >= 5:
                    drops_for_project.append((kw, round(prev_ranks[kw], 1), round(curr, 1), round(delta, 1)))
        all_drops.extend(drops_for_project)

    all_drops.sort(key=lambda x: x[3], reverse=True)
    drops = all_drops
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


@with_retry(max_retries=1)
async def run_render_verification() -> None:
    """每日 10:00 — 驗證前 2 小時內發布的文章是否含所有必要 SEO 元素。

    對有缺失的文章發 Slack 告警。不寫新 DB 表。
    """
    from contentflow.models.database import Article
    from contentflow.tools.render_verify import verify_rendered_html

    cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
    with SessionLocal() as session:
        articles = (
            session.query(Article)
            .filter(
                Article.published_at >= cutoff,
                Article.publish_url.isnot(None),
                Article.publish_url != "",
            )
            .all()
        )
        targets = [(a.id, a.title, a.publish_url) for a in articles]

    if not targets:
        logger.info("[RenderVerify] 最近 2 小時無新發布文章")
        return

    logger.info(f"[RenderVerify] 驗證 {len(targets)} 篇文章")
    slack_url = settings.slack_webhook_url
    failed_count = 0

    for art_id, art_title, pub_url in targets:
        issues = await verify_rendered_html(pub_url)
        if issues:
            failed_count += 1
            msg = (
                f"⚠️ *[Render Verify]* 《{art_title}》發布後 SEO 元素缺失\n"
                f"URL: {pub_url}\n"
                f"缺失項目：{', '.join(issues)}"
            )
            logger.warning(f"[RenderVerify] #{art_id} '{art_title}' — {issues}")
            if slack_url:
                try:
                    async with httpx.AsyncClient(timeout=10) as client:
                        await client.post(slack_url, json={"text": msg})
                except Exception as exc:
                    logger.warning(f"[RenderVerify] Slack 發送失敗：{exc}")
        else:
            logger.info(f"[RenderVerify] ✅ #{art_id} '{art_title}' 通過")

    logger.info(f"[RenderVerify] 完成，{failed_count}/{len(targets)} 篇有缺失")


async def _notify_google_indexing(url: str) -> None:
    """Google Indexing API 通知（best-effort，失敗不拋例外）。"""
    import httpx
    svc_file = settings.google_service_account_file
    if not svc_file or not url:
        return
    try:
        import google.oauth2.service_account as _sa
        import google.auth.transport.requests as _gtr
        _creds = _sa.Credentials.from_service_account_file(
            svc_file, scopes=["https://www.googleapis.com/auth/indexing"]
        )
        _creds.refresh(_gtr.Request())
        async with httpx.AsyncClient(timeout=20) as _hc:
            _r = await _hc.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={"Authorization": f"Bearer {_creds.token}", "Content-Type": "application/json"},
                json={"url": url, "type": "URL_UPDATED"},
            )
            if _r.status_code == 200:
                logger.info(f"[IndexingAPI] ✅ 提交成功：{url}")
            else:
                logger.warning(f"[IndexingAPI] 非 200 回應 {_r.status_code}：{_r.text[:100]}")
    except Exception as _ie:
        logger.debug(f"[IndexingAPI] 略過（non-fatal）：{_ie}")


@with_retry(max_retries=2)
async def check_scheduled_publishes() -> None:
    """每日 04:05 — 掃描已到期的排程發布文章，自動推送至各平台。

    觸發條件（OR 關係）：
    1. status="approved"，且 scheduled_publish_at <= now（有預訂時間且到期）
    2. status="approved"，且 scheduled_publish_at IS NULL（人工核准、無排程 → 立即發布）
    3. status="review_required"，且 seo_score >= project.auto_publish_min_score
       （seo 分數符合自動發布門檻但因舊 bug 未被自動發布的文章，補救發布）
    """
    from contentflow.agents.seo_check_agent import run_seo_check_agent
    from contentflow.agents.seo_qa_agent import run_seo_qa_agent
    from contentflow.models.database import Article, Project
    from contentflow.models.schemas import ArticleDraft, ResearchReport
    from sqlalchemy import or_
    import json

    def _parse_secondary_keywords(raw_keywords: str | None) -> list[str]:
        if not raw_keywords:
            return []

        text = raw_keywords.strip()
        if not text:
            return []

        if text.startswith("["):
            try:
                payload = json.loads(text)
                if isinstance(payload, list):
                    return [str(item).strip() for item in payload if str(item).strip()]
            except (TypeError, ValueError):
                pass

        return [item.strip() for item in re.split(r"[,，、\n]+", text) if item.strip()]

    def _article_has_factcheck_risk(article: Article) -> bool:
        raw_flags = article.factcheck_flags_json or "[]"
        try:
            payload = json.loads(raw_flags)
        except (TypeError, ValueError):
            return True
        return isinstance(payload, list) and len(payload) > 0

    def _build_research_report(article: Article) -> ResearchReport:
        payload: dict = {}
        if article.research_report_json:
            try:
                loaded = json.loads(article.research_report_json)
                if isinstance(loaded, dict):
                    payload = loaded
            except (TypeError, ValueError):
                payload = {}

        primary_keyword = (article.primary_keyword or "").strip()
        secondary_keywords = _parse_secondary_keywords(article.secondary_keywords)
        keywords = payload.get("keywords") if isinstance(payload.get("keywords"), list) else []
        suggested_keywords = payload.get("suggested_keywords") if isinstance(payload.get("suggested_keywords"), list) else []

        if primary_keyword and primary_keyword not in keywords:
            keywords = [primary_keyword, *keywords]
        if secondary_keywords:
            suggested_keywords = [*suggested_keywords, *secondary_keywords]

        payload["article_title"] = payload.get("article_title") or article.title or primary_keyword or "Untitled"
        payload["keywords"] = [item for item in keywords if item]
        payload["suggested_keywords"] = [item for item in suggested_keywords if item]
        payload["paa_questions"] = payload.get("paa_questions") if isinstance(payload.get("paa_questions"), list) else []
        payload["competitor_headings"] = payload.get("competitor_headings") if isinstance(payload.get("competitor_headings"), list) else []

        try:
            return ResearchReport.model_validate(payload)
        except Exception:
            return ResearchReport(
                article_title=article.title or primary_keyword or "Untitled",
                keywords=[primary_keyword] if primary_keyword else [],
                suggested_keywords=secondary_keywords,
            )

    async def _rescue_review_required_backlog(project_thresholds: dict[int, int]) -> int:
        if not project_thresholds:
            return 0

        score_gap_limit = 8
        stale_before = now - timedelta(days=2)

        with SessionLocal() as session:
            candidates = (
                session.query(Article)
                .filter(
                    Article.status == "review_required",
                    Article.project_id.in_(list(project_thresholds.keys())),
                    Article.seo_score.isnot(None),
                    Article.slug.isnot(None),
                    Article.updated_at <= stale_before,
                )
                .all()
            )

            candidate_ids = [
                article.id
                for article in sorted(
                    [
                        article
                        for article in candidates
                        if 0 < project_thresholds.get(article.project_id, 85) - (article.seo_score or 0) <= score_gap_limit
                    ],
                    key=lambda article: (
                        project_thresholds.get(article.project_id, 85) - (article.seo_score or 0),
                        article.updated_at or datetime.now(timezone.utc),
                    ),
                )[:5]
            ]

        rescued_count = 0
        for article_id in candidate_ids:
            with SessionLocal() as session:
                article = session.get(Article, article_id)
                if not article or not (article.draft_content or "").strip() or _article_has_factcheck_risk(article):
                    continue

                primary_keyword = (article.primary_keyword or article.title or "").strip()
                secondary_keywords = _parse_secondary_keywords(article.secondary_keywords)
                threshold = project_thresholds.get(article.project_id, 85)
                draft = ArticleDraft(
                    title=article.title or primary_keyword or "Untitled",
                    meta_title=article.meta_title or article.title or "",
                    meta_description=article.meta_description or "",
                    content_markdown=article.draft_content or "",
                    word_count=len(article.draft_content or ""),
                    slug=article.slug or "",
                    faq_schema_json=article.faq_schema_json or "",
                    howto_schema_json=article.howto_schema_json or "",
                    article_schema_json=article.article_schema_json or "",
                    paa_questions_json=article.paa_questions_json or "[]",
                    hero_image_url=article.hero_image_url or "",
                    status=article.status,
                    seo_score=article.seo_score or 0,
                )
                report = _build_research_report(article)

                initial_result = run_seo_check_agent(
                    draft=draft,
                    primary_keyword=primary_keyword,
                    secondary_keywords=secondary_keywords,
                )
                current_draft = draft
                current_result = initial_result

                if current_result["score"] < threshold and threshold - current_result["score"] <= score_gap_limit:
                    current_draft = await run_seo_qa_agent(
                        draft=current_draft,
                        report=report,
                        primary_keyword=primary_keyword,
                        secondary_keywords=secondary_keywords,
                        failed_checks=current_result.get("checks", []),
                        project_id=article.project_id,
                    )
                    current_result = run_seo_check_agent(
                        draft=current_draft,
                        primary_keyword=primary_keyword,
                        secondary_keywords=secondary_keywords,
                    )

                article.meta_title = current_draft.meta_title
                article.meta_description = current_draft.meta_description
                article.draft_content = current_draft.content_markdown
                article.seo_score = current_result["score"] or None
                if current_result["score"] >= threshold:
                    article.status = "approved"
                    rescued_count += 1
                    logger.info(
                        f"[ScheduledPublish] 補救 review_required 成功：article={article.id} score={current_result['score']} threshold={threshold}"
                    )
                else:
                    logger.info(
                        f"[ScheduledPublish] review_required 仍未達標：article={article.id} score={current_result['score']} threshold={threshold}"
                    )
                session.commit()

        return rescued_count

    now = datetime.now(timezone.utc)
    with SessionLocal() as session:
        # 取得 project 門檻對照表
        project_thresholds: dict[int, int] = {
            p.id: (p.auto_publish_min_score or 85)
            for p in session.query(Project).filter(Project.auto_publish_enabled.is_(True)).all()
        }

    rescued_review_required = await _rescue_review_required_backlog(project_thresholds)

    with SessionLocal() as session:
        # 條件 1 & 2：approved 文章（有排程且到期 OR 無排程）
        approved_articles = (
            session.query(Article)
            .filter(
                Article.status == "approved",
                Article.project_id.in_(list(project_thresholds.keys())),
                or_(
                    Article.scheduled_publish_at.is_(None),
                    Article.scheduled_publish_at <= now,
                ),
            )
            .all()
        )

        # 條件 3：review_required 且 seo_score >= 門檻（補救自動發布）
        review_rescue_articles = (
            session.query(Article)
            .filter(
                Article.status == "review_required",
                Article.project_id.in_(list(project_thresholds.keys())),
                Article.seo_score.isnot(None),
                Article.slug.isnot(None),
            )
            .all()
        )
        # 按專案門檻過濾
        review_rescue_articles = [
            a for a in review_rescue_articles
            if (a.seo_score or 0) >= project_thresholds.get(a.project_id, 85)
        ]

        due_articles = approved_articles + review_rescue_articles

    if not due_articles:
        logger.info("[ScheduledPublish] 無到期排程文章")
        return

    logger.info(
        f"[ScheduledPublish] 找到 {len(due_articles)} 篇待發布文章"
        f"（approved={len(approved_articles)} 補救={len(review_rescue_articles)}"
        f" 近門檻修補={rescued_review_required}）"
    )
    published_count = 0

    for article in due_articles:
        try:
            result = None
            if article.wp_post_id:
                from contentflow.publishers.wordpress import WordPressPublisher
                pub = WordPressPublisher()
                result = await pub.publish_post(article.wp_post_id)
            elif article.forgebase_id:
                from contentflow.publishers.forgebase import ForgeBasePublisher
                pub = ForgeBasePublisher()
                result = await pub.publish_post(article.forgebase_id)
            else:
                # 原生 blog 路徑：直接將文章標記為已發佈
                if not article.slug:
                    logger.warning(
                        f"[ScheduledPublish] 文章 #{article.id} '{article.title}' "
                        "缺少 slug，跳過"
                    )
                    continue
                with SessionLocal() as session:
                    art = session.get(Article, article.id)
                    if art:
                        art.status = "published"
                        art.published_at = now
                        if not art.publish_url:
                            _site_root = settings.site_url.rstrip("/")
                            art.publish_url = f"{_site_root}/blog/{art.slug}"
                        if not art.publish_date:
                            art.publish_date = now.strftime("%Y-%m-%d")
                        session.commit()
                        publish_url = art.publish_url
                published_count += 1
                logger.info(
                    f"[ScheduledPublish] ✅ 原生發布：'{article.title}' → {publish_url}"
                )
                await _notify_google_indexing(publish_url)
                continue

            if result and result.success:
                _pub_url = result.publish_url or ""
                with SessionLocal() as session:
                    art = session.get(Article, article.id)
                    if art:
                        art.status = "published"
                        art.published_at = now
                        if _pub_url:
                            art.publish_url = _pub_url
                        session.commit()
                published_count += 1
                logger.info(
                    f"[ScheduledPublish] ✅ 已發布：'{article.title}' → {_pub_url}"
                )
                # Google Indexing API：加速 Googlebot 收錄
                if _pub_url:
                    await _notify_google_indexing(_pub_url)
            else:
                err = result.error if result else "未知錯誤"
                logger.error(f"[ScheduledPublish] 文章 #{article.id} 發布失敗：{err}")
        except Exception as exc:
            logger.error(f"[ScheduledPublish] 文章 #{article.id} 例外：{exc}")

    logger.info(f"[ScheduledPublish] 完成，本次發布 {published_count}/{len(due_articles)} 篇")


@with_retry(max_retries=1)
async def sync_keyword_trends() -> None:
    """每月 1 日 03:45 — 用 SerpAPI Google Trends 同步關鍵字趨勢方向。

    每次處理所有有效關鍵字（search_volume > 0），優先更新 trend_direction 為 None
    或超過 30 天未更新的關鍵字，每個關鍵字間隔 0.5 秒避免 rate limit。
    """
    if not settings.serpapi_key:
        logger.info("[TrendsSync] 未設定 SERPAPI_KEY，跳過")
        return

    from contentflow.models.database import Keyword
    from contentflow.tools.serp import fetch_trends

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    with SessionLocal() as session:
        keywords = (
            session.query(Keyword)
            .filter(
                Keyword.search_volume > 0,
            )
            .filter(
                (Keyword.trend_direction == None) |  # noqa: E711
                (Keyword.updated_at < cutoff)
            )
            .order_by(Keyword.search_volume.desc())
            .limit(200)  # 每月最多 200 個，控制 API 成本
            .all()
        )
        kw_list = [(k.id, k.keyword) for k in keywords]

    if not kw_list:
        logger.info("[TrendsSync] 無需更新的關鍵字")
        return

    logger.info(f"[TrendsSync] 開始同步 {len(kw_list)} 個關鍵字趨勢")
    updated = 0
    for kw_id, kw_text in kw_list:
        try:
            trend = await fetch_trends(kw_text)
            with SessionLocal() as session:
                kw = session.get(Keyword, kw_id)
                if kw:
                    kw.trends_score = trend["score"]
                    kw.trend_direction = trend["direction"]
                    session.commit()
            updated += 1
            await asyncio.sleep(0.5)
        except Exception as exc:
            logger.warning(f"[TrendsSync] 關鍵字「{kw_text}」失敗：{exc}")

    logger.info(f"[TrendsSync] 完成，已更新 {updated}/{len(kw_list)} 個關鍵字")


# ── 排程設定進入點 ────────────────────────────────────────────

@with_retry(max_retries=2)
async def check_gsc_sitemap_health() -> None:
    """每週一 04:45 — 稽核 GSC 已提交的 Sitemap 狀態，偵測「無法擷取」並告警。

    使用 GSC Sitemaps API（webmasters v3）列出所有已提交 sitemap，
    逐一檢查 lastDownloaded、errors、isPending。
    若發現 unreachable / fetch error，寫入知識庫並送出告警。
    此為 run_index_coverage_check 的前置基礎設施健康檢查。
    """
    from contentflow.models.database import Project, KnowledgeEntry
    import json as _json_sm
    import httpx

    svc_file = settings.google_service_account_file
    if not svc_file:
        logger.info("[SitemapHealth] 未設定 GOOGLE_SERVICE_ACCOUNT_FILE，跳過")
        return

    try:
        import google.oauth2.service_account as _sa
        import google.auth.transport.requests as _gtr
        creds = _sa.Credentials.from_service_account_file(
            svc_file,
            scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
        )
        creds.refresh(_gtr.Request())
    except Exception as exc:
        logger.warning(f"[SitemapHealth] Service Account 初始化失敗：{exc}")
        return

    with SessionLocal() as session:
        projects = session.query(Project).filter(Project.brand_url != "").all()
        project_data = [(p.id, p.brand_url) for p in projects]

    if not project_data:
        logger.info("[SitemapHealth] 無可稽核的專案")
        return

    for project_id, brand_url in project_data:
        site_url = _to_gsc_site_url(brand_url)
        api_site_url = site_url.replace("sc-domain:", "sc-domain%3A")
        api_url = f"https://www.googleapis.com/webmasters/v3/sites/{api_site_url}/sitemaps"

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    api_url,
                    headers={"Authorization": f"Bearer {creds.token}"},
                )
                if resp.status_code == 404:
                    logger.info(f"[SitemapHealth] project={project_id} GSC 無已提交的 sitemap")
                    continue
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning(f"[SitemapHealth] project={project_id} API 呼叫失敗：{exc}")
            continue

        sitemaps = data.get("sitemap", [])
        if not sitemaps:
            # 沒有任何已提交的 sitemap → 這本身就是問題
            logger.warning(f"[SitemapHealth] project={project_id} {site_url} 無已提交 Sitemap")
            alert_msg = f"⚠️ [{brand_url}] GSC 無已提交 Sitemap，建議手動提交 /sitemap.xml"
            await _send_failure_alert("SitemapHealth", alert_msg)
            with SessionLocal() as session:
                session.add(KnowledgeEntry(
                    project_id=project_id,
                    category="sitemap_health",
                    pattern="GSC 無已提交 Sitemap",
                    evidence_count=0,
                    confidence_level="verified",
                    metadata_json=_json_sm.dumps({"site_url": site_url, "issue": "no_sitemap_submitted"}),
                ))
                session.commit()
            continue

        broken = []
        for sm in sitemaps:
            sm_url = sm.get("path", "")
            try:
                errors = int(sm.get("errors", 0) or 0)
            except (TypeError, ValueError):
                errors = 0
            try:
                warnings = int(sm.get("warnings", 0) or 0)
            except (TypeError, ValueError):
                warnings = 0
            is_pending_raw = sm.get("isPending", False)
            if isinstance(is_pending_raw, str):
                is_pending = is_pending_raw.strip().lower() == "true"
            else:
                is_pending = bool(is_pending_raw)
            # GSC 用 "lastDownloaded" 空值或 errors > 0 代表無法擷取
            if errors > 0 or (not sm.get("lastDownloaded") and not is_pending):
                broken.append({"url": sm_url, "errors": errors, "warnings": warnings})

        if broken:
            issue_summary = f"{len(broken)} 個 Sitemap 無法擷取：{[b['url'] for b in broken]}"
            logger.warning(f"[SitemapHealth] project={project_id} {issue_summary}")
            await _send_failure_alert("SitemapHealth", f"⚠️ [{brand_url}] {issue_summary}")
            with SessionLocal() as session:
                session.add(KnowledgeEntry(
                    project_id=project_id,
                    category="sitemap_health",
                    pattern=issue_summary,
                    evidence_count=len(broken),
                    confidence_level="verified",
                    metadata_json=_json_sm.dumps({
                        "site_url": site_url,
                        "broken_sitemaps": broken,
                        "total_submitted": len(sitemaps),
                    }),
                ))
                session.commit()
        else:
            logger.info(f"[SitemapHealth] project={project_id} {len(sitemaps)} 個 Sitemap 均正常")

    logger.info("[SitemapHealth] Sitemap 健康稽核完成")


@with_retry(max_retries=2)
async def check_published_noindex() -> None:
    """每日 04:10（發布後）— 驗證已發布文章的 HTML 無 noindex，robots.txt 無誤封鎖。

    發布後的「後驗」機制：
    1. 抓取最近 7 天發布的文章 URL，確認 <meta name="robots"> 無 noindex
    2. 抓取 robots.txt，確認 /blog/ 路徑未被 Disallow
    3. 發現問題立即告警，不靜默失敗
    """
    import httpx
    import re as _re
    from contentflow.models.database import Project, Article

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    with SessionLocal() as session:
        projects = session.query(Project).filter(Project.brand_url != "").all()
        project_data = [(p.id, p.brand_url) for p in projects]

    for project_id, brand_url in project_data:
        # 取最近 7 天已發布文章
        with SessionLocal() as session:
            articles = (
                session.query(Article)
                .filter(
                    Article.project_id == project_id,
                    Article.status == "published",
                    Article.published_at >= cutoff,
                )
                .order_by(Article.published_at.desc())
                .limit(10)
                .all()
            )
            url_slug_pairs = [(a.id, a.slug) for a in articles if a.slug]

        if not url_slug_pairs:
            continue

        base = brand_url.rstrip("/")
        issues = []

        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            # 1. 檢查 robots.txt
            try:
                rb = await client.get(f"{base}/robots.txt")
                robots_text = rb.text if rb.status_code == 200 else ""
                if _re.search(r"Disallow:\s*/blog", robots_text, _re.IGNORECASE):
                    issues.append("robots.txt Disallow: /blog → 文章路徑被封鎖")
                if _re.search(r"Disallow:\s*/\s*$", robots_text, _re.MULTILINE):
                    issues.append("robots.txt Disallow: / → 全站被封鎖")
            except Exception:
                pass

            # 2. 抽查最多 3 篇文章的 HTML noindex
            for art_id, slug in url_slug_pairs[:3]:
                article_url = f"{base}/blog/{slug}"
                try:
                    resp = await client.get(article_url)
                    if resp.status_code == 200:
                        html = resp.text
                        if _re.search(
                            r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex',
                            html, _re.IGNORECASE
                        ):
                            issues.append(f"文章 #{art_id} ({slug}) HTML 含 noindex")
                    elif resp.status_code == 404:
                        issues.append(f"文章 #{art_id} ({slug}) 返回 404（未正確發布）")
                except Exception:
                    pass

        if issues:
            msg = f"⚠️ [{brand_url}] 發布後驗證發現問題：{'; '.join(issues)}"
            logger.warning(f"[PublishVerify] project={project_id} {msg}")
            await _send_failure_alert("PublishVerify", msg)
        else:
            logger.info(f"[PublishVerify] project={project_id} {len(url_slug_pairs)} 篇文章驗證通過")

    logger.info("[PublishVerify] 發布後驗證完成")


@with_retry(max_retries=2)
async def run_index_coverage_check() -> None:
    """每週五 05:00 — Index Coverage 掃描，偵測新失索頁面並寫入知識庫。"""
    from contentflow.tools.tech_seo import GSCIndexCoverageMonitor
    from contentflow.models.database import Project, KnowledgeEntry
    import json as _json_ic

    with SessionLocal() as session:
        projects = session.query(Project).filter(Project.brand_url != "").all()
        project_data = [(p.id, p.brand_url) for p in projects]

    if not project_data:
        logger.info("[IndexCoverage] 無可掃描的專案")
        return

    monitor = GSCIndexCoverageMonitor()
    now = datetime.now(timezone.utc)
    end_date = now.date().isoformat()
    start_date = (now - timedelta(days=28)).date().isoformat()

    for project_id, brand_url in project_data:
        site_url = _to_gsc_site_url(brand_url)
        try:
            report = await monitor.get_coverage_report(site_url, start_date, end_date)
            if report.error:
                logger.warning(f"[IndexCoverage] project={project_id} GSC 錯誤：{report.error}")
                continue

            summary = (
                f"已索引 {report.total_indexed} 頁"
                f"，未索引 {report.total_not_indexed} 頁"
                f"，新失索 {len(report.newly_unindexed)} 頁"
            )
            logger.info(f"[IndexCoverage] project={project_id} {summary}")

            with SessionLocal() as session:
                session.add(KnowledgeEntry(
                    project_id=project_id,
                    category="index_coverage",
                    pattern=summary,
                    evidence_count=len(report.newly_unindexed),
                    confidence_level="verified",
                    metadata_json=_json_ic.dumps({
                        "site_url": site_url,
                        "total_indexed": report.total_indexed,
                        "total_not_indexed": report.total_not_indexed,
                        "newly_unindexed": report.newly_unindexed[:20],  # 最多記 20 筆
                        "date_range": f"{start_date}~{end_date}",
                    }),
                ))
                session.commit()
        except Exception as exc:
            logger.warning(f"[IndexCoverage] project={project_id} 失敗：{exc}")

    logger.info("[IndexCoverage] Index Coverage 掃描完成")


# ── 反向連結監控（DataForSEO Backlinks API）─────────────────────────────────

import json as _json_bl
from contentflow.models.database import BacklinkSnapshot


@with_retry()
async def sync_backlink_metrics() -> None:
    """每週同步各專案的反向連結摘要（DataForSEO Backlinks Summary Live API）。"""
    from contentflow.tools.backlinks import DataForSEOBacklinksClient
    from datetime import date

    if not getattr(settings, "backlink_sync_enabled", False):
        logger.info("[Backlinks] BACKLINK_SYNC_ENABLED=false，跳過")
        return

    if not settings.dataforseo_login or not settings.dataforseo_password:
        logger.warning("[Backlinks] DataForSEO 憑證未設定，跳過")
        return

    with SessionLocal() as session:
        from contentflow.models.database import Project
        projects = session.query(Project).filter(Project.brand_url != "").all()
        project_data = [(p.id, p.brand_url) for p in projects if p.brand_url]

    if not project_data:
        logger.info("[Backlinks] 無可掃描的專案（brand_url 未設定）")
        return

    client = DataForSEOBacklinksClient()
    today = date.today()

    for project_id, brand_url in project_data:
        try:
            summary = await client.get_backlink_summary(brand_url)
            if summary.has_error:
                logger.warning(f"[Backlinks] project={project_id} 查詢失敗：{summary.error}")
                continue

            with SessionLocal() as session:
                snap = BacklinkSnapshot(
                    project_id=project_id,
                    target_url=summary.target_url,
                    total_backlinks=summary.total_backlinks,
                    referring_domains=summary.referring_domains,
                    new_backlinks=summary.new_backlinks,
                    lost_backlinks=summary.lost_backlinks,
                    domain_rank=summary.domain_rank,
                    broken_backlinks=summary.broken_backlinks,
                    nofollow_backlinks=summary.nofollow_backlinks,
                    dofollow_backlinks=summary.dofollow_backlinks,
                    top_anchors_json=_json_bl.dumps(summary.top_anchors, ensure_ascii=False),
                    top_referring_domains_json=_json_bl.dumps(
                        summary.top_referring_domains, ensure_ascii=False
                    ),
                    tracked_date=today,
                )
                session.add(snap)

                # 若有大量失去反向連結，記入知識庫並預警
                if summary.lost_backlinks > 50 or (
                    summary.referring_domains > 0
                    and summary.lost_backlinks / max(summary.referring_domains, 1) > 0.1
                ):
                    from contentflow.models.database import KnowledgeEntry
                    session.add(KnowledgeEntry(
                        project_id=project_id,
                        category="backlink_alert",
                        pattern=(
                            f"反向連結大幅減少：本週失去 {summary.lost_backlinks} 條 backlinks，"
                            f"引薦域名 {summary.referring_domains}，"
                            f"請確認是否有 URL 異動或懲罰問題"
                        ),
                        evidence_count=summary.lost_backlinks,
                        confidence_level="verified",
                        metadata_json=_json_bl.dumps({
                            "target_url": summary.target_url,
                            "total_backlinks": summary.total_backlinks,
                            "referring_domains": summary.referring_domains,
                            "new_backlinks": summary.new_backlinks,
                            "lost_backlinks": summary.lost_backlinks,
                            "domain_rank": summary.domain_rank,
                            "tracked_date": str(today),
                        }, ensure_ascii=False),
                    ))
                    await _send_failure_alert(
                        "sync_backlink_metrics",
                        f"project={project_id} 本週失去 {summary.lost_backlinks} 條反向連結！"
                        f"引薦域名數：{summary.referring_domains}",
                    )

                session.commit()
                logger.info(
                    f"[Backlinks] project={project_id} 同步完成："
                    f"total={summary.total_backlinks} domains={summary.referring_domains} "
                    f"+{summary.new_backlinks}/-{summary.lost_backlinks}"
                )

        except Exception as exc:
            logger.warning(f"[Backlinks] project={project_id} 失敗：{exc}")

    logger.info("[Backlinks] 反向連結同步完成")


# ── Google 商家檔案指標同步（GBP Business Profile API）──────────────────────

import json as _json_gbp
from contentflow.models.database import GoogleBusinessMetric


@with_retry()
async def sync_gbp_metrics() -> None:
    """每日同步 Google Business Profile 指標（Business Profile API v4）。"""
    from datetime import date, timedelta

    if not getattr(settings, "gbp_sync_enabled", False):
        logger.info("[GBP] GBP_SYNC_ENABLED=false，跳過")
        return

    gbp_location_ids_raw = getattr(settings, "gbp_location_ids", "")
    gbp_oauth_access_token = getattr(settings, "gbp_oauth_access_token", "")
    gbp_location_project_map_raw = getattr(settings, "gbp_location_project_map", "")
    if not gbp_location_ids_raw:
        logger.info("[GBP] GBP_LOCATION_IDS 未設定，跳過")
        return
    if not gbp_oauth_access_token:
        logger.info("[GBP] GBP_OAUTH_ACCESS_TOKEN 未設定，跳過")
        return
    if not gbp_location_project_map_raw:
        logger.info("[GBP] GBP_LOCATION_PROJECT_MAP 未設定，跳過")
        return

    location_ids = [lid.strip() for lid in gbp_location_ids_raw.split(",") if lid.strip()]
    if not location_ids:
        logger.info("[GBP] GBP_LOCATION_IDS 為空，跳過")
        return

    location_project_map: dict[str, int] = {}
    for pair in gbp_location_project_map_raw.split(","):
        pair = pair.strip()
        if not pair or ":" not in pair:
            continue
        location_id, project_id_raw = pair.split(":", 1)
        location_id = location_id.strip()
        project_id_raw = project_id_raw.strip()
        if not location_id or not project_id_raw:
            continue
        try:
            location_project_map[location_id] = int(project_id_raw)
        except ValueError:
            logger.warning(f"[GBP] 無效的 location/project 映射：{pair}")

    if not location_project_map:
        logger.warning("[GBP] GBP_LOCATION_PROJECT_MAP 無有效映射，跳過")
        return

    yesterday = date.today() - timedelta(days=1)

    # GBP Business Profile API v4 端點
    GBP_METRICS_URL = (
        "https://businessprofileperformance.googleapis.com/v1/"
        "locations/{location_id}:fetchMultiDailyMetricsTimeSeries"
    )

    import httpx as _httpx

    for location_id in location_ids:
        project_id = location_project_map.get(location_id)
        if project_id is None:
            logger.warning(f"[GBP] location={location_id} 未配置 project_id，跳過")
            continue

        try:
            params = {
                "dailyMetrics": [
                    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
                    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
                    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
                    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
                    "CALL_CLICKS",
                    "WEBSITE_CLICKS",
                    "BUSINESS_DIRECTION_REQUESTS",
                ],
                "dailyRange.startDate.year": yesterday.year,
                "dailyRange.startDate.month": yesterday.month,
                "dailyRange.startDate.day": yesterday.day,
                "dailyRange.endDate.year": yesterday.year,
                "dailyRange.endDate.month": yesterday.month,
                "dailyRange.endDate.day": yesterday.day,
            }

            url = GBP_METRICS_URL.format(location_id=location_id)
            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    url,
                    params=params,
                    headers={
                        "Authorization": f"Bearer {gbp_oauth_access_token}",
                        "X-GOOG-API-FORMAT-VERSION": "2",
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            # 解析各指標值
            metric_vals: dict[str, int] = {}
            for series in data.get("multiDailyMetricTimeSeries", []):
                metric_name = series.get("dailyMetric", "")
                for ts in series.get("dailyMetricTimeSeries", {}).get("datedValues", []):
                    metric_vals[metric_name] = int(ts.get("value", 0) or 0)

            views_search = (
                metric_vals.get("BUSINESS_IMPRESSIONS_DESKTOP_SEARCH", 0)
                + metric_vals.get("BUSINESS_IMPRESSIONS_MOBILE_SEARCH", 0)
            )
            views_maps = (
                metric_vals.get("BUSINESS_IMPRESSIONS_DESKTOP_MAPS", 0)
                + metric_vals.get("BUSINESS_IMPRESSIONS_MOBILE_MAPS", 0)
            )

            with SessionLocal() as session:
                session.add(GoogleBusinessMetric(
                    project_id=project_id,
                    location_id=location_id,
                    views_search=views_search,
                    views_maps=views_maps,
                    clicks_website=metric_vals.get("WEBSITE_CLICKS", 0),
                    clicks_phone=metric_vals.get("CALL_CLICKS", 0),
                    clicks_directions=metric_vals.get("BUSINESS_DIRECTION_REQUESTS", 0),
                    tracked_date=yesterday,
                ))
                session.commit()

            logger.info(
                f"[GBP] location={location_id} 同步完成："
                f"search={views_search} maps={views_maps} "
                f"website_clicks={metric_vals.get('WEBSITE_CLICKS', 0)}"
            )

        except _httpx.HTTPStatusError as e:
            logger.warning(f"[GBP] location={location_id} API 錯誤 {e.response.status_code}: {e}")
        except Exception as exc:
            logger.warning(f"[GBP] location={location_id} 失敗：{exc}")

    logger.info("[GBP] GBP 指標同步完成")


def schedule_all_jobs() -> None:
    """註冊全部排程任務。由 site_app startup 呼叫。"""
    global _scheduler_lock_fd

    if not settings.scheduler_enabled:
        logger.info("[Scheduler] SCHEDULER_ENABLED=false，跳過排程初始化")
        return

    # 多 worker 部署：用檔案鎖確保只有一個 process 啟動排程
    try:
        _scheduler_lock_fd = open("/tmp/contentflow_scheduler.lock", "w")
        if fcntl is not None:
            fcntl.flock(_scheduler_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _scheduler_lock_fd.write(str(os.getpid()))
        _scheduler_lock_fd.flush()
        os.fsync(_scheduler_lock_fd.fileno())
    except (IOError, OSError):
        logger.info("[Scheduler] 另一個 worker 已持有排程鎖，跳過")
        return

    scheduler.add_job(sync_gsc_all_projects,      CronTrigger(hour=3,  minute=0),                              id="gsc_sync",        replace_existing=True)
    scheduler.add_job(sync_ga4_all_projects,       CronTrigger(hour=3,  minute=30),                             id="ga4_sync",        replace_existing=True)
    scheduler.add_job(sync_keyword_trends,         CronTrigger(day=1,   hour=3,  minute=45),                    id="trends_sync",     replace_existing=True)
    scheduler.add_job(backfill_action_outcomes,     CronTrigger(hour=4,  minute=0),                              id="outcome_backfill", replace_existing=True)
    scheduler.add_job(check_scheduled_publishes,   CronTrigger(hour=4,  minute=5),                              id="sched_publish",   replace_existing=True)
    scheduler.add_job(check_published_noindex,      CronTrigger(hour=4,  minute=10),                             id="publish_verify",  replace_existing=True)
    scheduler.add_job(check_gsc_sitemap_health,    CronTrigger(day_of_week="mon", hour=4, minute=45),           id="sitemap_health",  replace_existing=True)
    scheduler.add_job(run_competitor_serp_check,   CronTrigger(day_of_week="mon", hour=4, minute=30),           id="competitor_serp", replace_existing=True)
    scheduler.add_job(run_attribution_engine,      CronTrigger(day_of_week="mon", hour=5, minute=0),            id="attribution",     replace_existing=True)
    scheduler.add_job(check_refresh_triggers,      CronTrigger(day_of_week="tue", hour=4, minute=0),            id="refresh_check",   replace_existing=True)
    scheduler.add_job(run_l1_pattern_analysis,     CronTrigger(day=1,   hour=6,  minute=0),                     id="l1_learn",        replace_existing=True)
    scheduler.add_job(run_l2_roi_analysis,         CronTrigger(day=1,   hour=7,  minute=0),                     id="l2_learn",        replace_existing=True)
    scheduler.add_job(run_auto_pipeline,           CronTrigger(hour=8,  minute=0),                              id="auto_pipeline",   replace_existing=True)
    scheduler.add_job(run_render_verification,     CronTrigger(hour=10, minute=0),                              id="render_verify",   replace_existing=True)
    scheduler.add_job(run_weekly_reflection,        CronTrigger(day_of_week="sun", hour=8, minute=0),            id="weekly_reflection", replace_existing=True)
    scheduler.add_job(send_weekly_report,          CronTrigger(day_of_week="sun", hour=9, minute=0),            id="weekly_report",   replace_existing=True)
    scheduler.add_job(check_ranking_drops,         CronTrigger(day_of_week="wed", hour=6, minute=0),            id="ranking_drops",   replace_existing=True)
    scheduler.add_job(run_index_coverage_check,    CronTrigger(day_of_week="fri", hour=5, minute=0),            id="index_coverage",  replace_existing=True)
    scheduler.add_job(sync_gbp_metrics,            CronTrigger(hour=3,  minute=50),                             id="gbp_sync",        replace_existing=True)
    scheduler.add_job(sync_backlink_metrics,       CronTrigger(day_of_week="tue", hour=5, minute=30),           id="backlink_sync",   replace_existing=True)
    scheduler.add_job(_scheduler_heartbeat_job,    IntervalTrigger(minutes=1),                                  id="scheduler_heartbeat", replace_existing=True)

    scheduler.start()
    _write_scheduler_heartbeat("startup")
    # 寫入獨立的心跳檔案（繞過 flock 的 overlay fs 問題）
    with open("/tmp/contentflow_scheduler.pid", "w") as pf:
        pf.write(str(os.getpid()))
    logger.info(f"[Scheduler] 已啟動 {len(scheduler.get_jobs())} 個排程任務 (PID={os.getpid()})")
