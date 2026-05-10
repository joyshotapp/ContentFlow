"""Tests for Strategic Agent — Enhanced B 的 Strategic 層"""

import json
import pytest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from contentflow.models.database import (
    Base, Project, Article, ContentCalendar, SEORanking,
    StrategicPlan, PipelineRun,
)
from contentflow.agents.strategic_agent import (
    _calculate_generate_capacity,
    _collect_project_context,
    _fallback_plan,
    _normalize_plan_result,
    run_strategic_agent,
    execute_strategic_plan,
)


# ── _collect_project_context ──────────────────────────────────


class TestCollectProjectContext:
    def test_collects_basic_stats(self, db_session, sample_project):
        """收集基本文章統計數量"""
        pid = sample_project.id
        # Add articles with different statuses
        db_session.add(Article(project_id=pid, title="A1", status="planned"))
        db_session.add(Article(project_id=pid, title="A2", status="published"))
        db_session.add(Article(project_id=pid, title="A3", status="review_required"))
        db_session.commit()

        ctx = _collect_project_context(pid, db_session)
        assert ctx["article_stats"]["planned"] == 1
        assert ctx["article_stats"]["published"] == 1
        assert ctx["article_stats"]["reviewing"] == 1
        assert "today" in ctx

    def test_collects_empty_project(self, db_session, sample_project):
        """空專案不應報錯"""
        ctx = _collect_project_context(sample_project.id, db_session)
        assert ctx["calendar_items"] == []
        assert ctx["ranking_changes_top10"] == []
        assert ctx["article_stats"]["planned"] == 0

    def test_collects_calendar_items(self, db_session, sample_project):
        """收集 planned calendar 條目"""
        pid = sample_project.id
        today = date.today()
        db_session.add(ContentCalendar(
            project_id=pid, title="測試文章",
            keywords="骨刺,膝蓋", month=today.month,
            week=1, status="planned",
        ))
        db_session.commit()

        ctx = _collect_project_context(pid, db_session)
        assert len(ctx["calendar_items"]) == 1
        assert ctx["calendar_items"][0]["title"] == "測試文章"

    def test_rank_group_uses_exact_publish_url_path(self, db_session, sample_project):
        pid = sample_project.id
        art = Article(
            project_id=pid,
            title="骨文章",
            slug="bone",
            publish_url="https://test.example.com/blog/bone",
            status="published",
        )
        db_session.add(art)
        db_session.commit()

        db_session.add(SEORanking(
            project_id=pid,
            keyword="骨文章",
            landing_page="https://test.example.com/blog/bone-spur",
            position=6,
            tracked_date=date.today(),
        ))
        db_session.commit()

        ctx = _collect_project_context(pid, db_session)
        assert ctx["rank_groups_summary"]["F"]["count"] == 1


# ── _fallback_plan ────────────────────────────────────────────



    def test_increases_quota_for_large_backlog(self):
        ctx = {
            "calendar_items": [{"calendar_id": index} for index in range(1, 13)],
            "article_stats": {"reviewing": 0},
            "ranking_changes_top10": [],
            "action_outcome_stats": {},
        }

        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 5
            mock_settings.max_articles_per_run = 5
            capacity = _calculate_generate_capacity(ctx)

        assert capacity["quota"] == 4
        assert "large_backlog" in capacity["signals"]

    def test_reduces_quota_when_reviewing_backlog_builds(self):
        ctx = {
            "calendar_items": [{"calendar_id": index} for index in range(1, 7)],
            "article_stats": {"reviewing": 6},
            "ranking_changes_top10": [],
            "action_outcome_stats": {},
        }

        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 5
            mock_settings.max_articles_per_run = 5
            capacity = _calculate_generate_capacity(ctx)

        assert capacity["quota"] == 2
        assert "review_backlog_high" in capacity["signals"]

    def test_reduces_quota_when_generate_outcomes_decline(self):
        ctx = {
            "calendar_items": [{"calendar_id": index} for index in range(1, 10)],
            "article_stats": {"reviewing": 0},
            "ranking_changes_top10": [],
            "action_outcome_stats": {
                "generate": {"total": 6, "improved": 1, "declined": 4, "stable": 1},
            },
        }

        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 5
            mock_settings.max_articles_per_run = 5
            capacity = _calculate_generate_capacity(ctx)

        assert capacity["quota"] == 1
        assert "generate_decline_rate_high" in capacity["signals"]



