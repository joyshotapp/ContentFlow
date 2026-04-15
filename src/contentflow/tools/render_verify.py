"""Render Verification Tool — 驗證已發布文章的 HTML 是否含必要 SEO 元素（L2-4）

每日 10:00 由 scheduler 呼叫，掃描前 2 小時內發布的文章。
對缺少必要元素的文章發送 Slack 告警，不建新 DB 表。

檢查項目：
  - <title>
  - <meta name="description">
  - <h1>
  - <script type="application/ld+json">（結構化資料）
  - <link rel="canonical">
    - Open Graph 基本欄位
    - html lang / robots indexability
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit, urlunsplit

from loguru import logger

REQUIRED_CHECKS = [
    ("title", "缺少 <title>"),
    ("meta_description", "缺少 <meta name='description'>"),
    ("h1", "缺少 <h1>"),
    ("schema", "缺少 JSON-LD 結構化資料"),
    ("canonical", "缺少 <link rel='canonical'>"),
]


def _normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def _meta_content(soup, *, name: str | None = None, prop: str | None = None) -> str:
    attrs = {}
    if name:
        attrs["name"] = name
    if prop:
        attrs["property"] = prop
    tag = soup.find("meta", attrs=attrs)
    return (tag.get("content") or "").strip() if tag else ""


async def verify_rendered_html(article_url: str) -> list[str]:
    """httpx GET → BeautifulSoup 檢查，回傳缺失項目列表（空列表代表全部通過）。

    Args:
        article_url: 文章的公開 URL（需可公開存取）

    Returns:
        缺失項目的 key 列表，例如 ["missing_h1", "missing_schema"]
    """
    import httpx
    from bs4 import BeautifulSoup

    try:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "ContentFlow-RenderVerify/1.0"},
        ) as client:
            resp = await client.get(article_url)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning(f"[RenderVerify] 無法取得 {article_url}：{exc}")
        return [f"fetch_error:{exc}"]

    soup = BeautifulSoup(resp.text, "html.parser")
    issues: list[str] = []
    final_url = _normalize_url(str(resp.url))

    if not soup.find("title") or not soup.find("title").get_text(strip=True):
        issues.append("missing_title")

    meta_description = _meta_content(soup, name="description")
    if not meta_description:
        issues.append("missing_meta_description")

    h1_tags = [tag.get_text(strip=True) for tag in soup.find_all("h1") if tag.get_text(strip=True)]
    if not h1_tags:
        issues.append("missing_h1")
    elif len(h1_tags) > 1:
        issues.append("multiple_h1")

    schema_tags = soup.find_all("script", attrs={"type": "application/ld+json"})
    if not schema_tags:
        issues.append("missing_schema")
    else:
        valid_schema_found = False
        for tag in schema_tags:
            raw_schema = (tag.string or tag.get_text() or "").strip()
            if not raw_schema:
                continue
            try:
                json.loads(raw_schema)
            except json.JSONDecodeError:
                continue
            valid_schema_found = True
            break
        if not valid_schema_found:
            issues.append("invalid_schema")

    canonical_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical_href = (canonical_tag.get("href") or "").strip() if canonical_tag else ""
    if not canonical_href:
        issues.append("missing_canonical")
    elif _normalize_url(canonical_href) != final_url:
        issues.append("canonical_mismatch")

    html_tag = soup.find("html")
    if not html_tag or not (html_tag.get("lang") or "").strip():
        issues.append("missing_html_lang")

    robots_content = _meta_content(soup, name="robots").lower()
    if "noindex" in robots_content:
        issues.append("noindex_detected")

    if not _meta_content(soup, prop="og:type"):
        issues.append("missing_og_type")

    if not _meta_content(soup, prop="og:title"):
        issues.append("missing_og_title")

    if not _meta_content(soup, prop="og:description"):
        issues.append("missing_og_description")

    if not _meta_content(soup, prop="og:image"):
        issues.append("missing_og_image")

    og_url = _meta_content(soup, prop="og:url")
    if not og_url:
        issues.append("missing_og_url")
    elif _normalize_url(og_url) != final_url:
        issues.append("og_url_mismatch")

    return issues
