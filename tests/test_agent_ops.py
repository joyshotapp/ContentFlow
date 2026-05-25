"""Admin Agent 治理儀表資料層測試。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contentflow.admin.agent_ops import (
    INTENT_LOW_THRESHOLD,
    build_intent_refresh_queue,
    build_publish_gate_snapshot,
)
from contentflow.models.database import Article, Base, KnowledgeEntry, Project


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    project = Project(slug="test", name="Test", auto_publish_enabled=True, auto_publish_min_score=85)
    session.add(project)
    session.commit()
    yield session, project.id
    session.close()


def test_publish_gate_counts_review_and_factcheck(db_session):
    session, pid = db_session
    session.add(Article(
        project_id=pid,
        title="待審",
        status="review_required",
        draft_content="# x",
        seo_score=90,
        factcheck_flags_json="[]",
    ))
    session.add(Article(
        project_id=pid,
        title="高風險",
        status="approved",
        draft_content="# x",
        seo_score=90,
        factcheck_flags_json='[{"claim": "c", "needs_review": true}]',
    ))
    session.add(Article(
        project_id=pid,
        title="可發",
        status="approved",
        draft_content="# x",
        seo_score=90,
        factcheck_flags_json="[]",
    ))
    session.commit()

    snap = build_publish_gate_snapshot(session, pid)
    assert snap["review_required"] == 1
    assert snap["factcheck_risk_count"] == 1
    assert snap["approved_ready_to_auto_publish"] == 1
    assert len(snap["blocked_candidates"]) >= 2


def test_intent_queue_prioritizes_low_score(db_session):
    session, pid = db_session
    now = datetime.now(timezone.utc)
    session.add(Article(
        project_id=pid,
        title="低意圖",
        status="published",
        slug="low",
        primary_keyword="骨刺",
        intent_match_score=30.0,
        intent_match_checked_at=now,
        published_at=now - timedelta(days=20),
    ))
    session.add(Article(
        project_id=pid,
        title="高意圖",
        status="published",
        slug="high",
        primary_keyword="膝蓋",
        intent_match_score=80.0,
        intent_match_checked_at=now,
        published_at=now - timedelta(days=20),
    ))
    session.commit()

    data = build_intent_refresh_queue(session, pid)
    assert data["low_intent_count"] == 1
    assert data["queue"][0]["priority"] == "high"
    assert data["queue"][0]["intent_match_score"] < INTENT_LOW_THRESHOLD


def test_intent_queue_handles_naive_published_at(db_session):
    session, pid = db_session
    naive = datetime(2020, 1, 1, 12, 0, 0)  # no tz — simulates PostgreSQL naive
    session.add(Article(
        project_id=pid,
        title="舊文",
        status="published",
        slug="old",
        published_at=naive,
        intent_match_score=None,
    ))
    session.commit()
    data = build_intent_refresh_queue(session, pid)
    assert any(item["title"].startswith("舊文") for item in data["queue"])


def test_intent_kb_hints(db_session):
    session, pid = db_session
    session.add(KnowledgeEntry(
        project_id=pid,
        category="intent_match_low",
        pattern="article 1 意圖低分",
        is_active=True,
        evidence_count=2,
    ))
    session.commit()

    data = build_intent_refresh_queue(session, pid)
    assert len(data["kb_hints"]) == 1
    assert data["kb_hints"][0]["category"] == "intent_match_low"
