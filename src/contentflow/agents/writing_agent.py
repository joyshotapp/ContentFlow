"""Writing Agent：根據研究報告自動產出 SEO 文章初稿（第二階段）"""

from __future__ import annotations
from loguru import logger
from ..models import ResearchReport, ArticleDraft, ArticleStatus


async def run_writing_agent(
    report: ResearchReport,
    target_word_count: int = 3000,
) -> ArticleDraft:
    """
    TODO（第二階段）：根據研究報告生成完整文章初稿。

    目前為骨架，第二階段實作以下功能：
    - 大綱生成（結合 SEO 最佳實踐）
    - 分段文章撰寫（避免長文品質衰減）
    - Meta Title / Description 生成
    - 自動插入期刊引用
    """
    logger.info(f"[Writing Agent] 啟動（第二階段待實作）：「{report.article_title}」")
    raise NotImplementedError("Writing Agent 將於第二階段實作")
