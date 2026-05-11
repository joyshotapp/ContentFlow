from __future__ import annotations

from datetime import datetime, timezone

from loguru import logger

from contentflow.config import settings
from contentflow.models.database import Article


def _native_blog_url(slug: str) -> str:
    base = settings.site_url.rstrip("/")
    return f"{base}/blog/{slug}"


def _mark_article_published(art: Article, publish_url: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    art.status = "published"
    art.published_at = now
    art.publish_date = now.strftime("%Y-%m-%d")
    art.updated_at = now
    if publish_url:
        art.publish_url = publish_url


async def _submit_to_google_indexing(url: str) -> None:
    """Submit a URL to Google Indexing API for faster crawling."""
    try:
        import google.auth.transport.requests as _gtr
        import google.oauth2.service_account as _sa
        import httpx

        service_account_path = settings.google_service_account_file
        if not service_account_path:
            return

        creds = _sa.Credentials.from_service_account_file(
            service_account_path,
            scopes=["https://www.googleapis.com/auth/indexing"],
        )
        auth_req = _gtr.Request()
        creds.refresh(auth_req)
        token = creds.token

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://indexing.googleapis.com/v3/urlNotifications:publish",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"url": url, "type": "URL_UPDATED"},
            )
            if resp.status_code == 200:
                logger.info(f"[Indexing API] 已提交: {url}")
            else:
                logger.warning(f"[Indexing API] 失敗 {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.warning(f"[Indexing API] 例外: {exc}")