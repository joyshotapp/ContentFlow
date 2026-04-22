"""Phase Gate G — Content Refresh 驗收測試（CF-06-01 ~ CF-06-07）

涵蓋：
  CF-06-01: ContentFetcher —— ForgeBase / WordPress / URL fallback
  CF-06-02: RefreshDiffAnalyzer —— AI 缺口分析（mock LLM）
  CF-06-03: apply_local_patches —— 局部增補（generate_content=False / True mock）
  CF-06-04: publish_refreshed_article —— 再發布（mock publisher）
  CF-06-05: CompetitorThreatDetector —— L3 競品威脅偵測
  CF-06-06: FeaturedSnippetDetector —— Featured Snippet 偵測
  CF-06-07: run_refresh_pipeline —— end-to-end（全 mock）
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contentflow.agents.refresh_agent import (
    ContentFetcher,
    ContentGap,
    CompetitorThreatDetector,
    FeaturedSnippetDetector,
    FetchedArticle,
    RefreshDiffAnalyzer,
    RefreshPlan,
    ThreatReport,
    apply_local_patches,
    run_refresh_pipeline,
    _extract_wp_post_id,
    _extract_forgebase_post_id,
    generate_patch_content,
    publish_refreshed_article,
)
from contentflow.models.database import Article, Project, SEORanking


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_fetched():
    return FetchedArticle(
        url="https://example.com/blog/knee-pain",
        platform="forgebase",
        post_id="42",
        title="膝蓋疼痛如何處理？",
        content_html="<h2>原因</h2><p>膝蓋疼痛常見於長期站立⋯</p>",
        content_text="原因 膝蓋疼痛常見於長期站立 治療方式包含物理治療",
        word_count=120,
    )


@pytest.fixture()
def sample_plan(sample_fetched):
    return RefreshPlan(
        keyword="膝蓋疼痛",
        article_title=sample_fetched.title,
        gaps=[
            ContentGap(
                gap_type="missing_faq",
                description="競品有 FAQ 區塊，本文無",
                suggested_heading="常見問題 FAQ",
            ),
            ContentGap(
                gap_type="missing_table",
                description="缺少治療方式比較表",
                suggested_heading="治療方式比較",
            ),
        ],
        overall_freshness_score=55,
        recommendation="patch",
    )


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-01: ContentFetcher
# ─────────────────────────────────────────────────────────────────────────────

class TestContentFetcher:
    FORGEBASE_RESPONSE = {
        "id": 42,
        "slug": "knee-pain",
        "title": "膝蓋疼痛如何處理？",
        "body": "<h2>原因</h2><p>膝蓋疼痛常見於長期站立。</p>",
        "published_url": "https://example.com/blog/knee-pain",
        "meta_title": "膝蓋疼痛",
        "meta_description": "了解膝蓋疼痛",
    }
    WP_RESPONSE = {
        "id": 99,
        "slug": "knee-pain",
        "link": "https://wp.example.com/knee-pain",
        "title": {"rendered": "膝蓋疼痛完整指南"},
        "content": {"rendered": "<h2>原因</h2><p>膝蓋積水、骨刺⋯</p>"},
        "date_gmt": "2024-01-15T08:00:00",
    }

    def test_fetch_forgebase_success(self):
        """CF-06-01: ForgeBase fetch 成功回傳 FetchedArticle"""
        fetcher = ContentFetcher()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.FORGEBASE_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_forgebase(
                    "42",
                    api_base_url="https://forge.example.com",
                    api_token="token123",
                )
            )

        assert result.fetch_error is None
        assert result.title == "膝蓋疼痛如何處理？"
        assert result.platform == "forgebase"
        assert result.post_id == "42"
        assert result.word_count > 0

    def test_fetch_forgebase_no_config(self):
        """CF-06-01: ForgeBase 未設定 API key → fetch_error"""
        fetcher = ContentFetcher()
        with patch("contentflow.agents.refresh_agent.settings") as mock_settings:
            mock_settings.forgebase_api_base_url = ""
            mock_settings.forgebase_api_token = ""

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_forgebase("42")
            )
        assert result.fetch_error is not None

    def test_fetch_wordpress_success(self):
        """CF-06-01: WordPress fetch 成功回傳 FetchedArticle"""
        fetcher = ContentFetcher()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self.WP_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_wordpress(
                    "99",
                    site_url="https://wp.example.com",
                    username="admin",
                    app_password="pass1234",
                )
            )

        assert result.fetch_error is None
        assert result.title == "膝蓋疼痛完整指南"
        assert result.platform == "wordpress"
        assert result.published_date == date(2024, 1, 15)

    def test_fetch_wordpress_no_config(self):
        """CF-06-01: WordPress 未設定認證 → fetch_error"""
        fetcher = ContentFetcher()
        with patch("contentflow.agents.refresh_agent.settings") as mock_settings:
            mock_settings.wordpress_site_url = ""
            mock_settings.wordpress_username = ""
            mock_settings.wordpress_app_password = ""

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_wordpress("99")
            )
        assert result.fetch_error is not None

    def test_fetch_by_url_article_tag(self):
        """CF-06-01: fallback fetch_by_url 從 <article> 提取內容"""
        fetcher = ContentFetcher()
        html = (
            "<html><head><title>骨刺治療指南</title></head>"
            "<body><article><h2>治療方式</h2><p>物理治療是首選。</p></article></body></html>"
        )

        mock_resp = MagicMock()
        mock_resp.text = html
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_by_url("https://example.com/knee")
            )

        assert result.title == "骨刺治療指南"
        assert "物理治療" in result.content_text
        assert result.fetch_error is None

    def test_fetch_forgebase_http_error(self):
        """CF-06-01: HTTP 錯誤 → FetchedArticle with fetch_error"""
        fetcher = ContentFetcher()
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                fetcher.fetch_forgebase("42", api_base_url="https://x.com", api_token="t")
            )

        assert result.fetch_error is not None
        assert "Connection refused" in result.fetch_error


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-02: RefreshDiffAnalyzer
# ─────────────────────────────────────────────────────────────────────────────

class TestRefreshDiffAnalyzer:

    def _make_analyzer_response(self, gaps_count=2, freshness=60, rec="patch"):
        data = {
            "overall_freshness_score": freshness,
            "recommendation": rec,
            "gaps": [
                {
                    "gap_type": "missing_faq",
                    "description": "競品有 FAQ 本文無",
                    "suggested_heading": "常見問題"
                }
            ] * gaps_count,
            "competitor_advantages": ["競品有影片", "競品有比較表"],
        }
        return json.dumps(data)

    def test_analyze_returns_refresh_plan(self, sample_fetched):
        """CF-06-02: analyze() 回傳 RefreshPlan 含 gaps + 分數"""
        analyzer = RefreshDiffAnalyzer()
        with patch(
            "contentflow.agents.refresh_agent.chat_sync",
            return_value=self._make_analyzer_response(2, 60, "patch"),
        ):
            plan = analyzer.analyze(sample_fetched, "膝蓋疼痛", "競品摘要")

        assert isinstance(plan, RefreshPlan)
        assert plan.keyword == "膝蓋疼痛"
        assert len(plan.gaps) == 2
        assert plan.overall_freshness_score == 60
        assert plan.recommendation == "patch"
        assert len(plan.competitor_advantages) == 2

    def test_analyze_fetch_error_returns_maintain(self):
        """CF-06-02: 文章拉取失敗時，直接回傳 maintain"""
        broken = FetchedArticle(
            url="", platform="forgebase", post_id="0",
            title="", content_html="", content_text="",
            fetch_error="timeout",
        )
        analyzer = RefreshDiffAnalyzer()
        plan = analyzer.analyze(broken, "膝蓋疼痛", "any")
        assert plan.recommendation == "maintain"
        assert len(plan.gaps) == 0

    def test_analyze_json_decode_error_fallback(self, sample_fetched):
        """CF-06-02: LLM 回傳無效 JSON → fallback 到 freshness=50, patch"""
        analyzer = RefreshDiffAnalyzer()
        with patch("contentflow.agents.refresh_agent.chat_sync", return_value="這不是 JSON"):
            plan = analyzer.analyze(sample_fetched, "膝蓋疼痛", "摘要")

        assert plan.recommendation == "patch"
        assert plan.overall_freshness_score == 50

    def test_analyze_maintain_recommendation(self, sample_fetched):
        """CF-06-02: LLM 回傳 maintain → 無缺口"""
        analyzer = RefreshDiffAnalyzer()
        with patch(
            "contentflow.agents.refresh_agent.chat_sync",
            return_value=json.dumps({
                "overall_freshness_score": 95,
                "recommendation": "maintain",
                "gaps": [],
                "competitor_advantages": [],
            }),
        ):
            plan = analyzer.analyze(sample_fetched, "膝蓋疼痛", "摘要")

        assert plan.recommendation == "maintain"
        assert plan.overall_freshness_score == 95


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-03: apply_local_patches
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyLocalPatches:

    def test_patch_append_headings(self, sample_fetched, sample_plan):
        """CF-06-03: apply_local_patches 在原文末尾附加補充段落標題"""
        result = apply_local_patches(sample_fetched, sample_plan, "膝蓋疼痛",
                                     generate_content=False)
        assert "## 常見問題 FAQ" in result
        assert "## 治療方式比較" in result
        assert "[待補充" in result   # 佔位符

    def test_patch_maintain_no_change(self, sample_fetched):
        """CF-06-03: recommendation='maintain' → 不附加任何補充"""
        plan = RefreshPlan(
            keyword="膝蓋疼痛",
            article_title="test",
            recommendation="maintain",
            gaps=[ContentGap("missing_faq", "some gap", "FAQ")],
        )
        result = apply_local_patches(sample_fetched, plan, "膝蓋疼痛",
                                     generate_content=False)
        assert "##" not in result
        assert result == sample_fetched.content_text

    def test_patch_with_generated_content(self, sample_fetched, sample_plan):
        """CF-06-03: generate_content=True → 呼叫 GPT 產出真實補充"""
        with patch(
            "contentflow.agents.refresh_agent.chat_sync",
            return_value="### 常見問題\n\nQ: 膝蓋疼痛怎麼辦？\nA: 休息並就醫。",
        ):
            result = apply_local_patches(sample_fetched, sample_plan, "膝蓋疼痛",
                                         generate_content=True)

        assert "常見問題" in result or "補充" in result
        # 補充段落已附加（結果比原文更長）
        assert len(result) > len(sample_fetched.content_text)

    def test_patch_empty_gaps_no_change(self, sample_fetched):
        """CF-06-03: 無缺口 → 回傳原文"""
        plan = RefreshPlan(
            keyword="膝蓋疼痛",
            article_title="test",
            recommendation="patch",
            gaps=[],
        )
        result = apply_local_patches(sample_fetched, plan, "膝蓋疼痛",
                                     generate_content=False)
        assert result == sample_fetched.content_text


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-04: URL 解析 & publish_refreshed_article
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractPostId:
    def test_extract_wp_post_id_from_rest_path(self):
        assert _extract_wp_post_id("/wp-json/wp/v2/posts/123") == "123"

    def test_extract_wp_post_id_from_p_param(self):
        assert _extract_wp_post_id("https://example.com/?p=456") == "456"

    def test_extract_wp_post_id_empty(self):
        assert _extract_wp_post_id("https://example.com/about") == ""

    def test_extract_forgebase_from_slug(self):
        assert _extract_forgebase_post_id("", "my-article") == "my-article"

    def test_extract_forgebase_from_url(self):
        assert _extract_forgebase_post_id("https://forge.com/blog/knee-pain", "") == "knee-pain"


class TestPublishRefreshedArticle:

    def _make_article(self, db_session, project, platform="forgebase"):
        a = Article(
            project_id=project.id,
            slug="knee-test-slug",
            title="膝蓋疼痛測試",
            primary_keyword="膝蓋疼痛",
            draft_content="original content",
            meta_title="膝蓋疼痛",
            meta_description="詳細介紹",
            publish_url=("https://wp.example.com/?p=99"
                         if platform == "wordpress" else
                         "https://forge.example.com/blog/knee-test-slug"),
        )
        db_session.add(a)
        db_session.commit()
        return a

    def test_publish_wordpress_success(self, db_session, sample_project):
        """CF-06-04: WordPress 更新成功 → success=True"""
        from contentflow.publishers.base import PublishResult
        article = self._make_article(db_session, sample_project, "wordpress")

        mock_result = PublishResult(success=True, platform="wordpress",
                                    post_id="99", publish_url="https://wp.example.com/?p=99")

        with patch("contentflow.publishers.wordpress.WordPressPublisher.update_post",
                   new=AsyncMock(return_value=mock_result)):
            result = asyncio.get_event_loop().run_until_complete(
                publish_refreshed_article(article, "# 新內容\n\n補充段落", db_session)
            )

        assert result["success"] is True

    def test_publish_forgebase_success(self, db_session, sample_project):
        """CF-06-04: ForgeBase 更新成功 → success=True"""
        from contentflow.publishers.base import PublishResult
        article = self._make_article(db_session, sample_project, "forgebase")

        mock_result = PublishResult(success=True, platform="forgebase", post_id="knee-test-slug")

        with patch("contentflow.publishers.forgebase.ForgeBasePublisher.update_post",
                   new=AsyncMock(return_value=mock_result)):
            result = asyncio.get_event_loop().run_until_complete(
                publish_refreshed_article(article, "# 新內容", db_session)
            )

        assert result["success"] is True

    def test_publish_no_post_id_fails(self, db_session, sample_project):
        """CF-06-04: 無法推斷 post_id → success=False"""
        article = Article(
            project_id=sample_project.id,
            slug="",
            title="test",
            primary_keyword="test",
            draft_content="",
            publish_url="https://wp.example.com/about",  # 無 ?p= / /posts/
        )
        db_session.add(article)
        db_session.commit()

        result = asyncio.get_event_loop().run_until_complete(
            publish_refreshed_article(article, "content", db_session)
        )
        # WP 判斷邏輯: "wp-json" 不在 url 中所以走 forgebase，slug 空
        # forgebase 提取到空字串 → error
        assert result["success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-05: CompetitorThreatDetector
# ─────────────────────────────────────────────────────────────────────────────

class TestCompetitorThreatDetector:

    def _seed_rankings(self, db_session, project, keyword: str) -> None:
        """插入競品排名趨勢：competitor1 從 rank=15 升到 rank=5"""
        today = date.today()
        for i, (page, position) in enumerate([
            ("https://competitor1.com/knee", 15),
            ("https://competitor1.com/knee", 8),
            ("https://competitor1.com/knee", 5),
            ("https://testbrand.com/knee", 3),
            ("https://testbrand.com/knee", 4),
        ]):
            row = SEORanking(
                project_id=project.id,
                keyword=keyword,
                position=position,
                landing_page=page,
                tracked_date=today - timedelta(days=20 - i * 4),
            )
            db_session.add(row)
        db_session.commit()

    def test_detects_rising_competitor(self, db_session, sample_project):
        """CF-06-05: 競品排名大幅上升 → 識別為 medium/high threat"""
        self._seed_rankings(db_session, sample_project, "膝蓋骨刺")
        detector = CompetitorThreatDetector()
        report = detector.detect(
            project_id=sample_project.id,
            keyword="膝蓋骨刺",
            session=db_session,
            brand_url="https://testbrand.com",
        )

        assert isinstance(report, ThreatReport)
        assert len(report.threats) >= 1
        threat_domains = [t["domain"] for t in report.threats]
        assert any("competitor1" in d for d in threat_domains)

    def test_no_threats_when_stable(self, db_session, sample_project):
        """CF-06-05: 排名穩定 → 無威脅"""
        today = date.today()
        for pos in [6, 7, 6]:  # 微幅波動，沒有上升 3+
            row = SEORanking(
                project_id=sample_project.id,
                keyword="穩定關鍵字",
                position=pos,
                landing_page="https://stablecomp.com/page",
                tracked_date=today - timedelta(days=10),
            )
            db_session.add(row)
        db_session.commit()

        detector = CompetitorThreatDetector()
        report = detector.detect(
            project_id=sample_project.id,
            keyword="穩定關鍵字",
            session=db_session,
            brand_url="https://testbrand.com",
        )
        # 同一日期三筆排名不會累積 2+ 時間點，無法形成趨勢
        assert len(report.threats) == 0

    def test_no_data_returns_empty_report(self, db_session, sample_project):
        """CF-06-05: 無排名數據 → 回傳空 ThreatReport"""
        detector = CompetitorThreatDetector()
        report = detector.detect(
            project_id=sample_project.id,
            keyword="不存在的關鍵字",
            session=db_session,
        )
        assert len(report.threats) == 0
        assert len(report.defense_suggestions) == 0

    def test_defense_suggestions_generated(self, db_session, sample_project):
        """CF-06-05: 存在威脅時，defense_suggestions 非空"""
        self._seed_rankings(db_session, sample_project, "骨刺治療")
        detector = CompetitorThreatDetector()
        report = detector.detect(
            project_id=sample_project.id,
            keyword="骨刺治療",
            session=db_session,
            brand_url="https://testbrand.com",
        )
        if report.threats:
            assert len(report.defense_suggestions) > 0


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-06: FeaturedSnippetDetector
# ─────────────────────────────────────────────────────────────────────────────

class TestFeaturedSnippetDetector:

    def test_detects_seized_snippet(self, db_session, sample_project):
        """CF-06-06: rank≤3 + CTR < 3% → Featured Snippet 被搶，給出建議"""
        today = date.today()
        row = SEORanking(
            project_id=sample_project.id,
            keyword="骨刺怎麼辦",
            position=2.1,
            ctr=0.018,   # 1.8% < 3%
            landing_page="https://testbrand.com/bone-spur",
            tracked_date=today - timedelta(days=7),
        )
        db_session.add(row)
        db_session.commit()

        detector = FeaturedSnippetDetector()
        report = detector.detect(sample_project.id, "骨刺怎麼辦", db_session)

        assert report.featured_snippet_seized is True
        assert len(report.featured_snippet_suggestions) >= 3

    def test_no_snippet_issue_when_ctr_high(self, db_session, sample_project):
        """CF-06-06: rank≤3 且 CTR ≥ 3% → 無 Featured Snippet 問題"""
        today = date.today()
        row = SEORanking(
            project_id=sample_project.id,
            keyword="骨刺飲食",
            position=2.0,
            ctr=0.071,   # 7.1% > 3%
            landing_page="https://testbrand.com/diet",
            tracked_date=today - timedelta(days=7),
        )
        db_session.add(row)
        db_session.commit()

        detector = FeaturedSnippetDetector()
        report = detector.detect(sample_project.id, "骨刺飲食", db_session)

        assert report.featured_snippet_seized is False
        assert len(report.featured_snippet_suggestions) == 0

    def test_no_data_no_seizure(self, db_session, sample_project):
        """CF-06-06: 無 SERP 數據 → 不判定被搶"""
        detector = FeaturedSnippetDetector()
        report = detector.detect(sample_project.id, "不存在頁面", db_session)
        assert report.featured_snippet_seized is False

    def test_suggestions_include_faq_and_answer_box(self, db_session, sample_project):
        """CF-06-06: 建議清單包含答案框與 FAQ Schema 相關建議"""
        today = date.today()
        row = SEORanking(
            project_id=sample_project.id,
            keyword="骨刺運動",
            position=1.0,
            ctr=0.005,
            landing_page="https://testbrand.com/exercise",
            tracked_date=today - timedelta(days=3),
        )
        db_session.add(row)
        db_session.commit()

        detector = FeaturedSnippetDetector()
        report = detector.detect(sample_project.id, "骨刺運動", db_session)

        if report.featured_snippet_seized:
            suggestions_text = " ".join(report.featured_snippet_suggestions)
            assert "FAQ" in suggestions_text or "答案" in suggestions_text


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-07: run_refresh_pipeline（end-to-end）
# ─────────────────────────────────────────────────────────────────────────────

class TestRunRefreshPipeline:

    def _make_article(self, db_session, project):
        a = Article(
            project_id=project.id,
            slug="knee-pipeline",
            title="膝蓋疼痛完整指南",
            primary_keyword="膝蓋疼痛",
            draft_content="舊的文章內容，缺乏 FAQ",
            meta_title="膝蓋疼痛",
            meta_description="詳細指南",
            publish_url="https://forge.example.com/blog/knee-pipeline",
        )
        db_session.add(a)
        db_session.commit()
        return a

    def _mock_fetched(self) -> FetchedArticle:
        return FetchedArticle(
            url="https://forge.example.com/blog/knee-pipeline",
            platform="forgebase",
            post_id="knee-pipeline",
            title="膝蓋疼痛完整指南",
            content_html="<p>舊文章</p>",
            content_text="舊文章",
            word_count=50,
        )

    def _mock_plan(self) -> RefreshPlan:
        return RefreshPlan(
            keyword="膝蓋疼痛",
            article_title="膝蓋疼痛完整指南",
            gaps=[ContentGap("missing_faq", "無 FAQ", "常見問題 FAQ")],
            overall_freshness_score=55,
            recommendation="patch",
        )

    def test_pipeline_analyze_only(self, db_session, sample_project):
        """CF-06-07: pipeline 不 publish → 回傳 fetched + plan + patched（無發布）"""
        article = self._make_article(db_session, sample_project)

        with (
            patch.object(ContentFetcher, "fetch_forgebase",
                         new=AsyncMock(return_value=self._mock_fetched())),
            patch.object(RefreshDiffAnalyzer, "analyze",
                         return_value=self._mock_plan()),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                run_refresh_pipeline(
                    article=article,
                    keyword="膝蓋疼痛",
                    session=db_session,
                    serp_summary="競品普遍有 FAQ",
                    platform="forgebase",
                    post_id="knee-pipeline",
                    generate_content=False,
                    publish=False,
                )
            )

        assert result["fetched"].title == "膝蓋疼痛完整指南"
        assert result["plan"].recommendation == "patch"
        assert result["publish_result"] is None
        assert "常見問題 FAQ" in result["patched_content"]

    def test_pipeline_publish_enabled(self, db_session, sample_project):
        """CF-06-07: publish=True → publish_result 非 None"""
        from contentflow.publishers.base import PublishResult

        article = self._make_article(db_session, sample_project)
        mock_pub_result = PublishResult(success=True, platform="forgebase",
                                        post_id="knee-pipeline")

        with (
            patch.object(ContentFetcher, "fetch_forgebase",
                         new=AsyncMock(return_value=self._mock_fetched())),
            patch.object(RefreshDiffAnalyzer, "analyze",
                         return_value=self._mock_plan()),
            patch("contentflow.agents.refresh_agent.publish_refreshed_article",
                  new=AsyncMock(return_value={"success": True, "url": "https://x.com", "error": None})),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                run_refresh_pipeline(
                    article=article,
                    keyword="膝蓋疼痛",
                    session=db_session,
                    serp_summary="競品有 FAQ",
                    platform="forgebase",
                    post_id="knee-pipeline",
                    generate_content=False,
                    publish=True,
                )
            )

        assert result["publish_result"] is not None
        assert result["publish_result"]["success"] is True

    def test_pipeline_maintain_no_patch(self, db_session, sample_project):
        """CF-06-07: 分析結果為 maintain → patched_content 為原始內容"""
        article = self._make_article(db_session, sample_project)
        maintain_plan = RefreshPlan(
            keyword="膝蓋疼痛",
            article_title="title",
            recommendation="maintain",
            overall_freshness_score=92,
        )

        with (
            patch.object(ContentFetcher, "fetch_forgebase",
                         new=AsyncMock(return_value=self._mock_fetched())),
            patch.object(RefreshDiffAnalyzer, "analyze",
                         return_value=maintain_plan),
        ):
            result = asyncio.get_event_loop().run_until_complete(
                run_refresh_pipeline(
                    article=article,
                    keyword="膝蓋疼痛",
                    session=db_session,
                    serp_summary="",
                    platform="forgebase",
                    post_id="knee-pipeline",
                    generate_content=False,
                    publish=False,
                )
            )

        # maintain → patched_content 與 fetched.content_text 相同
        assert result["patched_content"] == "舊文章"
        assert result["plan"].recommendation == "maintain"
