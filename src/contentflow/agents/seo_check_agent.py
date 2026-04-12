"""SEO Check Agent：使用規則檢查文章的 SEO 基本面。"""

from __future__ import annotations

import re

from loguru import logger

from ..models import ArticleDraft


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _get_first_paragraph(markdown: str) -> str:
    lines = (markdown or "").splitlines()
    paragraph = []
    started = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if started:
                break
            continue
        if stripped.startswith("#"):
            continue
        if not started:
            started = True
        paragraph.append(stripped)
    return _clean_text(" ".join(paragraph))


def _get_h2s(markdown: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+)$", markdown or "", re.MULTILINE)]


def _contains_faq(markdown: str) -> bool:
    return bool(re.search(r"^##\s+(FAQ|常見問題)", markdown or "", re.MULTILINE | re.IGNORECASE))


def _keyword_in_text(keyword: str, text: str) -> bool:
    return bool(keyword and keyword in (text or ""))


def _keyword_density(keyword: str, content_markdown: str) -> float:
    """計算主關鍵字密度（出現次數 × 關鍵字長度 / 去除標記後總字元數）。"""
    if not keyword or not content_markdown:
        return 0.0
    # 去除 Markdown 標記取純文字
    plain = re.sub(r"^#{1,6}\s+", "", content_markdown, flags=re.MULTILINE)
    plain = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", plain)   # 連結
    plain = re.sub(r"[*_`~#>|!\[\]]", "", plain)               # 強調/符號
    total_chars = len(re.sub(r"\s+", "", plain))
    if total_chars == 0:
        return 0.0
    count = len(re.findall(re.escape(keyword), plain))
    return count * len(keyword) / total_chars


def _kw_in_context(kw: str, text: str) -> bool:
    """完整詞比對：中文關鍵字至少 2 字才比對；2 字關鍵字透過 jieba 分詞判斷是否為獨立詞。"""
    if len(kw) < 2:
        return False
    if len(kw) >= 3:
        return kw in text
    # 2 字關鍵字：先快速判斷字面是否存在
    if kw not in text:
        return False
    # 透過 jieba 分詞確認是否為獨立詞（避免「骨盆」被「髖骨盆腔」誤配）
    try:
        import jieba
        tokens = jieba.lcut(text)
        return kw in tokens
    except ImportError:
        # 無 jieba 時退回簡單比對
        return True


def suggest_internal_links(
    content_markdown: str,
    primary_keyword: str,
    existing_articles: list[dict],
) -> list[dict]:
    """找出內文中可插入內部連結的錨文字與候選目標文章。

    Args:
        content_markdown:  本篇文章的 Markdown 內容
        primary_keyword:   本篇主關鍵字（避免和自身配對）
        existing_articles: 已發布文章列表，每筆格式：
            {"title": str, "url": str, "primary_keyword": str, "secondary_keywords": str}

    Returns:
        最多 5 條建議，每條：
        {"anchor_text": str, "target_url": str, "target_title": str, "reason": str}
    """
    suggestions: list[dict] = []
    seen_urls: set[str] = set()

    for art in existing_articles:
        target_url = art.get("url", "").strip()
        target_title = art.get("title", "").strip()
        target_kw = art.get("primary_keyword", "").strip()
        target_sec = art.get("secondary_keywords", "")

        if not target_url or not target_title:
            continue
        if target_url in seen_urls:
            continue

        # 把目標文章的關鍵字清單（主 + 副）都拿來比對
        candidate_kws = [target_kw] + [
            k.strip() for k in re.split(r"[\n,，]+", target_sec) if k.strip()
        ]
        for kw in candidate_kws[:6]:
            if (
                kw
                and len(kw) >= 2
                and kw != primary_keyword
                and _kw_in_context(kw, content_markdown)
            ):
                suggestions.append({
                    "anchor_text": kw,
                    "target_url": target_url,
                    "target_title": target_title,
                    "reason": f"內文提及「{kw}」，可連結至相關文章《{target_title}》",
                })
                seen_urls.add(target_url)
                break

    return suggestions[:5]


