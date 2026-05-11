from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func

from contentflow.models.database import (
    ActionOutcome,
    AgentDecisionLog,
    GAPageMetric,
    PipelineRun,
    SchedulerLog,
    SEORanking,
)


def _get_agent_cost_metrics(db):
    """回傳 Agent 真實成本彙總；AgentDecisionLog 無資料時 fallback 至 PipelineRun.total_cost。"""
    run_costs: dict = {}
    total_cost_raw = None
    monthly_cost_raw = None
    avg_run_cost = None

    cost_col = getattr(AgentDecisionLog, "cost_usd", None)
    if cost_col is not None:
        valid_filters = [cost_col.isnot(None), cost_col > 0]
        run_cost_rows = (
            db.query(
                AgentDecisionLog.run_id,
                func.sum(cost_col).label("run_cost"),
            )
            .filter(*valid_filters)
            .group_by(AgentDecisionLog.run_id)
            .all()
        )
        run_costs = {
            run_id: round(float(run_cost), 4)
            for run_id, run_cost in run_cost_rows
            if run_cost
        }
        total_cost_raw = (
            db.query(func.sum(cost_col))
            .filter(*valid_filters)
            .scalar()
        )
        monthly_cost_raw = (
            db.query(func.sum(cost_col))
            .filter(
                *valid_filters,
                AgentDecisionLog.created_at >= datetime.now(timezone.utc) - timedelta(days=30),
            )
            .scalar()
        )
        if run_costs:
            avg_run_cost = round(sum(run_costs.values()) / len(run_costs), 4)

    if not run_costs and total_cost_raw is None:
        pr_total = db.query(func.sum(PipelineRun.total_cost)).filter(
            PipelineRun.total_cost.isnot(None), PipelineRun.total_cost > 0
        ).scalar()
        if pr_total:
            total_cost_raw = pr_total
            pr_run_rows = db.query(PipelineRun.run_id, PipelineRun.total_cost).filter(
                PipelineRun.total_cost.isnot(None), PipelineRun.total_cost > 0
            ).all()
            run_costs = {r.run_id: round(float(r.total_cost), 4) for r in pr_run_rows if r.total_cost}
            avg_run_cost = round(sum(run_costs.values()) / len(run_costs), 4) if run_costs else None
            monthly_cost_raw = db.query(func.sum(PipelineRun.total_cost)).filter(
                PipelineRun.total_cost.isnot(None), PipelineRun.total_cost > 0,
                PipelineRun.started_at >= datetime.now(timezone.utc) - timedelta(days=30),
            ).scalar()

    return {
        "avg_run_cost": avg_run_cost,
        "monthly_cost": round(float(monthly_cost_raw), 2) if monthly_cost_raw else None,
        "total_cost": round(float(total_cost_raw), 2) if total_cost_raw else None,
        "run_costs": run_costs,
    }


def _health_tone(status: str) -> tuple[str, str]:
    if status == "healthy":
        return "正常", "success"
    if status == "warning":
        return "注意", "warning"
    return "異常", "danger"


