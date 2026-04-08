"""SERP API 工具模組（使用 Serper.dev）"""

from __future__ import annotations
import httpx
from loguru import logger
from ..config import settings
from ..models import SerpAnalysis, SerpResult, PeopleAlsoAsk

SERPER_URL = "https://google.serper.dev/search"


async def search_serp(
    query: str,
    num_results: int = 10,
    gl: str = "tw",
    hl: str = "zh-tw",
) -> SerpAnalysis:
    """
    用 Serper.dev 搜尋 Google，回傳前 N 名結果與 PAA。

    範例：
        result = await search_serp("刺五加 骨關節炎功效")
    """
    if not settings.serper_api_key:
        raise ValueError("SERPER_API_KEY 未設定，請在 .env 填入金鑰")

    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "q": query,
        "num": num_results,
        "gl": gl,
        "hl": hl,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(SERPER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    top_results = _parse_organic(data.get("organic", []))
    paa = _parse_paa(data.get("peopleAlsoAsk", []))
    related = [r.get("query", "") for r in data.get("relatedSearches", [])]

    logger.info(
        f"SERP 搜尋「{query}」取得 {len(top_results)} 筆結果，"
        f"{len(paa)} 個 PAA 問題"
    )
    return SerpAnalysis(
        query=query,
        top_results=top_results,
        people_also_ask=paa,
        related_searches=related,
    )


def _parse_organic(items: list[dict]) -> list[SerpResult]:
    results: list[SerpResult] = []
    for item in items:
        results.append(
            SerpResult(
                position=item.get("position", 0),
                title=item.get("title", ""),
                url=item.get("link", ""),
                snippet=item.get("snippet", ""),
            )
        )
    return results


def _parse_paa(items: list[dict]) -> list[PeopleAlsoAsk]:
    return [
        PeopleAlsoAsk(
            question=item.get("question", ""),
            answer=item.get("snippet", ""),
        )
        for item in items
    ]
