"""SERP API 工具模組（優先使用 SerpAPI，備用 Serper.dev）"""

from __future__ import annotations
import re
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


SERPAPI_TRENDS_URL = "https://serpapi.com/search.json"


async def fetch_trends(keyword: str, geo: str = "TW") -> dict:
    """
    使用 SerpAPI Google Trends 取得關鍵字相對熱度（0-100）與趨勢方向。

    返回 dict：
      - score: int  → 近 52 週平均熱度（0-100）
      - direction: str  → "up" / "down" / "stable"
      - recent_avg: int → 近 4 週平均
      - prev_avg: int   → 前 4 週平均
    """
    if not settings.serpapi_key:
        raise ValueError("請設定 SERPAPI_KEY")

    params = {
        "engine": "google_trends",
        "q": keyword,
        "data_type": "TIMESERIES",
        "geo": geo,
        "api_key": settings.serpapi_key,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(SERPAPI_TRENDS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    timeline = data.get("interest_over_time", {}).get("timeline_data", [])
    if not timeline:
        return {"score": 0, "direction": "stable", "recent_avg": 0, "prev_avg": 0}

    values = []
    for point in timeline:
        for v in point.get("values", []):
            try:
                values.append(int(v.get("extracted_value", 0)))
            except (TypeError, ValueError):
                pass

    if not values:
        return {"score": 0, "direction": "stable", "recent_avg": 0, "prev_avg": 0}

    score = round(sum(values) / len(values))
    recent_avg = round(sum(values[-4:]) / min(4, len(values)))
    prev_end = max(0, len(values) - 4)
    prev_start = max(0, prev_end - 4)
    prev_avg = round(sum(values[prev_start:prev_end]) / max(1, prev_end - prev_start)) if prev_end > prev_start else score

    delta = recent_avg - prev_avg
    if delta >= 5:
        direction = "up"
    elif delta <= -5:
        direction = "down"
    else:
        direction = "stable"

    logger.info(f"[Trends] 「{keyword}」score={score} recent={recent_avg} prev={prev_avg} dir={direction}")
    return {"score": score, "direction": direction, "recent_avg": recent_avg, "prev_avg": prev_avg}


DATAFORSEO_KW_URL = "https://api.dataforseo.com/v3/keywords_data/google_ads/search_volume/live"


_DATAFORSEO_INVALID_CHARS = re.compile(r"[？！，。、；：「」『』【】〔〕…—─《》〈〉]")


def _is_valid_dataforseo_keyword(kw: str) -> bool:
    """
    DataForSEO Google Ads 不接受含全形標點或超長文字的關鍵字。
    過濾掉問句、文章標題等不適合查搜尋量的字串。
    """
    if not kw or len(kw) > 80:
        return False
    if _DATAFORSEO_INVALID_CHARS.search(kw):
        return False
    return True


async def fetch_search_volume(keywords: list[str], language_code: str = "zh_TW") -> dict[str, dict]:
    """
    使用 DataForSEO Google Ads 取得關鍵字月搜尋量與競爭指數。
    每次最多 700 個關鍵字（API 限制）。
    含全形標點或超長的關鍵字會被自動略過（DataForSEO 不支援）。

    返回 dict：  keyword → {"search_volume": int|None, "competition_index": int|None, "cpc": float|None}
    """
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise ValueError("請在 .env 設定 DATAFORSEO_LOGIN 與 DATAFORSEO_PASSWORD")

    # 過濾 DataForSEO 不接受的關鍵字（全形標點、過長字串）
    valid_kws = [kw for kw in keywords if _is_valid_dataforseo_keyword(kw)]
    skipped = len(keywords) - len(valid_kws)
    if skipped:
        logger.info(f"[DataForSEO] 略過 {skipped} 個含無效字元或過長的關鍵字")

    if not valid_kws:
        logger.info("[DataForSEO] 無有效關鍵字可查詢")
        return {}

    import base64
    credentials = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/json",
    }
    payload = [{
        "keywords": valid_kws[:700],
        "language_code": language_code,
    }]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(DATAFORSEO_KW_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    results: dict[str, dict] = {}
    for task in data.get("tasks", []):
        for item in (task.get("result") or []):
            kw = item.get("keyword", "")
            results[kw] = {
                "search_volume": item.get("search_volume"),
                "competition_index": item.get("competition_index"),
                "cpc": item.get("cpc"),
            }

    found = sum(1 for v in results.values() if v["search_volume"] is not None)
    logger.info(f"[DataForSEO] {len(keywords)} 個關鍵字，{found} 個有搜尋量資料")
    return results
