import httpx
import pytest

from contentflow.tools.render_verify import verify_rendered_html


class _DummyAsyncClient:
    def __init__(self, response: httpx.Response):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str):
        return self._response


@pytest.mark.asyncio
async def test_verify_rendered_html_passes_for_well_formed_article(monkeypatch):
    html = """
    <!DOCTYPE html>
    <html lang="zh-TW">
    <head>
      <title>骨刺治療指南</title>
      <meta name="description" content="完整說明骨刺常見症狀與治療方式。">
      <meta property="og:type" content="article">
      <meta property="og:title" content="骨刺治療指南">
      <meta property="og:description" content="完整說明骨刺常見症狀與治療方式。">
      <meta property="og:image" content="https://example.com/static/og-default.png">
      <meta property="og:url" content="https://example.com/blog/test-article">
      <link rel="canonical" href="https://example.com/blog/test-article">
      <script type="application/ld+json">{"@context":"https://schema.org","@type":"Article"}</script>
    </head>
    <body>
      <h1>骨刺治療指南</h1>
    </body>
    </html>
    """
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/blog/test-article"),
        text=html,
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _DummyAsyncClient(response))

    issues = await verify_rendered_html("https://example.com/blog/test-article")

    assert issues == []


@pytest.mark.asyncio
async def test_verify_rendered_html_reports_extended_seo_issues(monkeypatch):
    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <title> </title>
      <meta name="description" content=" ">
      <meta name="robots" content="noindex,nofollow">
      <meta property="og:type" content="article">
      <meta property="og:url" content="https://example.com/blog/wrong-slug">
      <link rel="canonical" href="https://example.com/blog/wrong-slug">
      <script type="application/ld+json">{not-json}</script>
    </head>
    <body>
      <h1>主標題</h1>
      <h1>第二個主標題</h1>
    </body>
    </html>
    """
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://example.com/blog/test-article"),
        text=html,
    )
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: _DummyAsyncClient(response))

    issues = await verify_rendered_html("https://example.com/blog/test-article")

    assert "missing_title" in issues
    assert "missing_meta_description" in issues
    assert "multiple_h1" in issues
    assert "invalid_schema" in issues
    assert "canonical_mismatch" in issues
    assert "missing_html_lang" in issues
    assert "noindex_detected" in issues
    assert "missing_og_title" in issues
    assert "missing_og_description" in issues
    assert "missing_og_image" in issues
    assert "og_url_mismatch" in issues