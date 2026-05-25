"""品牌提及監測與外鏈外展任務（P2 Off-page 最小閉環）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from urllib.parse import urlparse

import httpx
from loguru import logger

from contentflow.config import settings


async def sync_brand_mentions(project_id: int, brand_name: str, *, limit: int = 10) -> int:
    """以 Serper 搜尋品牌提及，寫入 brand_mention_snapshots 並建立 outreach_tasks。"""
    if not settings.serper_api_key or not brand_name:
        logger.info("[BrandMentions] 略過：未設定 SERPER 或品牌名稱")
        return 0

    from contentflow.db import SessionLocal
    from contentflow.models.database import BrandMentionSnapshot, OutreachTask

    query = f'"{brand_name}" -site:{urlparse(settings.site_url).netloc or "localhost"}'
    headers = {"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"}
    today = date.today()
    written = 0

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://google.serper.dev/search",
            headers=headers,
            json={"q": query, "gl": "tw", "hl": "zh-tw", "num": limit},
        )
        resp.raise_for_status()
        data = resp.json()

    organic = data.get("organic") or []
    with SessionLocal() as session:
        for item in organic[:limit]:
            url = (item.get("link") or "").strip()
            if not url:
                continue
            title = (item.get("title") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            session.add(
                BrandMentionSnapshot(
                    project_id=project_id,
                    brand_query=brand_name,
                    mention_url=url,
                    mention_title=title,
                    mention_snippet=snippet,
                    tracked_date=today,
                )
            )
            domain = urlparse(url).netloc
            session.add(
                OutreachTask(
                    project_id=project_id,
                    task_type="brand_mention",
                    target_url=url,
                    target_domain=domain,
                    suggested_action=f"評估是否可爭取 {brand_name} 相關反向連結或媒體合作",
                    status="open",
                    priority=3,
                    metadata_json=json.dumps({"title": title[:120]}, ensure_ascii=False),
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            written += 1
        session.commit()

    logger.info(f"[BrandMentions] project={project_id} 新增 {written} 筆提及與外展任務")
    return written
