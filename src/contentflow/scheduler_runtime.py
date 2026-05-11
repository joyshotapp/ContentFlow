from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from contentflow.models.database import SchedulerLog


def scheduler_heartbeat_path(settings) -> Path:
    return Path(settings.scheduler_heartbeat_path)


def write_scheduler_heartbeat(*, settings, reason: str) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "reason": reason,
    }
    heartbeat_path = scheduler_heartbeat_path(settings)
    heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_scheduler_log(
    *,
    session_factory,
    job_id: str,
    job_name: str,
    status: str,
    started_at: datetime,
    retry_count: int = 0,
    error_message: str | None = None,
    duration_seconds: float | None = None,
) -> None:
    with session_factory() as session:
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


async def send_failure_alert(*, settings, webhook_url: str | None, logger, job_name: str, error: str) -> None:
    import httpx

    if not webhook_url:
        return
    msg = f"🚨 ContentFlow Scheduler 失敗\n任務：{job_name}\n錯誤：{error[:200]}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(webhook_url, json={"text": msg})
    except Exception as exc:
        logger.warning(f"[Scheduler] Slack 通知失敗：{exc}")