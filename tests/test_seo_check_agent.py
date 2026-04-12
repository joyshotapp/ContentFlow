"""測試 SEO Check Agent（純規則，不需 LLM）"""

from contentflow.models import ArticleDraft
from contentflow.agents.seo_check_agent import run_seo_check_agent


def _make_draft(
    title="龜鹿二仙膠功效完整解析",
    meta_title="龜鹿二仙膠功效｜專家帶你了解保養秘訣",
    meta_description="想了解龜鹿二仙膠功效嗎？本文從成分、適用族群到食用方式，完整解析龜鹿二仙膠的保養價值。",
    content_markdown=None,
    word_count=2000,
) -> ArticleDraft:
    if content_markdown is None:
        content_markdown = (
            "# 龜鹿二仙膠功效完整解析\n\n"
            "龜鹿二仙膠功效廣受推崇，是傳統漢方中最知名的滋補配方之一，"
            "尤其適合需要補充骨質的族群，了解龜鹿二仙膠功效有助於做出最適合的保養選擇。\n\n"
            "## 龜鹿二仙膠功效與主要成分\n\n"
            "龜鹿二仙膠功效源自龜板、鹿角、人參、枸杞四味珍貴藥材，可滋補肝腎、強健筋骨。\n\n"
            "## 龜鹿二仙膠功效的科學根據\n\n"
            "現代研究顯示，龜鹿二仙膠功效與其膠原蛋白及胺基酸成分密切相關。\n\n"
            "## 適用族群\n\n"
            "適合銀髮族、產後調理、運動族群使用龜鹿二仙膠功效補充所需。\n\n"
            "## 食用方式與注意事項\n\n"
            "建議空腹食用，每日一次，搭配溫開水，以充分發揮龜鹿二仙膠功效。\n\n"
            "## FAQ 常見問題\n\n"
            "### Q: 龜鹿二仙膠功效多久才能感受到？\n\n"
            "A: 一般建議連續食用 4-6 週，才能明顯感受到龜鹿二仙膠功效的滋補效果。\n\n"
        )
    return ArticleDraft(
        title=title,
        meta_title=meta_title,
        meta_description=meta_description,
        content_markdown=content_markdown,
        word_count=word_count,
    )


class TestSEOCheckAgent:
    def test_perfect_article_scores_high(self):
        """一篇 SEO 完善的文章應該拿到高分"""
        draft = _make_draft()
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        assert result["score"] >= 80
        assert result["passed_count"] >= 9   # 11 條規則，完善文章應通過至少 9 條

    def test_missing_keyword_in_title_fails(self):
        draft = _make_draft(title="保養品推薦")
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        title_check = next(c for c in result["checks"] if c["name"] == "title_has_primary_keyword")
        assert title_check["passed"] is False

    def test_short_article_fails_word_count(self):
        draft = _make_draft(word_count=500)
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        wc_check = next(c for c in result["checks"] if c["name"] == "word_count_ok")
        assert wc_check["passed"] is False

    def test_no_faq_fails(self):
        md = "# 標題\n\n龜鹿二仙膠功效很好。\n\n## 段落一\n\n內容\n\n## 段落二\n\n內容\n\n## 段落三\n\n內容\n"
        draft = _make_draft(content_markdown=md, word_count=2000)
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        faq_check = next(c for c in result["checks"] if c["name"] == "faq_section_exists")
        assert faq_check["passed"] is False

    def test_result_structure(self):
        draft = _make_draft()
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        assert "score" in result
        assert "passed_count" in result
        assert "total_count" in result
        assert "checks" in result
        assert "h2s" in result
        assert isinstance(result["checks"], list)
        assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])

    def test_secondary_keyword_coverage(self):
        draft = _make_draft()
        result = run_seo_check_agent(
            draft,
            primary_keyword="龜鹿二仙膠功效",
            secondary_keywords=["龜板", "鹿角"],
        )
        sec_check = next(c for c in result["checks"] if c["name"] == "secondary_keyword_coverage")
        assert sec_check["passed"] is True

    def test_h2_count_extracted_correctly(self):
        draft = _make_draft()
        result = run_seo_check_agent(draft, primary_keyword="龜鹿二仙膠功效")
        assert len(result["h2s"]) == 5  # 五個 ## 段落

    def test_empty_draft(self):
        """空白草稿不應 crash"""
        draft = ArticleDraft(title="", content_markdown="", word_count=0)
        result = run_seo_check_agent(draft, primary_keyword="")
        assert result["score"] == 0 or isinstance(result["score"], int)
