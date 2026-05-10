from datetime import date, datetime, timedelta, timezone

from contentflow.admin.app import _build_operations_health
from contentflow.models.database import ActionOutcome, Article, GAPageMetric, PipelineRun, Project, SchedulerLog, SEORanking


def _seed_project_article(db_session):
    project = Project(
        slug="ops-test",
        name="Ops Test",
        brand_name="Ops Brand",
        brand_url="https://ops.example.com",
    )
    db_session.add(project)
    db_session.flush()
    article = Article(
        project_id=project.id,
        title="測試文章",
        primary_keyword="骨刺",
        status="published",
        publish_url="https://ops.example.com/blog/test",
    )
    db_session.add(article)
    db_session.commit()
    return project, article


def test_build_operations_health_reports_healthy_state(db_session):
    project, article = _seed_project_article(db_session)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    db_session.add(SEORanking(
        project_id=project.id,
        keyword="骨刺",
        position=6.0,
        impressions=100,
        clicks=6,
        ctr=0.06,
        landing_page=article.publish_url,
        tracked_date=(now - timedelta(days=1)).date(),
    ))
    db_session.add(GAPageMetric(
        project_id=project.id,
        page_path="/blog/test",
        active_users=50,
        sessions=60,
        conversions=3,
        tracked_date=(now - timedelta(days=1)).date(),
    ))
    db_session.add(SchedulerLog(
        job_id="gsc_sync",
        job_name="GSC Sync",
        status="success",
        started_at=now - timedelta(hours=6),
        finished_at=now - timedelta(hours=5, minutes=55),
    ))
    db_session.add(PipelineRun(
        run_id="run-healthy-1",
        project_id=project.id,
        article_id=article.id,
        status="completed",
        trigger="strategic_agent",
        started_at=now - timedelta(days=2),
        finished_at=now - timedelta(days=2, minutes=-10),
    ))
    db_session.add_all([
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="refresh",
            action_date=(now - timedelta(days=35)).date(),
            primary_keyword="骨刺",
            success_flag="improved",
            checked_28d_at=now - timedelta(days=7),
        ),
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="refresh",
            action_date=(now - timedelta(days=40)).date(),
            primary_keyword="骨刺",
            success_flag="improved",
            checked_28d_at=now - timedelta(days=10),
        ),
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="generate",
            action_date=(now - timedelta(days=50)).date(),
            primary_keyword="新關鍵字",
            success_flag="stable",
            checked_28d_at=now - timedelta(days=15),
        ),
    ])
    db_session.commit()

    health = _build_operations_health(db_session, now=now)

    assert all(item.status == "healthy" for item in health["freshness_items"])
    assert health["execution_items"][0].status == "healthy"
    assert health["summary_cards"][1].value == "100%"
    assert not any(alert.level == "critical" for alert in health["alerts"])


def test_build_operations_health_flags_stale_and_weak_outcomes(db_session):
    project, article = _seed_project_article(db_session)
    now = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)

    db_session.add(SEORanking(
        project_id=project.id,
        keyword="骨刺",
        position=18.0,
        impressions=20,
        clicks=1,
        ctr=0.05,
        landing_page=article.publish_url,
        tracked_date=(now - timedelta(days=7)).date(),
    ))
    db_session.add(SchedulerLog(
        job_id="gsc_sync",
        job_name="GSC Sync",
        status="failed",
        started_at=now - timedelta(days=2),
        finished_at=now - timedelta(days=2, minutes=-1),
        error_message="boom",
    ))
    db_session.add(PipelineRun(
        run_id="run-fail-1",
        project_id=project.id,
        article_id=article.id,
        status="failed",
        trigger="strategic_agent",
        started_at=now - timedelta(days=5),
        finished_at=now - timedelta(days=5, minutes=-5),
    ))
    db_session.add_all([
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="refresh",
            action_date=(now - timedelta(days=35)).date(),
            primary_keyword="骨刺",
            success_flag="declined",
            checked_28d_at=now - timedelta(days=7),
        ),
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="refresh",
            action_date=(now - timedelta(days=45)).date(),
            primary_keyword="骨刺",
            success_flag="declined",
            checked_28d_at=now - timedelta(days=14),
        ),
        ActionOutcome(
            project_id=project.id,
            article_id=article.id,
            action_type="refresh",
            action_date=(now - timedelta(days=55)).date(),
            primary_keyword="骨刺",
            success_flag="stable",
            checked_28d_at=now - timedelta(days=20),
        ),
    ])
    db_session.commit()

    health = _build_operations_health(db_session, now=now)

    freshness_by_name = {item.name: item for item in health["freshness_items"]}
    assert freshness_by_name["GSC 同步"].status == "critical"
    assert freshness_by_name["GA4 同步"].status == "critical"
    assert health["execution_items"][0].status == "warning"
    refresh_outcome = next(item for item in health["outcome_items"] if item.name == "refresh")
    assert refresh_outcome.status == "critical"
    assert any("GSC 同步" in alert.message for alert in health["alerts"])
    assert any("refresh 近 90 天成效偏弱" in alert.message for alert in health["alerts"])