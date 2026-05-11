from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from contentflow.models.database import (
    ActionOutcome,
    GAPageMetric,
    OperationsHealthSnapshot,
    PipelineRun,
    SchedulerLog,
    SEORanking,
)


async def persist_operations_health_snapshot_impl(*, session_factory, logger) -> None:
    """每日持久化 operations health 摘要，供 dashboard 與月度回顧使用。"""
    now = datetime.now(timezone.utc)
    snapshot_date = now.date()
    with session_factory() as session:
        latest_gsc = session.query(func.max(SEORanking.tracked_date)).scalar()
        latest_ga4 = session.query(func.max(GAPageMetric.tracked_date)).scalar()
        stale_sources = 0
        if latest_gsc is None or (snapshot_date - latest_gsc).days > 4:
            stale_sources += 1
        if latest_ga4 is None or (snapshot_date - latest_ga4).days > 4:
            stale_sources += 1

        scheduler_cutoff = now - timedelta(days=7)
        pipeline_cutoff = now - timedelta(days=30)
        outcome_cutoff = snapshot_date - timedelta(days=90)

        scheduler_rows = session.query(SchedulerLog).filter(SchedulerLog.started_at >= scheduler_cutoff).all()
        scheduler_total = len(scheduler_rows)
        scheduler_ok = sum(1 for row in scheduler_rows if row.status == "success")
        scheduler_success_rate = round((scheduler_ok / scheduler_total * 100), 2) if scheduler_total else None

        pipeline_rows = session.query(PipelineRun).filter(PipelineRun.started_at >= pipeline_cutoff).all()
        pipeline_total = len(pipeline_rows)
        pipeline_ok = sum(1 for row in pipeline_rows if row.status == "completed")
        pipeline_success_rate = round((pipeline_ok / pipeline_total * 100), 2) if pipeline_total else None

        outcome_rows = (
            session.query(ActionOutcome)
            .filter(ActionOutcome.checked_28d_at.isnot(None), ActionOutcome.action_date >= outcome_cutoff)
            .all()
        )
        outcome_total = len(outcome_rows)
        outcome_improved = sum(1 for row in outcome_rows if row.success_flag == "improved")
        outcome_improved_rate = round((outcome_improved / outcome_total * 100), 2) if outcome_total else None

        alert_count = 0
        if stale_sources:
            alert_count += stale_sources
        if scheduler_success_rate is not None and scheduler_success_rate < 90:
            alert_count += 1
        if pipeline_success_rate is not None and pipeline_success_rate < 85:
            alert_count += 1
        if outcome_improved_rate is not None and outcome_improved_rate < 50:
            alert_count += 1

        overall_status = "healthy"
        if alert_count >= 3:
            overall_status = "critical"
        elif alert_count >= 1:
            overall_status = "warning"

        summary = {
            "latest_gsc": latest_gsc.isoformat() if latest_gsc else None,
            "latest_ga4": latest_ga4.isoformat() if latest_ga4 else None,
            "scheduler_total": scheduler_total,
            "pipeline_total": pipeline_total,
            "outcome_total": outcome_total,
        }

        snapshot = (
            session.query(OperationsHealthSnapshot)
            .filter(
                OperationsHealthSnapshot.snapshot_date == snapshot_date,
                OperationsHealthSnapshot.snapshot_type == "daily",
            )
            .first()
        )
        if snapshot is None:
            snapshot = OperationsHealthSnapshot(snapshot_date=snapshot_date, snapshot_type="daily")
            session.add(snapshot)

        snapshot.overall_status = overall_status
        snapshot.stale_sources = stale_sources
        snapshot.scheduler_success_rate = scheduler_success_rate
        snapshot.pipeline_success_rate = pipeline_success_rate
        snapshot.outcome_improved_rate = outcome_improved_rate
        snapshot.alert_count = alert_count
        snapshot.summary_json = json.dumps(summary, ensure_ascii=False)
        session.commit()

    logger.info(
        f"[OperationsSnapshot] 已寫入 {snapshot_date} status={overall_status} "
        f"stale={stale_sources} alerts={alert_count}"
    )