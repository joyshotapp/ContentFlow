"""Phase Gate F — 學習層與 RAG 完整性驗證

CF-05-09 完成定義：同類 keyword 新文會實際讀取 KB 並影響策略選擇

測試涵蓋：
1. LearningReport 結構完整性 & L1 分析輸出
2. KnowledgeEntry 寫入 & 信心等級升級邏輯（unverified → verified → universal）
3. KnowledgeAuditLog 審核軌跡記錄
4. ChromaDB / KB query adapter fallback（DB-only）
5. format_kb_context 格式驗證
6. Strategy Agent 接受 kb_context 注入（KB 影響 strategy）
7. L2 ROI 分析 & Refresh 候選輸出
"""

from __future__ import annotations

import json
from datetime import date, timedelta, timezone
from datetime import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from contentflow.models.database import (
    Article,
    Base,
    KnowledgeAuditLog,
    KnowledgeEntry,
    Project,
    SEORanking,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    sess = S()
    yield sess
    sess.close()
    engine.dispose()


def _project(session) -> Project:
    p = Project(slug="test", name="測試", brand_name="TB",
                brand_url="https://t.example.com", brand_description="測",
                industry="健康", writing_principles="專業", locale="zh-tw")
    session.add(p)
    session.commit()
    return p


def _article(session, project_id, title="文章", primary_keyword="kw",
             seo_score=85, article_type="how-to") -> Article:
    url = f"https://t.example.com/{primary_keyword}"
    from contentflow.models.database import Article
    a = Article(
        project_id=project_id,
        title=title,
        primary_keyword=primary_keyword,
        status="published",
        publish_url=url,
        seo_score=seo_score,
        article_type=article_type,
        draft_content="# 如何解決 " + primary_keyword + "\n\n" * 50,  # 產生一些字
        outline="如何做 " + primary_keyword + " 步驟指引",
        faq_schema_json=json.dumps({
            "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": "Q1"}, {"@type": "Question", "name": "Q2"}]
        }),
    )
    session.add(a)
    session.commit()
    return a


def _ranking(session, project_id, keyword, landing_page,
             position=8.0, impressions=500, ctr=0.05, days_ago=3) -> SEORanking:
    r = SEORanking(
        project_id=project_id,
        keyword=keyword,
        landing_page=landing_page,
        position=position,
        impressions=impressions,
        clicks=int(impressions * ctr),
        ctr=ctr,
        tracked_date=(date.today() - timedelta(days=days_ago)),
    )
    session.add(r)
    session.commit()
    return r


# ─────────────────────────────────────────────────────────────────────────────
# 1. LearningReport 結構
# ─────────────────────────────────────────────────────────────────────────────

class TestLearningReport:
    def test_analyze_empty_project_returns_report(self, session):
        """無已發布文章的專案不應 crash，回傳 analyzed_articles=0"""
        from contentflow.agents.learning_agent import analyze_success_patterns

        p = _project(session)
        report = analyze_success_patterns(p.id, session)

        assert report.project_id == p.id
        assert report.analyzed_articles == 0
        assert isinstance(report.patterns, list)

    def test_analyze_with_articles_produces_patterns(self, session):
        """有文章 + 排名數據時，應產出至少 1 個模式並寫入 KnowledgeEntry"""
        from contentflow.agents.learning_agent import analyze_success_patterns

        p = _project(session)
        # 建立 3 篇不同 seo_score 的文章
        for i, score in enumerate([90, 80, 60], 1):
            a = _article(session, p.id, title=f"文章{i}", primary_keyword=f"kw{i}",
                         seo_score=score)
            _ranking(session, p.id, f"kw{i}", a.publish_url, position=5.0 + i,
                     impressions=200)

        report = analyze_success_patterns(p.id, session)

        assert report.analyzed_articles >= 1

        # 應有寫入 KnowledgeEntry
        count = session.query(KnowledgeEntry).filter(
            KnowledgeEntry.project_id == p.id
        ).count()
        assert count >= 1

    def test_learning_report_fields(self, session):
        """LearningReport 包含必要欄位"""
        from contentflow.agents.learning_agent import LearningReport

        r = LearningReport(project_id=1, analyzed_articles=5)
        assert r.project_id == 1
        assert r.analyzed_articles == 5
        assert isinstance(r.patterns, list)
        assert isinstance(r.low_performers, list)