def run_seo_check_agent(
    draft: ArticleDraft,
    primary_keyword: str = "",
    secondary_keywords: list[str] | None = None,
) -> dict:
    """回傳 SEO 檢查結果，不修改文章內容。

    使用加權計分：title/meta 等高影響力項目權重較高。
    """
    secondary_keywords = secondary_keywords or []
    first_paragraph = _get_first_paragraph(draft.content_markdown)
    h2s = _get_h2s(draft.content_markdown)

    checks = []

    # weight: 項目權重，用於最終加權評分
    def add_check(name: str, passed: bool, detail: str, weight: float = 1.0):
        checks.append({"name": name, "passed": passed, "detail": detail, "weight": weight})

    # 高權重（直接影響排名）
    add_check("title_has_primary_keyword", _keyword_in_text(primary_keyword, draft.title), "標題應包含主關鍵字", weight=3.0)
    add_check("meta_title_has_primary_keyword", _keyword_in_text(primary_keyword, draft.meta_title), "Meta Title 應包含主關鍵字", weight=2.5)
    add_check("meta_description_has_primary_keyword", _keyword_in_text(primary_keyword, draft.meta_description), "Meta Description 應包含主關鍵字", weight=2.0)
    add_check("first_paragraph_has_primary_keyword", _keyword_in_text(primary_keyword, first_paragraph), "首段應直接提到主關鍵字", weight=2.0)

    # 中權重（結構性 SEO）
    add_check("meta_title_length_ok", 10 <= len(draft.meta_title.strip()) <= 30, f"Meta Title 長度目前 {len(draft.meta_title.strip())} 字，建議 10-30 字", weight=1.5)
    add_check("meta_description_length_ok", 30 <= len(draft.meta_description.strip()) <= 80, f"Meta Description 長度目前 {len(draft.meta_description.strip())} 字，建議 30-80 字", weight=1.5)
    add_check("h2_count_ok", 3 <= len(h2s) <= 8, f"H2 數量目前 {len(h2s)}，建議 3-8 個", weight=1.5)
    add_check("h2_has_primary_keyword", any(_keyword_in_text(primary_keyword, h2) for h2 in h2s) if h2s else False, f"至少一個 H2 標題應包含主關鍵字「{primary_keyword}」", weight=2.0)

    density = _keyword_density(primary_keyword, draft.content_markdown)
    add_check("keyword_density_ok", 0.005 <= density <= 0.03, f"主關鍵字密度 {density:.1%}（建議 0.5%-3.0%，目前{'偏低' if density < 0.005 else '偏高' if density > 0.03 else '合格'}）", weight=1.5)

    # 標準權重（內容品質）
    add_check("faq_section_exists", _contains_faq(draft.content_markdown), "建議包含 FAQ / 常見問題 區塊", weight=1.0)
    add_check("word_count_ok", draft.word_count >= 1200, f"文章長度目前 {draft.word_count} 字，建議至少 1200 字", weight=1.0)

    if secondary_keywords:
        covered = sum(1 for keyword in secondary_keywords if _keyword_in_text(keyword, draft.content_markdown))
        add_check("secondary_keyword_coverage", covered >= max(1, min(2, len(secondary_keywords))), f"副關鍵字覆蓋 {covered}/{len(secondary_keywords)}", weight=1.0)

    # 加權計分
    passed_count = sum(1 for item in checks if item["passed"])
    total_weight = sum(item["weight"] for item in checks)
    passed_weight = sum(item["weight"] for item in checks if item["passed"])
    score = round((passed_weight / total_weight) * 100) if total_weight else 0

    result = {
        "score": score,
        "passed_count": passed_count,
        "total_count": len(checks),
        "checks": checks,
        "first_paragraph": first_paragraph,
        "h2s": h2s,
    }
    logger.info(f"[SEO Check Agent] 完成：{passed_count}/{len(checks)}，加權分數 {score}")
    return result