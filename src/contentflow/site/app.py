"""ContentFlow Reference Site — 生產級 SEO 閉環驗證前端

完整路由：
  GET /            首頁（Organization + WebSite schema, 最新文章, 分類導覽, 主題叢集）
  GET /blog        文章列表（分頁, 按類型篩選）
  GET /blog/{slug} 文章詳情（TOC, 閱讀時間, 相關文章, FAQ accordion, BreadcrumbList, E-E-A-T）
  GET /category/{article_type} 分類頁（CollectionPage schema）
  GET /topic/{cluster_id}      主題叢集頁（Pillar + Satellite 拓撲）
  GET /about       關於我們（E-E-A-T 信號頁）
  GET /sitemap.xml 完整 sitemap（含分類、叢集頁）
  GET /robots.txt  robots
  GET /feed        RSS 2.0 feed
  GET /health      健康檢查
  404 handler      自訂 404 頁
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape as xml_escape

import markdown as md_module
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from urllib.parse import quote
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from contentflow.build_info import get_build_info
from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import Article, Category, TopicCluster
from contentflow.project_integrations import build_site_url, resolve_site_profile

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

_PUBLISHED = "published"
_CJK_CHARS_PER_MIN = 500
_ARTICLE_TYPE_MAP = {
    "知識": {"label": "知識文章", "desc": "深入淺出的專業知識解析，涵蓋成因、症狀、治療方法與最新研究。"},
    "情境": {"label": "情境指南", "desc": "針對特定情境提供實用建議與解決方案，幫助你在對的時機做對的選擇。"},
    "節慶": {"label": "節慶專題", "desc": "結合時節脈動的主題內容，提供應景的健康與生活資訊。"},
    "product": {"label": "產品深度評析", "desc": "以科學數據為基礎的產品分析，協助你做出更明智的消費決策。"},
}

# ─────────────────────────────────────────────────────────────
# Template engine & Markdown converter
# ─────────────────────────────────────────────────────────────

_BASE_DIR = Path(__file__).parent
_STATIC_DIR = _BASE_DIR / "static"
templates = Jinja2Templates(directory=str(_BASE_DIR / "templates"))

_md = md_module.Markdown(
    extensions=["tables", "fenced_code", "toc", "nl2br", "attr_list"],
    output_format="html",
)


def _read_scheduler_heartbeat(now: datetime | None = None) -> dict:
    if not settings.scheduler_required:
        return {"scheduler": "disabled"}

    now = now or datetime.now(timezone.utc)
    heartbeat_path = Path(settings.scheduler_heartbeat_path)
    if not heartbeat_path.exists():
        return {"scheduler": "missing_heartbeat"}

    try:
        payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        heartbeat_at = datetime.fromisoformat(payload["timestamp"])
        if heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        age_seconds = (now - heartbeat_at).total_seconds()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {"scheduler": f"invalid_heartbeat: {exc}"}

    status = "running" if age_seconds <= settings.scheduler_heartbeat_max_age_seconds else "stale_heartbeat"
    return {
        "scheduler": status,
        "scheduler_last_heartbeat": heartbeat_at.isoformat(),
        "scheduler_heartbeat_age_seconds": round(age_seconds, 1),
        "scheduler_pid": payload.get("pid"),
        "scheduler_reason": payload.get("reason"),
    }


def _to_html(text: str) -> str:
    """Convert Markdown to HTML, stripping the first H1 to avoid duplicate."""
    _md.reset()
    cleaned = re.sub(r"^#\s+.+\n*", "", text.strip(), count=1)
    return _md.convert(cleaned)


def _extract_toc(text: str) -> list[dict]:
    """Extract H2/H3 headings from Markdown for TOC generation."""
    toc = []
    for match in re.finditer(r"^(#{2,3})\s+(.+)$", text, re.MULTILINE):
        level = len(match.group(1))
        title = match.group(2).strip()
        anchor = re.sub(r"[^\w\u4e00-\u9fff\-]", "", title.replace(" ", "-").lower())
        if not anchor:
            anchor = hashlib.md5(title.encode()).hexdigest()[:8]
        toc.append({"level": level, "text": title, "id": anchor})
    return toc


def _reading_time(text: str) -> int:
    char_count = len(re.sub(r"\s+", "", text or ""))
    return max(1, math.ceil(char_count / _CJK_CHARS_PER_MIN))


def _parse_json_safe(raw: str) -> dict | list | None:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _word_count(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))


# ─────────────────────────────────────────────────────────────
# DB dependency
# ─────────────────────────────────────────────────────────────

def _get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DBDep = Annotated[Session, Depends(_get_db)]


# ─────────────────────────────────────────────────────────────
# URL & template context helpers
# ─────────────────────────────────────────────────────────────
def _site_profile(db: Session | None = None) -> dict:
    return resolve_site_profile(db=db).as_dict()


def _site_url(path: str = "", site_profile: dict | None = None) -> str:
    profile = site_profile or _site_profile()
    base = str(profile["site_url"]).rstrip("/")
    return f"{base}{path}" if path else base


def _common_ctx(request: Request, site_profile: dict | None = None) -> dict:
    profile = site_profile or _site_profile()
    base = _site_url(site_profile=profile)
    return {
        "site_url": base,
        "site_name": profile["site_name"],
        "site_description": profile["site_description"],
        "site_contact_email": profile["site_contact_email"],
        "ga4_id": settings.ga4_measurement_id,
        "article_type_map": _ARTICLE_TYPE_MAP,
        "topic_cluster_url": lambda cluster: f"{base}{_topic_cluster_path(cluster)}",
    }


def _ensure_managed_site_enabled() -> None:
    if not settings.managed_site_enabled:
        raise HTTPException(status_code=404, detail="Managed site disabled")


def _published_q(db: Session, site_profile: dict | None = None):
    query = db.query(Article).filter(Article.status == _PUBLISHED, Article.slug != "")
    project_id = site_profile.get("project_id") if site_profile else None
    if project_id is not None:
        query = query.filter(Article.project_id == project_id)
    return query


def _topic_clusters_q(db: Session, site_profile: dict | None = None):
    query = db.query(TopicCluster)
    project_id = site_profile.get("project_id") if site_profile else None
    if project_id is not None:
        query = query.filter(TopicCluster.project_id == project_id)
    return query


# ─────────────────────────────────────────────────────────────
# Related articles
# ─────────────────────────────────────────────────────────────

def _get_related_articles(db: Session, article: Article, limit: int = 4, site_profile: dict | None = None) -> list[Article]:
    from contentflow.models.database import ClusterMember

    related_ids: set[int] = set()
    related: list[Article] = []

    # 1) Same Topic Cluster
    my_clusters = (
        db.query(ClusterMember.cluster_id)
        .filter(ClusterMember.article_id == article.id)
        .subquery()
    )
    cluster_articles = (
        db.query(Article)
        .join(ClusterMember, ClusterMember.article_id == Article.id)
        .filter(
            ClusterMember.cluster_id.in_(db.query(my_clusters.c.cluster_id)),
            Article.id != article.id,
            Article.status == _PUBLISHED,
            Article.slug != "",
        )
        .limit(limit)
        .all()
    )
    project_id = site_profile.get("project_id") if site_profile else None
    if project_id is not None:
        cluster_articles = [a for a in cluster_articles if a.project_id == project_id]
    for a in cluster_articles:
        if a.id not in related_ids:
            related.append(a)
            related_ids.add(a.id)

    # 2) Same article_type
    if len(related) < limit and article.article_type:
        type_articles = (
            _published_q(db, site_profile)
            .filter(Article.article_type == article.article_type, Article.id != article.id)
            .filter(Article.id.notin_(related_ids))
            .order_by(desc(Article.updated_at))
            .limit(limit - len(related))
            .all()
        )
        for a in type_articles:
            related.append(a)
            related_ids.add(a.id)

    # 3) Fallback: recent
    if len(related) < limit:
        recent = (
            _published_q(db, site_profile)
            .filter(Article.id != article.id, Article.id.notin_(related_ids))
            .order_by(desc(Article.updated_at))
            .limit(limit - len(related))
            .all()
        )
        related.extend(recent)

    return related[:limit]


# ─────────────────────────────────────────────────────────────
# Sub-app
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def _site_lifespan(_: FastAPI):
    """初始化 DB + 排程（只在第一個 worker 啟動排程）。"""
    from contentflow.db import init_db
    from contentflow.scheduler import scheduler, schedule_all_jobs

    init_db()
    # site service 可選擇不持有 scheduler，避免多 worker 下的假健康狀態。
    if settings.scheduler_enabled and not scheduler.running:
        schedule_all_jobs()
    yield
    from contentflow.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


site_app = FastAPI(
    title="ContentFlow Reference Site",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=_site_lifespan,
)
site_app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _head_empty_response(response) -> Response:
    """HEAD 回應須無 body，且不可保留原 GET 的 Content-Length（否則 uvicorn 500）。"""
    headers = {
        k: v
        for k, v in response.headers.items()
        if k.lower() not in ("content-length", "content-type", "transfer-encoding")
    }
    return Response(status_code=response.status_code, headers=headers)


@site_app.middleware("http")
async def _support_head_requests(request: Request, call_next):
    """P1：HEAD 與 GET 共用路由，避免監控工具收到 405。"""
    if request.method != "HEAD":
        return await call_next(request)
    request.scope["method"] = "GET"
    response = await call_next(request)
    if isinstance(response, RedirectResponse):
        return _head_empty_response(response)
    if hasattr(response, "body_iterator"):
        return _head_empty_response(response)
    return _head_empty_response(response)


def _topic_cluster_path(cluster) -> str:
    slug = (getattr(cluster, "slug", None) or "").strip()
    return f"/topic/{quote(slug, safe='')}" if slug else f"/topic/{cluster.id}"


def _resolve_topic_cluster(db, site_profile: dict, cluster_ref: str):
    query = _topic_clusters_q(db, site_profile)
    if cluster_ref.isdigit():
        cluster = query.filter(TopicCluster.id == int(cluster_ref)).first()
        if cluster and (cluster.slug or "").strip():
            return cluster, RedirectResponse(
                url=_topic_cluster_path(cluster),
                status_code=301,
            )
        return cluster, None
    return query.filter(TopicCluster.slug == cluster_ref).first(), None


@site_app.get("/health")
async def health():
    """健康檢查：驗證 DB 連線 + 排程器運行狀態。"""
    checks: dict = {"service": "reference-site", **get_build_info()}
    checks["platform_mode"] = settings.platform_mode
    checks["managed_site_enabled"] = settings.managed_site_enabled

    # DB 連線
    try:
        db = SessionLocal()
        db.execute(func.now())
        db.close()
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    checks.update(_read_scheduler_heartbeat())

    scheduler_ok = checks["scheduler"] in {"running", "disabled"}
    ok = checks["db"] == "ok" and scheduler_ok
    checks["status"] = "ok" if ok else "degraded"

    status_code = 200 if ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(content=checks, status_code=status_code)


@site_app.get("/version")
async def version():
    return get_build_info()


# ─── Homepage ─────────────────────────────────────────────────

@site_app.get("/", response_class=HTMLResponse)
async def homepage(request: Request, db: DBDep):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    latest = _published_q(db, site_profile).order_by(desc(Article.updated_at)).limit(6).all()
    type_query = db.query(Article.article_type, func.count(Article.id)).filter(Article.status == _PUBLISHED, Article.slug != "")
    if site_profile["project_id"] is not None:
        type_query = type_query.filter(Article.project_id == site_profile["project_id"])
    type_counts = dict(type_query.group_by(Article.article_type).all())
    clusters = _topic_clusters_q(db, site_profile).order_by(desc(TopicCluster.updated_at)).limit(6).all()
    total_articles = _published_q(db, site_profile).count()

    org_schema = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": site_profile["site_name"], "url": _site_url(site_profile=site_profile),
        "description": site_profile["site_description"],
    }
    website_schema = {
        "@context": "https://schema.org", "@type": "WebSite",
        "name": site_profile["site_name"], "url": _site_url(site_profile=site_profile), "inLanguage": "zh-TW",
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{_site_url(site_profile=site_profile)}/blog?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }

    return templates.TemplateResponse(request, "index.html", {
        **_common_ctx(request, site_profile),
        "articles": latest, "type_counts": type_counts,
        "clusters": clusters, "total_articles": total_articles,
        "org_schema": org_schema, "website_schema": website_schema,
    })


# ─── Blog listing ─────────────────────────────────────────────

@site_app.get("/blog", response_class=HTMLResponse)
async def blog_list(request: Request, db: DBDep, page: int = 1, type: str | None = None, q: str | None = None):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    per_page = 12
    offset = (page - 1) * per_page
    query = _published_q(db, site_profile)

    if type and type in _ARTICLE_TYPE_MAP:
        query = query.filter(Article.article_type == type)
    if q:
        pattern = f"%{q}%"
        query = query.filter(
            (Article.title.ilike(pattern)) | (Article.meta_description.ilike(pattern))
            | (Article.primary_keyword.ilike(pattern))
        )

    total = query.count()
    articles = query.order_by(desc(Article.updated_at)).offset(offset).limit(per_page).all()

    breadcrumb = [{"name": "首頁", "url": _site_url("/", site_profile)}]
    if type and type in _ARTICLE_TYPE_MAP:
        breadcrumb.append({"name": "文章", "url": _site_url("/blog", site_profile)})
        breadcrumb.append({"name": _ARTICLE_TYPE_MAP[type]["label"], "url": None})
    else:
        breadcrumb.append({"name": "文章", "url": None})

    return templates.TemplateResponse(request, "blog_list.html", {
        **_common_ctx(request, site_profile),
        "articles": articles, "page": page, "total": total, "per_page": per_page,
        "has_prev": page > 1, "has_next": (offset + per_page) < total,
        "total_pages": max(1, math.ceil(total / per_page)),
        "current_type": type, "search_q": q or "",
        "breadcrumb": breadcrumb, "reading_time": _reading_time,
    })


# ─── Article detail ───────────────────────────────────────────

@site_app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str, request: Request, db: DBDep):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    article = _published_q(db, site_profile).filter(Article.slug == slug).first()
    if not article:
        # 若反查 old_slugs（曾用過的 slug），符合則 301 永久轉址
        import json as _json_r
        from fastapi.responses import RedirectResponse
        # 使用帶引號的 LIKE 避免 substring false-positive（如 slug='c' 誤中 'cervical-c'）
        # 跳脫 LIKE 萬用字元（% _ \）以防 slug 含底線時誤中其他記錄
        _escaped = slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        candidate = (
            _published_q(db, site_profile)
            .filter(Article.old_slugs.like(f'%"{_escaped}"%', escape="\\"))
            .first()
        )
        if candidate and candidate.slug:
            old_slugs_list = _json_r.loads(candidate.old_slugs or "[]")
            if slug in old_slugs_list:
                return RedirectResponse(url=f"/blog/{candidate.slug}", status_code=301)
        raise HTTPException(status_code=404, detail="Article not found")

    content_html = _to_html(article.draft_content)
    toc = _extract_toc(article.draft_content or "")
    read_min = _reading_time(article.draft_content or "")
    word_count = _word_count(article.draft_content or "")
    related = _get_related_articles(db, article, site_profile=site_profile)
    canonical_url = _site_url(f"/blog/{slug}", site_profile)

    faq_schema = _parse_json_safe(article.faq_schema_json)
    from contentflow.utils.article_schema import sync_article_schema_headline

    synced_schema_json = sync_article_schema_headline(
        article.article_schema_json or "",
        meta_title=article.meta_title or "",
        title=article.title or "",
        meta_description=article.meta_description or "",
    )
    article_schema = _parse_json_safe(synced_schema_json)

    if article_schema and isinstance(article_schema, dict):
        article_schema.setdefault("url", canonical_url)
        article_schema.setdefault("mainEntityOfPage", {"@type": "WebPage", "@id": canonical_url})
        if article.updated_at:
            article_schema["dateModified"] = article.updated_at.strftime("%Y-%m-%d")
        if article.created_at:
            article_schema.setdefault("datePublished", article.created_at.strftime("%Y-%m-%d"))
        article_schema.setdefault("wordCount", word_count)
        article_schema.setdefault("inLanguage", "zh-TW")
        article_schema.setdefault("publisher", {
            "@type": "Organization", "name": site_profile["site_name"], "url": _site_url(site_profile=site_profile),
        })
        article_schema.setdefault("author", {
            "@type": "Organization", "name": site_profile["site_name"], "url": _site_url("/about", site_profile),
        })

    breadcrumb_items = [
        {"name": "首頁", "url": _site_url("/", site_profile)},
        {"name": "文章", "url": _site_url("/blog", site_profile)},
    ]
    if article.article_type and article.article_type in _ARTICLE_TYPE_MAP:
        breadcrumb_items.append({
            "name": _ARTICLE_TYPE_MAP[article.article_type]["label"],
            "url": _site_url(f"/blog?type={article.article_type}", site_profile),
        })
    breadcrumb_items.append({"name": article.meta_title or article.title, "url": None})

    breadcrumb_schema = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": item["name"],
             **({"item": item["url"]} if item["url"] else {})}
            for i, item in enumerate(breadcrumb_items)
        ],
    }

    # Research sources
    research = _parse_json_safe(article.research_report_json)
    sources: list[dict] = []
    if research and isinstance(research, dict):
        for pq in research.get("pubmed_results", []):
            for a in pq.get("articles", [])[:5]:
                sources.append({
                    "title": a.get("title", ""), "journal": a.get("journal", ""),
                    "year": a.get("pub_year", ""), "url": a.get("url", ""),
                    "authors": ", ".join(a.get("authors", [])[:3]),
                })

    # FAQ items
    faq_items: list[dict] = []
    if faq_schema and isinstance(faq_schema, dict):
        for entity in faq_schema.get("mainEntity", []):
            faq_items.append({
                "question": entity.get("name", ""),
                "answer": entity.get("acceptedAnswer", {}).get("text", ""),
            })

    # Prev / Next
    prev_article = _published_q(db).filter(Article.id < article.id).order_by(desc(Article.id)).first()
    next_article = _published_q(db).filter(Article.id > article.id).order_by(Article.id).first()

    # Secondary keywords
    secondary_kws: list[str] = []
    if article.secondary_keywords:
        if isinstance(article.secondary_keywords, list):
            secondary_kws = article.secondary_keywords
        elif isinstance(article.secondary_keywords, str):
            try:
                secondary_kws = json.loads(article.secondary_keywords)
            except (json.JSONDecodeError, ValueError):
                secondary_kws = [k.strip() for k in article.secondary_keywords.split(",") if k.strip()]

    return templates.TemplateResponse(request, "blog_post.html", {
        **_common_ctx(request, site_profile),
        "article": article, "html_content": content_html,
        "toc": toc, "reading_time": read_min, "word_count": word_count,
        "related": related, "canonical_url": canonical_url,
        "faq_schema": faq_schema, "article_schema": article_schema,
        "breadcrumb_schema": breadcrumb_schema, "breadcrumb": breadcrumb_items,
        "research_sources": sources, "faq_items": faq_items,
        "prev_article": prev_article, "next_article": next_article,
        "secondary_kws": secondary_kws,
    })


# ─── Category page ────────────────────────────────────────────

@site_app.get("/category/{article_type}", response_class=HTMLResponse)
async def category_page(article_type: str, request: Request, db: DBDep, page: int = 1):
    _ensure_managed_site_enabled()
    if article_type not in _ARTICLE_TYPE_MAP:
        raise HTTPException(status_code=404, detail="Category not found")

    site_profile = _site_profile(db)
    meta = _ARTICLE_TYPE_MAP[article_type]
    per_page = 12
    offset = (page - 1) * per_page
    query = _published_q(db, site_profile).filter(Article.article_type == article_type)
    total = query.count()
    articles = query.order_by(desc(Article.updated_at)).offset(offset).limit(per_page).all()

    breadcrumb = [{"name": "首頁", "url": _site_url("/", site_profile)}, {"name": meta["label"], "url": None}]
    collection_schema = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": meta["label"], "description": meta["desc"],
        "url": _site_url(f"/category/{article_type}", site_profile),
        "isPartOf": {"@type": "WebSite", "name": site_profile["site_name"], "url": _site_url(site_profile=site_profile)},
    }

    return templates.TemplateResponse(request, "category.html", {
        **_common_ctx(request, site_profile),
        "articles": articles, "category_meta": meta, "cat_type": article_type,
        "page": page, "total": total, "per_page": per_page,
        "has_prev": page > 1, "has_next": (offset + per_page) < total,
        "total_pages": max(1, math.ceil(total / per_page)),
        "breadcrumb": breadcrumb, "collection_schema": collection_schema,
        "reading_time": _reading_time,
    })


# ─── Topic Cluster page ──────────────────────────────────────

@site_app.get("/topic/{cluster_ref}", response_class=HTMLResponse)
async def topic_cluster_page(cluster_ref: str, request: Request, db: DBDep):
    from contentflow.models.database import ClusterMember

    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    cluster, redirect = _resolve_topic_cluster(db, site_profile, cluster_ref)
    if redirect:
        return redirect
    if not cluster:
        raise HTTPException(status_code=404, detail="Topic cluster not found")
    cluster_id = cluster.id

    members = db.query(ClusterMember).filter(ClusterMember.cluster_id == cluster_id).all()
    member_articles = []
    for m in members:
        art = db.get(Article, m.article_id) if m.article_id else None
        member_articles.append({
            "keyword": m.keyword,
            "article": art if art and art.status == _PUBLISHED and art.slug else None,
            "link_to_pillar": m.link_to_pillar,
        })

    pillar_article = db.get(Article, cluster.pillar_article_id) if cluster.pillar_article_id else None
    coverage = sum(1 for m in member_articles if m["article"]) / max(len(member_articles), 1)

    breadcrumb = [
        {"name": "首頁", "url": _site_url("/", site_profile)},
        {"name": "主題叢集", "url": _site_url("/blog", site_profile)},
        {"name": cluster.pillar_keyword, "url": None},
    ]

    return templates.TemplateResponse(request, "topic_cluster.html", {
        **_common_ctx(request, site_profile),
        "cluster": cluster, "members": member_articles,
        "pillar_article": pillar_article, "coverage": coverage,
        "breadcrumb": breadcrumb,
    })


# ─── About page (E-E-A-T) ────────────────────────────────────

@site_app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: DBDep):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    total = _published_q(db, site_profile).count()
    org_schema = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": site_profile["site_name"], "url": _site_url(site_profile=site_profile),
        "description": site_profile["site_description"], "sameAs": [],
    }
    breadcrumb = [{"name": "首頁", "url": _site_url("/", site_profile)}, {"name": "關於我們", "url": None}]

    return templates.TemplateResponse(request, "about.html", {
        **_common_ctx(request, site_profile),
        "total_articles": total, "org_schema": org_schema, "breadcrumb": breadcrumb,
    })


# ─── Sitemap ──────────────────────────────────────────────────

@site_app.get("/sitemap.xml")
async def sitemap(db: DBDep):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    articles = _published_q(db, site_profile).order_by(desc(Article.updated_at)).all()
    clusters = _topic_clusters_q(db, site_profile).all()
    base = _site_url(site_profile=site_profile)

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for path, freq, priority in [("/", "daily", "1.0"), ("/blog", "daily", "0.9"), ("/about", "monthly", "0.4")]:
        lines.append(f'  <url><loc>{xml_escape(base + path)}</loc>'
                     f'<changefreq>{freq}</changefreq><priority>{priority}</priority></url>')
    for atype in _ARTICLE_TYPE_MAP:
        cat_path = f"/category/{quote(atype, safe='')}"
        lines.append(f'  <url><loc>{xml_escape(base)}{xml_escape(cat_path)}</loc>'
                     f'<changefreq>weekly</changefreq><priority>0.7</priority></url>')
    _seen_topic_paths: set[str] = set()
    for c in clusters:
        topic_path = _topic_cluster_path(c)
        if topic_path in _seen_topic_paths:
            continue
        _seen_topic_paths.add(topic_path)
        lines.append(f'  <url><loc>{xml_escape(base)}{xml_escape(topic_path)}</loc>'
                     f'<changefreq>weekly</changefreq><priority>0.7</priority></url>')
    for a in articles:
        lastmod = f"<lastmod>{a.updated_at.strftime('%Y-%m-%d')}</lastmod>" if a.updated_at else ""
        lines.append(f'  <url><loc>{xml_escape(base)}/blog/{xml_escape(a.slug)}</loc>'
                     f'{lastmod}<changefreq>weekly</changefreq><priority>0.8</priority></url>')

    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


@site_app.get("/sitemap_index.xml")
async def sitemap_index_redirect():
    """Redirect legacy /sitemap_index.xml to /sitemap.xml (GSC compatibility)."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/sitemap.xml", status_code=301)