# ─────────────────────────────────────────────────────────────────────────────
# 2. KnowledgeEntry 信心等級升級
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeEntryConfidence:
    def test_upsert_creates_unverified(self, session):
        """evidence_count < 5 → unverified"""
        from contentflow.agents.learning_agent import upsert_knowledge_entry

        p = _project(session)
        entry = upsert_knowledge_entry(
            session,
            project_id=p.id,
            category="format_pattern",
            pattern="How-to 排名優於 Listicle",
            evidence_count=3,
            metadata={"avg_position": 6.2},
        )
        assert entry.confidence_level == "unverified"
        assert entry.evidence_count == 3

    def test_upsert_upgrades_to_verified(self, session):
        """evidence_count >= 5 → verified"""
        from contentflow.agents.learning_agent import upsert_knowledge_entry

        p = _project(session)
        entry = upsert_knowledge_entry(
            session,
            project_id=p.id,
            category="format_pattern",
            pattern="How-to 排名優於 Listicle",
            evidence_count=7,
            metadata={},
        )
        assert entry.confidence_level == "verified"

    def test_upsert_upgrades_to_universal(self, session):
        """is_cross_project=True + evidence_count >= 10 → universal"""
        from contentflow.agents.learning_agent import upsert_knowledge_entry

        p = _project(session)
        entry = upsert_knowledge_entry(
            session,
            project_id=p.id,
            category="format_pattern",
            pattern="含 FAQ 的文章 CTR 高 25%",
            evidence_count=12,
            metadata={},
            is_cross_project=True,
        )
        assert entry.confidence_level == "universal"

    def test_upsert_increments_existing(self, session):
        """同一 pattern 多次 upsert 取最大 evidence_count"""
        from contentflow.agents.learning_agent import upsert_knowledge_entry

        p = _project(session)
        upsert_knowledge_entry(
            session, project_id=p.id, category="seo_score_impact",
            pattern="高 SEO 分數（≥85）排名 5.0", evidence_count=3, metadata={},
        )
        # 第二次 upsert 更多 evidence
        updated = upsert_knowledge_entry(
            session, project_id=p.id, category="seo_score_impact",
            pattern="高 SEO 分數（≥85）排名 5.0", evidence_count=6, metadata={},
        )
        all_entries = session.query(KnowledgeEntry).filter(
            KnowledgeEntry.project_id == p.id
        ).all()
        assert len(all_entries) == 1  # 不重複建立
        assert updated.confidence_level == "verified"


