"""Research Agent：整合 PubMed + SERP + 關鍵字分析，產出研究報告"""

from __future__ import annotations
import asyncio
from loguru import logger
from ..models import ResearchReport, PubMedSearchResult
from ..tools import search_pubmed, search_serp, extract_keywords_from_serp


async def run_research_agent(
    article_title: str,
    ingredient_keywords: list[str],
    condition_keywords: list[str],
) -> ResearchReport:
    """
    執行 Research Agent，傳入文章標題與關鍵字，回傳完整研究報告。

    Args:
        article_title:        文章標題，例如「刺五加的骨關節炎研究」
        ingredient_keywords:  成分英文名，例如 ["Acanthopanax senticosus"]
        condition_keywords:   病症/功效關鍵字，例如 ["osteoarthritis", "joint pain"]

    Returns:
        ResearchReport：包含期刊摘要、競品分析、建議關鍵字、PAA
    """
    logger.info(f"[Research Agent] 開始：「{article_title}」")

    # ── Step 1：並行執行 PubMed 多組查詢 + SERP ──────────────
    pubmed_queries = [
        f"{ing} {cond}"
        for ing in ingredient_keywords
        for cond in condition_keywords
    ]
    pubmed_tasks = [search_pubmed(q, max_results=10) for q in pubmed_queries[:4]]

    # 同時跑 SERP
    serp_task = search_serp(article_title)

    results = await asyncio.gather(*pubmed_tasks, serp_task, return_exceptions=True)

    pubmed_results: list[PubMedSearchResult] = []
    for r in results[:-1]:
        if isinstance(r, Exception):
            logger.warning(f"PubMed 查詢失敗：{r}")
        else:
            pubmed_results.append(r)

    serp_result = results[-1]
    if isinstance(serp_result, Exception):
        logger.warning(f"SERP 查詢失敗：{serp_result}")
        serp_result = None

    # ── Step 2：關鍵字分析 ───────────────────────────────────
    suggested_keywords: list[str] = []
    paa_questions: list[str] = []
    competitor_headings: list[str] = []

    if serp_result:
        suggested_keywords = extract_keywords_from_serp(serp_result, top_n=25)
        paa_questions = [p.question for p in serp_result.people_also_ask]
        competitor_headings = [r.title for r in serp_result.top_results]

    report = ResearchReport(
        article_title=article_title,
        keywords=ingredient_keywords + condition_keywords,
        pubmed_results=pubmed_results,
        serp_analysis=serp_result,
        suggested_keywords=suggested_keywords,
        paa_questions=paa_questions,
        competitor_headings=competitor_headings,
    )

    logger.info(
        f"[Research Agent] 完成：{sum(len(r.articles) for r in pubmed_results)} 篇期刊, "
        f"{len(paa_questions)} 個 PAA"
    )
    return report
