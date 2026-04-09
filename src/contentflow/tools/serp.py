"""SERP API 工具模組（優先使用 SerpAPI，備用 Serper.dev）"""

from __future__ import annotations
import httpx
from loguru import logger
from ..config import settings
from ..models import SerpAnalysis, SerpResult, PeopleAlsoAsk

SERPER_URL = "https://google.serper.dev/search"
SERPAPI_URL = "https://serpapi.com/search"


async def search_serp(
    query: str,
    num_results: int = 10,
    gl: str = "tw",
    hl: str = "zh-tw",
) -> SerpAnalysis:
    """
    搜尋 Google SERP，自動選擇可用的 API：
    - 優先使用 SerpAPI（SERPAPI_KEY）
    - 備用 Serper.dev（SERPER_API_KEY）
    """
    if settings.serper_api_key:
        return await _search_via_serper(query, num_results, gl, hl)
    elif settings.serpapi_key:
        return await _search_via_serpapi(query, num_results, gl, hl)
    else:
        raise ValueError("請在 .env 設定 SERPER_API_KEY 或 SERPAPI_KEY")


async def _search_via_serpapi(
    query: str,
    num_results: int,
    gl: str,
    hl: str,
) -> SerpAnalysis:
    """使用 SerpAPI（serpapi.com）"""
    params = {
        "q": query,
        "api_key": settings.serpapi_key,
        "engine": "google",
        "num": num_results,
        "gl": gl,
        "hl": hl,
        "output": "json",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SERPAPI_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    top_results = _parse_serpapi_organic(data.get("organic_results", []))
    paa = _parse_serpapi_paa(data.get("related_questions", []))
    related = [r.get("query", "") for r in data.get("related_searches", [])]

    logger.info(
        f"[SerpAPI] 搜尋「{query}」取得 {len(top_results)} 筆結果，"
        f"{len(paa)} 個 PAA"
    )
    return SerpAnalysis(
        query=query,
        top_results=top_results,
        people_also_ask=paa,
        related_searches=related,
    )


async def _search_via_serper(
    query: str,
    num_results: int,
    gl: str,
    hl: str,
) -> SerpAnalysis:
    """使用 Serper.dev"""
    headers = {
        "X-API-KEY": settings.serper_api_key,
        "Content-Type": "application/json",
    }
    payload = {"q": query, "num": num_results, "gl": gl, "hl": hl}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(SERPER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    top_results = _parse_organic(data.get("organic", []))
    paa = _parse_paa(data.get("peopleAlsoAsk", []))
    related = [r.get("query", "") for r in data.get("relatedSearches", [])]

    logger.info(
        f"[Serper] 搜尋「{query}」取得 {len(top_results)} 筆結果，"
        f"{len(paa)} 個 PAA"
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


def _parse_serpapi_organic(items: list[dict]) -> list[SerpResult]:
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


def _parse_serpapi_paa(items: list[dict]) -> list[PeopleAlsoAsk]:
    return [
        PeopleAlsoAsk(
            question=item.get("question", ""),
            answer=item.get("snippet", ""),
        )
        for item in items
    ]