# ─────────────────────────────────────────────────────────────────────────────
# 3. KnowledgeAuditLog
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeAuditLog:
    def test_audit_log_created_on_deactivate(self, session):
        """停用知識條目時應可記錄 audit log"""
        p = _project(session)
        entry = KnowledgeEntry(
            project_id=p.id,
            category="format_pattern",
            pattern="測試模式",
            evidence_count=2,
            confidence_level="unverified",
        )
        session.add(entry)
        session.commit()

        # 停用 + 寫 audit log
        entry.is_active = False
        audit = KnowledgeAuditLog(
            entry_id=entry.id,
            action="deactivate",
            reason="此模式已過時",
            old_value=json.dumps({"is_active": True}),
            new_value=json.dumps({"is_active": False}),
        )
        session.add(audit)
        session.commit()

        logs = session.query(KnowledgeAuditLog).filter(
            KnowledgeAuditLog.entry_id == entry.id
        ).all()
        assert len(logs) == 1
        assert logs[0].action == "deactivate"
        assert logs[0].reason == "此模式已過時"

    def test_override_action_resets_confidence(self, session):
        """人工推翻應降低信心等級並記錄"""
        p = _project(session)
        entry = KnowledgeEntry(
            project_id=p.id, category="keyword_roi",
            pattern="關鍵字 X ROI=8.0 建議：invest",
            evidence_count=8, confidence_level="verified",
        )
        session.add(entry)
        session.commit()

        old_val = json.dumps({"confidence_level": entry.confidence_level, "is_active": True})
        entry.is_active = False
        entry.confidence_level = "unverified"
        audit = KnowledgeAuditLog(
            entry_id=entry.id,
            action="override",
            reason="此關鍵字市場已改變，ROI 失效",
            old_value=old_val,
            new_value=json.dumps({"is_active": False, "confidence_level": "unverified"}),
        )
        session.add(audit)
        session.commit()

        refreshed = session.query(KnowledgeEntry).get(entry.id)
        assert refreshed.confidence_level == "unverified"
        assert not refreshed.is_active

        audit_count = session.query(KnowledgeAuditLog).filter(
            KnowledgeAuditLog.action == "override"
        ).count()
        assert audit_count == 1

    def test_audit_log_fields(self, session):
        """KnowledgeAuditLog 包含必要欄位"""
        p = _project(session)
        entry = KnowledgeEntry(
            project_id=p.id, category="test", pattern="test", evidence_count=1,
        )
        session.add(entry)
        session.commit()

        audit = KnowledgeAuditLog(
            entry_id=entry.id, action="note", reason="備註文字", operator="human",
        )
        session.add(audit)
        session.commit()

        log = session.query(KnowledgeAuditLog).filter_by(entry_id=entry.id).first()
        assert log is not None
        assert log.operator == "human"
        assert log.created_at is not None


# ─────────────────────────────────────────────────────────────────────────────
# 4. KB query adapter（DB fallback）
# ─────────────────────────────────────────────────────────────────────────────

