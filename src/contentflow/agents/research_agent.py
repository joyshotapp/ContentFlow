"""Research Agent：整合 SERP + 關鍵字分析（+ 可選 PubMed），產出研究報告"""

from __future__ import annotations
import asyncio
import json
import re
from loguru import logger
from ..config import settings
from ..llm_client import chat_sync
from ..models import ResearchReport, PubMedSearchResult
from ..policy_resolver import resolve_policy
from ..project_context import load_project_context
from ..tools import search_pubmed, search_serp, extract_keywords_from_serp


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))


def _translate_keywords_for_pubmed(keywords: list[str]) -> list[str]:
    """將中文關鍵字翻譯為英文醫學/學術用語，供 PubMed 查詢。"""
    cjk_keywords = [k for k in keywords if _contains_cjk(k)]
    if not cjk_keywords:
        return keywords  # 已經是英文

    try:
        raw = chat_sync(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a medical/scientific translator. "
                        "Translate each Chinese keyword to the best English "
                        "PubMed search term (MeSH preferred). "
                        "Return ONLY a JSON array of strings, same order as input. "
                        "Example: [\"osteophyte\", \"lumbar spine\"]"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(cjk_keywords, ensure_ascii=False),
                },
            ],
            temperature=0.1,
            max_tokens=256,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        translated = json.loads(raw.strip())
        if isinstance(translated, list) and len(translated) == len(cjk_keywords):
            # 把翻譯結果替換回去
            result = []
            cjk_idx = 0
            for k in keywords:
                if _contains_cjk(k):
                    result.append(translated[cjk_idx])
                    cjk_idx += 1
                else:
                    result.append(k)
            logger.info(f"[PubMed 翻譯] {cjk_keywords} → {translated}")
            return result
        logger.warning(f"[PubMed 翻譯] 回傳格式異常，沿用原關鍵字：{translated}")
    except Exception as e:
        logger.warning(f"[PubMed 翻譯] 失敗，使用原始關鍵字：{e}")

    return keywords


async def run_research_agent(
    article_title: str,
    ingredient_keywords: list[str] | None = None,
    condition_keywords: list[str] | None = None,
    search_keywords: list[str] | None = None,
    serp_gl: str = "tw",
    serp_hl: str = "zh-tw",
    use_pubmed: bool | None = None,
    project_id: int | None = None,
    article_type: str | None = None,
) -> ResearchReport:
    """
    執行 Research Agent，傳入文章標題與關鍵字，回傳完整研究報告。

    Args:
        article_title:        文章標題
        ingredient_keywords:  成分/專業關鍵字（用於 PubMed 查詢）
        condition_keywords:   症狀/場景關鍵字（用於 PubMed 查詢）
        search_keywords:      通用搜尋關鍵字（若未指定 ingredient/condition 則使用此項）
        serp_gl:              Google 搜尋國家代碼
        serp_hl:              Google 搜尋語言代碼
        use_pubmed:           是否查詢 PubMed；若未指定則由 project policy 決定
        project_id:           專案 ID，供 policy resolver 判斷領域與證據來源
        article_type:         文章型態，可參與 policy format 決策

    Returns:
        ResearchReport：包含競品分析、建議關鍵字、PAA
    """
    logger.info(f"[Research Agent] 開始：「{article_title}」")

    ingredient_keywords = ingredient_keywords or []
    condition_keywords = condition_keywords or []
    search_keywords = search_keywords or []
    all_keywords = ingredient_keywords + condition_keywords + search_keywords

    if use_pubmed is None and project_id:
        ctx = load_project_context(project_id)
        use_pubmed = resolve_policy(ctx, article_type=article_type).use_pubmed
    elif use_pubmed is None:
        use_pubmed = True

    # ── Step 1：並行執行 PubMed（可選）+ SERP ────────────────
    tasks = []

    # PubMed 查詢
    pubmed_task_count = 0
    if use_pubmed:
        pubmed_queries: list[str] = []
        if ingredient_keywords and condition_keywords:
            pubmed_queries = [
                f"{ing} {cond}"
                for ing in ingredient_keywords
                for cond in condition_keywords
            ]
        elif search_keywords:
            # 沒有 ingredient/condition 時，用 search_keywords 作為 PubMed 查詢
            pubmed_queries = list(search_keywords)

        if pubmed_queries:
            # 翻譯中文關鍵字為英文
            pubmed_queries = _translate_keywords_for_pubmed(pubmed_queries)
            for q in pubmed_queries[:4]:
                tasks.append(search_pubmed(q, max_results=10))
                pubmed_task_count += 1

    # SERP（總是執行）
    serp_task = search_serp(article_title, gl=serp_gl, hl=serp_hl)
    tasks.append(serp_task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    pubmed_results: list[PubMedSearchResult] = []
    for r in results[:pubmed_task_count]:
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
        keywords=all_keywords or [article_title],
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
