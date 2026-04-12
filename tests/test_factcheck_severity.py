"""禁用詞嚴重度分級測試"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from contentflow.agents.factcheck_agent import _check_forbidden_words, _SOFT_WORDS


# ── 基礎功能 ──────────────────────────────────────────────────

def test_educational_soft_word_not_flagged():
    """教育文章中，2 字通用動詞降為 warning（needs_review=False）"""
    items = _check_forbidden_words("可以改善腰痛", ["改善"], article_type="educational")
    assert len(items) == 1
    assert not items[0].needs_review
    assert "[提醒]" in items[0].claim


def test_educational_hard_word_flagged():
    """教育文章中，專業禁用詞仍為 error"""
    items = _check_forbidden_words("治療近視有效", ["治療近視"], article_type="educational")
    assert len(items) == 1
    assert items[0].needs_review
    assert "法規違規" in items[0].reviewer_note


def test_product_all_strict():
    """產品頁全部嚴格：即使是通用動詞也標為 error"""
    items = _check_forbidden_words("可以改善腰痛", ["改善"], article_type="product")
    assert len(items) == 1
    assert items[0].needs_review


def test_educational_two_char_hard_word_still_flagged():
    """教育文章中，不在白名單的兩字高風險詞仍應維持 error。"""
    items = _check_forbidden_words("這項產品宣稱可以壯陽", ["壯陽"], article_type="educational")
    assert len(items) == 1
    assert items[0].needs_review


def test_mixed_words_educational():
    """教育文章中混合詞：soft 是 warning，hard 是 error"""
    content = "改善腰痛，恢復視力"
    items = _check_forbidden_words(content, ["改善", "恢復視力"], article_type="educational")
    warnings = [i for i in items if not i.needs_review]
    errors = [i for i in items if i.needs_review]
    assert len(warnings) == 1  # 改善
    assert len(errors) == 1    # 恢復視力


def test_empty_forbidden_list():
    """空禁用詞列表回傳空結果"""
    items = _check_forbidden_words("whatever", [], article_type="educational")
    assert items == []


def test_no_match():
    """文章中無禁用詞"""
    items = _check_forbidden_words("正常的文章內容", ["治療近視"], article_type="educational")
    assert items == []


def test_soft_words_set_has_common_terms():
    """確認 _SOFT_WORDS 包含常見通用動詞"""
    expected = {"改善", "減輕", "舒緩", "促進", "增強", "緩解"}
    assert expected.issubset(_SOFT_WORDS)


def test_default_article_type_is_educational():
    """不指定 article_type 時預設為 educational"""
    items = _check_forbidden_words("可以改善腰痛", ["改善"])
    assert len(items) == 1
    assert not items[0].needs_review  # 教育模式
