"""測試 seo_check_agent 新增的 SEO 規則：關鍵字密度、H2 含關鍵字、內部連結建議、加權計分"""

import pytest
from contentflow.agents.seo_check_agent import (
    _keyword_density,
    _kw_in_context,
    run_seo_check_agent,
    suggest_internal_links,
)
from contentflow.models.schemas import ArticleDraft, ArticleStatus


# ════════════════════════════════════════════════════════════
# _keyword_density
# ════════════════════════════════════════════════════════════

class TestKeywordDensity:
    def test_within_range(self):
        # 10 次出現 × 3 字 / 600 字 = 5%? 調整讓它落在範圍內
        # 關鍵字 3 字，出現 3 次，總字元 600 → 3*3/600 = 1.5% ✓
        content = "骨刺 " * 3 + "其他文字" * 147
        density = _keyword_density("骨刺", content)
        assert 0.005 <= density <= 0.03

    def test_too_low(self):
        # 1 次出現 2 字，總字元 5000 → 2/5000 = 0.04% (太低)
        content = "骨刺 " + "填充文字" * 1249
        density = _keyword_density("骨刺", content)
        assert density < 0.005

    def test_too_high(self):
        # 20 次出現 2 字，總字元 200 → 40/200 = 20% (太高)
        content = "骨刺" * 30
        density = _keyword_density("骨刺", content)
        assert density > 0.03

    def test_empty_keyword(self):
        assert _keyword_density("", "some content") == 0.0

    def test_empty_content(self):
        assert _keyword_density("骨刺", "") == 0.0

    def test_markdown_tags_excluded(self):
        # Markdown 標記不應計入總字元
        content = "## 骨刺標題\n\n骨刺的原因很多，骨刺的治療方式也不同。\n\n**骨刺** 是常見問題。"
        density = _keyword_density("骨刺", content)
        assert density > 0  # 有找到關鍵字


# ════════════════════════════════════════════════════════════
# run_seo_check_agent — 新增的兩條規則
# ════════════════════════════════════════════════════════════

def _make_draft(content: str, kw: str = "骨刺") -> ArticleDraft:
    return ArticleDraft(
        title=f"{kw}的原因",
        meta_title=f"{kw}完整攻略",
        meta_description=f"了解{kw}的成因、症狀與治療方式，本文詳細說明。",
        content_markdown=content,
        word_count=len(content),
    )


class TestSeoCheckNewRules:
    def _get_check(self, name: str, checks: list[dict]) -> dict | None:
        return next((c for c in checks if c["name"] == name), None)

    def test_first_paragraph_keyword_stuffing_fails(self):
        kw = "落枕怎麼辦"
        stuffed = (
            f"{kw}的首段開場。" * 4
            + "\n\n## 原因\n\n說明。\n\n## 治療\n\n說明。\n\n## FAQ\n\n### 問題？\n\n答案。\n"
        )
        draft = _make_draft(stuffed, kw=kw)
        result = run_seo_check_agent(draft, primary_keyword=kw)
        check = self._get_check("first_paragraph_no_keyword_stuffing", result["checks"])
        assert check is not None
        assert check["passed"] is False

    def test_keyword_density_check_present(self):
        content = (
            "骨刺是一種常見的骨科問題。骨刺會造成疼痛不適。\n\n"
            "## 骨刺的成因\n\n長期姿勢不良容易造成骨刺生長。\n\n"
            "## 常見問題\n\n### 骨刺怎麼辦？\n\n諮詢醫師。\n\n"
        ) * 8
        draft = _make_draft(content)
        result = run_seo_check_agent(draft, primary_keyword="骨刺")
        check = self._get_check("keyword_density_ok", result["checks"])
        assert check is not None, "keyword_density_ok 規則應存在"

    def test_h2_has_keyword_pass(self):
        content = (
            "骨刺是常見的關節問題，本文深入介紹骨刺。\n\n"
            "## 骨刺的主要成因\n\n長期磨損是主因。\n\n"
            "## 常見問題\n\n### 如何預防？\n\n多運動。\n\n"
        ) * 5
        draft = _make_draft(content)
        result = run_seo_check_agent(draft, primary_keyword="骨刺")
        check = self._get_check("h2_has_primary_keyword", result["checks"])
        assert check is not None
        assert check["passed"] is True

    def test_h2_missing_keyword_fail(self):
        content = (
            "骨刺很常見，本文詳細說明。\n\n"
            "## 成因分析\n\n與磨損有關。\n\n"
            "## 治療方式\n\n需要就醫。\n\n"
            "## 常見問題\n\n### 如何預防？\n\n多運動。\n\n"
        ) * 5
        draft = _make_draft(content)
        result = run_seo_check_agent(draft, primary_keyword="骨刺")
        check = self._get_check("h2_has_primary_keyword", result["checks"])
        assert check is not None
        assert check["passed"] is False

    def test_total_checks_increased(self):
        """加入新規則後總 check 數應比原本多 2"""
        content = (
            "骨刺是一種常見的骨科問題。\n\n"
            "## 骨刺成因\n\n磨損所致。\n\n"
            "## 常見問題\n\n### 怎麼辦？\n\n就醫。\n"
        ) * 6
        draft = _make_draft(content)
        result = run_seo_check_agent(draft, primary_keyword="骨刺")
        # 原本 9 條（無副關鍵字），現在應有 11 條
        assert result["total_count"] >= 11


