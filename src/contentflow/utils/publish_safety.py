"""自動發布安全閘（P0）：FactCheck、pipeline 狀態、YMYL 政策。"""

from __future__ import annotations

import json
from typing import Any

from ..models.schemas import FactCheckItem


def serialize_factcheck_flags(items: list[FactCheckItem] | None) -> str:
    """將 FactCheck 結果序列化為 DB 欄位 factcheck_flags_json。"""
    if not items:
        return "[]"
    payload = [
        {
            "claim": item.claim,
            "paragraph_index": item.paragraph_index,
            "confidence": item.confidence.value if hasattr(item.confidence, "value") else str(item.confidence),
            "needs_review": bool(item.needs_review),
            "reviewer_note": item.reviewer_note or "",
        }
        for item in items
        if item.needs_review
    ]
    return json.dumps(payload, ensure_ascii=False)


def parse_factcheck_flags(raw: str | None) -> list[dict[str, Any]]:
    if not raw or not str(raw).strip():
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return [{"claim": "invalid_factcheck_flags_json", "needs_review": True}]
    if not isinstance(payload, list):
        return [{"claim": "invalid_factcheck_flags_json", "needs_review": True}]
    return [item for item in payload if isinstance(item, dict)]


def article_has_factcheck_risk(factcheck_flags_json: str | None) -> bool:
    """有需人工審核的 factcheck 旗標時視為高風險。"""
    flags = parse_factcheck_flags(factcheck_flags_json)
    if not flags:
        return False
    if any(flag.get("needs_review") for flag in flags):
        return True
    # 無法解析或格式異常：保守阻擋自動發布
    return any(flag.get("claim") == "invalid_factcheck_flags_json" for flag in flags)


def normalize_pipeline_status(status: Any) -> str:
    if status is None:
        return ""
    if hasattr(status, "value"):
        return str(status.value)
    return str(status).strip()


def can_auto_publish_article(
    *,
    pipeline_status: str | Any,
    factcheck_flags_json: str | None,
    compliance_profile: str | None = None,
    auto_publish_enabled: bool = True,
) -> bool:
    """是否允許進入自動發布路徑。

    硬條件：
    - auto_publish_enabled
    - pipeline 狀態為 approved（非 review_required）
    - factcheck_flags_json 為空（無需審核項目）
    """
    if not auto_publish_enabled:
        return False

    status = normalize_pipeline_status(pipeline_status).lower()
    if status != "approved":
        return False

    if article_has_factcheck_risk(factcheck_flags_json):
        return False

    # YMYL 仍可在人工核准且無 factcheck 風險時自動發布；預設應關閉 auto_publish_enabled
    _ = (compliance_profile or "").strip().lower()
    return True
