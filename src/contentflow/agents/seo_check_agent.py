"""SEO Check Agent：使用規則檢查文章的 SEO 基本面。"""

from __future__ import annotations

import re

from loguru import logger

from ..models import ArticleDraft


def _count_chinese_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))


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


def _count_keyword_occurrences(keyword: str, text: str) -> int:
    if not keyword or not text:
        return 0
    return len(re.findall(re.escape(keyword), text))


def _first_paragraph_keyword_stuffing(keyword: str, first_paragraph: str, *, max_occurrences: int = 2) -> tuple[bool, str]:
    """首段主關鍵字出現次數不得過多，避免為通過 SEO 規則而堆砌。"""
    if not keyword or not first_paragraph:
        return True, "首段無主關鍵字或無首段"
    count = _count_keyword_occurrences(keyword, first_paragraph)
    if count <= max_occurrences:
        return True, f"首段主關鍵字出現 {count} 次（上限 {max_occurrences}）"
    return False, f"首段主關鍵字「{keyword}」出現 {count} 次，超過上限 {max_occurrences}（疑似堆砌）"


def _opening_section_keyword_stuffing(
    keyword: str,
    markdown: str,
    *,
    char_window: int = 600,
    max_occurrences: int = 4,
) -> tuple[bool, str]:
    """開頭區塊（首段 + 緊接段落）關鍵字密度過高視為堆砌。"""
    if not keyword:
        return True, "未設定主關鍵字"
    plain_parts: list[str] = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if plain_parts:
                break
            continue
        if stripped.startswith("#"):
            if plain_parts:
                break
            continue
        plain_parts.append(stripped)
    opening = _clean_text(" ".join(plain_parts))[:char_window]
    if not opening:
        return True, "開頭區塊為空"
    count = _count_keyword_occurrences(keyword, opening)
    if count <= max_occurrences:
        return True, f"開頭 {char_window} 字內主關鍵字出現 {count} 次（上限 {max_occurrences}）"
    return False, f"開頭區塊主關鍵字「{keyword}」出現 {count} 次，超過上限 {max_occurrences}（疑似堆砌）"


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


def _is_cjk_char(char: str) -> bool:
    return bool(char) and bool(re.match(r"[\u3400-\u4dbf\u4e00-\u9fff]", char))


