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
import time
from datetime import datetime, timezone
from functools import wraps
from typing import Callable, Awaitable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import SchedulerLog

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
            await client.sync_to_db(project_id=project.id, site_url=project.brand_url)
    logger.info(f"[GSCSync] 已同步 {len(projects)} 個專案")


@with_retry(max_retries=3)
async def sync_ga4_all_projects() -> None:
    """每日 03:30 — 同步全專案 GA4 頁面指標。"""
    # GA4 client 實作後替換
    logger.info("[GA4Sync] placeholder — GA4 client 尚未實作")


@with_retry(max_retries=2)
async def run_competitor_serp_check() -> None:
    """每週一 04:00 — 追蹤競品 SERP 排名變化。"""
    logger.info("[CompetitorSERP] placeholder — serp tracker 尚未實作")


@with_retry(max_retries=2)
async def run_attribution_engine() -> None:
    """每週一 05:00 — 文章表現歸因分析。"""
    logger.info("[Attribution] placeholder — attribution engine 尚未實作")


@with_retry(max_retries=2)
async def check_refresh_triggers() -> None:
    """每週二 04:00 — 檢查 Content Refresh 觸發條件。"""
    logger.info("[RefreshCheck] placeholder — refresh checker 尚未實作")


@with_retry(max_retries=1)
async def run_l1_pattern_analysis() -> None:
    """每月 1 號 06:00 — L1 成功模式學習。"""
    logger.info("[L1Learn] placeholder — learning agent 尚未實作")


@with_retry(max_retries=1)
async def run_l2_roi_analysis() -> None:
    """每月 1 號 07:00 — L2 ROI 分析。"""
    logger.info("[L2Learn] placeholder — ROI analyser 尚未實作")


# ── 排程設定進入點 ────────────────────────────────────────────

def schedule_all_jobs() -> None:
    """註冊全部排程任務。由 api.py startup 呼叫。"""
    if not settings.scheduler_enabled:
        logger.info("[Scheduler] SCHEDULER_ENABLED=false，跳過排程初始化")
        return

    scheduler.add_job(sync_gsc_all_projects,      CronTrigger(hour=3,  minute=0),                              id="gsc_sync",        replace_existing=True)
    scheduler.add_job(sync_ga4_all_projects,       CronTrigger(hour=3,  minute=30),                             id="ga4_sync",        replace_existing=True)
    scheduler.add_job(run_competitor_serp_check,   CronTrigger(day_of_week="mon", hour=4, minute=0),            id="competitor_serp", replace_existing=True)
    scheduler.add_job(run_attribution_engine,      CronTrigger(day_of_week="mon", hour=5, minute=0),            id="attribution",     replace_existing=True)
    scheduler.add_job(check_refresh_triggers,      CronTrigger(day_of_week="tue", hour=4, minute=0),            id="refresh_check",   replace_existing=True)
    scheduler.add_job(run_l1_pattern_analysis,     CronTrigger(day=1,   hour=6,  minute=0),                     id="l1_learn",        replace_existing=True)
    scheduler.add_job(run_l2_roi_analysis,         CronTrigger(day=1,   hour=7,  minute=0),                     id="l2_learn",        replace_existing=True)

    scheduler.start()
    logger.info(f"[Scheduler] 已啟動 {len(scheduler.get_jobs())} 個排程任務")
