"""測試 pipeline 輔助函式（不呼叫 LLM，只測 load_article / keyword 處理邏輯）"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

# 直接 import pipeline 輔助函式
from scripts.run_article_pipeline import (
    _clean_keyword_text,
    _split_keywords,
    _normalize_article_keywords,
    clean_code_fences,
)


class TestCleanKeywordText:
    def test_removes_volume_in_parens(self):
        assert _clean_keyword_text("龜鹿二仙膠 (1200)") == "龜鹿二仙膠"

    def test_removes_trailing_number(self):
        assert _clean_keyword_text("膝蓋痛 880") == "膝蓋痛"

    def test_strips_whitespace(self):
        assert _clean_keyword_text("  測試  ") == "測試"

    def test_none_input(self):
        assert _clean_keyword_text(None) == ""


class TestSplitKeywords:
    def test_splits_newlines(self):
        result = _split_keywords("A\nB\nC")
        assert result == ["A", "B", "C"]

    def test_splits_commas(self):
        result = _split_keywords("A，B,C")
        assert result == ["A", "B", "C"]

    def test_deduplicates(self):
        result = _split_keywords("A\nA\nB")
        assert result == ["A", "B"]

    def test_empty_input(self):
        assert _split_keywords("") == []
        assert _split_keywords(None) == []


class TestNormalizeArticleKeywords:
    def test_first_line_becomes_primary(self):
        primary, secondary = _normalize_article_keywords("A\nB\nC", "D")
        assert primary == "A"
        assert "B" in secondary
        assert "C" in secondary
        assert "D" in secondary

    def test_no_duplicates_in_secondary(self):
        primary, secondary = _normalize_article_keywords("A\nB", "B\nC")
        assert primary == "A"
        assert secondary.count("B") == 1

    def test_empty_input(self):
        primary, secondary = _normalize_article_keywords("", "")
        assert primary == ""
        assert secondary == []


class TestCleanCodeFences:
    def test_removes_markdown_fence(self):
        text = "```markdown\n# Hello\n```"
        result = clean_code_fences(text)
        assert "```" not in result
        assert "# Hello" in result

    def test_handles_no_fences(self):
        text = "Normal text"
        assert clean_code_fences(text) == "Normal text"

    def test_collapses_extra_newlines(self):
        text = "A\n\n\n\n\nB"
        result = clean_code_fences(text)
        assert "\n\n\n" not in result
