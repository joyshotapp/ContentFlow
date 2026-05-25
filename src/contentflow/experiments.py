"""內容實驗框架（P3）：holdout 與更新前後對照。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger


def start_content_experiment(
    *,
    session,
    project_id: int,
    article_id: int,
    experiment_key: str,
    variant: str = "treatment",
    holdout: bool = False,
    baseline_metrics: dict[str, Any] | None = None,
) -> int:
    from contentflow.models.database import ContentExperiment

    row = ContentExperiment(
        project_id=project_id,
        article_id=article_id,
        experiment_key=experiment_key,
        variant=variant,
        holdout=holdout,
        baseline_metric_json=json.dumps(baseline_metrics or {}, ensure_ascii=False),
        started_at=datetime.now(timezone.utc),
        status="running",
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    logger.info(f"[Experiment] 啟動 {experiment_key} article={article_id} variant={variant}")
    return row.id


def complete_content_experiment(
    *,
    session,
    experiment_id: int,
    result_metrics: dict[str, Any],
    success: bool = True,
) -> None:
    from contentflow.models.database import ContentExperiment

    row = session.get(ContentExperiment, experiment_id)
    if not row:
        return
    row.result_metric_json = json.dumps(result_metrics, ensure_ascii=False)
    row.ended_at = datetime.now(timezone.utc)
    row.status = "completed" if success else "failed"
    session.commit()


def snapshot_gsc_baseline(session, project_id: int, article_id: int, publish_url: str) -> dict[str, Any]:
    """擷取實驗前 GSC 基線（用日級表最近 7 天）。"""
    from datetime import date, timedelta
    from contentflow.models.database import GSCDailyMetric

    cutoff = date.today() - timedelta(days=7)
    rows = (
        session.query(GSCDailyMetric)
        .filter(GSCDailyMetric.project_id == project_id, GSCDailyMetric.metric_date >= cutoff)
        .all()
    )
    pub = (publish_url or "").rstrip("/")
    clicks = impressions = 0
    for row in rows:
        page = (row.landing_page or "").rstrip("/")
        if pub and page and pub not in page and page not in pub:
            continue
        clicks += int(row.clicks or 0)
        impressions += int(row.impressions or 0)
    return {"clicks_7d": clicks, "impressions_7d": impressions, "article_id": article_id}
