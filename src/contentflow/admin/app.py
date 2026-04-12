"""ContentFlow Admin Dashboard — FastAPI 後台管理介面

完整 12 頁架構（對應系統所有模組）：

 儀表板          /
 ─── 內容管理 ────
 文章管理         /articles  (list + detail /{id})
 內容日曆         /calendar
 關鍵字庫         /keywords
 主題叢集         /clusters
 ─── SEO 分析 ───
 GSC 績效         /seo
 競品追蹤         /competitors
 ─── AI 引擎 ────
 Agent 執行中心   /agents
 知識庫           /knowledge
 ─── 系統 ───────
 排程監控         /scheduler
 系統健康         /health
 專案設定         /settings
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter, defaultdict
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks, FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from sqlalchemy import func, desc

from starlette.middleware.sessions import SessionMiddleware

from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import (
    Article,
    AgentDecisionLog,
    ContentCalendar,
    Competitor,
    KnowledgeEntry,
    KnowledgeAuditLog,
    Keyword,
    LegalTerm,
    Product,
    Project,
    SchedulerLog,
    SEORanking,
    TopicCluster,
    ClusterMember,
    WritingRule,
    ContentStrategy,
)

# ── App ───────────────────────────────────────────────────────

admin_app = FastAPI(title="ContentFlow Admin", docs_url=None, redoc_url=None)
admin_app.add_middleware(
    SessionMiddleware,
    secret_key=settings.api_secret_key or "dev-secret-change-me",
)

_here = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(_here / "templates"))
# Add custom Jinja2 filters
templates.env.filters["fromjson"] = json.loads


def _db():
    return SessionLocal()


def _check_login(request: Request) -> bool:
    return bool(request.session.get("admin_logged_in"))


# ── Label / color maps ────────────────────────────────────────

STATUS_LABELS = {
    "planned": "規劃中",
    "researching": "研究中",
    "writing": "撰寫中",
    "reviewing": "審閱中",
    "published": "已發佈",
}
STATUS_COLORS = {
    "planned": "neutral",
    "researching": "info",
    "writing": "warning",
    "reviewing": "purple",
    "published": "success",
}
CONFIDENCE_LABELS = {
    "unverified": "未驗證", "verified": "已驗證", "universal": "通用規則",
}
CONFIDENCE_COLORS = {
    "unverified": "warning", "verified": "success", "universal": "info",
}

PIPELINE_STEPS = [
    ("research",    "研究",   "#6366f1"),
    ("strategy",    "策略",   "#8b5cf6"),
    ("writing",     "撰文",   "#3b82f6"),
    ("seo_check",   "SEO 檢查", "#f59e0b"),
    ("seo_qa",      "SEO 修正", "#f97316"),
    ("factcheck",   "事實查核", "#10b981"),
    ("budget_guard","預算守衛", "#64748b"),
]


# ═══════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": None})


@admin_app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    if password == (settings.api_secret_key or "admin"):
        request.session["admin_logged_in"] = True
        return RedirectResponse("/admin/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": "密碼錯誤"})


@admin_app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# ═══════════════════════════════════════════════════════════════
# DASHBOARD  /
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        now = datetime.now(timezone.utc)

        # KPI
        total_articles = db.query(Article).count()
        published    = db.query(Article).filter(Article.status == "published").count()
        reviewing    = db.query(Article).filter(Article.status == "reviewing").count()
        total_kw     = db.query(Keyword).count()
        total_clusters = db.query(TopicCluster).count()
        knowledge_count = db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count()

        # Article status dist
        raw_status = db.query(Article.status, func.count()).group_by(Article.status).all()
        status_counts = {s: c for s, c in raw_status}

        # GSC summary
        seo = db.query(
            func.avg(SEORanking.position),
            func.sum(SEORanking.clicks),
            func.sum(SEORanking.impressions),
        ).first()
        avg_position     = round(seo[0], 1) if seo[0] else 0
        total_clicks     = seo[1] or 0
        total_impressions = seo[2] or 0

        # Pipeline runs (last 8)
        runs_raw = (
            db.query(
                AgentDecisionLog.run_id,
                AgentDecisionLog.article_id,
                func.min(AgentDecisionLog.created_at).label("started"),
                func.max(AgentDecisionLog.created_at).label("ended"),
                func.count(AgentDecisionLog.id).label("steps"),
            )
            .group_by(AgentDecisionLog.run_id, AgentDecisionLog.article_id)
            .order_by(desc("started"))
            .limit(8)
            .all()
        )
        pipeline_runs = []
        for r in runs_raw:
            art = db.query(Article).filter(Article.id == r.article_id).first() if r.article_id else None
            steps = db.query(AgentDecisionLog).filter(AgentDecisionLog.run_id == r.run_id).all()
            over_budget = any("強制" in (d.decision or "") for d in steps if d.step == "budget_guard")
            last_step = steps[-1].step if steps else ""
            pipeline_runs.append({
                "run_id": r.run_id,
                "run_id_short": r.run_id[:8],
                "article_title": (art.title[:45] if art else "—"),
                "article_status": art.status if art else "",
                "started": r.started,
                "steps": r.steps,
                "is_complete": last_step in ("budget_guard", "factcheck"),
                "over_budget": over_budget,
            })

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        est_cost = total_runs * 0.15

        # Pending review
        pending_review = (
            db.query(Article).filter(Article.status == "reviewing")
            .order_by(desc(Article.updated_at)).limit(5).all()
        )

        # Calendar this month
        cm = now.month
        cal_total = db.query(ContentCalendar).filter(ContentCalendar.month == cm).count()
        cal_done  = db.query(ContentCalendar).filter(
            ContentCalendar.month == cm, ContentCalendar.status == "published"
        ).count()

        # Recent scheduler
        sched_success = db.query(SchedulerLog).filter(SchedulerLog.status == "success").count()
        sched_fail    = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count()
        recent_sched  = db.query(SchedulerLog).order_by(desc(SchedulerLog.started_at)).limit(5).all()

        return templates.TemplateResponse(request, "dashboard.html", {
            "request": request, "page": "dashboard", "now": now,
            "total_articles": total_articles, "published": published, "reviewing": reviewing,
            "total_kw": total_kw, "total_clusters": total_clusters, "knowledge_count": knowledge_count,
            "status_counts": json.dumps(status_counts),
            "avg_position": avg_position, "total_clicks": total_clicks, "total_impressions": total_impressions,
            "pipeline_runs": pipeline_runs, "total_runs": total_runs, "est_cost": est_cost,
            "pending_review": pending_review,
            "cal_total": cal_total, "cal_done": cal_done, "cal_month": cm,
            "sched_success": sched_success, "sched_fail": sched_fail, "recent_sched": recent_sched,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# ARTICLES  /articles  /articles/{id}
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/articles", response_class=HTMLResponse)
async def articles_list(request: Request, status: str = "", q: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        PAGE_SIZE = 20
        query = db.query(Article).order_by(desc(Article.updated_at))
        if status:
            query = query.filter(Article.status == status)
        if q:
            like = f"%{q}%"
            query = query.filter((Article.title.ilike(like)) | (Article.primary_keyword.ilike(like)))
        total = query.count()
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(1, min(page, total_pages))
        articles = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
        raw = db.query(Article.status, func.count()).group_by(Article.status).all()
        sc = {s: c for s, c in raw}
        return templates.TemplateResponse(request, "articles.html", {
            "request": request, "page": page, "page_size": PAGE_SIZE,
            "articles": articles, "status_filter": status, "search_q": q,
            "total": total, "total_pages": total_pages,
            "sc": sc, "status_counts": sc,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/articles/create")
async def create_article(
    request: Request,
    keyword: str = Form(...),
    title: str = Form(""),
    article_type: str = Form("知識"),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = Article(
            title=title or keyword,
            primary_keyword=keyword,
            article_type=article_type,
            status="planned",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(art)
        db.commit()
        db.refresh(art)
        return RedirectResponse(f"/admin/articles/{art.id}", status_code=303)
    finally:
        db.close()


@admin_app.post("/articles/bulk-create")
async def bulk_create_articles(request: Request):
    """從 JSON body 批量建立 planned 文章（[{keyword, title, article_type}, ...]）"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    data = await request.json()
    db = _db()
    try:
        created = []
        for item in data:
            kw = item.get("keyword", "").strip()
            if not kw:
                continue
            art = Article(
                title=item.get("title", kw),
                primary_keyword=kw,
                article_type=item.get("article_type", "知識"),
                status="planned",
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(art)
            created.append(kw)
        db.commit()
        return {"created": len(created), "keywords": created}
    finally:
        db.close()


@admin_app.get("/articles/{article_id}", response_class=HTMLResponse)
async def article_detail(request: Request, article_id: int):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(status_code=404)

        # SEO ranking history for this keyword
        seo_history = []
        if article.primary_keyword:
            seo_history = [
                {"date": str(r.tracked_date), "position": round(float(r.position), 1) if r.position else 0,
                 "clicks": r.clicks or 0, "impressions": r.impressions or 0}
                for r in (
                    db.query(SEORanking)
                    .filter(SEORanking.keyword == article.primary_keyword)
                    .order_by(SEORanking.tracked_date).limit(30).all()
                )
            ]

        # Pipeline decision logs — convert ORM to dicts for template rendering
        _STEP_NAMES = {
            "research": "Research Agent", "strategy": "Strategy Agent",
            "writing": "Writing Agent", "seo_check": "SEO Check Agent",
            "seo_qa": "SEO QA", "factcheck": "FactCheck Agent",
            "budget_guard": "Budget Guard", "publish": "Publish Agent",
        }
        decisions = [
            {
                "agent_name": _STEP_NAMES.get(d.step, d.step),
                "step": d.step,
                "decision": d.decision,
                "reasoning": d.reason,          # model field is `reason`
                "confidence": d.confidence,
                "created_at": d.created_at,
            }
            for d in (
                db.query(AgentDecisionLog)
                .filter(AgentDecisionLog.article_id == article.id)
                .order_by(AgentDecisionLog.created_at).all()
            )
        ]

        # Group by run (for pipeline_runs reference — keep for backwards compat)
        runs_dict: dict = defaultdict(list)
        for d in (db.query(AgentDecisionLog).filter(AgentDecisionLog.article_id == article.id).all()):
            runs_dict[d.run_id].append(d)

        # Research JSON
        research_data = {}
        if article.research_report_json:
            try:
                research_data = json.loads(article.research_report_json)
            except Exception:
                pass

        return templates.TemplateResponse(request, "article_detail.html", {
            "request": request, "page": "articles",
            "art": article,                               # template uses `art`
            "decisions": decisions,
            "seo_history": seo_history,                  # list of dicts (JSON-serializable)
            "research_data": research_data,
            "PIPELINE_STEPS": PIPELINE_STEPS,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/articles/{article_id}/status")
async def update_article_status(request: Request, article_id: int, status: str = Form(...)):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        art = db.query(Article).filter(Article.id == article_id).first()
        if art:
            art.status = status
            art.updated_at = datetime.now(timezone.utc)
            db.commit()
        return RedirectResponse(f"/admin/articles/{article_id}", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# CONTENT CALENDAR  /calendar
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/calendar", response_class=HTMLResponse)
async def calendar_page(request: Request, month: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        now = datetime.now(timezone.utc)
        if month == 0:
            month = now.month

        all_entries = (
            db.query(ContentCalendar)
            .order_by(ContentCalendar.month, ContentCalendar.week)
            .all()
        )

        # Enrich entries with linked article data
        enriched = []
        for e in all_entries:
            art = db.query(Article).filter(Article.id == e.article_id).first() if e.article_id else None
            enriched.append({
                "id": e.article_id or e.id,
                "cal_id": e.id,
                "status": e.status,
                "title": (art.title if art else e.title) or "(未命名)",
                "primary_keyword": (art.primary_keyword if art else None) or (e.keywords.split(",")[0].strip() if e.keywords else ""),
                "seo_score": art.seo_score if art else None,
                "scheduled_date": None,
                "article_type": e.article_type,
                "month": e.month or 0,
                "week": e.week or 0,
            })

        # Status counts
        sc = {}
        for item in enriched:
            sc[item["status"]] = sc.get(item["status"], 0) + 1

        # Group by month → weeks → items, only show requested month (or all if month=0)
        months_map: dict = {}
        MONTH_NAMES = {1:"1月",2:"2月",3:"3月",4:"4月",5:"5月",6:"6月",7:"7月",8:"8月",9:"9月",10:"10月",11:"11月",12:"12月"}
        for item in enriched:
            m = item["month"]
            if m == 0: continue
            if month and m != month: continue
            if m not in months_map:
                months_map[m] = {}
            w = item["week"]
            if w not in months_map[m]:
                months_map[m][w] = []
            months_map[m][w].append(SimpleNamespace(**item))

        calendar = []
        for m in sorted(months_map.keys()):
            weeks = []
            for w in sorted(months_map[m].keys()):
                weeks.append(SimpleNamespace(
                    week_num=w,
                    date_range=f"第 {w} 週",
                    items=months_map[m][w],
                ))
            calendar.append((MONTH_NAMES.get(m, f"{m}月"), weeks))

        months_with_data = sorted(set(e["month"] for e in enriched if e["month"]))

        return templates.TemplateResponse(request, "calendar.html", {
            "request": request, "page": "calendar", "now": now,
            "calendar": calendar,
            "current_month": month, "months_with_data": months_with_data,
            "total": len(enriched),
            "sc": sc,
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# KEYWORDS  /keywords
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request, q: str = "", sort: str = "volume"):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        query = db.query(Keyword)
        if q:
            query = query.filter(Keyword.keyword.ilike(f"%{q}%"))
        if sort == "difficulty":
            query = query.order_by(desc(Keyword.seo_difficulty))
        elif sort == "cpc":
            query = query.order_by(desc(Keyword.cpc))
        else:
            query = query.order_by(desc(Keyword.search_volume))
        kws = query.all()

        total = len(kws)
        avg_vol = round(sum(k.search_volume or 0 for k in kws) / max(total, 1))
        avg_diff = round(sum(k.seo_difficulty or 0 for k in kws) / max(total, 1), 1)
        high_vol = sum(1 for k in kws if (k.search_volume or 0) >= 1000)
        diff_low  = sum(1 for k in kws if (k.seo_difficulty or 0) <= 33)
        diff_mid  = sum(1 for k in kws if 33 < (k.seo_difficulty or 0) <= 66)
        diff_high = sum(1 for k in kws if (k.seo_difficulty or 0) > 66)
        vol_max   = max((k.search_volume or 0 for k in kws), default=1) or 1

        _vol_buckets = {"<100": 0, "100-500": 0, "500-1k": 0, "1k-5k": 0, "5k+": 0}
        for k in kws:
            v = k.search_volume or 0
            if v < 100: _vol_buckets["<100"] += 1
            elif v < 500: _vol_buckets["100-500"] += 1
            elif v < 1000: _vol_buckets["500-1k"] += 1
            elif v < 5000: _vol_buckets["1k-5k"] += 1
            else: _vol_buckets["5k+"] += 1
        vol_buckets = [{"label": lbl, "count": cnt} for lbl, cnt in _vol_buckets.items()]

        return templates.TemplateResponse(request, "keywords.html", {
            "request": request, "page": "keywords",
            "keywords": kws, "q": q, "search_q": q, "sort": sort,
            "total": total, "total_kw": total,
            "avg_volume": avg_vol, "avg_difficulty": avg_diff,
            "high_value_count": high_vol,
            "diff_low": diff_low, "diff_mid": diff_mid, "diff_high": diff_high,
            "vol_max": vol_max, "vol_buckets": vol_buckets,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# TOPIC CLUSTERS  /clusters
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/clusters", response_class=HTMLResponse)
async def clusters_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        topic_clusters = db.query(TopicCluster).order_by(desc(TopicCluster.updated_at)).all()
        clusters = []
        for c in topic_clusters:
            members_orm = db.query(ClusterMember).filter(ClusterMember.cluster_id == c.id).all()
            # Enrich each member with article data
            enriched_members = []
            pub_cnt = rev_cnt = wri_cnt = res_cnt = 0
            for m in members_orm:
                art = db.query(Article).filter(Article.id == m.article_id).first() if m.article_id else None
                st = art.status if art else "planned"
                if st == "published": pub_cnt += 1
                elif st == "reviewing": rev_cnt += 1
                elif st == "writing": wri_cnt += 1
                elif st == "researching": res_cnt += 1
                enriched_members.append({
                    "article_id": m.article_id,
                    "article_title": art.title if art else m.keyword,
                    "article_status": st,
                    "article_seo_score": art.seo_score if art else None,
                    "keyword": m.keyword,
                    "link_to_pillar": m.link_to_pillar,
                })
            clusters.append({
                "id": c.id,
                "pillar_topic": c.pillar_keyword,     # model field is pillar_keyword
                "description": c.pillar_title or "",   # use pillar_title as description
                "status": c.status,
                "updated_at": c.updated_at,
                "member_count": len(members_orm),
                "published_count": pub_cnt,
                "reviewing_count": rev_cnt,
                "writing_count": wri_cnt,
                "members": enriched_members,
            })

        return templates.TemplateResponse(request, "clusters.html", {
            "request": request, "page": "clusters",
            "clusters": clusters,
            "total_clusters": len(topic_clusters),
            "total_members": sum(c["member_count"] for c in clusters),
            "completed_clusters": sum(1 for c in topic_clusters if c.status == "complete"),
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SEO PERFORMANCE  /seo
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/seo", response_class=HTMLResponse)
async def seo_page(request: Request, days: int = 30):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date()

        daily = (
            db.query(
                SEORanking.tracked_date,
                func.sum(SEORanking.clicks).label("clicks"),
                func.sum(SEORanking.impressions).label("impressions"),
                func.avg(SEORanking.position).label("avg_pos"),
            )
            .filter(SEORanking.tracked_date >= cutoff)
            .group_by(SEORanking.tracked_date)
            .order_by(SEORanking.tracked_date)
            .all()
        )

        top_keywords = (
            db.query(
                SEORanking.keyword,
                func.sum(SEORanking.clicks).label("total_clicks"),
                func.sum(SEORanking.impressions).label("total_impressions"),
                func.avg(SEORanking.position).label("avg_position"),
                func.avg(SEORanking.ctr).label("avg_ctr"),
            )
            .group_by(SEORanking.keyword)
            .order_by(desc("total_clicks"))
            .limit(20).all()
        )

        opportunities_raw = (
            db.query(SEORanking)
            .filter(SEORanking.position >= 3, SEORanking.position <= 15, SEORanking.impressions > 0)
            .order_by(desc(SEORanking.impressions))
            .limit(15).all()
        )
        # Normalise field names for template
        opportunity_kws = [SimpleNamespace(
            query=r.keyword, position=r.position or 0,
            impressions=r.impressions or 0, page=r.landing_page,
        ) for r in opportunities_raw]

        # Recent individual GSC rows for the table
        gsc_raw = (
            db.query(SEORanking)
            .order_by(desc(SEORanking.tracked_date), desc(SEORanking.clicks))
            .limit(30).all()
        )
        gsc_data = [SimpleNamespace(
            query=r.keyword, page=r.landing_page, ctr=r.ctr or 0,
            position=r.position or 0, date=r.tracked_date,
            clicks=r.clicks or 0, impressions=r.impressions or 0,
        ) for r in gsc_raw]

        gsc_trend = json.dumps([{
            "date": str(d.tracked_date), "clicks": int(d.clicks or 0),
            "impressions": int(d.impressions or 0),
            "avg_pos": round(float(d.avg_pos), 1) if d.avg_pos else 0,
        } for d in daily])

        total_clicks_sum = db.query(func.sum(SEORanking.clicks)).scalar() or 0
        total_impressions_sum = db.query(func.sum(SEORanking.impressions)).scalar() or 0
        avg_pos_overall = db.query(func.avg(SEORanking.position)).scalar() or 0
        avg_ctr_overall = db.query(func.avg(SEORanking.ctr)).scalar() or 0

        return templates.TemplateResponse(request, "seo.html", {
            "request": request, "page": "seo", "now": datetime.now(timezone.utc), "days": days,
            "top_keywords": top_keywords, "opportunity_kws": opportunity_kws,
            "gsc_data": gsc_data, "gsc_trend": gsc_trend,
            "chart_labels":      json.dumps([str(d.tracked_date) if d.tracked_date else "" for d in daily]),
            "chart_clicks":      json.dumps([int(d.clicks or 0) for d in daily]),
            "chart_impressions": json.dumps([int(d.impressions or 0) for d in daily]),
            "chart_positions":   json.dumps([round(float(d.avg_pos), 1) if d.avg_pos else 0 for d in daily]),
            "total_records":     db.query(SEORanking).count(),
            "total_clicks":      total_clicks_sum,
            "total_impressions": total_impressions_sum,
            "avg_position":      round(float(avg_pos_overall), 1) if avg_pos_overall else 0,
            "avg_ctr":           round(float(avg_ctr_overall), 4),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# COMPETITORS  /competitors
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/competitors", response_class=HTMLResponse)
async def competitors_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        competitors = db.query(Competitor).order_by(Competitor.brand_name).all()
        products    = db.query(Product).all()
        return templates.TemplateResponse(request, "competitors.html", {
            "request": request, "page": "competitors",
            "competitors": competitors, "products": products,
            "total": len(competitors),
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AGENT PIPELINE  /agents
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request, run_id: str = ""):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        _STEP_NAMES = {
            "research": "Research Agent", "strategy": "Strategy Agent",
            "writing": "Writing Agent", "seo_check": "SEO Check Agent",
            "seo_qa": "SEO QA", "factcheck": "FactCheck Agent",
            "budget_guard": "Budget Guard", "publish": "Publish Agent",
        }

        runs_raw = (
            db.query(
                AgentDecisionLog.run_id,
                AgentDecisionLog.article_id,
                func.min(AgentDecisionLog.created_at).label("started"),
                func.max(AgentDecisionLog.created_at).label("ended"),
                func.count(AgentDecisionLog.id).label("step_count"),
            )
            .group_by(AgentDecisionLog.run_id, AgentDecisionLog.article_id)
            .order_by(desc("started"))
            .limit(20).all()
        )

        runs = []
        for r in runs_raw:
            art = db.query(Article).filter(Article.id == r.article_id).first() if r.article_id else None
            steps_orm = (
                db.query(AgentDecisionLog)
                .filter(AgentDecisionLog.run_id == r.run_id)
                .order_by(AgentDecisionLog.created_at).all()
            )
            steps = [
                {
                    "agent_name": _STEP_NAMES.get(d.step, d.step),
                    "step": d.step,
                    "decision": d.decision,
                    "reasoning": d.reason,
                    "confidence": d.confidence,
                    "created_at": d.created_at,
                }
                for d in steps_orm
            ]
            over_budget = any("強制" in (d["decision"] or "") for d in steps if d["step"] == "budget_guard")
            last_step = steps[-1]["step"] if steps else ""
            is_complete = last_step in ("budget_guard", "factcheck", "publish")
            duration = None
            if r.started and r.ended and r.ended > r.started:
                dur = (r.ended - r.started).total_seconds()
                duration = f"{int(dur // 60)}m {int(dur % 60)}s"
            est_run_cost = round(r.step_count * 0.01, 4)
            completed_step_names = [d["step"] for d in steps]

            runs.append({
                "run_id": r.run_id, "run_id_short": r.run_id[:8],
                "article_id": r.article_id,
                "article_title": (art.title[:50] if art else "—"),
                "article_status": art.status if art else "",
                "started_at": r.started, "ended": r.ended,
                "step_count": r.step_count, "duration": duration,
                "is_complete": is_complete,
                "over_budget": over_budget,
                "est_cost": est_run_cost,
                "completed_steps": completed_step_names,
                "steps": steps,
            })

        selected_run = next((r for r in runs if r["run_id"] == run_id), None) if run_id else None

        runnable = (
            db.query(Article)
            .filter(Article.status.in_(["planned", "researching", "writing", "reviewing"]))
            .order_by(desc(Article.updated_at)).limit(30).all()
        )

        # Step frequency
        recent_decisions = db.query(AgentDecisionLog).order_by(desc(AgentDecisionLog.created_at)).limit(200).all()
        step_counts = Counter(d.step for d in recent_decisions)
        confidence_counts = Counter(d.confidence for d in recent_decisions)

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        success_runs = sum(1 for r in runs if r["is_complete"])

        return templates.TemplateResponse(request, "agents.html", {
            "request": request, "page": "agents",
            "runs": runs, "selected_run": selected_run,
            "trigger_articles": runnable,
            "projects": db.query(Project).order_by(Project.id).all(),
            "run_id": run_id,
            "total_runs": total_runs,
            "success_runs": success_runs,
            "budget_exceeded": sum(1 for r in runs if r["over_budget"]),
            "est_total_cost": round(total_runs * 0.15, 2),
            "step_counts_json": json.dumps(dict(step_counts.most_common(8))),
            "confidence_counts": dict(confidence_counts),
            "PIPELINE_STEPS": [step for step, _, _ in PIPELINE_STEPS],
            "STATUS_LABELS": STATUS_LABELS, "STATUS_COLORS": STATUS_COLORS,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()



# ── In-memory pipeline run state ─────────────────────────────
_pipeline_runs: dict[str, dict] = {}  # run_id -> {status, article_id, log, started_at}


async def _background_pipeline(run_id: str, article_id: int, project_id: int | None) -> None:
    """在背景執行 orchestrator 並回寫 DB。"""
    from contentflow.agents.orchestrator import run_orchestrator
    from contentflow.models import ArticleStatus, ArticleTask

    _pipeline_runs[run_id] = {
        "status": "running", "article_id": article_id,
        "log": ["✅ Pipeline 啟動…"], "started_at": datetime.now(timezone.utc).isoformat()
    }

    db = _db()
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            _pipeline_runs[run_id]["status"] = "error"
            _pipeline_runs[run_id]["log"].append(f"❌ Article id={article_id} 不存在")
            return

        keyword = article.primary_keyword or article.title or "untitled"
        title = article.title or keyword
        article.status = "researching"
        db.commit()
    finally:
        db.close()

    _pipeline_runs[run_id]["log"].append(f"📖 開始研究：{title}")

    task = ArticleTask(
        task_id=run_id,
        title=title,
        keywords=[keyword],
    )

    try:
        result = await run_orchestrator(task, project_id=project_id, article_id=article_id)
        _pipeline_runs[run_id]["log"].append("✍️  草稿生成完成")

        db2 = _db()
        try:
            article2 = db2.query(Article).filter(Article.id == article_id).first()
            if article2:
                draft = result.draft
                if draft:
                    article2.draft_content = draft.content_markdown
                    article2.meta_title = draft.meta_title
                    article2.meta_description = draft.meta_description
                    article2.slug = draft.slug
                    article2.faq_schema_json = draft.faq_schema_json
                    article2.article_schema_json = draft.article_schema_json
                    article2.seo_score = draft.seo_score or None
                article2.status = result.status or "reviewing"
                article2.updated_at = datetime.now(timezone.utc)
                db2.commit()
        finally:
            db2.close()

        _pipeline_runs[run_id]["status"] = "done"
        _pipeline_runs[run_id]["log"].append(f"🎉 完成！狀態：{result.status}")

    except Exception as exc:
        _pipeline_runs[run_id]["status"] = "error"
        _pipeline_runs[run_id]["log"].append(f"❌ 失敗：{exc}")
        db3 = _db()
        try:
            a3 = db3.query(Article).filter(Article.id == article_id).first()
            if a3:
                a3.status = "failed"
                db3.commit()
        finally:
            db3.close()


@admin_app.post("/agents/trigger")
async def trigger_agent(
    request: Request,
    background_tasks: BackgroundTasks,
    article_id: int = Form(0),
    project_id: int = Form(0),
    start_step: str = Form("research"),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    if not article_id:
        return RedirectResponse("/admin/agents?error=no_article", status_code=303)
    run_id = str(uuid.uuid4())
    background_tasks.add_task(
        _background_pipeline, run_id, article_id, project_id or None
    )
    return RedirectResponse(f"/admin/agents?run_id={run_id}&triggered={article_id}", status_code=303)


@admin_app.get("/agents/run-status/{run_id}")
async def run_status(request: Request, run_id: str):
    """輪詢 pipeline 執行狀態（JSON）"""
    if not _check_login(request):
        raise HTTPException(status_code=403)
    info = _pipeline_runs.get(run_id, {"status": "unknown", "log": []})
    return JSONResponse(info)



# ═══════════════════════════════════════════════════════════════
# KNOWLEDGE BASE  /knowledge
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request, cat: str = "", confidence: str = "", q: str = "", page: int = 1):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        query = db.query(KnowledgeEntry).order_by(desc(KnowledgeEntry.evidence_count), desc(KnowledgeEntry.updated_at))
        if cat:
            query = query.filter(KnowledgeEntry.category == cat)
        if confidence:
            query = query.filter(KnowledgeEntry.confidence_level == confidence)
        if q:
            query = query.filter(KnowledgeEntry.pattern.ilike(f"%{q}%"))
        all_entries = query.all()

        # Pagination
        per_page = 30
        total = len(all_entries)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(1, min(page, total_pages))
        entries = all_entries[(page - 1) * per_page : page * per_page]

        all_cats = [r[0] for r in db.query(KnowledgeEntry.category).distinct().all() if r[0]]
        active = db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count()
        override_count = db.query(KnowledgeAuditLog).filter(KnowledgeAuditLog.action == "override").count()

        cat_raw = db.query(KnowledgeEntry.category, func.count()).group_by(KnowledgeEntry.category).all()
        cat_counts = {c: n for c, n in cat_raw}

        recent_audits = db.query(KnowledgeAuditLog).order_by(desc(KnowledgeAuditLog.created_at)).limit(8).all()

        return templates.TemplateResponse(request, "knowledge.html", {
            "request": request, "page": "knowledge",
            "entries": entries, "cat_filter": cat, "filter_confidence": confidence, "q": q,
            "categories": all_cats,
            "total": total, "active_count": active,
            "override_count": override_count,
            "page": page, "total_pages": total_pages,
            "cat_counts_json": json.dumps({k: v for k, v in cat_counts.items() if k}),
            "recent_audits": recent_audits,
            "CONFIDENCE_LABELS": CONFIDENCE_LABELS, "CONFIDENCE_COLORS": CONFIDENCE_COLORS,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


@admin_app.post("/knowledge/{entry_id}/toggle")
async def toggle_knowledge(request: Request, entry_id: int):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        if entry:
            entry.is_active = not entry.is_active
            entry.updated_at = datetime.now(timezone.utc)
            db.add(KnowledgeAuditLog(
                entry_id=entry_id,
                action="deactivate" if not entry.is_active else "reactivate",
                reason="Admin 手動操作", operator="human",
            ))
            db.commit()
        return RedirectResponse("/admin/knowledge", status_code=303)
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SCHEDULER  /scheduler
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/scheduler", response_class=HTMLResponse)
async def scheduler_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        logs = db.query(SchedulerLog).order_by(desc(SchedulerLog.started_at)).limit(50).all()

        job_latest: dict = {}
        for log in logs:
            if log.job_id not in job_latest:
                job_latest[log.job_id] = log

        known_jobs = [
            {"id": "sync_gsc_all_projects",    "name": "GSC 排名同步",    "schedule": "每日 03:00", "icon": "📊"},
            {"id": "sync_ga4_all_projects",     "name": "GA4 頁面指標",    "schedule": "每日 03:30", "icon": "📈"},
            {"id": "run_competitor_serp_check", "name": "競品 SERP 追蹤",  "schedule": "每週一 04:00","icon": "🔍"},
            {"id": "run_attribution_engine",    "name": "成效歸因分析",    "schedule": "每週一 05:00","icon": "🧮"},
        ]
        for j in known_jobs:
            j["latest"] = job_latest.get(j["id"])

        success_c = db.query(SchedulerLog).filter(SchedulerLog.status == "success").count()
        fail_c    = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count()

        cutoff7 = datetime.now(timezone.utc) - timedelta(days=7)
        logs7 = db.query(SchedulerLog).filter(SchedulerLog.started_at >= cutoff7).all()
        daily_stats: dict = {}
        for log in logs7:
            day = log.started_at.strftime("%m/%d")
            if day not in daily_stats:
                daily_stats[day] = {"success": 0, "failed": 0}
            daily_stats[day][log.status] = daily_stats[day].get(log.status, 0) + 1

        return templates.TemplateResponse(request, "scheduler.html", {
            "request": request, "page": "scheduler",
            "logs": logs, "known_jobs": known_jobs,
            "success_count": success_c, "fail_count": fail_c,
            "total_count": db.query(SchedulerLog).count(),
            "daily_stats": json.dumps(daily_stats),
            "scheduler_enabled": settings.scheduler_enabled,
            "SCHEDULER_TIMEZONE": settings.scheduler_timezone,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SYSTEM HEALTH  /health
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/health", response_class=HTMLResponse)
async def health_page(request: Request):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        def _svc(name, ok, model="", description="", latency_ms=None):
            return SimpleNamespace(name=name, ok=ok, model=model, description=description, latency_ms=latency_ms)

        api_groups = {
            "ai": [
                _svc("OpenAI",    bool(settings.openai_api_key),    model=getattr(settings, "llm_lite_model", ""),     description="Research + SEO QA + FactCheck"),
                _svc("Anthropic", bool(settings.anthropic_api_key), model=getattr(settings, "llm_writing_model", ""),  description="Writing Agent（主力寫作）"),
            ],
            "data": [
                _svc("SerpAPI / Serper", bool(getattr(settings, "serper_api_key", None) or getattr(settings, "serpapi_key", None)), description="SERP 分析 + 競品追蹤"),
                _svc("Google Search Console", bool(getattr(settings, "google_service_account_file", None)), description="每日 GSC 排名同步"),
                _svc("PubMed / NCBI", bool(getattr(settings, "ncbi_api_key", None)), description="Research Agent 學術佐證"),
            ],
            "publish": [
                _svc("WordPress", bool(getattr(settings, "wordpress_site_url", None)), description="文章自動發布"),
                _svc("ForgeBase", bool(getattr(settings, "forgebase_api_base_url", None)), description="ForgeBase 發布後端"),
            ],
            "notify": [
                _svc("Slack Webhook", bool(getattr(settings, "slack_webhook_url", None)), description="排程失敗通知"),
            ],
        }
        all_svcs = [s for grp in api_groups.values() for s in grp]
        ok_count = sum(1 for s in all_svcs if s.ok)
        total_services = len(all_svcs)
        all_ok = ok_count == total_services
        error_count = total_services - ok_count

        db_stats = [
            SimpleNamespace(table="articles",        count=db.query(Article).count()),
            SimpleNamespace(table="keywords",         count=db.query(Keyword).count()),
            SimpleNamespace(table="seo_rankings",     count=db.query(SEORanking).count()),
            SimpleNamespace(table="agent_decisions",  count=db.query(AgentDecisionLog).count()),
            SimpleNamespace(table="knowledge_entries",count=db.query(KnowledgeEntry).count()),
            SimpleNamespace(table="scheduler_logs",   count=db.query(SchedulerLog).count()),
            SimpleNamespace(table="topic_clusters",   count=db.query(TopicCluster).count()),
            SimpleNamespace(table="projects",         count=db.query(Project).count()),
        ]

        total_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0
        monthly_runs = db.query(func.count(func.distinct(AgentDecisionLog.run_id))).filter(
            AgentDecisionLog.created_at >= datetime.now(timezone.utc) - timedelta(days=30)
        ).scalar() or 0
        avg_article_cost = 0.15  # placeholder
        month_cost = round(monthly_runs * avg_article_cost, 2)
        total_cost = round(total_runs * avg_article_cost, 2)

        recent_errors = db.query(SchedulerLog).filter(SchedulerLog.status == "failed").order_by(desc(SchedulerLog.started_at)).limit(5).all()

        db_display = settings.database_url
        if "@" in db_display:
            db_display = db_display.split("@")[-1]

        return templates.TemplateResponse(request, "health.html", {
            "request": request, "page": "health",
            "api_groups": api_groups, "all_ok": all_ok,
            "ok_count": ok_count, "error_count": error_count, "total_services": total_services,
            "db_stats": db_stats, "total_rows": sum(s.count for s in db_stats),
            "recent_errors": recent_errors,
            "total_pipeline_runs": total_runs, "monthly_runs": monthly_runs,
            "avg_article_cost": avg_article_cost,
            "month_cost": month_cost, "total_cost": total_cost,
            "scheduler_enabled": settings.scheduler_enabled,
            "database_url": db_display,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# SETTINGS  /settings
# ═══════════════════════════════════════════════════════════════

@admin_app.post("/settings/project/save")
async def save_project(
    request: Request,
    project_id: int = Form(0),
    slug: str = Form(...),
    name: str = Form(...),
    brand_name: str = Form(""),
    brand_url: str = Form(""),
    brand_description: str = Form(""),
    industry: str = Form(""),
    writing_principles: str = Form(""),
    serp_gl: str = Form("tw"),
    serp_hl: str = Form("zh-tw"),
):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        now = datetime.now(timezone.utc)
        if project_id:
            proj = db.query(Project).filter(Project.id == project_id).first()
            if proj:
                proj.name = name; proj.slug = slug
                proj.brand_name = brand_name; proj.brand_url = brand_url
                proj.brand_description = brand_description; proj.industry = industry
                proj.writing_principles = writing_principles
                proj.serp_gl = serp_gl; proj.serp_hl = serp_hl
                proj.updated_at = now
                db.commit()
                return RedirectResponse(f"/admin/settings?project_id={proj.id}&saved=1", status_code=303)
        else:
            proj = Project(
                slug=slug, name=name,
                brand_name=brand_name, brand_url=brand_url,
                brand_description=brand_description, industry=industry,
                writing_principles=writing_principles,
                serp_gl=serp_gl, serp_hl=serp_hl,
                locale="zh-tw",
                created_at=now, updated_at=now,
            )
            db.add(proj); db.commit(); db.refresh(proj)
            return RedirectResponse(f"/admin/settings?project_id={proj.id}&saved=1", status_code=303)
    finally:
        db.close()


@admin_app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, project_id: int = 0):
    if not _check_login(request):
        return RedirectResponse("/admin/login", status_code=303)
    db = _db()
    try:
        projects = db.query(Project).order_by(Project.name).all()
        if project_id == 0 and projects:
            project_id = projects[0].id

        current_project = None
        rules_by_type: dict = {}
        strategy_by_section: dict = {}
        products = []
        legal_by_type: dict = {}

        if project_id:
            current_project = db.query(Project).filter(Project.id == project_id).first()
            rules = db.query(WritingRule).filter(WritingRule.project_id == project_id).order_by(WritingRule.order_num).all()
            for r in rules:
                rules_by_type.setdefault(r.rule_type or "其他", []).append(r)
            strats = db.query(ContentStrategy).filter(ContentStrategy.project_id == project_id).order_by(ContentStrategy.order_num).all()
            for s in strats:
                strategy_by_section.setdefault(s.section or "其他", []).append(s)
            products = db.query(Product).filter(Product.project_id == project_id).all()
            legal = db.query(LegalTerm).filter(LegalTerm.project_id == project_id).all()
            for lt in legal:
                legal_by_type.setdefault(lt.term_type or "other", []).append(lt)

        return templates.TemplateResponse(request, "settings.html", {
            "request": request, "page": "settings",
            "projects": projects, "current_project": current_project, "project_id": project_id,
            "rules_by_type": rules_by_type, "strategy_by_section": strategy_by_section,
            "products": products, "legal_by_type": legal_by_type,
            "llm_writing_model": settings.llm_writing_model,
            "llm_lite_model": settings.llm_lite_model,
            "scheduler_enabled": settings.scheduler_enabled,
            "scheduler_timezone": settings.scheduler_timezone,
            "now": datetime.now(timezone.utc),
        })
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AJAX  /api/*
# ═══════════════════════════════════════════════════════════════

@admin_app.get("/api/stats")
async def api_stats(request: Request):
    if not _check_login(request):
        raise HTTPException(status_code=403)
    db = _db()
    try:
        return {
            "articles":        db.query(Article).count(),
            "published":       db.query(Article).filter(Article.status == "published").count(),
            "keywords":        db.query(Keyword).count(),
            "clusters":        db.query(TopicCluster).count(),
            "knowledge":       db.query(KnowledgeEntry).filter(KnowledgeEntry.is_active == True).count(),
            "scheduler_errors":db.query(SchedulerLog).filter(SchedulerLog.status == "failed").count(),
            "pipeline_runs":   db.query(func.count(func.distinct(AgentDecisionLog.run_id))).scalar() or 0,
        }
    finally:
        db.close()
