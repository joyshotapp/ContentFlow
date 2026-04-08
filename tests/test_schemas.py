"""測試 Pydantic schemas"""

from contentflow.models import (
    ArticleTask,
    ArticleStatus,
    ResearchReport,
    PubMedArticle,
)


def test_article_task_defaults():
    task = ArticleTask(task_id="t001", title="刺五加的骨關節炎研究")
    assert task.status == ArticleStatus.PENDING
    assert task.keywords == []
    assert task.target_word_count == 3000


def test_research_report_creation():
    report = ResearchReport(article_title="測試文章")
    assert report.article_title == "測試文章"
    assert report.pubmed_results == []
    assert report.paa_questions == []


def test_pubmed_article_url():
    article = PubMedArticle(
        pmid="12345678",
        title="Test Title",
        abstract="Test abstract",
    )
    assert "12345678" in article.url