def _coerce_datetime(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def _staleness_status(latest_value, now: datetime, *, warn_hours: int, critical_hours: int):
    latest_dt = _coerce_datetime(latest_value)
    if latest_dt is None:
        status = "critical"
        hours = None
    else:
        hours = max((now - latest_dt).total_seconds() / 3600, 0)
        if hours > critical_hours:
            status = "critical"
        elif hours > warn_hours:
            status = "warning"
        else:
            status = "healthy"
    label, tone = _health_tone(status)
    return SimpleNamespace(status=status, label=label, tone=tone, hours=hours, latest=latest_dt)


def _build_operations_health(db, *, now: datetime | None = None):
    now = now or datetime.now(timezone.utc)

    latest_gsc = db.query(func.max(SEORanking.tracked_date)).scalar()
    latest_ga4 = db.query(func.max(GAPageMetric.tracked_date)).scalar()
    latest_scheduler = db.query(func.max(SchedulerLog.started_at)).scalar()
    latest_pipeline = db.query(func.max(PipelineRun.started_at)).scalar()

    gsc_freshness = _staleness_status(latest_gsc, now, warn_hours=60, critical_hours=108)
    ga4_freshness = _staleness_status(latest_ga4, now, warn_hours=60, critical_hours=108)
    scheduler_freshness = _staleness_status(latest_scheduler, now, warn_hours=24, critical_hours=48)
    pipeline_freshness = _staleness_status(latest_pipeline, now, warn_hours=72, critical_hours=168)

    freshness_items = [
        SimpleNamespace(name="GSC 同步", detail=(gsc_freshness.latest.strftime("%Y-%m-%d") if gsc_freshness.latest else "尚無資料"), metric=(f"{gsc_freshness.hours:.0f}h" if gsc_freshness.hours is not None else "—"), **gsc_freshness.__dict__),
        SimpleNamespace(name="GA4 同步", detail=(ga4_freshness.latest.strftime("%Y-%m-%d") if ga4_freshness.latest else "尚無資料"), metric=(f"{ga4_freshness.hours:.0f}h" if ga4_freshness.hours is not None else "—"), **ga4_freshness.__dict__),
        SimpleNamespace(name="Scheduler 日誌", detail=(scheduler_freshness.latest.strftime("%Y-%m-%d %H:%M") if scheduler_freshness.latest else "尚無資料"), metric=(f"{scheduler_freshness.hours:.0f}h" if scheduler_freshness.hours is not None else "—"), **scheduler_freshness.__dict__),
        SimpleNamespace(name="Pipeline 執行", detail=(pipeline_freshness.latest.strftime("%Y-%m-%d %H:%M") if pipeline_freshness.latest else "尚無資料"), metric=(f"{pipeline_freshness.hours:.0f}h" if pipeline_freshness.hours is not None else "—"), **pipeline_freshness.__dict__),
    ]

    scheduler_cutoff = now - timedelta(days=7)
    scheduler_7d = db.query(SchedulerLog).filter(SchedulerLog.started_at >= scheduler_cutoff).all()
    scheduler_ok = sum(1 for row in scheduler_7d if row.status == "success")
    scheduler_fail = sum(1 for row in scheduler_7d if row.status == "failed")
    scheduler_total = len(scheduler_7d)
    scheduler_success_rate = (scheduler_ok / scheduler_total * 100) if scheduler_total else None
    scheduler_status = "critical" if scheduler_fail >= 3 else ("warning" if scheduler_fail >= 1 else "healthy")
    scheduler_label, scheduler_tone = _health_tone(scheduler_status)

    pipeline_cutoff = now - timedelta(days=30)
    pipeline_30d = db.query(PipelineRun).filter(PipelineRun.started_at >= pipeline_cutoff).all()
    pipeline_ok = sum(1 for row in pipeline_30d if row.status == "completed")
    pipeline_fail = sum(1 for row in pipeline_30d if row.status == "failed")
    pipeline_running = sum(1 for row in pipeline_30d if row.status == "running")
    pipeline_total = len(pipeline_30d)
    pipeline_success_rate = (pipeline_ok / pipeline_total * 100) if pipeline_total else None
    pipeline_status = "critical" if pipeline_fail >= 5 else ("warning" if pipeline_fail >= 1 else "healthy")
    pipeline_label, pipeline_tone = _health_tone(pipeline_status)

    execution_items = [
        SimpleNamespace(name="Scheduler 7d 成功率", metric=(f"{scheduler_success_rate:.0f}%" if scheduler_success_rate is not None else "—"), detail=(f"成功 {scheduler_ok} / 失敗 {scheduler_fail}" if scheduler_total else "近 7 天無排程紀錄"), status=scheduler_status, label=scheduler_label, tone=scheduler_tone),
        SimpleNamespace(name="Pipeline 30d 成功率", metric=(f"{pipeline_success_rate:.0f}%" if pipeline_success_rate is not None else "—"), detail=(f"完成 {pipeline_ok} / 失敗 {pipeline_fail} / 執行中 {pipeline_running}" if pipeline_total else "近 30 天無 pipeline 紀錄"), status=pipeline_status, label=pipeline_label, tone=pipeline_tone),
    ]

    outcome_cutoff = now - timedelta(days=90)
    evaluated_outcomes = (
        db.query(ActionOutcome)
        .filter(
            ActionOutcome.checked_28d_at.isnot(None),
            ActionOutcome.checked_28d_at >= outcome_cutoff,
        )
        .all()
    )
    grouped = Counter((row.action_type or "unknown", row.success_flag or "stable") for row in evaluated_outcomes)
    outcome_items = []
    overall_improved = 0
    overall_total = 0
    for action_type in sorted({row.action_type or "unknown" for row in evaluated_outcomes}):
        improved = grouped[(action_type, "improved")]
        stable = grouped[(action_type, "stable")]
        declined = grouped[(action_type, "declined")]
        total = improved + stable + declined
        overall_improved += improved
        overall_total += total
        improved_rate = (improved / total * 100) if total else None
        status = "critical"
        if improved_rate is not None:
            if declined == 0:
                status = "healthy"
            elif improved_rate >= 55:
                status = "healthy"
            elif improved_rate >= 35:
                status = "warning"
        label, tone = _health_tone(status)
        outcome_items.append(
            SimpleNamespace(
                name=action_type,
                detail=f"improved {improved} / stable {stable} / declined {declined}",
                metric=(f"{improved_rate:.0f}%" if improved_rate is not None else "—"),
                status=status,
                label=label,
                tone=tone,
                total=total,
            )
        )

    overall_improved_rate = (overall_improved / overall_total * 100) if overall_total else None

    alerts = []
    for item in freshness_items:
        if item.status == "critical":
            alerts.append(SimpleNamespace(level="critical", message=f"{item.name} 超過新鮮度門檻：{item.detail}"))
        elif item.status == "warning":
            alerts.append(SimpleNamespace(level="warning", message=f"{item.name} 接近過期：{item.detail}"))
    if scheduler_fail:
        alerts.append(SimpleNamespace(level=("critical" if scheduler_fail >= 3 else "warning"), message=f"近 7 天 Scheduler 失敗 {scheduler_fail} 次"))
    if pipeline_fail:
        alerts.append(SimpleNamespace(level=("critical" if pipeline_fail >= 5 else "warning"), message=f"近 30 天 Pipeline 失敗 {pipeline_fail} 次"))
    for item in outcome_items:
        if item.status in ("warning", "critical"):
            alerts.append(SimpleNamespace(level=item.status, message=f"{item.name} 近 90 天成效偏弱：{item.detail}"))

    summary_cards = [
        SimpleNamespace(title="資料新鮮度異常", value=sum(1 for item in freshness_items if item.status != "healthy"), tone=("danger" if any(item.status == "critical" for item in freshness_items) else "warning")),
        SimpleNamespace(title="Scheduler 7d 成功率", value=(f"{scheduler_success_rate:.0f}%" if scheduler_success_rate is not None else "—"), tone=("success" if scheduler_status == "healthy" else ("warning" if scheduler_status == "warning" else "danger"))),
        SimpleNamespace(title="Pipeline 30d 成功率", value=(f"{pipeline_success_rate:.0f}%" if pipeline_success_rate is not None else "—"), tone=("success" if pipeline_status == "healthy" else ("warning" if pipeline_status == "warning" else "danger"))),
        SimpleNamespace(title="Outcome improved rate", value=(f"{overall_improved_rate:.0f}%" if overall_improved_rate is not None else "—"), tone=("success" if overall_improved_rate is not None and overall_improved_rate >= 55 else ("warning" if overall_improved_rate is not None and overall_improved_rate >= 35 else "danger"))),
    ]

    return {
        "summary_cards": summary_cards,
        "freshness_items": freshness_items,
        "execution_items": execution_items,
        "outcome_items": outcome_items,
        "alerts": alerts,
    }


def _serialize_operations_health(operations_health: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary_cards": [
            {"title": card.title, "value": card.value, "tone": card.tone}
            for card in operations_health.get("summary_cards", [])
        ],
        "freshness_items": [
            {
                "name": item.name,
                "status": item.status,
                "label": item.label,
                "tone": item.tone,
                "detail": item.detail,
                "metric": item.metric,
            }
            for item in operations_health.get("freshness_items", [])
        ],
        "execution_items": [
            {
                "name": item.name,
                "status": item.status,
                "label": item.label,
                "tone": item.tone,
                "detail": item.detail,
                "metric": item.metric,
            }
            for item in operations_health.get("execution_items", [])
        ],
        "outcome_items": [
            {
                "name": item.name,
                "status": item.status,
                "label": item.label,
                "tone": item.tone,
                "detail": item.detail,
                "metric": item.metric,
                "total": getattr(item, "total", 0),
            }
            for item in operations_health.get("outcome_items", [])
        ],
        "alerts": [
            {"level": alert.level, "message": alert.message}
            for alert in operations_health.get("alerts", [])
        ],
    }