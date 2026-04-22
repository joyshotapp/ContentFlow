"""測試 Research Agent 的 PubMed 翻譯輔助邏輯。"""

from types import SimpleNamespace

from contentflow.agents.research_agent import _translate_keywords_for_pubmed


def test_translate_keywords_parses_fenced_json(monkeypatch):
    monkeypatch.setattr(
        "contentflow.agents.research_agent.chat_sync",
        lambda **kwargs: '```json\n["osteophyte"]\n```',
    )

    result = _translate_keywords_for_pubmed(["長骨刺原因"])
    assert result == ["osteophyte"]