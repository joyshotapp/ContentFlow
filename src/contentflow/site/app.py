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
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape as xml_escape

import markdown as md_module
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import Article, Category, TopicCluster

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

def _site_url(path: str = "") -> str:
    base = settings.site_url.rstrip("/")
    return f"{base}{path}" if path else base


def _common_ctx(request: Request) -> dict:
    return {
        "site_url": _site_url(),
        "site_name": settings.site_name,
        "site_description": settings.site_description,
        "ga4_id": settings.ga4_measurement_id,
        "article_type_map": _ARTICLE_TYPE_MAP,
    }


def _published_q(db: Session):
    return db.query(Article).filter(Article.status == _PUBLISHED, Article.slug != "")


# ─────────────────────────────────────────────────────────────
# Related articles
# ─────────────────────────────────────────────────────────────

def _get_related_articles(db: Session, article: Article, limit: int = 4) -> list[Article]:
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
    for a in cluster_articles:
        if a.id not in related_ids:
            related.append(a)
            related_ids.add(a.id)

    # 2) Same article_type
    if len(related) < limit and article.article_type:
        type_articles = (
            _published_q(db)
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
            _published_q(db)
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

site_app = FastAPI(
    title="ContentFlow Reference Site",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
site_app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@site_app.on_event("startup")
async def _startup():
    """初始化 DB + 排程（只在第一個 worker 啟動排程）。"""
    from contentflow.db import init_db
    from contentflow.scheduler import scheduler, schedule_all_jobs

    init_db()
    # 多 worker 模式下只啟動一次 scheduler
    if not scheduler.running:
        schedule_all_jobs()


@site_app.on_event("shutdown")
async def _shutdown():
    from contentflow.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown(wait=False)


@site_app.get("/health")
async def health():
    """健康檢查：驗證 DB 連線 + 排程器運行狀態。"""
    import os
    from pathlib import Path

    checks: dict = {"service": "reference-site"}

    # DB 連線
    try:
        db = SessionLocal()
        db.execute(func.now())
        db.close()
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    # 排程器 — 多 worker 下只有 1 個 worker 持有鎖，透過 PID 檔案檢查
    pid_path = Path("/tmp/contentflow_scheduler.pid")
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            # 檢查該 PID 是否仍存活
            os.kill(pid, 0)
            checks["scheduler"] = "running"
            checks["scheduler_pid"] = pid
        except (ValueError, ProcessLookupError, PermissionError):
            checks["scheduler"] = "stale_pid"
    else:
        checks["scheduler"] = "no_pid_file"

    ok = checks["db"] == "ok" and checks["scheduler"] == "running"
    checks["status"] = "ok" if ok else "degraded"

    status_code = 200 if ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(content=checks, status_code=status_code)


# ─── Homepage ─────────────────────────────────────────────────

@site_app.get("/", response_class=HTMLResponse)
async def homepage(request: Request, db: DBDep):
    latest = _published_q(db).order_by(desc(Article.updated_at)).limit(6).all()
    type_counts = dict(
        db.query(Article.article_type, func.count(Article.id))
        .filter(Article.status == _PUBLISHED, Article.slug != "")
        .group_by(Article.article_type)
        .all()
    )
    clusters = db.query(TopicCluster).order_by(desc(TopicCluster.updated_at)).limit(6).all()
    total_articles = _published_q(db).count()

    org_schema = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": settings.site_name, "url": _site_url(),
        "description": settings.site_description,
    }
    website_schema = {
        "@context": "https://schema.org", "@type": "WebSite",
        "name": settings.site_name, "url": _site_url(), "inLanguage": "zh-TW",
        "potentialAction": {
            "@type": "SearchAction",
            "target": f"{_site_url()}/blog?q={{search_term_string}}",
            "query-input": "required name=search_term_string",
        },
    }

    return templates.TemplateResponse(request, "index.html", {
        **_common_ctx(request),
        "articles": latest, "type_counts": type_counts,
        "clusters": clusters, "total_articles": total_articles,
        "org_schema": org_schema, "website_schema": website_schema,
    })


# ─── Blog listing ─────────────────────────────────────────────

@site_app.get("/blog", response_class=HTMLResponse)
async def blog_list(request: Request, db: DBDep, page: int = 1, type: str | None = None, q: str | None = None):
    per_page = 12
    offset = (page - 1) * per_page
    query = _published_q(db)

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

    breadcrumb = [{"name": "首頁", "url": _site_url("/")}]
    if type and type in _ARTICLE_TYPE_MAP:
        breadcrumb.append({"name": "文章", "url": _site_url("/blog")})
        breadcrumb.append({"name": _ARTICLE_TYPE_MAP[type]["label"], "url": None})
    else:
        breadcrumb.append({"name": "文章", "url": None})

    return templates.TemplateResponse(request, "blog_list.html", {
        **_common_ctx(request),
        "articles": articles, "page": page, "total": total, "per_page": per_page,
        "has_prev": page > 1, "has_next": (offset + per_page) < total,
        "total_pages": max(1, math.ceil(total / per_page)),
        "current_type": type, "search_q": q or "",
        "breadcrumb": breadcrumb, "reading_time": _reading_time,
    })


# ─── Article detail ───────────────────────────────────────────

@site_app.get("/blog/{slug}", response_class=HTMLResponse)
async def blog_post(slug: str, request: Request, db: DBDep):
    article = db.query(Article).filter(Article.slug == slug, Article.status == _PUBLISHED).first()
    if not article:
        # 若反查 old_slugs（曾用過的 slug），符合則 301 永久轉址
        import json as _json_r
        from fastapi.responses import RedirectResponse
        candidate = (
            db.query(Article)
            .filter(Article.old_slugs.contains(slug), Article.status == _PUBLISHED)
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
    related = _get_related_articles(db, article)
    canonical_url = _site_url(f"/blog/{slug}")

    faq_schema = _parse_json_safe(article.faq_schema_json)
    article_schema = _parse_json_safe(article.article_schema_json)

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
            "@type": "Organization", "name": settings.site_name, "url": _site_url(),
        })
        article_schema.setdefault("author", {
            "@type": "Organization", "name": settings.site_name, "url": _site_url("/about"),
        })

    breadcrumb_items = [
        {"name": "首頁", "url": _site_url("/")},
        {"name": "文章", "url": _site_url("/blog")},
    ]
    if article.article_type and article.article_type in _ARTICLE_TYPE_MAP:
        breadcrumb_items.append({
            "name": _ARTICLE_TYPE_MAP[article.article_type]["label"],
            "url": _site_url(f"/blog?type={article.article_type}"),
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
        **_common_ctx(request),
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
    if article_type not in _ARTICLE_TYPE_MAP:
        raise HTTPException(status_code=404, detail="Category not found")

    meta = _ARTICLE_TYPE_MAP[article_type]
    per_page = 12
    offset = (page - 1) * per_page
    query = _published_q(db).filter(Article.article_type == article_type)
    total = query.count()
    articles = query.order_by(desc(Article.updated_at)).offset(offset).limit(per_page).all()

    breadcrumb = [{"name": "首頁", "url": _site_url("/")}, {"name": meta["label"], "url": None}]
    collection_schema = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": meta["label"], "description": meta["desc"],
        "url": _site_url(f"/category/{article_type}"),
        "isPartOf": {"@type": "WebSite", "name": settings.site_name, "url": _site_url()},
    }

    return templates.TemplateResponse(request, "category.html", {
        **_common_ctx(request),
        "articles": articles, "category_meta": meta, "cat_type": article_type,
        "page": page, "total": total, "per_page": per_page,
        "has_prev": page > 1, "has_next": (offset + per_page) < total,
        "total_pages": max(1, math.ceil(total / per_page)),
        "breadcrumb": breadcrumb, "collection_schema": collection_schema,
        "reading_time": _reading_time,
    })


# ─── Topic Cluster page ──────────────────────────────────────

@site_app.get("/topic/{cluster_id}", response_class=HTMLResponse)
async def topic_cluster_page(cluster_id: int, request: Request, db: DBDep):
    from contentflow.models.database import ClusterMember

    cluster = db.get(TopicCluster, cluster_id)
    if not cluster:
        raise HTTPException(status_code=404, detail="Topic cluster not found")

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
        {"name": "首頁", "url": _site_url("/")},
        {"name": "主題叢集", "url": _site_url("/blog")},
        {"name": cluster.pillar_keyword, "url": None},
    ]

    return templates.TemplateResponse(request, "topic_cluster.html", {
        **_common_ctx(request),
        "cluster": cluster, "members": member_articles,
        "pillar_article": pillar_article, "coverage": coverage,
        "breadcrumb": breadcrumb,
    })


