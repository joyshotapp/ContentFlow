"""Tests for Action Outcome Tracking — 因果閉環驗證"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contentflow.models.database import (
    Base, Project, Article, SEORanking, ActionOutcome, ActionOutcomeEvaluation, StrategicPlan, PipelineRun,
)
from contentflow.scheduler import _get_gsc_snapshot, backfill_action_outcomes


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def project_and_article(db_session):
    p = Project(
        slug="goodbone", name="好骨頭", brand_name="GoodBone",
        brand_url="https://goodbone.com.tw", industry="骨科",
    )
    db_session.add(p)
    db_session.flush()
    a = Article(
        project_id=p.id, title="膝蓋長骨刺怎麼辦",
        primary_keyword="膝蓋骨刺", status="published",
    )
    db_session.add(a)
    db_session.commit()
    return p, a


# ── ActionOutcome Model Tests ─────────────────────────────────

class TestActionOutcomeModel:
    def test_create_outcome(self, db_session, project_and_article):
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id,
            article_id=a.id,
            action_type="generate",
            action_date=date.today(),
            primary_keyword="膝蓋骨刺",
            baseline_rank=12.5,
            baseline_impressions=100,
            baseline_clicks=5,
            baseline_ctr=0.05,
            success_flag="too_early",
        )
        db_session.add(outcome)
        db_session.commit()

        assert outcome.id is not None
        assert outcome.action_type == "generate"
        assert outcome.baseline_rank == 12.5
        assert outcome.success_flag == "too_early"
        assert outcome.learning_confidence == "low"

    def test_outcome_repr(self, db_session, project_and_article):
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="refresh", action_date=date.today(),
            primary_keyword="骨刺治療", success_flag="improved",
        )
        db_session.add(outcome)
        db_session.commit()
        assert "refresh" in repr(outcome)
        assert "improved" in repr(outcome)

    def test_new_article_no_baseline(self, db_session, project_and_article):
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="generate", action_date=date.today(),
            primary_keyword="新關鍵字",
            baseline_rank=None,  # 新文章沒有基線
            success_flag="too_early",
        )
        db_session.add(outcome)
        db_session.commit()
        assert outcome.baseline_rank is None


# ── Backfill Logic Tests ──────────────────────────────────────

class TestOutcomeBackfill:
    def _seed_gsc(self, db_session, project_id, keyword, tracked_date, position):
        """插入 GSC ranking 測試資料。"""
        ranking = SEORanking(
            project_id=project_id,
            keyword=keyword,
            position=position,
            impressions=200,
            clicks=10,
            ctr=0.05,
            landing_page="https://goodbone.com.tw/blog/test",
            tracked_date=tracked_date,
        )
        db_session.add(ranking)
        db_session.commit()

    def test_7d_backfill_logic(self, db_session, project_and_article):
        """驗證 7 天回填邏輯：action_date + 7d 有 GSC 數據 → 回填。"""
        p, a = project_and_article
        action_date = date.today() - timedelta(days=10)
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="refresh", action_date=action_date,
            primary_keyword="膝蓋骨刺",
            baseline_rank=15.0,
            success_flag="too_early",
        )
        db_session.add(outcome)
        db_session.commit()

        # 插入 7 天後的 GSC 資料
        self._seed_gsc(db_session, p.id, "膝蓋骨刺",
                        action_date + timedelta(days=7), 10.0)

        # 模擬回填邏輯
        from sqlalchemy import func
        kw = outcome.primary_keyword
        target = action_date + timedelta(days=7)
        window_start = target - timedelta(days=2)
        window_end = target + timedelta(days=2)
        rows = (
            db_session.query(
                func.avg(SEORanking.position),
                func.sum(SEORanking.impressions),
            )
            .filter(
                SEORanking.project_id == p.id,
                SEORanking.keyword == kw,
                SEORanking.tracked_date >= window_start,
                SEORanking.tracked_date <= window_end,
            )
            .first()
        )
        assert rows[0] is not None
        assert float(rows[0]) == 10.0

    def test_28d_success_judgment_improved(self, db_session, project_and_article):
        """28d 排名從 15 降到 8 → improved。"""
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="refresh", action_date=date.today() - timedelta(days=30),
            primary_keyword="膝蓋骨刺",
            baseline_rank=15.0,
            rank_after_28d=8.0,
            success_flag="too_early",
        )
        # 模擬判定邏輯
        delta = outcome.rank_after_28d - outcome.baseline_rank
        assert delta == -7.0
        if delta <= -3:
            outcome.success_flag = "improved"
            outcome.learning_confidence = "high"
        assert outcome.success_flag == "improved"
        assert outcome.learning_confidence == "high"

    def test_28d_success_judgment_declined(self, db_session, project_and_article):
        """28d 排名從 8 升到 20 → declined。"""
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="refresh", action_date=date.today() - timedelta(days=30),
            primary_keyword="膝蓋骨刺",
            baseline_rank=8.0,
            rank_after_28d=20.0,
            success_flag="too_early",
        )
        delta = outcome.rank_after_28d - outcome.baseline_rank
        assert delta == 12.0
        if delta > 3:
            outcome.success_flag = "declined"
            outcome.learning_confidence = "high"
        assert outcome.success_flag == "declined"

    def test_new_article_success_judgment(self, db_session, project_and_article):
        """新文章（無 baseline）排名 <= 50 → improved。"""
        p, a = project_and_article
        outcome = ActionOutcome(
            project_id=p.id, article_id=a.id,
            action_type="generate", action_date=date.today() - timedelta(days=30),
            primary_keyword="新關鍵字",
            baseline_rank=None,
            rank_after_28d=25.0,
            success_flag="too_early",
        )
        if outcome.baseline_rank is None:
            if outcome.rank_after_28d and outcome.rank_after_28d <= 50:
                outcome.success_flag = "improved"
                outcome.learning_confidence = "medium"
        assert outcome.success_flag == "improved"

    def test_get_gsc_snapshot_prefers_latest_date_and_matching_path(self, db_session, project_and_article):
        p, a = project_and_article
        a.publish_url = "https://goodbone.com.tw/blog/test"
        db_session.commit()

        target = date.today() - timedelta(days=2)
        db_session.add_all([
            SEORanking(
                project_id=p.id,
                keyword="膝蓋骨刺",
                position=8.0,
                impressions=100,
                clicks=4,
                ctr=0.04,
                landing_page=a.publish_url,
                tracked_date=target - timedelta(days=1),
            ),
            SEORanking(
                project_id=p.id,
                keyword="膝蓋骨刺",
                position=6.0,
                impressions=120,
                clicks=6,
                ctr=0.05,
                landing_page=a.publish_url,
                tracked_date=target,
            ),
            SEORanking(
                project_id=p.id,
                keyword="膝蓋骨刺",
                position=25.0,
                impressions=999,
                clicks=1,
                ctr=0.001,
                landing_page="https://goodbone.com.tw/blog/other",
                tracked_date=target,
            ),
        ])
        db_session.commit()

        snapshot = _get_gsc_snapshot(
            db_session,
            p.id,
            "膝蓋骨刺",
            target,
            landing_page=a.publish_url,
        )

        assert snapshot["rank"] == 6.0
        assert snapshot["impressions"] == 120
        assert snapshot["clicks"] == 6

    @pytest.mark.asyncio
    async def test_backfill_uses_article_path_and_click_ctr_signal(self, db_session, project_and_article):
        p, a = project_and_article
        a.publish_url = "https://goodbone.com.tw/blog/test"
        db_session.commit()

        action_date = date.today() - timedelta(days=30)
        outcome = ActionOutcome(
            project_id=p.id,
            article_id=a.id,
            action_type="refresh",
            action_date=action_date,
            primary_keyword="膝蓋骨刺",
            baseline_rank=10.0,
            baseline_clicks=5,
            baseline_ctr=0.02,
            success_flag="too_early",
        )
        db_session.add(outcome)
        db_session.commit()

        target = action_date + timedelta(days=28)
        db_session.add_all([
            SEORanking(
                project_id=p.id,
                keyword="膝蓋骨刺",
                position=10.0,
                impressions=200,
                clicks=12,
                ctr=0.06,
                landing_page=a.publish_url,
                tracked_date=target,
            ),
            SEORanking(
                project_id=p.id,
                keyword="膝蓋骨刺",
                position=30.0,
                impressions=500,
                clicks=1,
                ctr=0.002,
                landing_page="https://goodbone.com.tw/blog/other",
                tracked_date=target,
            ),
        ])
        db_session.commit()

        class _SessionFactory:
            def __enter__(self):
                return db_session

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("contentflow.scheduler.SessionLocal", return_value=_SessionFactory()):
            await backfill_action_outcomes()

        db_session.refresh(outcome)
        assert outcome.rank_after_28d == 10.0
        assert outcome.clicks_after_28d == 12
        assert outcome.ctr_after_28d == 0.06
        assert outcome.success_flag == "improved"

    @pytest.mark.asyncio
    async def test_backfill_persists_evaluation_snapshot(self, db_session, project_and_article):
        p, a = project_and_article
        a.publish_url = "https://goodbone.com.tw/blog/test"
        db_session.commit()

        action_date = date.today() - timedelta(days=30)
        older = ActionOutcome(
            project_id=p.id,
            article_id=a.id,
            action_type="refresh",
            action_date=action_date - timedelta(days=7),
            primary_keyword="骨刺舊文",
            baseline_rank=11.0,
            baseline_clicks=8,
            baseline_ctr=0.03,
            rank_after_28d=9.0,
            clicks_after_28d=10,
            ctr_after_28d=0.04,
            checked_28d_at=datetime.now(timezone.utc),
            success_flag="improved",
            rank_delta=-2.0,
            learning_confidence="medium",
        )
        outcome = ActionOutcome(
            project_id=p.id,
            article_id=a.id,
            action_type="refresh",
            action_date=action_date,
            primary_keyword="膝蓋骨刺",
            baseline_rank=10.0,
            baseline_clicks=5,
            baseline_ctr=0.02,
            success_flag="too_early",
        )
        db_session.add_all([older, outcome])
        db_session.commit()

        target = action_date + timedelta(days=28)
        db_session.add(SEORanking(
            project_id=p.id,
            keyword="膝蓋骨刺",
            position=6.0,
            impressions=200,
            clicks=12,
            ctr=0.06,
            landing_page=a.publish_url,
            tracked_date=target,
        ))
        db_session.commit()

        class _SessionFactory:
            def __enter__(self):
                return db_session

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch("contentflow.scheduler.SessionLocal", return_value=_SessionFactory()):
            await backfill_action_outcomes()

        evaluation = (
            db_session.query(ActionOutcomeEvaluation)
            .filter(ActionOutcomeEvaluation.action_outcome_id == outcome.id)
            .first()
        )

        assert evaluation is not None
        assert evaluation.rank_delta == -4.0
        assert evaluation.control_rank_delta_median == -3.0
        assert evaluation.rank_advantage_vs_baseline > 0
        assert evaluation.control_adjustment > 0


# ── Strategic Agent Outcome Context Tests ─────────────────────

class TestStrategicAgentOutcomeContext:
    def test_outcome_stats_grouping(self, db_session, project_and_article):
        """驗證 outcome 統計按 action_type 正確分組。"""
        p, a = project_and_article
        # 插入不同成效結果
        for i, (atype, flag) in enumerate([
            ("generate", "improved"),
            ("generate", "declined"),
            ("refresh", "improved"),
            ("refresh", "improved"),
            ("refresh", "stable"),
        ]):
            db_session.add(ActionOutcome(
                project_id=p.id, article_id=a.id,
                action_type=atype,
                action_date=date.today() - timedelta(days=30 + i),
                primary_keyword=f"kw_{i}",
                success_flag=flag,
                learning_confidence="high",
            ))
        db_session.commit()

        # 模擬 strategic_agent 的統計邏輯
        outcomes = (
            db_session.query(ActionOutcome)
            .filter(
                ActionOutcome.project_id == p.id,
                ActionOutcome.success_flag.isnot(None),
                ActionOutcome.success_flag != "too_early",
            )
            .all()
        )
        stats = {}
        for o in outcomes:
            at = o.action_type
            if at not in stats:
                stats[at] = {"total": 0, "improved": 0, "declined": 0, "stable": 0}
            stats[at]["total"] += 1
            if o.success_flag in stats[at]:
                stats[at][o.success_flag] += 1

        assert stats["generate"]["total"] == 2
        assert stats["generate"]["improved"] == 1
        assert stats["generate"]["declined"] == 1
        assert stats["refresh"]["total"] == 3
        assert stats["refresh"]["improved"] == 2
        assert stats["refresh"]["stable"] == 1


# ── LLM Client Failover Tests ────────────────────────────────

class TestLLMClientFailover:
    def test_module_imports(self):
        """確認 llm_client 模組可正常 import。"""
        from contentflow.llm_client import achat, get_llm_client
        assert callable(achat)
        assert callable(get_llm_client)

    def test_cooldown_mechanism(self):
        """驗證 cooldown 機制正確運作。"""
        from contentflow.llm_client import _is_cooled_down, _set_cooldown
        assert _is_cooled_down("test_provider") is True
        _set_cooldown("test_provider")
        assert _is_cooled_down("test_provider") is False

    @pytest.mark.asyncio
    async def test_achat_all_fail_raises(self):
        """所有 provider 都失敗時應拋出 RuntimeError。"""
        from contentflow.llm_client import achat
        with patch("contentflow.llm_client.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""
            mock_settings.llm_lite_model = "gpt-4o-mini"
            with pytest.raises(RuntimeError, match="所有 provider 都失敗"):
                await achat(messages=[{"role": "user", "content": "test"}])
