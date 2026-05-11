"""Phase Gate C：排程系統完整性測試（CF-02-09）

完成定義：
- scheduler.py 中核心與新增 SEO health jobs 均有明確 cron 設定
- SchedulerLog ORM 可正常寫入與查詢
- with_retry 裝飾器在失敗後正確記錄 failed 狀態
- schedule_all_jobs 在 SCHEDULER_ENABLED=false 時不啟動 scheduler
- 各 job 函式可被 import（placeholder 時不崩潰）
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contentflow.models.database import Article, Base, Project, SchedulerLog


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

def test_scheduler_job_registry_has_expected_jobs():
    """scheduler registry 應定義 22 個 job，包含 operations snapshot 與 scheduler heartbeat。"""
    expected_job_ids = {
        "gsc_sync",
        "ga4_sync",
        "trends_sync",
        "gbp_sync",
        "outcome_backfill",
        "operations_snapshot",
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
        "scheduler_heartbeat",
    }
    from contentflow.scheduler_job_registry import SCHEDULER_JOB_SPECS

    registry_ids = {job["scheduler_id"] for job in SCHEDULER_JOB_SPECS}
    assert len(SCHEDULER_JOB_SPECS) == 22
    assert registry_ids == expected_job_ids


def test_write_scheduler_heartbeat(tmp_path, monkeypatch):
    heartbeat_path = tmp_path / "scheduler_heartbeat.json"

    from contentflow.config import settings
    original = settings.scheduler_heartbeat_path
    settings.scheduler_heartbeat_path = str(heartbeat_path)
    try:
        from contentflow.scheduler import _write_scheduler_heartbeat

        _write_scheduler_heartbeat("startup")

        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        assert payload["reason"] == "startup"
        assert isinstance(payload["pid"], int)
        assert payload["timestamp"]
    finally:
        settings.scheduler_heartbeat_path = original


def test_read_scheduler_heartbeat_running(tmp_path, monkeypatch):
    heartbeat_path = tmp_path / "scheduler_heartbeat.json"
    heartbeat_path.write_text(json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pid": 123,
        "reason": "tick",
    }, ensure_ascii=False), encoding="utf-8")

    from contentflow.config import settings
    original_path = settings.scheduler_heartbeat_path
    original_required = settings.scheduler_required
    original_max_age = settings.scheduler_heartbeat_max_age_seconds
    settings.scheduler_heartbeat_path = str(heartbeat_path)
    settings.scheduler_required = True
    settings.scheduler_heartbeat_max_age_seconds = 180
    try:
        from contentflow.site.app import _read_scheduler_heartbeat

        result = _read_scheduler_heartbeat()
        assert result["scheduler"] == "running"
        assert result["scheduler_pid"] == 123
        assert result["scheduler_reason"] == "tick"
    finally:
        settings.scheduler_heartbeat_path = original_path
        settings.scheduler_required = original_required
        settings.scheduler_heartbeat_max_age_seconds = original_max_age


def test_read_scheduler_heartbeat_stale(tmp_path):
    heartbeat_path = tmp_path / "scheduler_heartbeat.json"
    heartbeat_path.write_text(json.dumps({
        "timestamp": datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat(),
        "pid": 123,
        "reason": "tick",
    }, ensure_ascii=False), encoding="utf-8")

    from contentflow.config import settings
    original_path = settings.scheduler_heartbeat_path
    original_required = settings.scheduler_required
    original_max_age = settings.scheduler_heartbeat_max_age_seconds
    settings.scheduler_heartbeat_path = str(heartbeat_path)
    settings.scheduler_required = True
    settings.scheduler_heartbeat_max_age_seconds = 180
    try:
        from contentflow.site.app import _read_scheduler_heartbeat

        result = _read_scheduler_heartbeat(now=datetime(2020, 1, 1, 0, 5, tzinfo=timezone.utc))
        assert result["scheduler"] == "stale_heartbeat"
    finally:
        settings.scheduler_heartbeat_path = original_path
        settings.scheduler_required = original_required
        settings.scheduler_heartbeat_max_age_seconds = original_max_age


def test_check_scheduled_publishes_rescues_review_required_backlog(monkeypatch):
    """接近門檻且無 factcheck 風險的 review_required 稿件，應先被補救升級為 approved。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    project = Project(
        slug="goodbone",
        name="GoodBone",
        auto_publish_enabled=True,
        auto_publish_min_score=85,
    )
    session.add(project)
    session.flush()

    article = Article(
        project_id=project.id,
        title="膝蓋痛怎麼辦",
        primary_keyword="膝蓋痛",
        secondary_keywords="膝蓋痛原因, 膝蓋痛舒緩",
        status="review_required",
        slug="knee-pain-guide",
        draft_content="# 膝蓋痛怎麼辦\n\n原始首段內容。\n\n## 原因\n\n說明。\n\n## 治療\n\n說明。\n\n## FAQ\n\n常見問題。",
        meta_title="膝蓋痛處理",
        meta_description="膝蓋痛處理方式整理",
        seo_score=82,
        factcheck_flags_json="[]",
        research_report_json=json.dumps({"article_title": "膝蓋痛怎麼辦", "keywords": ["膝蓋痛"]}, ensure_ascii=False),
        scheduled_publish_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    session.add(article)
    session.commit()

    monkeypatch.setattr("contentflow.scheduler.SessionLocal", Session)

    seo_scores = iter([
        {"score": 82, "checks": [{"name": "meta_description_has_primary_keyword", "passed": False, "detail": "缺主關鍵字"}]},
        {"score": 87, "checks": []},
    ])

    def fake_seo_check_agent(*args, **kwargs):
        return next(seo_scores)

    async def fake_seo_qa_agent(draft, **kwargs):
        draft.meta_title = "膝蓋痛｜處理重點"
        draft.meta_description = "膝蓋痛常見原因與舒緩重點整理。"
        draft.content_markdown = draft.content_markdown + "\n\n## 膝蓋痛怎麼辦？\n\n先冰敷並降低負重，再依症狀安排評估。"
        return draft

    monkeypatch.setattr("contentflow.agents.seo_check_agent.run_seo_check_agent", fake_seo_check_agent)
    monkeypatch.setattr("contentflow.agents.seo_qa_agent.run_seo_qa_agent", fake_seo_qa_agent)

    from contentflow.scheduler import check_scheduled_publishes

    asyncio.run(check_scheduled_publishes())

    refreshed = session.get(Article, article.id)
    assert refreshed is not None
    assert refreshed.status == "approved"
    assert refreshed.seo_score == 87
    assert "膝蓋痛" in refreshed.meta_title

    session.close()
    engine.dispose()
