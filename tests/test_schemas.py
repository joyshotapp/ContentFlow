"""測試 Pydantic schemas（覆蓋所有 model）"""

from contentflow.models import (
    ArticleTask,
    ArticleStatus,
    ConfidenceLevel,
    ResearchReport,
    PubMedArticle,
    PubMedSearchResult,
    SerpResult,
    PeopleAlsoAsk,
    SerpAnalysis,
    ArticleOutline,
    FactCheckItem,
    ArticleDraft,
)


# ── 原有測試 ──────────────────────────────────────────────────

def test_article_task_defaults():
    task = ArticleTask(task_id="t001", title="刺五加的骨關節炎研究")
    assert task.status == ArticleStatus.PENDING
    assert task.keywords == []
    assert task.target_word_count == 1200


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


# ── 新增：SERP 相關 ──────────────────────────────────────────

def test_serp_result_minimal():
    r = SerpResult(position=1, title="Top Result", url="https://example.com")
    assert r.snippet == ""
    assert r.headings == []


def test_serp_analysis_with_paa():
    paa = PeopleAlsoAsk(question="為什麼膝蓋會痛？", answer="常見原因包括...")
    sa = SerpAnalysis(query="膝蓋痛", people_also_ask=[paa])
    assert len(sa.people_also_ask) == 1
    assert sa.related_searches == []


# ── 新增：FactCheck 相關 ─────────────────────────────────────

def test_factcheck_item_defaults():
    item = FactCheckItem(
        claim="龜鹿二仙膠可以補腎",
        paragraph_index=0,
        confidence=ConfidenceLevel.MEDIUM,
    )
    assert item.needs_review is False
    assert item.supporting_evidence == []


def test_factcheck_item_flagged():
    item = FactCheckItem(
        claim="可以治療癌症",
        paragraph_index=2,
        confidence=ConfidenceLevel.LOW,
        needs_review=True,
        reviewer_note="醫療效能宣稱",
    )
    assert item.needs_review is True


# ── 新增：ArticleDraft 相關 ──────────────────────────────────

def test_article_draft_defaults():
    draft = ArticleDraft(title="測試草稿")
    assert draft.status == ArticleStatus.WRITING
    assert draft.word_count == 0
    assert draft.fact_check_items == []
    assert draft.image_prompts == []


def test_article_draft_with_factcheck():
    items = [
        FactCheckItem(claim="A", paragraph_index=0, confidence=ConfidenceLevel.HIGH),
        FactCheckItem(claim="B", paragraph_index=1, confidence=ConfidenceLevel.LOW, needs_review=True),
    ]
    draft = ArticleDraft(title="完整草稿", fact_check_items=items, word_count=2000)
    assert len(draft.fact_check_items) == 2
    flagged = [i for i in draft.fact_check_items if i.needs_review]
    assert len(flagged) == 1


# ── 新增：ArticleOutline ─────────────────────────────────────

def test_article_outline():
    outline = ArticleOutline(
        title="SEO 文章大綱",
        meta_description="測試 meta",
        sections=[{"h2": "段落一", "h3s": ["子段落"], "keywords": ["kw"]}],
    )
    assert len(outline.sections) == 1


# ── 新增：PubMedSearchResult ─────────────────────────────────

def test_pubmed_search_result():
    r = PubMedSearchResult(query="test", total_found=10)
    assert r.articles == []


# ── 新增：ConfidenceLevel 列舉 ───────────────────────────────

def test_confidence_levels():
    assert ConfidenceLevel.HIGH == "high"
    assert ConfidenceLevel.MEDIUM == "medium"
    assert ConfidenceLevel.LOW == "low"
