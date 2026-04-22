"""Phase Gate C：排程系統完整性測試（CF-02-09）

完成定義：
- scheduler.py 中核心與新增 SEO health jobs 均有明確 cron 設定
- SchedulerLog ORM 可正常寫入與查詢
- with_retry 裝飾器在失敗後正確記錄 failed 狀態
- schedule_all_jobs 在 SCHEDULER_ENABLED=false 時不啟動 scheduler
- 各 job 函式可被 import（placeholder 時不崩潰）
"""

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contentflow.models.database import Base, SchedulerLog


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


# ── 1. scheduler.py 全部 job 可 import ───────────────────────────────────

def test_all_job_functions_importable():
    """所有排程任務函式均可正常 import，不因 placeholder 崩潰。"""
    from contentflow.scheduler import (
        sync_gsc_all_projects,
        sync_ga4_all_projects,
        sync_keyword_trends,
        sync_gbp_metrics,
        sync_backlink_metrics,
        run_competitor_serp_check,
        run_attribution_engine,
        check_scheduled_publishes,
        check_published_noindex,
        check_gsc_sitemap_health,
        check_refresh_triggers,
        run_index_coverage_check,
        run_l1_pattern_analysis,
        run_l2_roi_analysis,
    )
    assert callable(sync_gsc_all_projects)
    assert callable(sync_ga4_all_projects)
    assert callable(sync_keyword_trends)
    assert callable(sync_gbp_metrics)
    assert callable(sync_backlink_metrics)
    assert callable(run_competitor_serp_check)
    assert callable(run_attribution_engine)
    assert callable(check_scheduled_publishes)
    assert callable(check_published_noindex)
    assert callable(check_gsc_sitemap_health)
    assert callable(check_refresh_triggers)
    assert callable(run_index_coverage_check)
    assert callable(run_l1_pattern_analysis)
    assert callable(run_l2_roi_analysis)


# ── 2. schedule_all_jobs 在 disabled 時不啟動 ─────────────────────────────

def test_schedule_all_jobs_disabled():
    """SCHEDULER_ENABLED=false 時 schedule_all_jobs 不呼叫 scheduler.start。"""
    from contentflow.scheduler import scheduler, schedule_all_jobs
    from contentflow.config import settings

    original = settings.scheduler_enabled
    try:
        settings.scheduler_enabled = False
        # 確認 scheduler 未啟動
        was_running = scheduler.running if hasattr(scheduler, "running") else False
        schedule_all_jobs()
        # 若原本就未啟動，應保持未啟動
        if not was_running:
            assert not scheduler.running
    finally:
        settings.scheduler_enabled = original


# ── 3. SchedulerLog 寫入與查詢 ────────────────────────────────────────────

def test_scheduler_log_write_and_query(mem_session):
    """SchedulerLog 可正確寫入 success/failed 記錄並查詢。"""
    now = datetime.now(timezone.utc)
    mem_session.add(SchedulerLog(
        job_id="gsc_sync",
        job_name="GSC 排名同步",
        status="success",
        started_at=now,
        finished_at=now,
        retry_count=0,
        duration_seconds=3.14,
    ))
    mem_session.add(SchedulerLog(
        job_id="gsc_sync",
        job_name="GSC 排名同步",
        status="failed",
        started_at=now,
        finished_at=now,
        retry_count=3,
        error_message="connection refused",
        duration_seconds=1.0,
    ))
    mem_session.commit()

    logs = mem_session.query(SchedulerLog).filter_by(job_id="gsc_sync").all()
    assert len(logs) == 2
    statuses = {l.status for l in logs}
    assert statuses == {"success", "failed"}


def test_scheduler_log_retry_count(mem_session):
    """retry_count 應正確反映重試次數。"""
    mem_session.add(SchedulerLog(
        job_id="attribution",
        job_name="文章表現歸因分析",
        status="failed",
        started_at=datetime.now(timezone.utc),
        retry_count=2,
        error_message="timeout",
    ))
    mem_session.commit()
    log = mem_session.query(SchedulerLog).filter_by(job_id="attribution").first()
    assert log.retry_count == 2
    assert log.error_message == "timeout"


# ── 4. with_retry 裝飾器行為 ─────────────────────────────────────────────

def test_with_retry_success_writes_log(monkeypatch, mem_session):
    """with_retry 包裝的 job 成功時應寫入 success log（mock SessionLocal）。"""
    written = []

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def add(self, obj): written.append(obj)
        def commit(self): pass

    monkeypatch.setattr("contentflow.scheduler.SessionLocal", lambda: FakeSession())

    from contentflow.scheduler import with_retry

    @with_retry(max_retries=1, base_delay=0)
    async def _ok_job():
        pass

    asyncio.get_event_loop().run_until_complete(_ok_job())
    assert any(getattr(w, "status", None) == "success" for w in written)


def test_with_retry_failure_writes_failed_log(monkeypatch):
    """with_retry 在全部重試失敗後應寫入 failed log。"""
    written = []

    class FakeSession:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def add(self, obj): written.append(obj)
        def commit(self): pass

    monkeypatch.setattr("contentflow.scheduler.SessionLocal", lambda: FakeSession())
    monkeypatch.setattr("contentflow.scheduler._send_failure_alert", AsyncMock())

    from contentflow.scheduler import with_retry

    @with_retry(max_retries=1, base_delay=0)
    async def _bad_job():
        raise RuntimeError("壞掉了")

    # with_retry 在全部重試失敗後不 re-raise，直接 return，需確認 log 已寫入
    asyncio.get_event_loop().run_until_complete(_bad_job())
    assert any(getattr(w, "status", None) == "failed" for w in written)


# ── 5. cron 排程數量確認 ──────────────────────────────────────────────────

def test_scheduler_has_20_jobs_defined():
    """scheduler.py 中應定義 20 個 job，並包含本次新增的 SEO health / off-site 監控。"""
    expected_job_ids = {
        "gsc_sync",
        "ga4_sync",
        "trends_sync",
        "gbp_sync",
        "outcome_backfill",
        "sched_publish",
        "publish_verify",
        "auto_pipeline",
        "render_verify",
        "sitemap_health",
        "competitor_serp",
        "attribution",
        "refresh_check",
        "backlink_sync",
        "ranking_drops",
        "index_coverage",
        "weekly_reflection",
        "weekly_report",
        "l1_learn",
        "l2_learn",
    }
    import inspect
    from contentflow import scheduler as sched_mod
    src = inspect.getsource(sched_mod.schedule_all_jobs)
    assert src.count("scheduler.add_job(") == 20
    for jid in expected_job_ids:
        assert jid in src, f"schedule_all_jobs 缺少 job id: {jid}"
