"""測試 Research Agent 的 PubMed 翻譯輔助邏輯。"""

from types import SimpleNamespace

from contentflow.agents.research_agent import _translate_keywords_for_pubmed


def test_translate_keywords_parses_fenced_json(monkeypatch):
    class FakeClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                message=SimpleNamespace(
                                    content='```json\n["osteophyte"]\n```'
                                )
                            )
                        ]
                    )

    monkeypatch.setattr("contentflow.agents.research_agent.OpenAI", lambda api_key=None: FakeClient())

    result = _translate_keywords_for_pubmed(["長骨刺原因"])
    assert result == ["osteophyte"]