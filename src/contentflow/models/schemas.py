"""資料模型（Pydantic schemas）"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── 狀態枚舉 ─────────────────────────────────────────────────

class ArticleStatus(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    WRITING = "writing"
    FACT_CHECKING = "fact_checking"
    GENERATING_IMAGES = "generating_images"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    PUBLISHED = "published"
    FAILED = "failed"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── PubMed 相關 ───────────────────────────────────────────────

class PubMedArticle(BaseModel):
    pmid: str
    title: str
    abstract: str
    authors: list[str] = Field(default_factory=list)
    journal: str = ""
    pub_year: Optional[int] = None
    study_type: str = ""          # 動物實驗 / 人體試驗 / 系統性綜述 等
    citation_count: int = 0
    url: str = ""


class PubMedSearchResult(BaseModel):
    query: str
    articles: list[PubMedArticle] = Field(default_factory=list)
    total_found: int = 0


# ── SERP 相關 ─────────────────────────────────────────────────

class SerpResult(BaseModel):
    position: int
    title: str
    url: str
    snippet: str = ""
    headings: list[str] = Field(default_factory=list)


class PeopleAlsoAsk(BaseModel):
    question: str
    answer: str = ""


class SerpAnalysis(BaseModel):
    query: str
    top_results: list[SerpResult] = Field(default_factory=list)
    people_also_ask: list[PeopleAlsoAsk] = Field(default_factory=list)
    related_searches: list[str] = Field(default_factory=list)


# ── 研究報告 ──────────────────────────────────────────────────

class ResearchReport(BaseModel):
    article_title: str
    keywords: list[str] = Field(default_factory=list)
    pubmed_results: list[PubMedSearchResult] = Field(default_factory=list)
    serp_analysis: Optional[SerpAnalysis] = None
    suggested_keywords: list[str] = Field(default_factory=list)
    paa_questions: list[str] = Field(default_factory=list)
    competitor_headings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 文章相關 ──────────────────────────────────────────────────

class ArticleOutline(BaseModel):
    title: str
    meta_description: str = ""
    sections: list[dict] = Field(default_factory=list)   # [{h2, h3s, keywords}]


class FactCheckItem(BaseModel):
    claim: str
    paragraph_index: int
    confidence: ConfidenceLevel
    supporting_evidence: list[str] = Field(default_factory=list)
    needs_review: bool = False
    reviewer_note: str = ""


class ArticleDraft(BaseModel):
    title: str
    meta_title: str = ""
    meta_description: str = ""
    content_markdown: str = ""
    word_count: int = 0
    fact_check_items: list[FactCheckItem] = Field(default_factory=list)
    image_prompts: list[str] = Field(default_factory=list)
    status: ArticleStatus = ArticleStatus.WRITING
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── 任務 ──────────────────────────────────────────────────────

class ArticleTask(BaseModel):
    task_id: str
    title: str
    keywords: list[str] = Field(default_factory=list)
    target_word_count: int = 3000
    status: ArticleStatus = ArticleStatus.PENDING
    research_report: Optional[ResearchReport] = None
    draft: Optional[ArticleDraft] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