class TestFallbackPlan:
    def test_generates_from_calendar(self):
        """日曆到期 → 產生 generate action"""
        ctx = {
            "calendar_items": [
                {"calendar_id": 7, "title": "Test"},
                {"calendar_id": 8, "title": "Test2"},
                {"calendar_id": 9, "title": "Test3"},
            ],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 0},
        }
        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 3
            mock_settings.max_articles_per_run = 5
            plan = _fallback_plan(ctx)

        generates = [a for a in plan["actions"] if a["action"] == "generate"]
        assert len(generates) == 2
        assert generates[0]["calendar_id"] == 7

    def test_alerts_when_calendar_backlog_exceeds_limit(self):
        """planned backlog 超過每日上限時應提醒"""
        ctx = {
            "calendar_items": [
                {"calendar_id": 7, "title": "Test"},
                {"calendar_id": 8, "title": "Test2"},
                {"calendar_id": 9, "title": "Test3"},
            ],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 0},
        }

        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 2
            mock_settings.max_articles_per_run = 5
            plan = _fallback_plan(ctx)

        alerts = [a for a in plan["actions"] if a["action"] == "alert"]
        assert "今日系統自動核定僅產出 2 筆" in alerts[0]["message"]

    def test_generates_refresh_for_rank_drop(self):
        """排名下滑超過 5 位 → refresh"""
        ctx = {
            "calendar_items": [],
            "ranking_changes_top10": [
                {"keyword": "膝蓋長骨刺", "current_position": 18, "previous_position": 8, "delta": 10},
                {"keyword": "其他字", "current_position": 5, "previous_position": 4, "delta": 1},
            ],
            "article_stats": {"reviewing": 0},
        }
        plan = _fallback_plan(ctx)
        refreshes = [a for a in plan["actions"] if a["action"] == "refresh"]
        assert len(refreshes) == 1
        assert refreshes[0]["keyword"] == "膝蓋長骨刺"

    def test_generates_alert_for_review_backlog(self):
        """待審閱 ≥ 5 → alert"""
        ctx = {
            "calendar_items": [],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 7},
        }
        plan = _fallback_plan(ctx)
        alerts = [a for a in plan["actions"] if a["action"] == "alert"]
        assert len(alerts) == 1
        assert "7" in alerts[0]["message"]

    def test_empty_context_returns_no_actions(self):
        """空數據 → 空計畫"""
        ctx = {
            "calendar_items": [],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 0},
        }
        plan = _fallback_plan(ctx)
        assert plan["actions"] == []

    def test_normalize_plan_result_clamps_generate_actions(self):
        ctx = {
            "calendar_items": [
                {"calendar_id": 1, "title": "A"},
                {"calendar_id": 2, "title": "B"},
                {"calendar_id": 3, "title": "C"},
            ],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 0},
            "action_outcome_stats": {},
            "generate_capacity": {"quota": 1, "ceiling": 5},
        }
        plan_result = {
            "actions": [
                {"action": "generate", "calendar_id": 1, "priority": 1},
                {"action": "generate", "calendar_id": 2, "priority": 1},
                {"action": "refresh", "article_id": 9, "priority": 2},
            ],
            "summary": "test",
        }

        normalized = _normalize_plan_result(plan_result, ctx)

        generates = [a for a in normalized["actions"] if a["action"] == "generate"]
        alerts = [a for a in normalized["actions"] if a["action"] == "alert"]
        assert len(generates) == 1
        assert len(alerts) == 1
        assert "動態 generate 配額：1 篇" in normalized["summary"]


# ── run_strategic_agent ───────────────────────────────────────