# ════════════════════════════════════════════════════════════
# suggest_internal_links
# ════════════════════════════════════════════════════════════

class TestSuggestInternalLinks:
    _CONTENT = (
        "骨刺是常見問題，椎間盤突出也可能合併發生。"
        "膝蓋骨刺會造成膝關節疼痛。"
        "頸椎骨刺的症狀包括手麻與肩膀痠痛。"
    )
    _EXISTING = [
        {
            "title": "椎間盤突出完整攻略",
            "url": "https://example.com/disc",
            "primary_keyword": "椎間盤突出",
            "secondary_keywords": "腰椎, 坐骨神經",
        },
        {
            "title": "膝蓋痛原因與治療",
            "url": "https://example.com/knee",
            "primary_keyword": "膝關節疼痛",
            "secondary_keywords": "膝蓋骨刺, 半月板",
        },
        {
            "title": "完全無關的美食文章",
            "url": "https://example.com/food",
            "primary_keyword": "牛肉麵",
            "secondary_keywords": "台北美食",
        },
    ]

    def test_finds_matching_articles(self):
        result = suggest_internal_links(self._CONTENT, "骨刺", self._EXISTING)
        urls = [s["target_url"] for s in result]
        assert "https://example.com/disc" in urls or "https://example.com/knee" in urls

    def test_excludes_unrelated_articles(self):
        result = suggest_internal_links(self._CONTENT, "骨刺", self._EXISTING)
        urls = [s["target_url"] for s in result]
        assert "https://example.com/food" not in urls

    def test_excludes_primary_keyword_from_anchor(self):
        result = suggest_internal_links(self._CONTENT, "椎間盤突出", self._EXISTING)
        anchor_texts = [s["anchor_text"] for s in result]
        assert "椎間盤突出" not in anchor_texts

    def test_max_five_suggestions(self):
        many = [
            {
                "title": f"文章{i}",
                "url": f"https://example.com/{i}",
                "primary_keyword": f"詞{i}",
                "secondary_keywords": "",
            }
            for i in range(20)
        ]
        content = "".join(f"詞{i} " for i in range(20))
        result = suggest_internal_links(content, "other", many)
        assert len(result) <= 5

    def test_empty_existing_returns_empty(self):
        result = suggest_internal_links(self._CONTENT, "骨刺", [])
        assert result == []

    def test_result_has_required_keys(self):
        result = suggest_internal_links(self._CONTENT, "骨刺", self._EXISTING)
        if result:
            s = result[0]
            assert "anchor_text" in s
            assert "target_url" in s
            assert "target_title" in s
            assert "reason" in s

    def test_two_char_keyword_boundary(self):
        """2 字關鍵字「骨盆」不應誤配到「髖骨盆腔」中間的碎片"""
        content = "髖骨盆腔是一個常見的解剖結構。"
        existing = [
            {"title": "骨盆前傾矯正", "url": "https://example.com/pelvis",
             "primary_keyword": "骨盆", "secondary_keywords": ""},
        ]
        result = suggest_internal_links(content, "other", existing)
        # 「骨盆」前方是「髖」（漢字），不應配對
        assert len(result) == 0

    def test_two_char_keyword_matches_standalone(self):
        """2 字關鍵字「骨盆」在獨立出現時應正常配對"""
        content = "骨盆前傾是常見問題，多做伸展有幫助。"
        existing = [
            {"title": "骨盆前傾矯正", "url": "https://example.com/pelvis",
             "primary_keyword": "骨盆", "secondary_keywords": ""},
        ]
        result = suggest_internal_links(content, "other", existing)
        assert len(result) == 1


