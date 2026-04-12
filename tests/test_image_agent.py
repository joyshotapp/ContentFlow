"""Image Agent 單元測試（不呼叫 API）"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from contentflow.agents.image_agent import _extract_sections


def test_extract_sections_basic():
    md = """## 第一節
段落一內容。

## 第二節
段落二內容。

## 第三節
段落三內容。"""
    sections = _extract_sections(md)
    assert len(sections) == 3
    assert sections[0]["heading"] == "第一節"
    assert "段落一" in sections[0]["summary"]


def test_extract_sections_no_h2():
    md = "# 只有一級標題\n\n沒有二級標題"
    sections = _extract_sections(md)
    assert sections == []


def test_extract_sections_mixed_headings():
    md = """# H1 標題

## H2 段落一
內容一

### H3 子標題
子內容

## H2 段落二
內容二"""
    sections = _extract_sections(md)
    assert len(sections) == 2
    assert sections[0]["heading"] == "H2 段落一"
    assert sections[1]["heading"] == "H2 段落二"


def test_extract_sections_long_summary_truncated():
    long_content = "字" * 500
    md = f"## 長段落\n{long_content}"
    sections = _extract_sections(md)
    assert len(sections) == 1
    assert len(sections[0]["summary"]) <= 200


def test_extract_sections_empty_body():
    md = "## 空段落\n\n## 另一段\n有內容"
    sections = _extract_sections(md)
    assert len(sections) == 2
    assert sections[0]["summary"] == ""
    assert "有內容" in sections[1]["summary"]
