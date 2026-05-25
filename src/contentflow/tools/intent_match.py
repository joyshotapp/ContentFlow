"""上線後搜尋意圖命中評分（P2）。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

from loguru import logger


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def score_intent_match(primary_keyword: str, gsc_queries: list[dict[str, Any]]) -> tuple[float, str]:
    """比對主關鍵字與 GSC 實際查詢詞，回傳 0-100 分與說明。"""
    pk = _normalize(primary_keyword)
    if not pk:
        return 0.0, "缺少主關鍵字"

    if not gsc_queries:
        return 0.0, "無 GSC 查詢資料"

    best_ratio = 0.0
    best_query = ""
    total_impressions = 0
    weighted = 0.0

    for row in gsc_queries:
        q = _normalize(str(row.get("query") or row.get("keyword") or ""))
        if not q:
            continue
        imp = int(row.get("impressions") or 0)
        total_impressions += imp
        ratio = SequenceMatcher(None, pk, q).ratio()
        if pk in q or q in pk:
            ratio = max(ratio, 0.85)
        weighted += ratio * max(imp, 1)
        if ratio > best_ratio:
            best_ratio = ratio
            best_query = q

    if total_impressions > 0:
        score = (weighted / total_impressions) * 100
    else:
        score = best_ratio * 100

    score = round(min(100.0, max(0.0, score)), 1)
    detail = f"最佳查詢「{best_query or '—'}」相似度 {best_ratio:.0%}；加權分 {score}"
    return score, detail


async def evaluate_published_article_intent(
    *,
    project_id: int,
    article_id: int,
    primary_keyword: str,
    publish_url: str,
    days_since_publish: int = 14,
) -> tuple[float, str]:
    """依日級 GSC 資料計算單篇文章意圖命中分。"""
    from contentflow.db import SessionLocal
    from contentflow.models.database import GSCDailyMetric

    cutoff = date.today() - timedelta(days=max(days_since_publish, 1))
    queries: list[dict[str, Any]] = []

    with SessionLocal() as session:
        rows = (
            session.query(GSCDailyMetric)
            .filter(
                GSCDailyMetric.project_id == project_id,
                GSCDailyMetric.metric_date >= cutoff,
            )
            .all()
        )
        pub_path = (publish_url or "").rstrip("/")
        for row in rows:
            page = (row.landing_page or "").rstrip("/")
            if pub_path and page and pub_path not in page and page not in pub_path:
                continue
            queries.append({
                "query": row.keyword,
                "impressions": row.impressions,
                "clicks": row.clicks,
                "ctr": row.ctr,
            })

    score, detail = score_intent_match(primary_keyword, queries)
    logger.info(f"[IntentMatch] article={article_id} score={score} {detail}")
    return score, detail
