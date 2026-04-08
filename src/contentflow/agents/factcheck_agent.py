"""FactCheck Agent：比對文章宣稱與 PubMed 期刊證據（第二階段）"""

from __future__ import annotations
from loguru import logger
from ..models import ArticleDraft, ResearchReport


async def run_factcheck_agent(
    draft: ArticleDraft,
    report: ResearchReport,
) -> ArticleDraft:
    """
    TODO（第二階段）：
    - 比對文章段落中的成分功效宣稱與 PubMed 摘要
    - 輸出信心度評分（高/中/低）
    - 低信心段落標記為「需人工審核」
    """
    logger.info(f"[FactCheck Agent] 啟動（第二階段待實作）：「{draft.title}」")
    raise NotImplementedError("FactCheck Agent 將於第二階段實作")
