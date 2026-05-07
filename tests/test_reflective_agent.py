"""Tests for Reflective Loop Agent — Enhanced B 的 Reflective 層"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from contentflow.models.database import (
    Base, Project, Article, KnowledgeEntry, WritingRule,
    ReflectionLog, PipelineRun,
)
from contentflow.agents.reflective_agent import (
    _apply_knowledge_updates,
    _apply_writing_rule_updates,
    _fallback_reflection,
    _fallback_weekly_reflection,
    reflect_on_pipeline,
    reflect_on_human_edit,
)


# ── _apply_knowledge_updates ─────────────────────────────────


class TestApplyKnowledgeUpdates:
    def test_creates_new_entry(self, db_session, sample_project):
        pid = sample_project.id
        updates = [
            {"category": "seo_pattern", "pattern": "H2 標題含關鍵字提升排名"}
        ]
        count = _apply_knowledge_updates(db_session, pid, updates)
        assert count == 1

        entry = db_session.query(KnowledgeEntry).filter(
            KnowledgeEntry.project_id == pid,
            KnowledgeEntry.category == "seo_pattern",
        ).first()
        assert entry is not None
        assert "H2 標題" in entry.pattern
        assert entry.evidence_count == 1
        assert entry.confidence_level == "unverified"

    def test_deduplicates_existing(self, db_session, sample_project):
        """同 category + 前 50 字重複 → 只增加 evidence_count"""
        pid = sample_project.id
        db_session.add(KnowledgeEntry(
            project_id=pid,
            category="seo_pattern",
            pattern="H2 標題含關鍵字提升排名",
            evidence_count=1,
            confidence_level="unverified",
        ))
        db_session.commit()

        # 完全相同的 pattern → 應被去重
        updates = [
            {"category": "seo_pattern", "pattern": "H2 標題含關鍵字提升排名"}
        ]
        count = _apply_knowledge_updates(db_session, pid, updates)
        assert count == 0  # 不新建

        entry = db_session.query(KnowledgeEntry).filter(
            KnowledgeEntry.project_id == pid,
        ).first()
        assert entry.evidence_count == 2

    def test_auto_upgrade_confidence(self, db_session, sample_project):
        """evidence_count ≥ 5 → confidence_level = verified"""
        pid = sample_project.id
        db_session.add(KnowledgeEntry(
            project_id=pid,
            category="test",
            pattern="某個模式",
            evidence_count=4,
            confidence_level="unverified",
        ))
        db_session.commit()

        updates = [{"category": "test", "pattern": "某個模式"}]
        _apply_knowledge_updates(db_session, pid, updates)

        entry = db_session.query(KnowledgeEntry).first()
        assert entry.evidence_count == 5
        assert entry.confidence_level == "verified"

    def test_skips_empty_pattern(self, db_session, sample_project):
        count = _apply_knowledge_updates(db_session, sample_project.id, [{"category": "x", "pattern": ""}])
        assert count == 0


# ── _apply_writing_rule_updates ──────────────────────────────


class TestApplyWritingRuleUpdates:
    def test_creates_new_rule(self, db_session, sample_project):
        pid = sample_project.id
        updates = [
            {"rule_type": "principle", "name": "具體科別規範", "content": "使用具體科別名稱"}
        ]
        count = _apply_writing_rule_updates(db_session, pid, updates)
        assert count == 1

        rule = db_session.query(WritingRule).filter(WritingRule.project_id == pid).first()
        assert rule.name == "具體科別規範"

    def test_appends_to_existing_rule(self, db_session, sample_project):
        """同名規則 → 追加不覆蓋"""
        pid = sample_project.id
        db_session.add(WritingRule(
            project_id=pid, rule_type="principle",
            name="具體科別規範", content="原始內容", order_num=1,
        ))
        db_session.commit()

        updates = [
            {"rule_type": "principle", "name": "具體科別規範", "content": "新追加內容"}
        ]
        count = _apply_writing_rule_updates(db_session, pid, updates)
        assert count == 0  # 不新建

        rule = db_session.query(WritingRule).first()
        assert "原始內容" in rule.content
        assert "新追加內容" in rule.content


# ── _fallback_reflection ─────────────────────────────────────


class TestFallbackReflection:
    def test_low_seo_generates_issue(self):
        ctx = {
            "pipeline": {"seo_score": 72},
            "article": {"status": "reviewing"},
        }
        result = _fallback_reflection(ctx)
        assert len(result["insights"]) == 1
        assert result["insights"][0]["type"] == "issue"
        assert "72" in result["insights"][0]["observation"]

    def test_high_seo_no_issue(self):
        ctx = {
            "pipeline": {"seo_score": 90},
            "article": {"status": "published"},
        }
        result = _fallback_reflection(ctx)
        assert len(result["insights"]) == 0

    def test_summary_includes_status(self):
        ctx = {
            "pipeline": {"seo_score": 85},
            "article": {"status": "reviewing"},
        }
        result = _fallback_reflection(ctx)
        assert "reviewing" in result["session_summary"]


class TestFallbackWeeklyReflection:
    def test_generates_updates_when_week_has_data(self):
        ctx = {
            "articles_this_week": [
                {"title": "A", "seo_score": 82, "status": "review_required", "keyword": "膝蓋痛", "word_count": 1200},
                {"title": "B", "seo_score": 91, "status": "published", "keyword": "落枕", "word_count": 1500},
            ],
            "ranking_performance": [
                {"title": "B", "keyword": "落枕", "position": 6, "impressions": 500, "clicks": 30},
            ],
            "existing_knowledge": [],
        }

        result = _fallback_weekly_reflection(ctx)

        assert len(result["knowledge_updates"]) >= 1
        assert len(result["writing_rule_updates"]) >= 1
        assert "weekly_review fallback" in result["session_summary"]
        assert "平均 SEO" in result["session_summary"]

    def test_prioritizes_review_backlog_and_skips_duplicate_knowledge(self):
        ctx = {
            "articles_this_week": [
                {"title": "A", "seo_score": 84, "status": "review_required", "keyword": "膝蓋痛", "word_count": 900},
                {"title": "B", "seo_score": 81, "status": "review_required", "keyword": "落枕", "word_count": 1180},
                {"title": "C", "seo_score": 91, "status": "published", "keyword": "落枕", "word_count": 1500},
            ],
            "ranking_performance": [
                {"title": "C", "keyword": "落枕", "position": 4, "impressions": 800, "clicks": 55},
            ],
            "existing_knowledge": [
                {
                    "category": "content_strategy",
                    "pattern": "weekly_review：本週前 10 名文章顯示 落枕 類題目具持續投入價值，可優先延伸相關內容群。",
                }
            ],
        }

        result = _fallback_weekly_reflection(ctx)

        assert any(update["category"] == "refresh_priority" and "A（84）" in update["pattern"] for update in result["knowledge_updates"])
        assert any(rule["name"] == "待審稿優先處理順序" for rule in result["writing_rule_updates"])
        assert not any(update["category"] == "content_strategy" and "落枕 類題目具持續投入價值" in update["pattern"] for update in result["knowledge_updates"])

    def test_returns_no_updates_when_data_missing(self):
        result = _fallback_weekly_reflection({
            "articles_this_week": [],
            "ranking_performance": [],
            "existing_knowledge": [],
        })

        assert result["knowledge_updates"] == []
        assert result["writing_rule_updates"] == []
        assert "資料不足" in result["session_summary"]


# ── reflect_on_pipeline ──────────────────────────────────────


class TestReflectOnPipeline:
    @pytest.mark.asyncio
    async def test_creates_reflection_log(self, db_session, sample_project):
        """成功建立 ReflectionLog"""
        pid = sample_project.id
        run_id = "test-run-123"

        llm_response = {
            "insights": [{"type": "pattern", "observation": "test insight", "confidence": "high"}],
            "knowledge_updates": [],
            "writing_rule_updates": [],
            "session_summary": "test summary",
        }

        with patch("contentflow.agents.reflective_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.reflective_agent._call_reflection_llm", new_callable=AsyncMock) as mock_llm:

            mock_llm.return_value = llm_response
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            log = await reflect_on_pipeline(run_id, pid)

        assert log is not None
        assert log.reflection_type == "post_pipeline"
        assert log.run_id == run_id
        assert "test summary" in log.session_summary


# ── reflect_on_human_edit ────────────────────────────────────


class TestReflectOnHumanEdit:
    @pytest.mark.asyncio
    async def test_no_change_returns_none(self):
        """相同內容 → None"""
        with patch("contentflow.agents.reflective_agent.SessionLocal"):
            result = await reflect_on_human_edit(1, 1, "same text", "same text")
        assert result is None

    @pytest.mark.asyncio
    async def test_diff_triggers_reflection(self, db_session, sample_project):
        """有差異 → 觸發 LLM 反思"""
        pid = sample_project.id
        llm_response = {
            "insights": [{"type": "pattern", "observation": "更具體的醫療建議", "confidence": "medium"}],
            "knowledge_updates": [{"category": "eeat", "pattern": "具體科別比籠統用語佳"}],
            "writing_rule_updates": [],
            "session_summary": "人工修改學習",
        }

        with patch("contentflow.agents.reflective_agent.SessionLocal") as mock_sl, \
             patch("contentflow.agents.reflective_agent._call_reflection_llm", new_callable=AsyncMock) as mock_llm:

            mock_llm.return_value = llm_response
            mock_sl.return_value.__enter__ = MagicMock(return_value=db_session)
            mock_sl.return_value.__exit__ = MagicMock(return_value=False)

            log = await reflect_on_human_edit(
                pid, 1,
                original_content="建議就醫\n其他內容",
                edited_content="建議諮詢骨科醫師\n其他內容",
            )

        assert log is not None
        assert log.reflection_type == "human_edit"
        assert log.knowledge_updates == 1