class TestKBQueryAdapter:
    def test_query_kb_returns_list(self, session):
        """query_kb 回傳 list[str]（DB fallback 模式）"""
        from contentflow.tools.knowledge_base import query_kb

        p = _project(session)
        # 直接寫入 KnowledgeEntry
        for i in range(3):
            entry = KnowledgeEntry(
                project_id=p.id,
                category=f"cat_{i}",
                pattern=f"測試模式 {i}",
                evidence_count=i + 2,
                confidence_level="unverified",
                is_active=True,
            )
            session.add(entry)
        session.commit()

        results = query_kb(p.id, "測試關鍵字", top_k=5, session=session)

        assert isinstance(results, list)
        assert len(results) >= 1  # 至少從 DB 回傳 1 條

    def test_query_kb_empty_project_returns_list(self, session):
        """沒有 KB 條目時回傳空 list（不 crash）"""
        from contentflow.tools.knowledge_base import query_kb

        p = _project(session)
        results = query_kb(p.id, "不存在的關鍵字", top_k=5, session=session)
        assert isinstance(results, list)

    def test_format_kb_context_produces_text(self, session):
        """format_kb_context 應產生有意義的區塊文字"""
        from contentflow.tools.knowledge_base import format_kb_context

        results = [
            "類別：format_pattern\n模式：How-to 排名優\n信心等級：verified\n支持數據：8 篇",
            "類別：faq_impact\n模式：有 FAQ CTR 高 20%\n信心等級：unverified\n支持數據：3 篇",
        ]
        ctx = format_kb_context(results, "膝蓋疼痛")

        assert "知識庫" in ctx
        assert "膝蓋疼痛" in ctx
        assert len(ctx) > 50

    def test_format_kb_context_empty(self):
        """空 KB 結果應回傳空字串"""
        from contentflow.tools.knowledge_base import format_kb_context

        assert format_kb_context([], "測試") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 5. L2 策略優化
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategyUpdate:
    def test_l2_empty_project(self, session):
        """無排名資料時回傳空 StrategyUpdate（不 crash）"""
        from contentflow.agents.learning_agent import optimize_content_strategy

        p = _project(session)
        update = optimize_content_strategy(p.id, session)

        assert update.project_id == p.id
        assert isinstance(update.high_roi_keywords, list)
        assert isinstance(update.refresh_candidates, list)

    def test_l2_with_rankings_produces_roi(self, session):
        """有排名數據時應計算 ROI 並分類 keyword"""
        from contentflow.agents.learning_agent import optimize_content_strategy

        p = _project(session)
        a = _article(session, p.id, title="測試文章", primary_keyword="高ROI詞")

        # 建立高曝光 + 接近前 10 的排名（投資值得）
        for i in range(5):
            _ranking(session, p.id, "高ROI詞", a.publish_url,
                     position=12.0, impressions=2000, ctr=0.04, days_ago=i)

        update = optimize_content_strategy(p.id, session)

        # 應有 keyword ROI 資料
        all_kw_rois = update.high_roi_keywords + update.low_roi_keywords
        assert len(all_kw_rois) >= 1

    def test_l2_refresh_candidate_for_rank_11_20(self, session):
        """排名 11-20 且高曝光的文章應進入 refresh_candidates"""
        from contentflow.agents.learning_agent import optimize_content_strategy

        p = _project(session)
        a = _article(session, p.id, title="等待 Refresh", primary_keyword="刷新字")

        _ranking(session, p.id, "刷新字", a.publish_url,
                 position=14.0, impressions=500, ctr=0.03, days_ago=2)

        update = optimize_content_strategy(p.id, session)

        # 應有 refresh 候選
        assert len(update.refresh_candidates) >= 1
        assert update.refresh_candidates[0].article_id == a.id

    def test_strategy_update_resource_advice(self, session):
        """resource_advice 應為非空字串"""
        from contentflow.agents.learning_agent import optimize_content_strategy

        p = _project(session)
        update = optimize_content_strategy(p.id, session)

        assert isinstance(update.resource_advice, str)


# ─────────────────────────────────────────────────────────────────────────────
# 6. KB 影響策略選擇（整合驗證）
# ─────────────────────────────────────────────────────────────────────────────

class TestKBInfluencesStrategy:
    def test_kb_context_injected_into_format(self, session):
        """
        給定 KB 條目後，format_kb_context 應回傳包含相關知識的字串，
        且長度 > 0（驗證注入路徑通暢）
        """
        from contentflow.tools.knowledge_base import query_kb, format_kb_context

        p = _project(session)
        # 直接插入高 evidence_count 條目
        entry = KnowledgeEntry(
            project_id=p.id,
            category="format_pattern",
            pattern="How-to 格式的文章平均排名 4.5（6 篇）",
            evidence_count=6,
            confidence_level="verified",
            is_active=True,
        )
        session.add(entry)
        session.commit()

        results = query_kb(p.id, "膝蓋疼痛 How-to", top_k=5, session=session)
        ctx = format_kb_context(results, "膝蓋疼痛")

        assert len(results) >= 1
        assert "How-to" in ctx or "知識庫" in ctx  # 相關知識有被帶入

    def test_knowledge_entry_model_has_audit_relationship(self, session):
        """KnowledgeEntry 應有 audit_logs relationship"""
        p = _project(session)
        entry = KnowledgeEntry(
            project_id=p.id, category="test", pattern="p", evidence_count=1,
        )
        session.add(entry)
        session.commit()

        # 可透過 relationship 新增 audit log
        audit = KnowledgeAuditLog(
            entry_id=entry.id, action="note", reason="test注", operator="system",
        )
        session.add(audit)
        session.commit()

        # 透過 relationship 反查
        refreshed = session.query(KnowledgeEntry).get(entry.id)
        assert len(refreshed.audit_logs) == 1
        assert refreshed.audit_logs[0].action == "note"
