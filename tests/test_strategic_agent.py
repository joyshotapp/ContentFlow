"""Tests for Strategic Agent — Enhanced B 的 Strategic 層"""

import json
import pytest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from contentflow.models.database import (
    Base, Project, Article, ContentCalendar, SEORanking,
    StrategicPlan, PipelineRun, ActionOutcome, ActionOutcomeEvaluation,
)
from contentflow.agents.strategic_agent import (
    _calculate_generate_capacity,
    _attach_action_evidence,
    _attach_action_controls,
    _build_action_outcome_stats,
    _collect_project_context,
    _fallback_plan,
    _normalize_plan_result,
    _parse_business_goal_profile,
    _score_action_business_utility,
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

    def test_collects_business_goal_profile(self, db_session, sample_project):
        sample_project.business_goals = "品牌知名度 / 導購 / 收集名單"
        db_session.commit()

        ctx = _collect_project_context(sample_project.id, db_session)

        assert ctx["business_goal_profile"]["primary_goal"] in {"awareness", "conversion", "lead_capture"}
        assert round(sum(ctx["business_goal_profile"]["weights"].values()), 4) == 1.0

    def test_collects_empty_project(self, db_session, sample_project):
        """空專案不應報錯"""
        ctx = _collect_project_context(sample_project.id, db_session)
        assert ctx["calendar_items"] == []
        assert ctx["ranking_changes_top10"] == []
        assert ctx["article_stats"]["planned"] == 0

    def test_parses_structured_business_goal_profile(self):
        profile = _parse_business_goal_profile(json.dumps({
            "primary_goal": "conversion",
            "secondary_goal": "authority",
            "weights": {
                "traffic": 0.2,
                "conversion": 0.5,
                "authority": 0.3,
            },
            "priority_topics": ["膝蓋骨刺"],
            "money_pages": ["/products/joint-care"],
        }, ensure_ascii=False))

        assert profile["primary_goal"] == "conversion"
        assert profile["secondary_goal"] == "authority"
        assert profile["priority_topics"] == ["膝蓋骨刺"]
        assert profile["money_pages"] == ["/products/joint-care"]
        assert round(sum(profile["weights"].values()), 4) == 1.0

    def test_parses_legacy_metric_weight_keys_into_goal_weights(self):
        profile = _parse_business_goal_profile(json.dumps({
            "primary_goal": "awareness",
            "secondary_goal": "authority",
            "weights": {
                "traffic": 0.3,
                "ctr": 0.2,
                "conversion": 0.1,
                "engagement": 0.25,
                "coverage": 0.15,
            },
        }, ensure_ascii=False))

        assert profile["weights"]["awareness"] > profile["weights"]["conversion"]
        assert profile["weights"]["authority"] > 0
        assert round(sum(profile["weights"].values()), 4) == 1.0

    def test_goal_utility_gets_priority_topic_and_money_page_boost(self):
        context_snapshot = {
            "business_goal_profile": {
                "weights": {
                    "awareness": 0.2,
                    "conversion": 0.5,
                    "lead_capture": 0.1,
                    "authority": 0.2,
                },
                "priority_topics": ["膝蓋骨刺"],
                "money_pages": ["/products/joint-care"],
            },
            "action_policy_scores": {
                "refresh": {"policy_score": 0.4},
            },
        }

        boosted, _ = _score_action_business_utility({
            "action": "refresh",
            "title": "膝蓋骨刺 /products/joint-care 更新",
            "priority": 8,
        }, context_snapshot)
        baseline, _ = _score_action_business_utility({
            "action": "refresh",
            "title": "一般衛教文章更新",
            "priority": 8,
        }, context_snapshot)

        assert boosted > baseline

    def test_goal_utility_matches_money_page_from_article_lookup(self):
        context_snapshot = {
            "business_goal_profile": {
                "weights": {
                    "awareness": 0.2,
                    "conversion": 0.5,
                    "lead_capture": 0.1,
                    "authority": 0.2,
                },
                "money_pages": ["/products/joint-care"],
            },
            "article_lookup": {
                42: {
                    "title": "關節保養",
                    "primary_keyword": "膝蓋骨刺",
                    "slug": "joint-care",
                    "publish_path": "/products/joint-care",
                }
            },
            "action_policy_scores": {
                "refresh": {"policy_score": 0.4},
            },
        }

        boosted, _ = _score_action_business_utility({
            "action": "refresh",
            "article_id": 42,
            "priority": 8,
        }, context_snapshot)
        baseline, _ = _score_action_business_utility({
            "action": "refresh",
            "article_id": 99,
            "priority": 8,
        }, context_snapshot)

        assert boosted > baseline

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

    def test_collects_gsc_ctr_and_query_opportunities(self, db_session, sample_project):
        pid = sample_project.id
        art = Article(
            project_id=pid,
            title="骨刺文章",
            slug="bone-spur",
            publish_url="https://test.example.com/blog/bone-spur",
            primary_keyword="膝蓋骨刺",
            status="published",
            draft_content="old content",
        )
        db_session.add(art)
        db_session.commit()

        db_session.add_all([
            SEORanking(
                project_id=pid,
                keyword="膝蓋骨刺",
                landing_page=art.publish_url,
                position=5.0,
                impressions=120,
                clicks=2,
                ctr=0.016,
                tracked_date=date.today(),
            ),
            SEORanking(
                project_id=pid,
                keyword="膝蓋骨刺復健",
                landing_page=art.publish_url,
                position=6.0,
                impressions=90,
                clicks=1,
                ctr=0.011,
                tracked_date=date.today(),
            ),
        ])
        db_session.commit()

        ctx = _collect_project_context(pid, db_session)

        assert ctx["gsc_meta_opportunities"][0]["article_id"] == art.id
        assert ctx["gsc_query_opportunities"][0]["gsc_queries"][0]["query"] == "膝蓋骨刺"

    def test_collects_action_policy_scores(self, db_session, sample_project):
        pid = sample_project.id
        article = Article(
            project_id=pid,
            title="成效文章",
            status="published",
            primary_keyword="膝蓋骨刺",
        )
        db_session.add(article)
        db_session.flush()
        db_session.add_all([
            ActionOutcome(
                project_id=pid,
                article_id=article.id,
                action_type="generate",
                action_date=date.today(),
                primary_keyword="膝蓋骨刺",
                success_flag="improved",
                learning_confidence="high",
                baseline_impressions=220,
                impressions_after_28d=320,
                rank_delta=-8.0,
            ),
            ActionOutcome(
                project_id=pid,
                article_id=article.id,
                action_type="generate",
                action_date=date.today(),
                primary_keyword="膝蓋骨刺復健",
                success_flag="improved",
                learning_confidence="medium",
                baseline_impressions=180,
                impressions_after_28d=260,
                rank_delta=-5.0,
            ),
            ActionOutcome(
                project_id=pid,
                article_id=article.id,
                action_type="generate",
                action_date=date.today(),
                primary_keyword="膝蓋骨刺運動",
                success_flag="stable",
                learning_confidence="medium",
                baseline_impressions=120,
                impressions_after_28d=140,
                rank_delta=-1.0,
            ),
        ])
        db_session.commit()

        ctx = _collect_project_context(pid, db_session)

        assert ctx["action_outcome_stats"]["generate"]["weighted_improved_rate"] > 0.6
        assert ctx["action_policy_scores"]["generate"]["policy_score"] > 0
        assert ctx["action_policy_scores"]["generate"]["recommendation"] == "maintain"

    def test_builds_weighted_action_policy_scores(self):
        outcomes = [
            SimpleNamespace(
                action_type="refresh",
                success_flag="improved",
                learning_confidence="high",
                baseline_impressions=280,
                impressions_after_28d=340,
                baseline_clicks=10,
                clicks_after_28d=18,
                baseline_ctr=0.03,
                ctr_after_28d=0.051,
                rank_delta=-9.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="declined",
                learning_confidence="low",
                baseline_impressions=30,
                impressions_after_28d=25,
                baseline_clicks=2,
                clicks_after_28d=1,
                baseline_ctr=0.02,
                ctr_after_28d=0.012,
                rank_delta=2.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="stable",
                learning_confidence="medium",
                baseline_impressions=120,
                impressions_after_28d=110,
                baseline_clicks=6,
                clicks_after_28d=6,
                baseline_ctr=0.025,
                ctr_after_28d=0.026,
                rank_delta=-1.0,
            ),
        ]

        stats, policy_scores = _build_action_outcome_stats(outcomes)

        assert stats["refresh"]["total"] == 3
        assert stats["refresh"]["weighted_improved_rate"] > stats["refresh"]["weighted_declined_rate"]
        assert policy_scores["refresh"]["policy_score"] > 0
        assert policy_scores["refresh"]["control_baseline"]["rank_delta_median"] == -1.0
        assert policy_scores["refresh"]["recommendation"] == "maintain"

    def test_control_baseline_can_lift_true_outperformer_above_raw_success_rate(self):
        outcomes = [
            SimpleNamespace(
                action_type="generate",
                success_flag="improved",
                learning_confidence="high",
                baseline_impressions=260,
                impressions_after_28d=420,
                baseline_clicks=10,
                clicks_after_28d=28,
                baseline_ctr=0.03,
                ctr_after_28d=0.067,
                rank_delta=-6.0,
            ),
            SimpleNamespace(
                action_type="generate",
                success_flag="improved",
                learning_confidence="high",
                baseline_impressions=240,
                impressions_after_28d=390,
                baseline_clicks=9,
                clicks_after_28d=24,
                baseline_ctr=0.028,
                ctr_after_28d=0.061,
                rank_delta=-5.0,
            ),
            SimpleNamespace(
                action_type="generate",
                success_flag="stable",
                learning_confidence="medium",
                baseline_impressions=180,
                impressions_after_28d=230,
                baseline_clicks=8,
                clicks_after_28d=13,
                baseline_ctr=0.026,
                ctr_after_28d=0.038,
                rank_delta=-3.0,
            ),
            SimpleNamespace(
                action_type="generate",
                success_flag="stable",
                learning_confidence="medium",
                baseline_impressions=160,
                impressions_after_28d=210,
                baseline_clicks=7,
                clicks_after_28d=11,
                baseline_ctr=0.024,
                ctr_after_28d=0.035,
                rank_delta=-2.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="improved",
                learning_confidence="medium",
                baseline_impressions=150,
                impressions_after_28d=158,
                baseline_clicks=6,
                clicks_after_28d=7,
                baseline_ctr=0.026,
                ctr_after_28d=0.028,
                rank_delta=-1.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="improved",
                learning_confidence="medium",
                baseline_impressions=145,
                impressions_after_28d=154,
                baseline_clicks=6,
                clicks_after_28d=7,
                baseline_ctr=0.025,
                ctr_after_28d=0.027,
                rank_delta=-1.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="improved",
                learning_confidence="low",
                baseline_impressions=140,
                impressions_after_28d=146,
                baseline_clicks=5,
                clicks_after_28d=6,
                baseline_ctr=0.024,
                ctr_after_28d=0.026,
                rank_delta=0.0,
            ),
            SimpleNamespace(
                action_type="refresh",
                success_flag="stable",
                learning_confidence="low",
                baseline_impressions=138,
                impressions_after_28d=140,
                baseline_clicks=5,
                clicks_after_28d=5,
                baseline_ctr=0.023,
                ctr_after_28d=0.023,
                rank_delta=1.0,
            ),
        ]

        stats, policy_scores = _build_action_outcome_stats(outcomes)

        assert stats["refresh"]["weighted_improved_rate"] > stats["generate"]["weighted_improved_rate"]
        assert policy_scores["generate"]["rank_advantage_vs_baseline"] > 0
        assert policy_scores["generate"]["control_adjustment"] > policy_scores["refresh"]["control_adjustment"]
        assert policy_scores["generate"]["policy_score"] > policy_scores["refresh"]["policy_score"]

    def test_persisted_evaluations_can_drive_policy_scores(self):
        generate_a = SimpleNamespace(
            id=1,
            action_type="generate",
            success_flag="improved",
            learning_confidence="high",
            baseline_impressions=200,
            impressions_after_28d=260,
            rank_delta=-4.0,
        )
        generate_b = SimpleNamespace(
            id=2,
            action_type="generate",
            success_flag="declined",
            learning_confidence="high",
            baseline_impressions=200,
            impressions_after_28d=220,
            rank_delta=2.0,
        )
        refresh_a = SimpleNamespace(
            id=3,
            action_type="refresh",
            success_flag="improved",
            learning_confidence="medium",
            baseline_impressions=120,
            impressions_after_28d=140,
            rank_delta=-1.0,
        )
        refresh_b = SimpleNamespace(
            id=4,
            action_type="refresh",
            success_flag="declined",
            learning_confidence="medium",
            baseline_impressions=120,
            impressions_after_28d=118,
            rank_delta=1.0,
        )

        evaluations = {
            1: ActionOutcomeEvaluation(action_outcome_id=1, control_adjustment=0.42, rank_delta=-4.0, click_delta=8.0, ctr_delta=0.02),
            2: ActionOutcomeEvaluation(action_outcome_id=2, control_adjustment=0.38, rank_delta=2.0, click_delta=-1.0, ctr_delta=-0.002),
            3: ActionOutcomeEvaluation(action_outcome_id=3, control_adjustment=-0.12, rank_delta=-1.0, click_delta=1.0, ctr_delta=0.001),
            4: ActionOutcomeEvaluation(action_outcome_id=4, control_adjustment=-0.15, rank_delta=1.0, click_delta=-1.0, ctr_delta=-0.001),
        }

        stats, policy_scores = _build_action_outcome_stats(
            [generate_a, generate_b, refresh_a, refresh_b],
            evaluations,
        )

        assert stats["generate"]["control_adjustment"] > 0.35
        assert policy_scores["generate"]["policy_score"] > policy_scores["refresh"]["policy_score"]


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

    def test_increases_quota_when_generate_policy_score_is_strong(self):
        ctx = {
            "calendar_items": [{"calendar_id": index} for index in range(1, 13)],
            "article_stats": {"reviewing": 0},
            "ranking_changes_top10": [],
            "action_outcome_stats": {
                "generate": {"total": 5, "improved": 4, "declined": 0, "stable": 1},
            },
            "action_policy_scores": {
                "generate": {
                    "policy_score": 0.42,
                    "weighted_improved_rate": 0.74,
                    "weighted_declined_rate": 0.0,
                    "recommendation": "scale",
                },
            },
        }

        with patch("contentflow.agents.strategic_agent.settings") as mock_settings:
            mock_settings.strategic_daily_generate_limit = 5
            mock_settings.max_articles_per_run = 5
            capacity = _calculate_generate_capacity(ctx)

        assert capacity["quota"] == 5
        assert capacity["generate_policy_recommendation"] == "scale"
        assert "generate_performance_strong" in capacity["signals"]



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

    def test_generates_optimize_meta_from_gsc_ctr_opportunities(self):
        ctx = {
            "calendar_items": [],
            "ranking_changes_top10": [],
            "article_stats": {"reviewing": 0},
            "gsc_meta_opportunities": [
                {
                    "article_id": 5,
                    "reason": "CTR 偏低",
                    "gsc_queries": [{"query": "膝蓋骨刺復健", "impressions": 88, "ctr": 0.009}],
                }
            ],
            "gsc_query_opportunities": [],
        }

        plan = _fallback_plan(ctx)
        optimize_actions = [a for a in plan["actions"] if a["action"] == "optimize_meta"]
        assert len(optimize_actions) == 1
        assert optimize_actions[0]["article_id"] == 5
        assert optimize_actions[0]["gsc_queries"][0]["query"] == "膝蓋骨刺復健"

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

    def test_attachs_structured_evidence_to_actions(self):
        ctx = {
            "calendar_items": [{"calendar_id": 7, "title": "季節保養主題"}],
            "ranking_changes_top10": [
                {"keyword": "膝蓋骨刺", "current_position": 15, "previous_position": 8, "delta": 7}
            ],
            "gsc_meta_opportunities": [
                {
                    "article_id": 9,
                    "position": 5.0,
                    "impressions": 120,
                    "ctr": 0.016,
                    "gsc_queries": [{"query": "膝蓋骨刺復健"}],
                    "reason": "GSC 顯示 CTR 偏低",
                }
            ],
            "gsc_query_opportunities": [
                {
                    "article_id": 8,
                    "gsc_queries": [{"query": "膝蓋骨刺", "impressions": 88, "ctr": 0.011}],
                }
            ],
            "generate_capacity": {"backlog": 3, "quota": 1, "signals": ["medium_backlog"]},
            "article_stats": {"reviewing": 0},
        }
        plan_result = {
            "actions": [
                {"action": "generate", "calendar_id": 7, "priority": 1},
                {"action": "refresh", "article_id": 8, "keyword": "膝蓋骨刺", "priority": 2},
                {"action": "optimize_meta", "article_id": 9, "priority": 3},
            ]
        }

        enriched = _attach_action_evidence(plan_result, ctx)

        assert enriched["actions"][0]["evidence"]["primary_signals"][0]["label"] == "日曆項目"
        assert enriched["actions"][1]["evidence"]["thresholds_triggered"][0] == "排名下滑 >= 5 位"
        assert enriched["actions"][2]["evidence"]["confidence"] == "high"

    def test_attaches_goal_weighted_utility_and_review_controls(self):
        ctx = {
            "business_goal_profile": {
                "weights": {
                    "awareness": 0.2,
                    "conversion": 0.5,
                    "lead_capture": 0.2,
                    "authority": 0.1,
                }
            },
            "action_policy_scores": {
                "refresh": {"policy_score": 0.4},
            },
            "cannibalization_risks": [
                {"keyword": "膝蓋骨刺", "suggestion": "merge"}
            ],
        }
        plan_result = {
            "actions": [
                {
                    "action": "refresh",
                    "keyword": "膝蓋骨刺",
                    "priority": 9,
                    "evidence": {"confidence": "medium"},
                }
            ]
        }

        controlled = _attach_action_controls(plan_result, ctx)
        action = controlled["actions"][0]

        assert action["goal_weighted_utility"] > 0.5
        assert action["business_goal_alignment"][0]["label"] == "導購轉換"
        assert action["review_required"] is True
        assert action["review_status"] == "pending"


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
        saved_actions = json.loads(plan.actions_json)
        assert saved_actions[0]["evidence"]["summary"]

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

    @pytest.mark.asyncio
    async def test_generate_action_resolves_publish_platform_with_current_session(self, db_session, sample_project):
        import contentflow.agents.strategic_agent as strategic_agent_module

        sample_project.auto_publish_enabled = True
        sample_project.auto_publish_min_score = 85
        db_session.commit()

        calendar_item = ContentCalendar(
            project_id=sample_project.id,
            title="測試日曆",
            keywords="骨刺",
            month=date.today().month,
            week=1,
            status="planned",
        )
        db_session.add(calendar_item)
        db_session.commit()

        plan = StrategicPlan(
            project_id=sample_project.id,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {"action": "generate", "calendar_id": calendar_item.id, "priority": 1, "reason": "test"}
            ]),
            total_count=1,
            status="pending",
        )
        db_session.add(plan)
        db_session.commit()

        fake_draft = SimpleNamespace(
            title="測試文章",
            content_markdown="# 測試文章\n\n內容",
            meta_title="測試標題",
            meta_description="測試描述",
            slug="publish-me",
            faq_schema_json="",
            article_schema_json="",
            seo_score=92,
            internal_link_suggestions=[],
            fact_check_items=[],
        )
        fake_result = SimpleNamespace(draft=fake_draft, status="approved")

        def _assert_platform(*, db=None, project_id=None):
            assert db is db_session
            assert project_id == sample_project.id
            return "native"

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.orchestrator.run_orchestrator", new=AsyncMock(return_value=fake_result)), \
             patch("contentflow.agents.strategic_agent.resolve_publish_platform", side_effect=_assert_platform), \
             patch("contentflow.agents.strategic_agent.build_native_publish_url", return_value="https://client.example/blog/publish-me"), \
               patch("contentflow.scheduler.record_action_outcome"), \
             patch("contentflow.agents.strategic_agent.settings") as mock_settings:

            mock_settings.slack_webhook_url = None
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await strategic_agent_module._execute_generate(
                {"action": "generate", "calendar_id": calendar_item.id, "priority": 1, "reason": "test"},
                sample_project.id,
                plan_id=plan.id,
            )

        article = db_session.query(Article).filter(Article.project_id == sample_project.id).first()
        assert article is not None
        assert article.status == "published"
        assert article.publish_url == "https://client.example/blog/publish-me"

    @pytest.mark.asyncio
    async def test_optimize_meta_passes_gsc_feedback_to_seo_qa(self, db_session, sample_project):
        pid = sample_project.id
        art = Article(
            project_id=pid,
            title="待優化文章",
            primary_keyword="膝蓋骨刺",
            status="published",
            draft_content="舊內容",
            meta_title="舊標題",
            meta_description="舊描述",
            publish_url="https://test.example.com/blog/bone",
        )
        db_session.add(art)
        db_session.commit()
        db_session.add(SEORanking(
            project_id=pid,
            keyword="膝蓋骨刺復健",
            landing_page=art.publish_url,
            position=5.0,
            impressions=120,
            clicks=2,
            ctr=0.016,
            tracked_date=date.today(),
        ))
        db_session.commit()

        plan = StrategicPlan(
            project_id=pid,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {
                    "action": "optimize_meta",
                    "article_id": art.id,
                    "priority": 1,
                    "gsc_queries": [{"query": "膝蓋骨刺復健", "impressions": 120, "ctr": 0.016}],
                }
            ]),
            total_count=1,
            status="pending",
        )
        db_session.add(plan)
        db_session.commit()

        optimized_draft = SimpleNamespace(meta_title="新標題", meta_description="新描述")

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.seo_qa_agent.run_seo_qa_agent", new_callable=AsyncMock) as mock_qa:

            mock_qa.return_value = optimized_draft
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await execute_strategic_plan(plan.id)

        kwargs = mock_qa.await_args.kwargs
        assert kwargs["secondary_keywords"] == ["膝蓋骨刺復健"]
        assert any(check["name"] == "gsc_query_gap" for check in kwargs["failed_checks"])

    @pytest.mark.asyncio
    async def test_skips_pending_review_action_and_marks_plan_partial(self, db_session, sample_project):
        pid = sample_project.id
        plan = StrategicPlan(
            project_id=pid,
            plan_date=date.today(),
            plan_type="daily",
            actions_json=json.dumps([
                {
                    "action": "refresh",
                    "keyword": "膝蓋骨刺",
                    "priority": 1,
                    "review_required": True,
                    "review_status": "pending",
                }
            ]),
            total_count=1,
            status="pending",
        )
        db_session.add(plan)
        db_session.commit()

        with patch("contentflow.agents.strategic_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.refresh_agent.run_refresh_pipeline", new_callable=AsyncMock) as mock_refresh:

            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            await execute_strategic_plan(plan.id)

        db_session.refresh(plan)
        saved_actions = json.loads(plan.actions_json)
        assert mock_refresh.await_count == 0
        assert plan.status == "partial"
        assert saved_actions[0]["execution_status"] == "skipped"
