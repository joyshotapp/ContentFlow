"""測試 Orchestrator 與下游 agents 的介面契約。"""

from __future__ import annotations

import pytest

from contentflow.agents.orchestrator import run_orchestrator
from contentflow.models import (
    ArticleDraft,
    ArticleStatus,
    ArticleTask,
    PubMedSearchResult,
    ResearchReport,
)
from contentflow.project_context import ProjectContext


@pytest.mark.asyncio
async def test_orchestrator_uses_current_agent_signatures(monkeypatch):
    captured = {}

    ctx = ProjectContext(
        project_id=7,
        slug="tech",
        name="Tech",
        industry="科技",
    )

    class FakeStrategyReport:
        def to_strategy_context(self):
            return {
                "search_intent": "資訊性",
                "target_audience": "開發者",
                "writing_architecture": "寫深 + 思維流程",
                "faq_questions": "1.什麼是 asyncio",
            }

    async def fake_research_agent(**kwargs):
        captured["research"] = kwargs
        return ResearchReport(
            article_title=kwargs["article_title"],
            keywords=kwargs["search_keywords"],
            pubmed_results=[PubMedSearchResult(query="x", total_found=0)],
            paa_questions=["什麼是 asyncio？"],
        )

    async def fake_strategy_agent(**kwargs):
        captured["strategy"] = kwargs
        return FakeStrategyReport()

    async def fake_writing_agent(**kwargs):
        captured["writing"] = kwargs
        return ArticleDraft(
            title="測試文章",
            content_markdown="## 段落\n內容",
            meta_title="測試文章",
            meta_description="測試描述",
            word_count=1200,
        )

    async def fake_seo_qa_agent(**kwargs):
        captured["seo_qa"] = kwargs
        return kwargs["draft"]

    def fake_seo_check_agent(**kwargs):
        captured["seo_check"] = kwargs
        return {"score": 90, "passed_count": 9, "total_count": 10, "checks": []}

    async def fake_factcheck_agent(**kwargs):
        captured["factcheck"] = kwargs
        draft = kwargs["draft"]
        draft.status = ArticleStatus.APPROVED
        return draft

    monkeypatch.setattr("contentflow.agents.orchestrator.load_project_context", lambda **_: ctx)
    monkeypatch.setattr("contentflow.agents.orchestrator.project_uses_pubmed", lambda _: False)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_research_agent", fake_research_agent)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_strategy_agent", fake_strategy_agent)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_writing_agent", fake_writing_agent)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_seo_qa_agent", fake_seo_qa_agent)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_seo_check_agent", fake_seo_check_agent)
    monkeypatch.setattr("contentflow.agents.orchestrator.run_factcheck_agent", fake_factcheck_agent)

    task = ArticleTask(task_id="t-1", title="Python asyncio", keywords=["Python asyncio", "await"])
    result = await run_orchestrator(task, project_slug="tech", use_pubmed=None)

    assert result.status == ArticleStatus.APPROVED
    assert captured["research"]["use_pubmed"] is False
    assert captured["strategy"]["serp"] is None
    assert captured["strategy"]["project_id"] == 7
    assert captured["writing"]["report"].article_title == "Python asyncio"
    assert captured["writing"]["project_id"] == 7
    assert captured["seo_qa"]["report"].article_title == "Python asyncio"
    assert captured["seo_check"]["draft"].title == "測試文章"
    assert captured["factcheck"]["article_type"] == "educational"