# ════════════════════════════════════════════════════════════
# _kw_in_context
# ════════════════════════════════════════════════════════════

class TestKwInContext:
    def test_three_char_direct_match(self):
        assert _kw_in_context("椎間盤", "椎間盤突出是常見問題") is True

    def test_three_char_no_match(self):
        assert _kw_in_context("椎間盤", "脊椎很重要") is False

    def test_two_char_standalone(self):
        assert _kw_in_context("骨刺", "骨刺是常見問題") is True

    def test_two_char_embedded_rejected(self):
        assert _kw_in_context("骨盆", "髖骨盆腔是常見問題") is False

    def test_single_char_rejected(self):
        assert _kw_in_context("骨", "骨刺很常見") is False


# ════════════════════════════════════════════════════════════
# 加權計分
# ════════════════════════════════════════════════════════════

class TestWeightedScoring:
    def test_high_weight_items_impact_score_more(self):
        """title 關鍵字（權重 3）通過 vs 不通過，分數差距應明顯"""
        content = (
            "骨刺是常見問題，本文說明骨刺的相關知識。\n\n"
            "## 骨刺的成因\n\n長期磨損。\n\n"
            "## 治療\n\n物理治療。\n\n"
            "## 常見問題\n\n### 如何?\n\n就醫。\n"
        ) * 5
        draft_with = ArticleDraft(
            title="骨刺原因完整解析",
            meta_title="骨刺原因與治療方式完整說明",
            meta_description="深入了解骨刺原因，包括症狀、治療方式與預防方法，幫助你遠離骨刺困擾。",
            content_markdown=content, word_count=len(content),
        )
        draft_without = ArticleDraft(
            title="關節問題完整解析",
            meta_title="關節相關問題完整說明與分析指南",
            meta_description="深入了解關節相關問題，包括症狀、治療方式與預防方法，幫助你遠離關節困擾。",
            content_markdown=content, word_count=len(content),
        )
        score_with = run_seo_check_agent(draft_with, "骨刺")["score"]
        score_without = run_seo_check_agent(draft_without, "骨刺")["score"]
        # title+meta_title+meta_desc 三項合計權重 7.5，差距應超過 10 分
        assert score_with - score_without >= 10

    def test_check_has_weight_key(self):
        content = "骨刺。\n\n## H2\n\n段落。\n\n## 常見問題\n\n### Q?\n\nA.\n"
        draft = ArticleDraft(
            title="骨刺", meta_title="骨刺", meta_description="骨刺" * 15,
            content_markdown=content, word_count=len(content),
        )
        result = run_seo_check_agent(draft, "骨刺")
        for check in result["checks"]:
            assert "weight" in check, f"check '{check['name']}' 缺少 weight 欄位"
