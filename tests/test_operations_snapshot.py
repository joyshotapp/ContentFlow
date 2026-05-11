import asyncio
from datetime import date, datetime, timezone

from sqlalchemy.orm import sessionmaker

from contentflow.models.database import Article, ActionOutcome, GAPageMetric, OperationsHealthSnapshot, PipelineRun, SEORanking, SchedulerLog
from contentflow import scheduler as scheduler_module


def test_persist_operations_health_snapshot(db_session, sample_project, monkeypatch):
    now = datetime.now(timezone.utc)
    today = date.today()

    article = Article(project_id=sample_project.id, title="測試文章", status="published")
    db_session.add(article)
    db_session.flush()

    db_session.add(SEORanking(
        project_id=sample_project.id,
        keyword="膝蓋骨刺",
        position=5,
        landing_page="/blog/knee",
        tracked_date=today,
    ))
    db_session.add(GAPageMetric(
        project_id=sample_project.id,
        page_path="/blog/knee",
        sessions=120,
        tracked_date=today,
    ))
    db_session.add(SchedulerLog(
        job_id="gsc_sync",
        job_name="gsc_sync",
        status="success",
        started_at=now,
        finished_at=now,
    ))
    db_session.add(PipelineRun(
        run_id="run-123",
        project_id=sample_project.id,
        article_id=article.id,
        status="completed",
        current_step="completed",
        started_at=now,
        finished_at=now,
    ))
    db_session.add(ActionOutcome(
        project_id=sample_project.id,
        article_id=article.id,
        action_type="generate",
        action_date=today,
        primary_keyword="膝蓋骨刺",
        checked_28d_at=now,
        success_flag="improved",
    ))
    db_session.commit()

    TestSession = sessionmaker(bind=db_session.get_bind())
    monkeypatch.setattr(scheduler_module, "SessionLocal", TestSession)

    asyncio.run(scheduler_module.persist_operations_health_snapshot())

    snapshots = db_session.query(OperationsHealthSnapshot).all()
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.snapshot_type == "daily"
    assert snapshot.overall_status == "healthy"
    assert snapshot.alert_count == 0