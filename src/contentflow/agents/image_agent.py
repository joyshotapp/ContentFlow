"""Image Agent：分段生成配圖並篩選品質（第三階段）"""

from __future__ import annotations
from loguru import logger
from ..models import ArticleDraft


async def run_image_agent(draft: ArticleDraft) -> ArticleDraft:
    """
    TODO（第三階段）：
    - 分析文章段落，判斷哪些需要配圖
    - 生成圖片 Prompt
    - 串接 DALL-E 3 / Flux API
    - 品質篩選（每張生成 3-5 張，視覺模型評分）
    - Fallback：品質不達標則標記為「需手動配圖」
    """
    logger.info(f"[Image Agent] 啟動（第三階段待實作）：「{draft.title}」")
    raise NotImplementedError("Image Agent 將於第三階段實作")
