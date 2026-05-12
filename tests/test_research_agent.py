"""測試 Research Agent 的 PubMed 翻譯與 policy 整合邏輯。"""

from types import SimpleNamespace

import pytest

from contentflow.agents.research_agent import _translate_keywords_for_pubmed, run_research_agent
from contentflow.models.schemas import PubMedArticle, PubMedSearchResult, SerpAnalysis
from contentflow.project_context import ProjectContext


def test_translate_keywords_parses_fenced_json(monkeypatch):
    monkeypatch.setattr(
        "contentflow.agents.research_agent.chat_sync",
        lambda **kwargs: '```json\n["osteophyte"]\n```',
    )

    result = _translate_keywords_for_pubmed(["長骨刺原因"])
    assert result == ["osteophyte"]


@pytest.mark.asyncio
async def test_run_research_agent_uses_project_policy_to_disable_pubmed(monkeypatch):
    async def fake_serp(*args, **kwargs):
        return SerpAnalysis(query="SaaS SEO", people_also_ask=[], top_results=[])

    async def fake_pubmed(*args, **kwargs):
        raise AssertionError("tech project should not call PubMed")

    monkeypatch.setattr("contentflow.agents.research_agent.search_serp", fake_serp)
    monkeypatch.setattr("contentflow.agents.research_agent.search_pubmed", fake_pubmed)
    monkeypatch.setattr("contentflow.agents.research_agent.extract_keywords_from_serp", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "contentflow.agents.research_agent.load_project_context",
        lambda project_id: ProjectContext(project_id=project_id, slug="tech", name="Tech", domain_profile="tech", compliance_profile="general"),
    )

    report = await run_research_agent(
        article_title="SaaS SEO 指南",
        search_keywords=["SaaS SEO"],
        project_id=1,
        use_pubmed=None,
    )

    assert report.pubmed_results == []


@pytest.mark.asyncio
async def test_run_research_agent_uses_project_policy_to_enable_pubmed(monkeypatch):
    calls: list[str] = []

    async def fake_serp(*args, **kwargs):
        return SerpAnalysis(query="骨刺怎麼辦", people_also_ask=[], top_results=[])

    async def fake_pubmed(query, max_results=10):
        calls.append(query)
        return PubMedSearchResult(
            query=query,
            articles=[PubMedArticle(pmid="1", title="study", abstract="abstract")],
            total_found=1,
        )

    monkeypatch.setattr("contentflow.agents.research_agent.search_serp", fake_serp)
    monkeypatch.setattr("contentflow.agents.research_agent.search_pubmed", fake_pubmed)
    monkeypatch.setattr("contentflow.agents.research_agent.extract_keywords_from_serp", lambda *args, **kwargs: [])
    monkeypatch.setattr("contentflow.agents.research_agent._translate_keywords_for_pubmed", lambda items: items)
    monkeypatch.setattr(
        "contentflow.agents.research_agent.load_project_context",
        lambda project_id: ProjectContext(project_id=project_id, slug="health", name="Health", domain_profile="health", compliance_profile="ymyl_medical"),
    )

    report = await run_research_agent(
        article_title="骨刺怎麼辦",
        search_keywords=["骨刺怎麼辦"],
        project_id=2,
        use_pubmed=None,
    )

    assert len(calls) == 1
    assert len(report.pubmed_results) == 1