class TestRunStrategicAgent:
    @pytest.mark.asyncio
    async def test_creates_plan_in_db(self, db_session, sample_project):
        """成功建立 StrategicPlan 到 DB"""
        pid = sample_project.id
        calendar_item = ContentCalendar(
            project_id=pid,
            title="測試日曆",
            keywords="骨刺",
            month=date.today().month,
            week=1,
            status="planned",
        )
        db_session.add(calendar_item)
        db_session.commit()
        llm_response = {
            "actions": [
                {"action": "generate", "calendar_id": calendar_item.id, "reason": "test", "priority": 1}
            ],
            "summary": "test plan",
        }

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.planning_agent.generate_content_plan", new_callable=AsyncMock) as mock_plan, \
             patch("contentflow.agents.strategic_agent._call_strategic_llm", new_callable=AsyncMock) as mock_llm:

            mock_plan.return_value = SimpleNamespace(recommendations=[])
            mock_llm.return_value = llm_response
            # SessionLocal 回傳 db_session
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            plan = await run_strategic_agent(pid)

        assert plan.project_id == pid
        assert plan.total_count == 1
        assert plan.status == "pending"
        assert "test plan" in plan.summary

    @pytest.mark.asyncio
    async def test_fallback_on_llm_failure(self, db_session, sample_project):
        """LLM 失敗時使用 fallback 規則"""
        pid = sample_project.id

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.planning_agent.generate_content_plan", new_callable=AsyncMock) as mock_plan, \
             patch("contentflow.agents.strategic_agent._call_strategic_llm", new_callable=AsyncMock) as mock_llm:

            mock_plan.return_value = SimpleNamespace(recommendations=[])
            mock_llm.side_effect = Exception("API down")
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            plan = await run_strategic_agent(pid)

        # fallback 不應崩潰
        assert plan.status == "pending"
        assert plan.total_count >= 0

    @pytest.mark.asyncio
    async def test_injects_planning_recommendations_into_context(self, db_session, sample_project):
        pid = sample_project.id
        captured = {}

        async def _fake_llm(context_snapshot):
            captured.update(context_snapshot)
            return {"actions": [], "summary": "ok"}

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.planning_agent.generate_content_plan", new_callable=AsyncMock) as mock_plan, \
             patch("contentflow.agents.strategic_agent._call_strategic_llm", side_effect=_fake_llm):

            mock_plan.return_value = SimpleNamespace(
                recommendations=[
                    SimpleNamespace(
                        action="refresh",
                        priority="high",
                        keyword="骨刺",
                        article_id=5,
                        reason="排名下滑",
                    )
                ]
            )
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await run_strategic_agent(pid)

        assert captured["planning_recommendations"][0]["action"] == "refresh"


# ── execute_strategic_plan ────────────────────────────────────


class TestExecuteStrategicPlan:
    @pytest.mark.asyncio
    async def test_marks_plan_completed(self, db_session, sample_project):
        """執行完成後 plan.status == completed"""
        pid = sample_project.id
        plan = StrategicPlan(
            project_id=pid,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "alert", "message": "test alert", "priority": 0}
            ]),
            total_count=1,
            status="pending",
        )
        db_session.add(plan)
        db_session.commit()
        plan_id = plan.id

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.strategic_agent.settings") as mock_settings:

            mock_settings.slack_webhook_url = None
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await execute_strategic_plan(plan_id)

        db_session.refresh(plan)
        assert plan.status == "completed"
        assert plan.executed_count == 1

    @pytest.mark.asyncio
    async def test_refresh_action_runs_full_refresh_pipeline(self, db_session, sample_project):
        pid = sample_project.id
        art = Article(
            project_id=pid,
            title="待更新文章",
            primary_keyword="骨刺",
            status="published",
            draft_content="舊內容",
            publish_url="https://test.example.com/blog/bone",
        )
        db_session.add(art)
        db_session.commit()

        plan = StrategicPlan(
            project_id=pid,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "refresh", "article_id": art.id, "priority": 1, "reason": "test"}
            ]),
            total_count=1,
            status="pending",
        )
        db_session.add(plan)
        db_session.commit()

        refresh_plan = SimpleNamespace(overall_freshness_score=40, recommendation="patch")

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.refresh_agent.run_refresh_pipeline", new_callable=AsyncMock) as mock_refresh, \
             patch("contentflow.scheduler.record_action_outcome") as mock_record:

            mock_refresh.return_value = {"plan": refresh_plan, "publish_result": {"success": True}}
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await execute_strategic_plan(plan.id)

        assert mock_refresh.await_count == 1
        kwargs = mock_refresh.await_args.kwargs
        assert kwargs["generate_content"] is True
        assert kwargs["publish"] is True
        assert mock_record.called
