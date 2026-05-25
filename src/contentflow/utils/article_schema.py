"""Article JSON-LD 與可見標題對齊（P0 SEO）。"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


def schema_display_title(meta_title: str = "", title: str = "") -> str:
    """與前台 <title> / og:title 一致的可見標題（不含站名後綴）。"""
    return (meta_title or title or "").strip()


def sync_article_schema_headline(
    article_schema_json: str,
    *,
    meta_title: str = "",
    title: str = "",
    meta_description: str = "",
) -> str:
    """將 JSON-LD headline / description 與 meta 欄位對齊。"""
    display = schema_display_title(meta_title, title)
    if not article_schema_json or not article_schema_json.strip():
        return article_schema_json

    try:
        schema: dict[str, Any] = json.loads(article_schema_json)
    except (TypeError, ValueError):
        logger.warning("[ArticleSchema] 無法解析 article_schema_json，略過 headline 同步")
        return article_schema_json

    if not isinstance(schema, dict):
        return article_schema_json

    if display:
        schema["headline"] = display[:110]
    if meta_description:
        schema["description"] = meta_description[:200]

    return json.dumps(schema, ensure_ascii=False, indent=2)
