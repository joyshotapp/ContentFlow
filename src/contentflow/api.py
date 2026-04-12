"""ContentFlow FastAPI 路由層（CF-01-01 ~ CF-01-06, CF-01-15~17）

端點：
  POST /api/v1/articles/generate          觸發 pipeline，回傳 task_id
  GET  /api/v1/articles/{id}/status       查詢狀態
  GET  /api/v1/articles/{id}/draft        取回草稿 + SEO score + factcheck
  POST /api/v1/articles/{id}/publish      推送到指定平台
  POST /api/v1/articles/{id}/performance  寫入 GSC/GA4 數據
  POST /api/v1/articles/{id}/review-feedback  人工審閱 diff → KnowledgeEntry
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.orm import Session

from contentflow.config import settings
from contentflow.db import get_session, init_db
from contentflow.models import ArticleStatus, ArticleTask
from contentflow.models.database import Article, KnowledgeEntry, SEORanking
from contentflow.publishers.forgebase import ForgeBasePublisher
from contentflow.publishers.wordpress import WordPressPublisher

# ─────────────────────────────────────────────────────────────
# App init
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="ContentFlow API",
    version="1.0.0",
    description="SEO 文章自動化 AI Agent — REST API",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Admin Dashboard ──────────────────────────────────────────
from contentflow.admin.app import admin_app  # noqa: E402
app.mount("/admin", admin_app)

# ── Reference Site（SEO 閉環驗證前端） ─────────────────────────
from contentflow.site.app import site_app  # noqa: E402
app.mount("/site", site_app)


@app.on_event("startup")
async def _startup():
    init_db()
    from contentflow.scheduler import schedule_all_jobs
    schedule_all_jobs()
    logger.info("ContentFlow API 啟動完成")


@app.on_event("shutdown")
async def _shutdown():
    from contentflow.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler 已停止")


# ─────────────────────────────────────────────────────────────
# CF-01-02: API Key 認證中介層
# ─────────────────────────────────────────────────────────────

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(_api_key_header)) -> str:
    if not settings.api_secret_key:
        raise HTTPException(status_code=500, detail="API_SECRET_KEY 尚未設定")
    if api_key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key


AuthDep = Annotated[str, Depends(verify_api_key)]
DBDep = Annotated[Session, Depends(get_session)]

# ─────────────────────────────────────────────────────────────
# 通知 helper（CF-01-16）
# ─────────────────────────────────────────────────────────────

async def _send_slack(message: str) -> None:
    """向 Slack Webhook 發送通知（設定了 SLACK_WEBHOOK_URL 才發）。"""
    if not settings.slack_webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(settings.slack_webhook_url, json={"text": message})
    except Exception as exc:
        logger.warning(f"[Notify] Slack 發送失敗：{exc}")


async def _notify_draft_ready(article_id: int, title: str) -> None:
    """草稿就緒通知（Slack + log）。"""
    msg = f"✅ ContentFlow｜草稿就緒\n文章：{title}\n審閱連結：/api/v1/articles/{article_id}/draft"
    logger.info(f"[Notify] {msg}")
    await _send_slack(msg)


# ─────────────────────────────────────────────────────────────
# 背景 Pipeline 執行（CF-01-03）
# ─────────────────────────────────────────────────────────────

async def _run_pipeline(article_id: int, keyword: str, project_id: int) -> None:
    """在背景執行 orchestrator，完成後回寫 DB。"""
    from contentflow.agents.orchestrator import run_orchestrator

    with next(get_session()) as session:
        article = session.get(Article, article_id)
        if not article:
            logger.error(f"[Pipeline] article_id={article_id} 不存在")
            return
        article.status = ArticleStatus.RESEARCHING
        session.commit()

    task = ArticleTask(
        task_id=str(uuid.uuid4()),
        title=article.title if article else keyword,
        keywords=[keyword],
    )

    try:
        result = await run_orchestrator(task, project_id=project_id)

        with next(get_session()) as session:
            article = session.get(Article, article_id)
            if not article:
                return
            draft = result.draft
            if draft:
                article.draft_content = draft.content_markdown
                article.meta_title = draft.meta_title
                article.meta_description = draft.meta_description
                article.slug = draft.slug
                article.faq_schema_json = draft.faq_schema_json
                article.article_schema_json = draft.article_schema_json
                article.seo_score = draft.seo_score or None
            article.status = result.status
            session.commit()

        await _notify_draft_ready(article_id, task.title)

    except Exception as exc:
        logger.error(f"[Pipeline] article_id={article_id} 失敗：{exc}")
        with next(get_session()) as session:
            article = session.get(Article, article_id)
            if article:
                article.status = ArticleStatus.FAILED
                session.commit()


# ─────────────────────────────────────────────────────────────
# Request / Response schemas
# ─────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    project_id: int
    keyword: str
    title: str | None = None          # 不填則以 keyword 作為 title


class GenerateResponse(BaseModel):
    article_id: int
    task_id: str
    status: str


class StatusResponse(BaseModel):
    article_id: int
    status: str
    seo_score: int | None
    updated_at: datetime | None


class DraftResponse(BaseModel):
    article_id: int
    title: str
    meta_title: str
    meta_description: str
    content_markdown: str
    slug: str
    seo_score: int | None
    status: str


class PublishRequest(BaseModel):
    platform: Literal["wordpress", "forgebase"]
    seo_plugin: Literal["yoast", "rankmath", "aioseo"] = "yoast"  # WordPress only


class PublishResponse(BaseModel):
    article_id: int
    platform: str
    post_id: str | None
    publish_url: str | None
    success: bool
    error: str | None = None


class PerformanceRequest(BaseModel):
    keyword: str
    position: float | None = None
    impressions: int | None = None
    clicks: int | None = None
    ctr: float | None = None
    tracked_date: str | None = None   # ISO 8601 date string


class ReviewFeedbackRequest(BaseModel):
    diff_summary: str
    category: str = "human_edit_pattern"


# ─────────────────────────────────────────────────────────────
# CF-01-03: POST /api/v1/articles/generate
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/articles/generate", response_model=GenerateResponse)
async def generate_article(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    _: AuthDep,
    db: DBDep,
):
    """觸發完整 Pipeline（Research → Write → SEO QA → FactCheck）。

    立即回傳 article_id，pipeline 在背景執行。
    """
    title = body.title or body.keyword
    article = Article(
        project_id=body.project_id,
        primary_keyword=body.keyword,
        title=title,
        status=ArticleStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(article)
    db.flush()  # 取得 article.id

    task_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_pipeline,
        article_id=article.id,
        keyword=body.keyword,
        project_id=body.project_id,
    )

    logger.info(f"[API] generate article_id={article.id} keyword={body.keyword!r}")
    return GenerateResponse(
        article_id=article.id,
        task_id=task_id,
        status=ArticleStatus.PENDING,
    )


# ─────────────────────────────────────────────────────────────
# CF-01-04: GET /api/v1/articles/{id}/status
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/articles/{article_id}/status", response_model=StatusResponse)
async def get_status(article_id: int, _: AuthDep, db: DBDep):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {article_id} 不存在")
    return StatusResponse(
        article_id=article.id,
        status=article.status,
        seo_score=article.seo_score,
        updated_at=article.updated_at,
    )


# ─────────────────────────────────────────────────────────────
# CF-01-05: GET /api/v1/articles/{id}/draft
# ─────────────────────────────────────────────────────────────

@app.get("/api/v1/articles/{article_id}/draft", response_model=DraftResponse)
async def get_draft(article_id: int, _: AuthDep, db: DBDep):
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {article_id} 不存在")
    if not article.draft_content:
        raise HTTPException(status_code=422, detail="草稿尚未產生")
    return DraftResponse(
        article_id=article.id,
        title=article.title,
        meta_title=article.meta_title,
        meta_description=article.meta_description,
        content_markdown=article.draft_content,
        slug=article.slug,
        seo_score=article.seo_score,
        status=article.status,
    )


# ─────────────────────────────────────────────────────────────
# CF-01-06: POST /api/v1/articles/{id}/publish
# CF-01-15: 回寫 publish_url
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/articles/{article_id}/publish", response_model=PublishResponse)
async def publish_article(
    article_id: int,
    body: PublishRequest,
    _: AuthDep,
    db: DBDep,
):
    """推送草稿到指定平台（draft 狀態），人工於平台端確認後 publish。"""
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {article_id} 不存在")
    if not article.draft_content:
        raise HTTPException(status_code=422, detail="草稿尚未產生，無法發布")

    from contentflow.models.schemas import ArticleDraft

    draft = ArticleDraft(
        title=article.title,
        meta_title=article.meta_title,
        meta_description=article.meta_description,
        content_markdown=article.draft_content,
        slug=article.slug,
        faq_schema_json=article.faq_schema_json,
        article_schema_json=article.article_schema_json,
        word_count=len(article.draft_content.split()),
    )

    if body.platform == "wordpress":
        publisher = WordPressPublisher(seo_plugin=body.seo_plugin)
    else:
        publisher = ForgeBasePublisher()

    result = await publisher.publish_draft(draft)

    # CF-01-15: 回寫 publish_url 到 Article
    if result.success and result.publish_url:
        article.publish_url = result.publish_url
        article.status = ArticleStatus.PUBLISHED
        article.publish_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return PublishResponse(
        article_id=article_id,
        platform=result.platform,
        post_id=result.post_id,
        publish_url=result.publish_url,
        success=result.success,
        error=result.error,
    )


# ─────────────────────────────────────────────────────────────
# POST /api/v1/articles/{id}/performance  （GSC/GA4 數據回寫）
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/articles/{article_id}/performance", status_code=204)
async def record_performance(
    article_id: int,
    body: PerformanceRequest,
    _: AuthDep,
    db: DBDep,
):
    """接收 GSC/GA4 數據，寫入 SEORanking 表（供 LEARN 層使用）。"""
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {article_id} 不存在")

    from datetime import date

    tracked = None
    if body.tracked_date:
        try:
            tracked = date.fromisoformat(body.tracked_date)
        except ValueError:
            pass

    ranking = SEORanking(
        project_id=article.project_id,
        keyword=body.keyword,
        position=body.position,
        landing_page=article.publish_url or "",
        tracked_date=tracked,
        impressions=body.impressions,
        clicks=body.clicks,
        ctr=body.ctr,
    )
    db.add(ranking)


# ─────────────────────────────────────────────────────────────
# CF-01-17: POST /api/v1/articles/{id}/review-feedback
# ─────────────────────────────────────────────────────────────

@app.post("/api/v1/articles/{article_id}/review-feedback", status_code=204)
async def submit_review_feedback(
    article_id: int,
    body: ReviewFeedbackRequest,
    _: AuthDep,
    db: DBDep,
):
    """人工審閱後的修改 diff → 寫入 KnowledgeEntry（unverified）。

    供 LEARN 層後續統計與驗證，最終晉升為 verified / universal。
    """
    article = db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail=f"Article {article_id} 不存在")

    entry = KnowledgeEntry(
        project_id=article.project_id,
        category=body.category,
        pattern=body.diff_summary,
        evidence_count=1,
        confidence_level="unverified",
        metadata_json=f'{{"article_id": {article_id}}}',
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(entry)
    logger.info(f"[ReviewFeedback] article_id={article_id} 新增 KnowledgeEntry category={body.category!r}")
