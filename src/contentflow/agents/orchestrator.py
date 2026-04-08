"""Orchestrator Agent：流程編排、狀態管理（第三階段）"""

from __future__ import annotations
from loguru import logger
from ..models import ArticleTask


async def run_orchestrator(task: ArticleTask) -> ArticleTask:
    """
    TODO（第三階段）：串接所有 Agent 的完整流程
    - 讀取 Google Sheets 排程表
    - 依序執行：Research → Writing → FactCheck → Image
    - 錯誤處理與重試機制
    - 完成後回寫狀態
    - Slack / Email 通知
    """
    logger.info(f"[Orchestrator] 啟動（第三階段待實作）：任務 {task.task_id}")
    raise NotImplementedError("Orchestrator 將於第三階段實作")
