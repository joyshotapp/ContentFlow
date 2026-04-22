"""PubMed E-utilities API 工具模組"""

from __future__ import annotations
import asyncio
import httpx
from loguru import logger
from ..config import settings
from ..models import PubMedArticle, PubMedSearchResult

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"

# NCBI 建議：有 API Key 時最多 10 req/s，否則 3 req/s
_REQUEST_DELAY = 0.15 if settings.ncbi_api_key else 0.4


def _base_params() -> dict:
    params = {"retmode": "json", "email": settings.ncbi_email}
    if settings.ncbi_api_key:
        params["api_key"] = settings.ncbi_api_key
    return params


async def search_pubmed(
    query: str,
    max_results: int = 20,
    min_year: int = 2015,
) -> PubMedSearchResult:
    """
    依關鍵字搜尋 PubMed，回傳結構化結果。

    範例：
        result = await search_pubmed("Acanthopanax arthritis", max_results=10)
    """
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            return await _search_pubmed_once(query, max_results, min_year)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
            if attempt < max_attempts - 1:
                wait = 2 ** attempt  # 1s, 2s
                logger.warning(f"PubMed 連線失敗（第 {attempt + 1} 次），{wait}s 後重試：{e}")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"PubMed 查詢失敗（已重試 {max_attempts} 次）：{e}")
                return PubMedSearchResult(query=query, total_found=0)
    return PubMedSearchResult(query=query, total_found=0)  # unreachable but satisfies type checker


async def _search_pubmed_once(
    query: str,
    max_results: int = 20,
    min_year: int = 2015,
) -> PubMedSearchResult:
    async with httpx.AsyncClient(timeout=30) as client:
        # Step 1: ESearch — 取得 PMID 清單
        search_params = {
            **_base_params(),
            "db": "pubmed",
            "term": f"{query} AND ({min_year}[PDAT]:3000[PDAT])",
            "retmax": max_results,
            "sort": "relevance",
            "usehistory": "y",
        }
        resp = await client.get(ESEARCH_URL, params=search_params)
        resp.raise_for_status()
        search_data = resp.json()

        id_list: list[str] = search_data.get("esearchresult", {}).get("idlist", [])
        total = int(search_data.get("esearchresult", {}).get("count", 0))
        logger.info(f"PubMed 搜尋「{query}」找到 {total} 篇，取前 {len(id_list)} 篇")

        if not id_list:
            return PubMedSearchResult(query=query, total_found=0)

        await asyncio.sleep(_REQUEST_DELAY)

        # Step 2: EFetch — 取得摘要（PubMed XML 格式）
        fetch_params = {
            **_base_params(),
            "db": "pubmed",
            "id": ",".join(id_list),
            "rettype": "abstract",
            "retmode": "xml",
        }
        # 移除 retmode=json，改用 xml 解析
        fetch_params.pop("retmode", None)
        fetch_params["retmode"] = "xml"

        fetch_resp = await client.get(EFETCH_URL, params=fetch_params)
        fetch_resp.raise_for_status()

        articles = _parse_pubmed_xml(fetch_resp.text, id_list)
        return PubMedSearchResult(query=query, articles=articles, total_found=total)


def _parse_pubmed_xml(xml_text: str, id_list: list[str]) -> list[PubMedArticle]:
    """解析 PubMed XML 回傳，提取標題、摘要、作者、期刊等欄位"""
    from xml.etree import ElementTree as ET

    articles: list[PubMedArticle] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"PubMed XML 解析失敗：{e}")
        return articles

    for article_node in root.findall(".//PubmedArticle"):
        try:
            pmid_node = article_node.find(".//PMID")
            pmid = pmid_node.text if pmid_node is not None else ""

            title_node = article_node.find(".//ArticleTitle")
            title = "".join(title_node.itertext()) if title_node is not None else ""

            abstract_parts = article_node.findall(".//AbstractText")
            abstract = " ".join(
                "".join(p.itertext()) for p in abstract_parts
            )

            journal_node = article_node.find(".//Journal/Title")
            journal = journal_node.text if journal_node is not None else ""

            year_node = article_node.find(".//PubDate/Year")
            pub_year = int(year_node.text) if year_node is not None else None

            author_nodes = article_node.findall(".//Author")
            authors: list[str] = []
            for a in author_nodes[:5]:  # 只取前 5 位
                last = a.findtext("LastName", "")
                fore = a.findtext("ForeName", "")
                if last:
                    authors.append(f"{last} {fore}".strip())

            articles.append(
                PubMedArticle(
                    pmid=pmid,
                    title=title,
                    abstract=abstract,
                    authors=authors,
                    journal=journal,
                    pub_year=pub_year,
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                )
            )
        except Exception as e:
            logger.warning(f"跳過一篇解析失敗的文章：{e}")

    return articles