# ─── About page (E-E-A-T) ────────────────────────────────────

@site_app.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, db: DBDep):
    total = _published_q(db).count()
    org_schema = {
        "@context": "https://schema.org", "@type": "Organization",
        "name": settings.site_name, "url": _site_url(),
        "description": settings.site_description, "sameAs": [],
    }
    breadcrumb = [{"name": "首頁", "url": _site_url("/")}, {"name": "關於我們", "url": None}]

    return templates.TemplateResponse(request, "about.html", {
        **_common_ctx(request),
        "total_articles": total, "org_schema": org_schema, "breadcrumb": breadcrumb,
    })


# ─── Sitemap ──────────────────────────────────────────────────

@site_app.get("/sitemap.xml")
async def sitemap(db: DBDep):
    articles = _published_q(db).order_by(desc(Article.updated_at)).all()
    clusters = db.query(TopicCluster).all()
    base = _site_url()

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for path, freq, priority in [("/", "daily", "1.0"), ("/blog", "daily", "0.9"), ("/about", "monthly", "0.4")]:
        lines.append(f'  <url><loc>{xml_escape(base + path)}</loc>'
                     f'<changefreq>{freq}</changefreq><priority>{priority}</priority></url>')
    for atype in _ARTICLE_TYPE_MAP:
        lines.append(f'  <url><loc>{xml_escape(base)}/category/{xml_escape(atype)}</loc>'
                     f'<changefreq>weekly</changefreq><priority>0.7</priority></url>')
    for c in clusters:
        lines.append(f'  <url><loc>{xml_escape(base)}/topic/{c.id}</loc>'
                     f'<changefreq>weekly</changefreq><priority>0.7</priority></url>')
    for a in articles:
        lastmod = f"<lastmod>{a.updated_at.strftime('%Y-%m-%d')}</lastmod>" if a.updated_at else ""
        lines.append(f'  <url><loc>{xml_escape(base)}/blog/{xml_escape(a.slug)}</loc>'
                     f'{lastmod}<changefreq>weekly</changefreq><priority>0.8</priority></url>')

    lines.append("</urlset>")
    return Response(content="\n".join(lines), media_type="application/xml")


# ─── Robots ───────────────────────────────────────────────────

@site_app.get("/robots.txt")
async def robots():
    base = _site_url()
    return Response(
        content=f"User-agent: *\nAllow: /\nDisallow: /health\n\nSitemap: {base}/sitemap.xml\n",
        media_type="text/plain",
    )


# ─── RSS Feed ─────────────────────────────────────────────────

@site_app.get("/feed")
async def rss_feed(db: DBDep):
    articles = _published_q(db).order_by(desc(Article.updated_at)).limit(20).all()
    base = _site_url()
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
             "  <channel>",
             f"    <title>{xml_escape(settings.site_name)}</title>",
             f"    <link>{xml_escape(base)}</link>",
             f"    <description>{xml_escape(settings.site_description)}</description>",
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
    db = SessionLocal()
    try:
        popular = _published_q(db).order_by(desc(Article.updated_at)).limit(5).all()
    finally:
        db.close()
    return templates.TemplateResponse(request, "404.html", {**_common_ctx(request), "popular_articles": popular}, status_code=404)


# ─── Mount Admin ───────────────────────────────────────────────
from contentflow.admin.app import admin_app  # noqa: E402
site_app.mount("/admin", admin_app)
