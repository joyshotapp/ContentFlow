"""ForgeBase Publisher — 3-step 推送流程（CF-01-08~10）

【CF-01-11 定案】Body 格式策略：Markdown → HTML
  - 使用 markdown_to_html() 將草稿轉為 HTML 後存入 `body` 欄位
  - ForgeBase 接受標準 HTML；Markdown 直存不保留樣式，block JSON 尚無文件
  - 此決策可在取得正式 API spec 後再評估切換

流程：
  Step 1: POST /api/v1/content/briefs        → 取得 brief_id  （CF-01-08）
  Step 2: POST /api/v1/content/pages         → 建立草稿       （CF-01-09）
  Step 3: POST /api/v1/content/pages/{id}/publish → 發布      （CF-01-10）
"""
from __future__ import annotations

import httpx
from loguru import logger

from contentflow.config import settings
from contentflow.models.schemas import ArticleDraft
from .base import BasePublisher, PublishResult
from .wordpress import markdown_to_html  # 共用 Markdown→HTML 轉換


class ForgeBasePublisher(BasePublisher):
    """ForgeBase REST API Publisher。

    認證：Service Account JWT（content_editor 角色）。
    開發前提：settings.forgebase_api_base_url / forgebase_api_token 需已填入。
    """

    def __init__(
        self,
        api_base_url: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self._base = (api_base_url or settings.forgebase_api_base_url).rstrip("/")
        self._token = api_token or settings.forgebase_api_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _api(self, path: str) -> str:
        return f"{self._base}{path}"

    async def publish_draft(
        self,
        draft: ArticleDraft,
        primary_keyword: str | None = None,
    ) -> PublishResult:  # type: ignore[override]
        """Step 1+2：建立 Brief → 建立 Page（草稿）。

        Args:
            draft: 草稿物件。
            primary_keyword: 主要關鍵字；若未傳入則以 draft.title 代替。
        """
        if not self._base or not self._token:
            return PublishResult(
                success=False,
                platform="forgebase",
                error="FORGEBASE_API_BASE_URL / FORGEBASE_API_TOKEN 尚未設定。",
            )

        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: 建立 PageBrief
            brief_payload = {
                "target_page_type": "blog_post",
                "target_slug": draft.slug,
                "title_draft": draft.title,
                "primary_keyword": primary_keyword or draft.title,
                "secondary_keywords": [],
                "word_count_target": draft.word_count,
                "locale": "zh-tw",
            }
            try:
                r = await client.post(
                    self._api("/api/v1/content/briefs"),
                    json=brief_payload,
                    headers=self._headers(),
                )
                r.raise_for_status()
                brief_id = r.json()["id"]
                logger.info(f"[ForgeBase] Step 1 完成 brief_id={brief_id}")
            except Exception as exc:
                return PublishResult(success=False, platform="forgebase", error=f"Step1 失敗: {exc}")

            # Step 2: 建立 Page（草稿）
            body_html = markdown_to_html(draft.content_markdown)
            page_payload = {
                "page_type": "blog_post",
                "slug": draft.slug,
                "title": draft.title,
                "body": body_html,
                "seo_title": draft.meta_title or draft.title,
                "seo_description": draft.meta_description,
                "structured_data": draft.faq_schema_json,
                "locale": "zh-tw",
                "status": "draft",
                "brief_id": brief_id,
            }
            try:
                r = await client.post(
                    self._api("/api/v1/content/pages"),
                    json=page_payload,
                    headers=self._headers(),
                )
                r.raise_for_status()
                page_data = r.json()
                page_id = str(page_data["id"])
                logger.info(f"[ForgeBase] Step 2 完成 page_id={page_id}（草稿，等待人工審閱）")
                return PublishResult(
                    success=True,
                    platform="forgebase",
                    post_id=page_id,
                    publish_url=None,   # 草稿無 URL，Step 3 publish 後才有
                    metadata={"brief_id": brief_id, "status": "draft"},
                )
            except Exception as exc:
                return PublishResult(success=False, platform="forgebase", error=f"Step2 失敗: {exc}")

    async def publish_page(self, post_id: str) -> PublishResult:
        """Step 3：人工確認後調用此方法正式發布（CF-01-10）。

        正式發布後透過 get_post_url 取回完整 URL。
        """
        if not self._base or not self._token:
            return PublishResult(success=False, platform="forgebase", error="未設定金鑰")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    self._api(f"/api/v1/content/pages/{post_id}/publish"),
                    headers=self._headers(),
                )
                r.raise_for_status()
                data = r.json()
                slug = data.get("slug", "")
                full_url = f"{self._base.rstrip('/')}/{slug.lstrip('/')}" if slug else ""
                logger.info(f"[ForgeBase] Step 3 完成 page_id={post_id} url={full_url}")
                return PublishResult(
                    success=True,
                    platform="forgebase",
                    post_id=post_id,
                    publish_url=full_url or None,
                    metadata={"slug": slug, "status": "published"},
                )
        except Exception as exc:
            return PublishResult(success=False, platform="forgebase", error=f"Step3 失敗: {exc}")

    async def update_post(self, post_id: str, draft: ArticleDraft) -> PublishResult:
        """更新既有 ForgeBase page。"""
        if not self._base or not self._token:
            return PublishResult(success=False, platform="forgebase", error="未設定金鑰")
        body_html = markdown_to_html(draft.content_markdown)
        payload = {
            "title": draft.title,
            "body": body_html,
            "seo_title": draft.meta_title or draft.title,
            "seo_description": draft.meta_description,
            "structured_data": draft.faq_schema_json,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.patch(
                    self._api(f"/api/v1/content/pages/{post_id}"),
                    json=payload,
                    headers=self._headers(),
                )
                r.raise_for_status()
            logger.info(f"[ForgeBase] 更新成功 page_id={post_id}")
            return PublishResult(success=True, platform="forgebase", post_id=post_id)
        except Exception as exc:
            return PublishResult(success=False, platform="forgebase", error=str(exc))

    async def get_post_url(self, post_id: str) -> str:
        """取得已發布 page 的完整 URL（Step 3 發布後才有值）。"""
        if not self._base or not self._token:
            return ""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    self._api(f"/api/v1/content/pages/{post_id}"),
                    headers=self._headers(),
                )
                r.raise_for_status()
                slug = r.json().get("slug", "")
                if not slug:
                    return ""
                return f"{self._base.rstrip('/')}/{slug.lstrip('/')}"
        except Exception as exc:
            logger.warning(f"[ForgeBase] 取得 URL 失敗 page_id={post_id}: {exc}")
            return ""
