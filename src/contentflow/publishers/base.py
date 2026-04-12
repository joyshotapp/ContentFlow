"""發布平台抽象基底（CF-01-07）"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from contentflow.models.schemas import ArticleDraft


@dataclass
class PublishResult:
    success: bool
    platform: str                    # "wordpress" | "forgebase"
    post_id: str | None = None       # 平台端的 post / page ID
    publish_url: str | None = None   # 發布後的正式 URL
    error: str | None = None         # 失敗時的錯誤訊息
    metadata: dict = field(default_factory=dict)  # 平台回傳的額外資訊


class BasePublisher(ABC):
    """所有發布平台的抽象基底。

    子類別必須實作：
      - publish_draft   建立草稿（status = draft，人工確認後才 publish）
      - update_post     Content Refresh 時更新既有文章
      - get_post_url    取得發布後的公開 URL
    """

    @abstractmethod
    async def publish_draft(self, draft: ArticleDraft) -> PublishResult:
        """建立草稿並回傳 PublishResult（含 post_id）。"""
        ...

    @abstractmethod
    async def update_post(self, post_id: str, draft: ArticleDraft) -> PublishResult:
        """更新既有文章（Content Refresh 用途）。"""
        ...

    @abstractmethod
    async def get_post_url(self, post_id: str) -> str:
        """取得指定 post 的公開 URL。"""
        ...
