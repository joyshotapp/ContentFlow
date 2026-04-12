"""測試 project_context 模組 — 禁用詞抽取 + 上下文載入"""

import re
from contentflow.project_context import (
    _extract_forbidden_terms,
    ProjectContext,
    project_uses_pubmed,
)


class TestExtractForbiddenTerms:
    """_extract_forbidden_terms 應從法規條文中提取可比對的禁用詞"""

    def test_extracts_quoted_terms(self):
        text = '宣稱「治療近視」、「恢復視力」是禁止的。'
        result = _extract_forbidden_terms([text])
        assert "治療近視" in result
        assert "恢復視力" in result

    def test_extracts_example_sentences(self):
        text = '例句: 治療近視。恢復視力。防止便秘。利尿。壯陽。'
        result = _extract_forbidden_terms([text])
        assert "治療近視" in result
        assert "恢復視力" in result
        assert "防止便秘" in result

    def test_filters_boilerplate(self):
        """法規樣板用語不應被視為禁用詞"""
        text = "行政院衛生署為保障消費者權益，特訂定本基準。"
        result = _extract_forbidden_terms([text])
        for word in result:
            assert "行政院衛生署" not in word
            assert "保障消費者權益" not in word
            assert "特訂定本基準" not in word

    def test_filters_short_tokens(self):
        """長度 < 2 的 token 不應出現"""
        text = "例句: 降血壓。A。B。"
        result = _extract_forbidden_terms([text])
        assert all(len(w) >= 2 for w in result)

    def test_filters_alphanumeric_only(self):
        """含英數字的片段應被過濾"""
        text = "101年9月28日署授食字第1013000020號令發布"
        result = _extract_forbidden_terms([text])
        assert all(not re.search(r"[0-9a-zA-Z]", w) for w in result)

    def test_deduplicates(self):
        texts = [
            '例句: 治療近視。恢復視力。',
            '宣稱「治療近視」是禁止的。',
        ]
        result = _extract_forbidden_terms(texts)
        assert result.count("治療近視") == 1

    def test_empty_input(self):
        assert _extract_forbidden_terms([]) == []

    def test_real_regulation_sample(self):
        """模擬實際食品廣告用詞規定的完整段落"""
        sample = (
            "食品廣告標示詞句涉及誇張易生誤解或醫療效能之認定表\n"
            "(一)使用下列詞句者，應認定為涉及醫療效能:\n"
            " 1.宣稱預防、改善、減輕、診斷或治療疾病或特定生理情形:\n"
            " 例句: 治療近視。恢復視力。防止便秘。利尿。改善過敏體質。壯陽。強精。\n"
            " 2.宣稱減輕或降低導致疾病有關之體內成分:\n"
            " 例句: 解肝毒。降肝脂。\n"
        )
        result = _extract_forbidden_terms([sample])
        # 應該抽到具體的禁用詞
        assert "治療近視" in result
        assert "解肝毒" in result
        assert "降肝脂" in result
        # 不應包含法規樣板語
        assert not any("應認定" in w for w in result)


class TestProjectContextBuildPrompt:
    """ProjectContext.build_brand_prompt 格式驗證"""

    def test_includes_brand_name(self):
        ctx = ProjectContext(
            project_id=1, slug="test", name="Test",
            brand_name="好品牌",
        )
        prompt = ctx.build_brand_prompt()
        assert "好品牌" in prompt

    def test_includes_legal_terms(self):
        ctx = ProjectContext(
            project_id=1, slug="test", name="Test",
            legal_terms=["不可宣稱療效"],
        )
        prompt = ctx.build_brand_prompt()
        assert "不可宣稱療效" in prompt

    def test_empty_context_produces_minimal_prompt(self):
        ctx = ProjectContext(project_id=0, slug="default", name="Default")
        prompt = ctx.build_brand_prompt()
        # 至少不會 crash，內容應該很短
        assert isinstance(prompt, str)


class TestProjectPubmedPolicy:
    def test_health_project_uses_pubmed(self):
        ctx = ProjectContext(project_id=1, slug="health", name="Health", industry="保健食品")
        assert project_uses_pubmed(ctx) is True

    def test_non_health_project_skips_pubmed(self):
        ctx = ProjectContext(project_id=2, slug="tech", name="Tech", industry="科技媒體")
        assert project_uses_pubmed(ctx) is False
