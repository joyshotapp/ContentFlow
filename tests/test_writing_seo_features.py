"""測試 writing_agent 新增的 SEO 功能：FAQ JSON-LD、E-E-A-T 作者聲明、URL Slug"""

import json
import pytest
from unittest.mock import MagicMock, patch

from contentflow.agents.writing_agent import (
    _generate_faq_schema,
    _append_eeat_section,
    _generate_article_schema,
    _generate_slug,
)
from contentflow.project_context import ProjectContext


# ════════════════════════════════════════════════════════════
# _generate_faq_schema
# ════════════════════════════════════════════════════════════

class TestGenerateFaqSchema:
    _FAQ_CONTENT = """
## 骨刺的成因

長期姿勢不良是主要原因。

## 常見問題（FAQ）

### 骨刺會自己消失嗎？

骨刺一旦形成通常不會自行消失，但可以透過物理治療緩解症狀，減輕日常生活的不適。

### 骨刺需要開刀嗎？

大多數骨刺不需要手術，保守治療包括物理治療、消炎藥物即可改善症狀。

### 如何預防骨刺？

保持正確姿勢、適度運動、維持健康體重，是預防骨刺最有效的方式。
"""

    def test_extracts_qa_pairs(self):
        schema_json = _generate_faq_schema(self._FAQ_CONTENT)
        assert schema_json != ""
        schema = json.loads(schema_json)
        assert schema["@type"] == "FAQPage"
        entities = schema["mainEntity"]
        assert len(entities) == 3

    def test_schema_structure(self):
        schema_json = _generate_faq_schema(self._FAQ_CONTENT)
        schema = json.loads(schema_json)
        q = schema["mainEntity"][0]
        assert q["@type"] == "Question"
        assert "name" in q
        assert q["acceptedAnswer"]["@type"] == "Answer"
        assert "text" in q["acceptedAnswer"]

    def test_question_text_correct(self):
        schema_json = _generate_faq_schema(self._FAQ_CONTENT)
        schema = json.loads(schema_json)
        names = [e["name"] for e in schema["mainEntity"]]
        assert "骨刺會自己消失嗎？" in names

    def test_answer_not_empty(self):
        schema_json = _generate_faq_schema(self._FAQ_CONTENT)
        schema = json.loads(schema_json)
        for entity in schema["mainEntity"]:
            assert entity["acceptedAnswer"]["text"] != ""

    def test_no_faq_section_returns_empty(self):
        content = "## 成因\n\n磨損所致。\n\n## 治療\n\n物理治療。"
        assert _generate_faq_schema(content) == ""

    def test_context_schema_url(self):
        schema_json = _generate_faq_schema(self._FAQ_CONTENT)
        schema = json.loads(schema_json)
        assert schema["@context"] == "https://schema.org"

    def test_faq_heading_variant(self):
        """也支援 ## FAQ 標題"""
        content = (
            "## 介紹\n\n骨刺概述。\n\n"
            "## FAQ\n\n"
            "### 什麼是骨刺？\n\n骨骼邊緣增生的骨質突起。\n"
        )
        schema_json = _generate_faq_schema(content)
        assert schema_json != ""
        schema = json.loads(schema_json)
        assert len(schema["mainEntity"]) == 1


# ════════════════════════════════════════════════════════════
# _append_eeat_section
# ════════════════════════════════════════════════════════════

def _make_ctx(industry: str) -> ProjectContext:
    return ProjectContext(project_id=1, slug="test", name="測試", industry=industry)


class TestAppendEeatSection:
    _BASE = "## 骨刺成因\n\n長期磨損是主因。\n"

    def test_appended_for_health_project(self):
        ctx = _make_ctx("保健食品")
        result = _append_eeat_section(self._BASE, ctx)
        assert "本文資訊聲明" in result
        assert "免責聲明" in result

    def test_not_appended_for_tech_project(self):
        ctx = _make_ctx("科技媒體")
        result = _append_eeat_section(self._BASE, ctx)
        assert "本文資訊聲明" not in result
        assert result.strip() == self._BASE.strip()

    def test_idempotent_health(self):
        """已有 E-E-A-T 區塊時，不再重複加入"""
        ctx = _make_ctx("健康照護")
        once = _append_eeat_section(self._BASE, ctx)
        twice = _append_eeat_section(once, ctx)
        assert twice.count("本文資訊聲明") == 1

    def test_no_placeholder_in_eeat_section(self):
        ctx = _make_ctx("醫療保健")
        result = _append_eeat_section(self._BASE, ctx)
        assert "TODO" not in result
        assert "免責聲明" in result

    def test_industries_that_trigger_eeat(self):
        for industry in ["保健", "健康食品", "醫療器材", "生技", "營養補充"]:
            ctx = _make_ctx(industry)
            result = _append_eeat_section(self._BASE, ctx)
            assert "本文資訊聲明" in result, f"industry={industry} 應加入 E-E-A-T"


# ════════════════════════════════════════════════════════════
# _generate_slug
# ════════════════════════════════════════════════════════════

class TestGenerateSlug:
    def _mock_client(self, response_text: str):
        client = MagicMock()
        client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=response_text))]
        )
        return client

    def test_basic_slug(self):
        client = self._mock_client("bone-spur-causes-treatment")
        slug = _generate_slug(client, "骨刺原因與治療方式")
        assert slug == "bone-spur-causes-treatment"

    def test_slug_cleaned_of_special_chars(self):
        client = self._mock_client("bone spur!@# causes")
        slug = _generate_slug(client, "骨刺原因")
        assert " " not in slug
        assert "!" not in slug
        assert "@" not in slug

    def test_slug_lowercase(self):
        client = self._mock_client("Bone-Spur-Causes")
        slug = _generate_slug(client, "骨刺原因")
        assert slug == slug.lower()

    def test_fallback_on_exception(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = Exception("API error")
        slug = _generate_slug(client, "骨刺原因")
        assert slug == "article"

    def test_empty_response_fallback(self):
        client = self._mock_client("")
        slug = _generate_slug(client, "骨刺原因")
        assert slug == "article"


class TestGenerateArticleSchema:
    def test_schema_omits_placeholder_fields(self):
        ctx = ProjectContext(project_id=1, slug="test", name="測試品牌", brand_url="https://example.com")
        schema_json = _generate_article_schema(
            title="骨刺治療完整指南",
            meta_description="骨刺治療方式說明",
            slug="bone-spur-guide",
            word_count=1800,
            ctx=ctx,
        )
        schema = json.loads(schema_json)

        assert "author" not in schema
        assert "datePublished" not in schema
        assert "dateModified" not in schema
        assert "TODO" not in schema_json
