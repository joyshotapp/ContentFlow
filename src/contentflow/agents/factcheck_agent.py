"""FactCheck Agent：比對文章宣稱與研究證據 + 法規用詞檢查

使用 GPT-4o-mini，每次約 $0.005-0.01。
"""

from __future__ import annotations

import json
import re
from loguru import logger

from ..config import settings
from ..llm_client import chat_sync
from ..models import (
    ArticleDraft,
    ResearchReport,
    FactCheckItem,
    ConfidenceLevel,
    ArticleStatus,
)
from ..policy_resolver import resolve_policy
from ..project_context import ProjectContext, load_project_context


# ── 禁用詞正則比對 ────────────────────────────────────────────

# 兩字通用動詞，教育類文章中常見但非違規
_SOFT_WORDS = {
    "改善", "減輕", "舒緩", "調節", "促進", "增強", "緩解", "減緩",
    "維持", "幫助", "保養", "滋養", "強化", "修復", "補充", "提升",
    "保護", "平衡", "調理", "活化", "淨化", "潤滑", "放鬆", "暢通",
}


def _check_forbidden_words(
    content: str,
    forbidden_words: list[str],
    article_type: str = "educational",
    factcheck_mode: str = "",
) -> list[FactCheckItem]:
    """正則比對禁用詞，依嚴重度分級。

    article_type:
        "product"      → 產品頁（嚴格模式：全部禁用詞皆為 error）
        "educational"  → 教育/知識文章（寬鬆模式：僅白名單通用動詞降為 warning）
    """
    if not forbidden_words:
        return []

    strict_mode = article_type == "product" or factcheck_mode == "strict"
    items = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        for word in forbidden_words:
            if word in line:
                is_soft = (not strict_mode) and (word in _SOFT_WORDS)
                if is_soft:
                    items.append(FactCheckItem(
                        claim=f"[提醒] 使用「{word}」：{line.strip()[:100]}",
                        paragraph_index=i,
                        confidence=ConfidenceLevel.MEDIUM,
                        supporting_evidence=[f"「{word}」在教育文章中可接受，產品頁需替換"],
                        needs_review=False,
                        reviewer_note=f"ℹ️ 建議確認語境：「{word}」",
                    ))
                else:
                    items.append(FactCheckItem(
                        claim=f"使用禁用詞「{word}」：{line.strip()[:100]}",
                        paragraph_index=i,
                        confidence=ConfidenceLevel.LOW,
                        supporting_evidence=[f"法規禁止使用「{word}」"],
                        needs_review=True,
                        reviewer_note=f"⚠️ 法規違規：請替換「{word}」",
                    ))
    return items


# ── AI 查核 ───────────────────────────────────────────────────

def _ai_factcheck(
    content: str,
    report: ResearchReport,
    legal_terms: list[str],
) -> list[FactCheckItem]:
    """用 Gemini 檢查文章宣稱的可信度"""

    # 組裝研究證據
    evidence_parts = []
    for result in report.pubmed_results:
        for article in result.articles[:5]:
            evidence_parts.append(f"[PMID:{article.pmid}] {article.title}: {article.abstract[:300]}")
    evidence_text = "\n".join(evidence_parts[:10])

    legal_text = "\n".join(f"- {t[:200]}" for t in legal_terms[:10])

    system = """你是專業內容事實查核員。分析文章中的宣稱，比對研究證據。

輸出 JSON array，每項包含：
- claim: 文章中的具體宣稱
- confidence: "high" / "medium" / "low"
- evidence: 支持的來源或理由
- needs_review: true/false
- note: 建議修改方向

只回傳 JSON array，不要其他文字。"""

    user = f"""文章內容（節錄）：
{content[:4000]}

研究證據：
{evidence_text}

法規禁用詞參考：
{legal_text}

請檢查文章中的宣稱是否有足夠證據支持，以及是否有法規風險。"""

    raw = chat_sync(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=2048,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]

    items = []
    try:
        checks = json.loads(raw.strip())
        for c in checks:
            conf_map = {"high": ConfidenceLevel.HIGH, "medium": ConfidenceLevel.MEDIUM, "low": ConfidenceLevel.LOW}
            items.append(FactCheckItem(
                claim=c.get("claim", ""),
                paragraph_index=0,
                confidence=conf_map.get(c.get("confidence", "medium"), ConfidenceLevel.MEDIUM),
                supporting_evidence=[c.get("evidence", "")] if c.get("evidence") else [],
                needs_review=c.get("needs_review", False),
                reviewer_note=c.get("note", ""),
            ))
    except json.JSONDecodeError:
        logger.warning("[FactCheck] AI 回傳 JSON 解析失敗")

    return items


# ── 主流程 ────────────────────────────────────────────────────

async def run_factcheck_agent(
    draft: ArticleDraft,
    report: ResearchReport,
    project_id: int | None = None,
    article_type: str = "educational",
) -> ArticleDraft:
    """
    事實查核 + 法規合規檢查。

    1. 正則比對禁用詞（零成本，從專案法規資料載入）
    2. GPT-4o-mini 比對研究證據（~$0.005）
    3. 標記需人工審核的段落

    article_type: "educational"（寬鬆）或 "product"（嚴格）
    """
    logger.info(f"[FactCheck Agent] 啟動：「{draft.title}」（{article_type} 模式）")

    # 載入專案上下文
    ctx = load_project_context(project_id)
    policy = resolve_policy(ctx)

    # 1. 禁用詞檢查（依文章類型調整嚴重度）
    forbidden_items = _check_forbidden_words(
        draft.content_markdown,
        ctx.forbidden_words,
        article_type=article_type,
        factcheck_mode=policy.factcheck_mode,
    )
    error_count = sum(1 for i in forbidden_items if i.needs_review)
    warn_count = len(forbidden_items) - error_count
    logger.info(f"[FactCheck] 禁用詞檢查：{error_count} 處違規, {warn_count} 處提醒")

    # 2. AI 查核
    ai_items = _ai_factcheck(draft.content_markdown, report, ctx.legal_terms)
    logger.info(f"[FactCheck] AI 查核：{len(ai_items)} 項宣稱已檢查")

    # 3. 合併結果
    all_items = forbidden_items + ai_items
    needs_review = any(item.needs_review for item in all_items)

    draft.fact_check_items = all_items
    draft.status = ArticleStatus.REVIEW_REQUIRED if needs_review else ArticleStatus.APPROVED

    review_count = sum(1 for item in all_items if item.needs_review)
    logger.info(f"[FactCheck Agent] 完成！{len(all_items)} 項查核，{review_count} 項需人工審核")
    return draft
