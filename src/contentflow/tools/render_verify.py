"""Render Verification Tool — 驗證已發布文章的 HTML 是否含必要 SEO 元素（L2-4）

每日 10:00 由 scheduler 呼叫，掃描前 2 小時內發布的文章。
對缺少必要元素的文章發送 Slack 告警，不建新 DB 表。

檢查項目：
  - <title>
  - <meta name="description">
  - <h1>
  - <script type="application/ld+json">（結構化資料）
  - <link rel="canonical">
"""
from __future__ import annotations

from loguru import logger

REQUIRED_CHECKS = [
    ("title", "缺少 <title>"),
    ("meta_description", "缺少 <meta name='description'>"),
    ("h1", "缺少 <h1>"),
    ("schema", "缺少 JSON-LD 結構化資料"),
    ("canonical", "缺少 <link rel='canonical'>"),
]


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

    if not soup.find("title") or not soup.find("title").get_text(strip=True):
        issues.append("missing_title")

    if not soup.find("meta", attrs={"name": "description"}):
        issues.append("missing_meta_description")

    if not soup.find("h1"):
        issues.append("missing_h1")

    if not soup.find("script", attrs={"type": "application/ld+json"}):
        issues.append("missing_schema")

    if not soup.find("link", attrs={"rel": "canonical"}):
        issues.append("missing_canonical")

    return issues
