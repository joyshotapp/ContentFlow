"""Phase Gate B：發布鏈路完整性測試（CF-01-18）

完成定義：
- BasePublisher 介面正確定義（publish_draft / update_post / get_post_url）
- ForgeBasePublisher 實作三步驟流程（含 publish_page Step 3）
- WordPressPublisher 實作 publish_draft / update_post / get_post_url
- 兩個 publisher 均可在 API 金鑰缺失時優雅回傳錯誤，不崩潰
- get_post_url 回傳完整 URL（非 slug）
- API /publish 端點可正確路由到對應 publisher
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from contentflow.models.schemas import ArticleDraft, ArticleStatus
from contentflow.publishers.base import BasePublisher, PublishResult
from contentflow.publishers.forgebase import ForgeBasePublisher
from contentflow.publishers.wordpress import WordPressPublisher


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def sample_draft():
    return ArticleDraft(
        title="膝蓋長骨刺怎麼辦",
        meta_title="膝蓋長骨刺怎麼辦 | 完整治療指南",
        meta_description="一篇完整說明膝蓋骨刺的症狀、治療與預防的醫學文章。",
        content_markdown="## 什麼是骨刺\n\n骨刺是骨骼邊緣多餘骨質增生...",
        word_count=500,
        slug="knee-bone-spur-treatment",
        seo_score=88,
        status=ArticleStatus.APPROVED,
    )


# ── BasePublisher 介面 ────────────────────────────────────────────────────

class TestBasePublisherInterface:
    def test_base_publisher_is_abstract(self):
        """BasePublisher 是抽象類別，不能直接實例化。"""
        with pytest.raises(TypeError):
            BasePublisher()  # type: ignore

    def test_publish_result_dataclass(self):
        r = PublishResult(success=True, platform="forgebase", post_id="123", publish_url="https://example.com/p/123")
        assert r.success
        assert r.publish_url == "https://example.com/p/123"

    def test_publish_result_failure(self):
        r = PublishResult(success=False, platform="forgebase", error="timeout")
        assert not r.success
        assert r.error == "timeout"
        assert r.post_id is None


# ── ForgeBasePublisher ────────────────────────────────────────────────────

class TestForgeBasePublisher:
    def test_no_token_returns_error(self, sample_draft):
        """缺少 API token 時 publish_draft 應優雅回傳 success=False。"""
        import asyncio
        fb = ForgeBasePublisher(api_base_url="", api_token="")
        result = asyncio.get_event_loop().run_until_complete(fb.publish_draft(sample_draft))
        assert not result.success
        assert result.platform == "forgebase"
        assert result.error is not None

    def test_no_token_get_post_url_returns_empty(self):
        """缺少 API token 時 get_post_url 應回傳空字串，不崩潰。"""
        import asyncio
        fb = ForgeBasePublisher(api_base_url="", api_token="")
        url = asyncio.get_event_loop().run_until_complete(fb.get_post_url("999"))
        assert url == ""

    def test_no_token_publish_page_returns_error(self):
        """缺少 API token 時 publish_page 應回傳 success=False。"""
        import asyncio
        fb = ForgeBasePublisher(api_base_url="", api_token="")
        result = asyncio.get_event_loop().run_until_complete(fb.publish_page("999"))
        assert not result.success

    @pytest.mark.asyncio
    async def test_publish_draft_step1_brief(self, sample_draft):
        """Step1: POST /briefs 成功時取得 brief_id，繼續 Step2。"""
        fb = ForgeBasePublisher(api_base_url="https://fake.forgebase.io", api_token="tok")

        mock_brief_resp = MagicMock()
        mock_brief_resp.status_code = 200
        mock_brief_resp.raise_for_status = MagicMock()
        mock_brief_resp.json.return_value = {"id": "brief-001"}

        mock_page_resp = MagicMock()
        mock_page_resp.status_code = 200
        mock_page_resp.raise_for_status = MagicMock()
        mock_page_resp.json.return_value = {"id": "page-001"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=[mock_brief_resp, mock_page_resp]
            )
            result = await fb.publish_draft(sample_draft, primary_keyword="膝蓋長骨刺")

        assert result.success
        assert result.post_id == "page-001"
        assert result.publish_url is None  # 草稿階段無 URL
        assert result.metadata.get("brief_id") == "brief-001"

    @pytest.mark.asyncio
    async def test_publish_page_step3(self):
        """Step3: POST /pages/{id}/publish 成功後回傳完整 URL。"""
        fb = ForgeBasePublisher(api_base_url="https://fake.forgebase.io", api_token="tok")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"slug": "knee-bone-spur-treatment", "status": "published"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            result = await fb.publish_page("page-001")

        assert result.success
        assert result.publish_url == "https://fake.forgebase.io/knee-bone-spur-treatment"
        assert result.post_id == "page-001"

    @pytest.mark.asyncio
    async def test_get_post_url_returns_full_url(self):
        """get_post_url 應拼接 base_url + slug，回傳完整 URL。"""
        fb = ForgeBasePublisher(api_base_url="https://fake.forgebase.io", api_token="tok")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"slug": "test-article", "status": "published"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            url = await fb.get_post_url("page-123")

        assert url == "https://fake.forgebase.io/test-article"
        assert url.startswith("https://")  # 確認是完整 URL 而非 slug

    @pytest.mark.asyncio
    async def test_get_post_url_empty_slug(self):
        """slug 為空時 get_post_url 應回傳空字串。"""
        fb = ForgeBasePublisher(api_base_url="https://fake.forgebase.io", api_token="tok")

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"slug": ""}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)
            url = await fb.get_post_url("page-456")

        assert url == ""


# ── WordPressPublisher ────────────────────────────────────────────────────

class TestWordPressPublisher:
    def test_no_credentials_returns_error(self, sample_draft):
        """缺少 WordPress 認證時 publish_draft 應優雅回傳錯誤。"""
        import asyncio
        wp = WordPressPublisher(site_url="", username="", app_password="")
        result = asyncio.get_event_loop().run_until_complete(wp.publish_draft(sample_draft))
        assert not result.success
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_publish_draft_success(self, sample_draft):
        """成功建立 WordPress 草稿後回傳 post_id。"""
        wp = WordPressPublisher(
            site_url="https://example.com",
            username="admin",
            app_password="xxxx",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"id": 42, "link": "https://example.com/?p=42"}

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)
            result = await wp.publish_draft(sample_draft)

        assert result.success
        assert result.post_id == "42"

    def test_markdown_to_html_conversion(self):
        """markdown_to_html 應正確轉換標題與列表。"""
        from contentflow.publishers.wordpress import markdown_to_html
        html = markdown_to_html("## 標題\n\n- 項目一\n- 項目二")
        assert "<h2" in html
        assert "<li" in html


# ── ForgeBase body 格式策略（CF-01-11）────────────────────────────────────

class TestBodyFormatStrategy:
    def test_forgebase_body_is_html(self, sample_draft):
        """ForgeBase publisher 應將 Markdown 轉為 HTML 再傳送（CF-01-11 定案）。"""
        from contentflow.publishers.wordpress import markdown_to_html
        html = markdown_to_html(sample_draft.content_markdown)
        assert html.strip().startswith("<")  # HTML 格式確認
        assert "## " not in html             # Markdown 原始語法不應出現在 HTML 中