# ─── Robots ───────────────────────────────────────────────────

@site_app.get("/robots.txt")
async def robots():
    _ensure_managed_site_enabled()
    base = _site_url(site_profile=_site_profile())
    return Response(
        content=(
            f"User-agent: *\n"
            f"Allow: /\n"
            f"Disallow: /health\n"
            f"Disallow: /admin/\n"
            f"\nSitemap: {base}/sitemap.xml\n"
        ),
        media_type="text/plain",
    )


# ─── RSS Feed ─────────────────────────────────────────────────

@site_app.get("/feed")
async def rss_feed(db: DBDep):
    _ensure_managed_site_enabled()
    site_profile = _site_profile(db)
    articles = _published_q(db, site_profile).order_by(desc(Article.updated_at)).limit(20).all()
    base = _site_url(site_profile=site_profile)
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
             "  <channel>",
             f"    <title>{xml_escape(str(site_profile['site_name']))}</title>",
             f"    <link>{xml_escape(base)}</link>",
             f"    <description>{xml_escape(str(site_profile['site_description']))}</description>",
             f"    <language>zh-TW</language>",
             f"    <lastBuildDate>{now}</lastBuildDate>",
             f'    <atom:link href="{xml_escape(base)}/feed" rel="self" type="application/rss+xml"/>']

    for a in articles:
        pub_date = a.updated_at.strftime("%a, %d %b %Y %H:%M:%S +0000") if a.updated_at else ""
        lines.append("    <item>")
        lines.append(f"      <title>{xml_escape(a.meta_title or a.title)}</title>")
        lines.append(f"      <link>{xml_escape(base)}/blog/{xml_escape(a.slug)}</link>")
        lines.append(f'      <guid isPermaLink="true">{xml_escape(base)}/blog/{xml_escape(a.slug)}</guid>')
        if a.meta_description:
            lines.append(f"      <description>{xml_escape(a.meta_description)}</description>")
        if pub_date:
            lines.append(f"      <pubDate>{pub_date}</pubDate>")
        lines.append("    </item>")

    lines.extend(["  </channel>", "</rss>"])
    return Response(content="\n".join(lines), media_type="application/rss+xml; charset=utf-8")


# ─── Custom 404 ───────────────────────────────────────────────

@site_app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if not settings.managed_site_enabled:
        return Response(content="Not Found", status_code=404, media_type="text/plain")
    db = SessionLocal()
    try:
        site_profile = _site_profile(db)
        popular = _published_q(db, site_profile).order_by(desc(Article.updated_at)).limit(5).all()
    finally:
        db.close()
    return templates.TemplateResponse(request, "404.html", {**_common_ctx(request, site_profile), "popular_articles": popular}, status_code=404)


# ─── Mount Admin ───────────────────────────────────────────────
from contentflow.admin.app import admin_app  # noqa: E402
site_app.mount("/admin", admin_app)
