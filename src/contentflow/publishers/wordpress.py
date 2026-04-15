"""WordPress REST API v2 Publisher（CF-01-12, CF-01-13, CF-01-14）

支援：
  - 新增草稿（publish_draft）
  - 更新既有文章（update_post，Content Refresh 用）
  - 自動寫入 Yoast / RankMath / All in One SEO meta 欄位
  - Markdown → HTML 轉換（使用 markdown 套件）
"""
from __future__ import annotations

import base64
from typing import Any

import httpx
import markdown as md_lib
from loguru import logger

from contentflow.config import settings
from contentflow.models.schemas import ArticleDraft
from .base import BasePublisher, PublishResult

# ── SEO 外掛 meta key 對照表 ──────────────────────────────────
_SEO_META_KEYS: dict[str, dict[str, str]] = {
    "yoast": {
        "title": "_yoast_wpseo_title",
        "description": "_yoast_wpseo_metadesc",
    },
    "rankmath": {
        "title": "rank_math_title",
        "description": "rank_math_description",
    },
    "aioseo": {
        "title": "_aioseo_title",
        "description": "_aioseo_description",
    },
}


def markdown_to_html(md_text: str) -> str:
    """Markdown → HTML，啟用常用擴展（table / fenced_code / toc）。"""
    return md_lib.markdown(
        md_text,
        extensions=["tables", "fenced_code", "toc", "nl2br"],
    )


class WordPressPublisher(BasePublisher):
    """WordPress REST API v2 串接。

    認證採 Application Password（Basic Auth）。
    seo_plugin 可設 "yoast" / "rankmath" / "aioseo"，預設 yoast。
    """

    def __init__(
        self,
        site_url: str | None = None,
        username: str | None = None,
        app_password: str | None = None,
        seo_plugin: str = "yoast",
    ) -> None:
        self._site_url = (site_url or settings.wordpress_site_url).rstrip("/")
        self._username = username or settings.wordpress_username
        self._app_password = app_password or settings.wordpress_app_password
        self._seo_plugin = seo_plugin if seo_plugin in _SEO_META_KEYS else "yoast"
        self._auth_header = self._build_auth_header()

    def _build_auth_header(self) -> str:
        token = base64.b64encode(
            f"{self._username}:{self._app_password}".encode()
        ).decode()
        return f"Basic {token}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        }

    def _api(self, path: str) -> str:
        return f"{self._site_url}/wp-json/wp/v2{path}"

    def _build_meta(self, draft: ArticleDraft) -> dict[str, str]:
        """依 SEO 外掛產出 meta 欄位 dict。"""
        keys = _SEO_META_KEYS[self._seo_plugin]
        return {
            keys["title"]: draft.meta_title or draft.title,
            keys["description"]: draft.meta_description,
        }

    def _build_post_payload(self, draft: ArticleDraft, status: str = "draft") -> dict[str, Any]:
        html_content = markdown_to_html(draft.content_markdown)
        return {
            "title": draft.title,
            "content": html_content,
            "slug": draft.slug,
            "status": status,
            "meta": self._build_meta(draft),
        }

    # ── 公開介面 ──────────────────────────────────────────────

    async def publish_draft(self, draft: ArticleDraft) -> PublishResult:
        """建立 WordPress 草稿，回傳 post_id。"""
        payload = self._build_post_payload(draft, status="draft")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._api("/posts"),
                    json=payload,
                    headers=self._headers(),
                )
            resp.raise_for_status()
            data = resp.json()
            post_id = str(data["id"])
            link = data.get("link", "")
            logger.info(f"[WordPress] 草稿建立成功 post_id={post_id}")
            return PublishResult(
                success=True,
                platform="wordpress",
                post_id=post_id,
                publish_url=link,
                metadata={"slug": data.get("slug", "")},
            )
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error(f"[WordPress] 草稿建立失敗：{msg}")
            return PublishResult(success=False, platform="wordpress", error=msg)
        except Exception as exc:
            logger.error(f"[WordPress] 草稿建立異常：{exc}")
            return PublishResult(success=False, platform="wordpress", error=str(exc))

    async def update_post(self, post_id: str, draft: ArticleDraft) -> PublishResult:
        """更新既有 WordPress 文章（Content Refresh 用途）。"""
        payload = self._build_post_payload(draft, status="draft")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._api(f"/posts/{post_id}"),
                    json=payload,
                    headers=self._headers(),
                )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[WordPress] 文章更新成功 post_id={post_id}")
            return PublishResult(
                success=True,
                platform="wordpress",
                post_id=post_id,
                publish_url=data.get("link", ""),
            )
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error(f"[WordPress] 文章更新失敗：{msg}")
            return PublishResult(success=False, platform="wordpress", error=msg)
        except Exception as exc:
            logger.error(f"[WordPress] 文章更新異常：{exc}")
            return PublishResult(success=False, platform="wordpress", error=str(exc))

    async def publish_post(self, post_id: str) -> PublishResult:
        """將 WordPress 草稿改為已發布狀態（status: draft → publish）。"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    self._api(f"/posts/{post_id}"),
                    json={"status": "publish"},
                    headers=self._headers(),
                )
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"[WordPress] 文章發布成功 post_id={post_id}")
            return PublishResult(
                success=True,
                platform="wordpress",
                post_id=post_id,
                publish_url=data.get("link", ""),
            )
        except httpx.HTTPStatusError as exc:
            msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.error(f"[WordPress] 文章發布失敗：{msg}")
            return PublishResult(success=False, platform="wordpress", error=msg)
        except Exception as exc:
            logger.error(f"[WordPress] 文章發布異常：{exc}")
            return PublishResult(success=False, platform="wordpress", error=str(exc))

    async def get_post_url(self, post_id: str) -> str:
        """取得已發布文章的公開 URL."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    self._api(f"/posts/{post_id}"),
                    headers=self._headers(),
                )
            resp.raise_for_status()
            return resp.json().get("link", "")
        except Exception as exc:
            logger.warning(f"[WordPress] 取得 URL 失敗 post_id={post_id}: {exc}")
            return ""
