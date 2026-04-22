"""SEO QA Agent：對文章做低風險 SEO 微調。"""

from __future__ import annotations

import json
import re

from loguru import logger

from ..config import settings
from ..llm_client import chat_sync
from ..models import ArticleDraft, ResearchReport
from ..project_context import ProjectContext, load_project_context
from .writing_agent import _clean_gpt_artifacts


def _chat(system: str, user: str, temperature: float = 0.2) -> str:
    return chat_sync(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=settings.llm_seo_qa_max_completion_tokens,
    )


def _extract_primary_keyword(report: ResearchReport, fallback_title: str) -> str:
    if report.keywords:
        return report.keywords[0]
    title = fallback_title.strip()
    return title[:20] if title else ""


def _replace_first_paragraph(markdown: str, replacement: str) -> str:
    lines = markdown.splitlines()
    start = None
    end = None

    for idx, line in enumerate(lines):
        if line.strip() and not line.startswith("#") and not line.startswith("-") and not re.match(r"^\d+\.\s", line):
            start = idx
            break

    if start is None:
        return markdown

    end = start
    while end < len(lines) and lines[end].strip():
        end += 1

    new_lines = lines[:start] + [replacement.strip(), ""] + lines[end:]
    return "\n".join(new_lines).strip()


def _normalize_meta_title(meta_title: str, primary_keyword: str) -> str:
    meta_title = meta_title.strip()
    if primary_keyword and primary_keyword not in meta_title:
        meta_title = f"{primary_keyword}｜{meta_title}" if meta_title else primary_keyword
    return meta_title[:30].strip()


def _normalize_meta_description(meta_description: str, primary_keyword: str) -> str:
    meta_description = meta_description.strip()
    if primary_keyword and primary_keyword not in meta_description:
        meta_description = f"深入了解{primary_keyword}的重點資訊。{meta_description}".strip()
    return meta_description[:80].strip()


async def run_seo_qa_agent(
    draft: ArticleDraft,
    report: ResearchReport,
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
    failed_checks: list[dict] | None = None,
    project_id: int | None = None,
) -> ArticleDraft:
    """微調 meta 與首段，提升搜尋意圖匹配且維持低風險。"""
    logger.info(f"[SEO QA Agent] 啟動：「{draft.title}」")
    ctx = load_project_context(project_id)

    primary_keyword = primary_keyword or _extract_primary_keyword(report, draft.title)
    secondary_keywords = secondary_keywords or []
    failed_checks = failed_checks or []

    # 動態組裝禁用詞規則
    forbidden_rule = ""
    if ctx.forbidden_words:
        sample = "、".join(ctx.forbidden_words[:5])
        forbidden_rule = f"\n- 不可使用法規禁用詞彙（如「{sample}」等）"

    system = f"""你是 SEO 內容編輯，只能做低風險微調，不可重寫全文。

輸出 JSON：
{{"meta_title": "...", "meta_description": "...", "opening_paragraph": "..."}}

規則：
- 僅優化 meta title、meta description 與文章第一段直答內容
- meta_title 必須含主關鍵字，聚焦搜尋意圖，避免空泛品牌詞，長度 10-30 中文字
- meta_description 需含主關鍵字，明確說明讀者能得到什麼資訊，長度 30-80 中文字
- opening_paragraph 80-140 字，以繁體中文直接回應搜尋意圖，先回答問題再展開
- 不可使用 emoji
- 不可加入對話語{forbidden_rule}
- 不可提及未提供的產品名稱或品牌詞
- 若有未通過的 SEO 檢查，只修正那些問題，避免擴大改動範圍
- 回傳純 JSON"""

    failed_check_lines = "\n".join(
        f"- {item.get('name', '')}: {item.get('detail', '')}" for item in failed_checks if not item.get("passed", False)
    ) or "- 無"

    user = f"""標題：{draft.title}
主關鍵字：{primary_keyword}
副關鍵字：{', '.join(secondary_keywords[:5])}

現有 meta_title：{draft.meta_title}
現有 meta_description：{draft.meta_description}

文章前 1200 字：
{draft.content_markdown[:1200]}

研究關鍵字：{', '.join(report.suggested_keywords[:10])}

未通過 SEO 檢查：
{failed_check_lines}
"""

    raw = _chat(system, user, temperature=0.2).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]

    try:
        payload = json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.warning("[SEO QA Agent] JSON 解析失敗，維持原內容")
        return draft

    opening_paragraph = _clean_gpt_artifacts(payload.get("opening_paragraph", "").strip())
    if opening_paragraph:
        draft.content_markdown = _replace_first_paragraph(draft.content_markdown, opening_paragraph)

    draft.meta_title = _normalize_meta_title(
        _clean_gpt_artifacts(payload.get("meta_title", draft.meta_title)),
        primary_keyword,
    )
    draft.meta_description = _normalize_meta_description(
        _clean_gpt_artifacts(payload.get("meta_description", draft.meta_description)),
        primary_keyword,
    )
    draft.word_count = len(draft.content_markdown)

    logger.info("[SEO QA Agent] 完成：meta 與首段已微調")
    return draft