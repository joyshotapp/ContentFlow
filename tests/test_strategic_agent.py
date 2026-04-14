"""Tests for Strategic Agent — Enhanced B 的 Strategic 層"""

import json
import pytest
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from contentflow.models.database import (
    Base, Project, Article, ContentCalendar,
    StrategicPlan, PipelineRun,
)
from contentflow.agents.strategic_agent import (
    _collect_project_context,
    _fallback_plan,
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


# ── _fallback_plan ────────────────────────────────────────────


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
        plan = _fallback_plan(ctx)
        generates = [a for a in plan["actions"] if a["action"] == "generate"]
        assert len(generates) == 2  # max 2
        assert generates[0]["calendar_id"] == 7

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


# ── run_strategic_agent ───────────────────────────────────────


class TestRunStrategicAgent:
    @pytest.mark.asyncio
    async def test_creates_plan_in_db(self, db_session, sample_project):
        """成功建立 StrategicPlan 到 DB"""
        pid = sample_project.id
        llm_response = {
            "actions": [
                {"action": "generate", "calendar_id": 1, "reason": "test", "priority": 1}
            ],
            "summary": "test plan",
        }

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.strategic_agent._call_strategic_llm", new_callable=AsyncMock) as mock_llm:

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
             patch("contentflow.agents.strategic_agent._call_strategic_llm", new_callable=AsyncMock) as mock_llm:

            mock_llm.side_effect = Exception("API down")
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            plan = await run_strategic_agent(pid)

        # fallback 不應崩潰
        assert plan.status == "pending"
        assert plan.total_count >= 0


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