def _kw_in_context(kw: str, text: str) -> bool:
    """完整詞比對：2 字中文詞避免誤配到更長詞組中間的碎片。"""
    if len(kw) < 2:
        return False
    if len(kw) >= 3:
        return kw in text

    start = 0
    while True:
        idx = text.find(kw, start)
        if idx == -1:
            return False

        prev_char = text[idx - 1] if idx > 0 else ""
        next_index = idx + len(kw)
        next_char = text[next_index] if next_index < len(text) else ""

        # 兩側都被中文包住時，視為嵌在更長詞中的碎片，例如「髖骨盆腔」。
        if not (_is_cjk_char(prev_char) and _is_cjk_char(next_char)):
            return True

        start = idx + 1


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
    chinese_count = _count_chinese_chars(draft.content_markdown)

    checks = []

    # weight: 項目權重，用於最終加權評分
    def add_check(name: str, passed: bool, detail: str, weight: float = 1.0):
        checks.append({"name": name, "passed": passed, "detail": detail, "weight": weight})

    # 高權重（直接影響排名）
    add_check("title_has_primary_keyword", _keyword_in_text(primary_keyword, draft.title), "標題應包含主關鍵字", weight=3.0)
    add_check("meta_title_has_primary_keyword", _keyword_in_text(primary_keyword, draft.meta_title), "Meta Title 應包含主關鍵字", weight=2.5)
    add_check("meta_description_has_primary_keyword", _keyword_in_text(primary_keyword, draft.meta_description), "Meta Description 應包含主關鍵字", weight=2.0)
    add_check("first_paragraph_has_primary_keyword", _keyword_in_text(primary_keyword, first_paragraph), "首段應直接提到主關鍵字", weight=2.0)

    fp_stuff_ok, fp_stuff_detail = _first_paragraph_keyword_stuffing(primary_keyword, first_paragraph)
    add_check("first_paragraph_no_keyword_stuffing", fp_stuff_ok, fp_stuff_detail, weight=2.5)

    open_stuff_ok, open_stuff_detail = _opening_section_keyword_stuffing(primary_keyword, draft.content_markdown)
    add_check("opening_section_no_keyword_stuffing", open_stuff_ok, open_stuff_detail, weight=2.0)

    # 中權重（結構性 SEO）
    add_check("meta_title_length_ok", 10 <= len(draft.meta_title.strip()) <= 30, f"Meta Title 長度目前 {len(draft.meta_title.strip())} 字，建議 10-30 字", weight=1.5)
    add_check("meta_description_length_ok", 30 <= len(draft.meta_description.strip()) <= 80, f"Meta Description 長度目前 {len(draft.meta_description.strip())} 字，建議 30-80 字", weight=1.5)
    add_check("h2_count_ok", 3 <= len(h2s) <= 8, f"H2 數量目前 {len(h2s)}，建議 3-8 個", weight=1.5)
    add_check("h2_has_primary_keyword", any(_keyword_in_text(primary_keyword, h2) for h2 in h2s) if h2s else False, f"至少一個 H2 標題應包含主關鍵字「{primary_keyword}」", weight=2.0)

    density = _keyword_density(primary_keyword, draft.content_markdown)
    add_check("keyword_density_ok", 0.005 <= density <= 0.03, f"主關鍵字密度 {density:.1%}（建議 0.5%-3.0%，目前{'偏低' if density < 0.005 else '偏高' if density > 0.03 else '合格'}）", weight=1.5)

    # 標準權重（內容品質）
    add_check("faq_section_exists", _contains_faq(draft.content_markdown), "建議包含 FAQ / 常見問題 區塊", weight=1.0)
    add_check("word_count_ok", chinese_count >= 800, f"文章中文字數目前 {chinese_count} 字，建議至少 800 字", weight=1.0)

    if secondary_keywords:
        covered = sum(1 for keyword in secondary_keywords if _keyword_in_text(keyword, draft.content_markdown))
        add_check("secondary_keyword_coverage", covered >= max(1, min(2, len(secondary_keywords))), f"副關鍵字覆蓋 {covered}/{len(secondary_keywords)}", weight=1.0)

    # Featured Snippet 最佳化（H2 問句 + 緊接 40-60 字簡答段落）
    def _has_featured_snippet_pattern(md: str) -> bool:
        lines = (md or "").splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # H2 must end with ？ or ?
            if not re.match(r"^##\s+.+[？?]", stripped):
                continue
            # Look for the next non-empty paragraph within 3 lines
            for j in range(i + 1, min(i + 4, len(lines))):
                para = lines[j].strip()
                if not para or para.startswith("#") or para.startswith("|"):
                    continue
                # Para length in chars: target 40-80 (Chinese chars count more per word)
                char_count = len(re.sub(r"\s+", "", para))
                if 30 <= char_count <= 100:
                    return True
                break
        return False

    add_check(
        "featured_snippet_pattern",
        _has_featured_snippet_pattern(draft.content_markdown),
        "建議至少一個 H2 問句（結尾？）後緊接 40-80 字的直接回答段落，有助取得精選摘要",
        weight=1.5,
    )

    # 段落標題層级檢查：H2 應出現在 H3 之前
    def _heading_hierarchy_ok(md: str) -> bool:
        seen_h2 = False
        for m in re.finditer(r"^(#{2,3})\s+", md or "", re.MULTILINE):
            level = len(m.group(1))
            if level == 2:
                seen_h2 = True
            elif level == 3 and not seen_h2:
                return False
        return True

    add_check("heading_hierarchy_ok", _heading_hierarchy_ok(draft.content_markdown), "H3 標題應在 H2 之後出現（避免跳過層級）", weight=0.5)

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