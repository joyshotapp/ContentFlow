"""SEO URL slug 治理：弱 slug 偵測、語意化建議、變更時登記 301。"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger

# 測試/占位 slug（P1 治理）
_WEAK_SLUG_RE = re.compile(
    r"^(article-\d+|post-\d+|page-\d+|[a-z]{1,3}|[a-z]{1,2}-\d+)$",
    re.IGNORECASE,
)


def is_weak_slug(slug: str) -> bool:
    """是否為低品質 slug（需遷移或重生成）。"""
    s = (slug or "").strip().lower()
    if not s or s == "article":
        return True
    if _WEAK_SLUG_RE.match(s):
        return True
    if len(s) < 4:
        return True
    return False


def normalize_slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]", "-", (raw or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "article"


def slugify_topic_keyword(keyword: str, *, max_len: int = 80) -> str:
    """主題叢集 / 關鍵字導向的語意 slug（ASCII kebab）。"""
    kw = (keyword or "").strip()
    if not kw:
        return "topic"
    # 若已是英文 kebab，直接使用
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", kw.lower()):
        return kw.lower()[:max_len]
    try:
        from contentflow.llm_client import chat_sync

        raw = chat_sync(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert the Traditional Chinese keyword to an SEO URL slug. "
                        "Rules: lowercase English only, 3-6 words, hyphens, no stop words. "
                        "Return ONLY the slug."
                    ),
                },
                {"role": "user", "content": kw},
            ],
            temperature=0.1,
            max_tokens=48,
        )
        return normalize_slug(raw)[:max_len]
    except Exception as exc:
        logger.warning(f"[SlugGovernance] topic slug LLM 失敗：{exc}")
        return normalize_slug(re.sub(r"\s+", "-", kw))[:max_len]


def propose_article_slug(
    *,
    primary_keyword: str,
    title: str,
    existing_slug: str = "",
) -> str:
    """新稿建議 slug：優先主關鍵字，輔以標題。"""
    if existing_slug and not is_weak_slug(existing_slug):
        return normalize_slug(existing_slug)

    seed = (primary_keyword or title or "article").strip()
    if is_weak_slug(normalize_slug(existing_slug)):
        seed = primary_keyword or title or seed

    try:
        from contentflow.llm_client import chat_sync

        raw = chat_sync(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Create one SEO URL slug for a Traditional Chinese health article. "
                        "Primary keyword must appear as part of the slug (romanized English). "
                        "Rules: lowercase, hyphens, 3-6 words, no special chars. Return ONLY the slug."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Primary keyword: {primary_keyword}\nTitle: {title}",
                },
            ],
            temperature=0.1,
            max_tokens=64,
        )
        slug = normalize_slug(raw)
    except Exception as exc:
        logger.warning(f"[SlugGovernance] article slug LLM 失敗：{exc}")
        slug = normalize_slug(slugify_topic_keyword(seed))

    if primary_keyword:
        # 確保 slug 與關鍵字有弱關聯（至少 3 字英文種子）
        pk_slug = slugify_topic_keyword(primary_keyword)
        if pk_slug and pk_slug not in slug and slug != "article":
            slug = f"{pk_slug}-{slug}" if len(slug) < 12 else slug
        elif slug == "article":
            slug = pk_slug

    return slug[:80] or "article"


def register_slug_change(article: Any, new_slug: str) -> str:
    """更新 slug 並將舊值併入 old_slugs（供 301）。"""
    new_slug = normalize_slug(new_slug)
    old = normalize_slug(getattr(article, "slug", "") or "")
    if not old or old == new_slug:
        article.slug = new_slug
        return new_slug

    try:
        history = json.loads(getattr(article, "old_slugs", None) or "[]")
        if not isinstance(history, list):
            history = []
    except (TypeError, ValueError):
        history = []

    if old not in history:
        history.append(old)
    article.old_slugs = json.dumps(history, ensure_ascii=False)
    article.slug = new_slug
    return new_slug
