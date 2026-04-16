"""ContentFlow AI 對話 Agent — L1 報告 + L2 分析 + L3 指令

提供基於 OpenAI function calling 的對話介面，
讓使用者用自然語言查詢系統狀態、分析數據、並觸發操作。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import desc, func

from ..config import settings
from ..db import SessionLocal
from ..models.database import (
    Article,
    ActionOutcome,
    ContentCalendar,
    Competitor,
    CompetitorSnapshot,
    GAPageMetric,
    Keyword,
    KnowledgeEntry,
    PipelineRun,
    Project,
    ReflectionLog,
    SchedulerLog,
    SEORanking,
    StrategicPlan,
    TopicCluster,
    WritingRule,
)

# ── System prompt ─────────────────────────────────────────────

SYSTEM_PROMPT = """\
你是 ContentFlow AI 助理，一個 SEO 自主優化系統的智慧對話介面。
你能做三件事：
1. **報告**：查詢系統狀態（文章、排名、排程、Pipeline 執行情況等）
2. **分析**：交叉分析數據並產出 SEO 洞察（關鍵字 ROI、排名趨勢、競品動態等）
3. **操作**：根據使用者指示觸發系統動作（產文、刷新、排程等）

回答規則：
- 使用繁體中文（台灣用語）
- 簡潔有力，避免冗長
- 數據盡量用表格呈現
- 主動提供可操作的建議
- 如果對查詢結果有 SEO 觀點，主動補充
- 金額用美元、排名用 Google 排名位置

你代表的系統名稱是「ContentFlow」，品牌名稱是「{site_name}」。
現在時間：{now}
""".strip()

# ── Tool definitions (OpenAI function calling schema) ─────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_system_overview",
            "description": "取得系統整體概觀：文章數（各狀態）、關鍵字數、排程狀態、最近 Pipeline 等",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_articles",
            "description": "查詢文章列表，支援狀態過濾、關鍵字搜尋、排序",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "文章狀態過濾：planned/writing/reviewing/published/failed",
                        "enum": ["planned", "writing", "reviewing", "published", "failed"],
                    },
                    "keyword": {"type": "string", "description": "關鍵字搜尋（模糊比對標題或主關鍵字）"},
                    "limit": {"type": "integer", "description": "回傳筆數上限（預設 10）", "default": 10},
                    "sort_by": {
                        "type": "string",
                        "description": "排序欄位",
                        "enum": ["seo_score", "updated_at", "published_at"],
                        "default": "updated_at",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_article_detail",
            "description": "取得單篇文章的詳細資訊（SEO 分數、狀態、發布 URL、Pipeline 成本等）",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "文章 ID"},
                },
                "required": ["article_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_rankings",
            "description": "查詢 GSC 排名數據：特定關鍵字的排名、點擊、曝光趨勢",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要查詢的關鍵字"},
                    "days": {"type": "integer", "description": "查詢最近 N 天（預設 28）", "default": 28},
                    "limit": {"type": "integer", "description": "回傳筆數上限", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_top_keywords",
            "description": "查詢表現最好或最差的關鍵字（依點擊、曝光、排名）",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "排序指標",
                        "enum": ["clicks", "impressions", "position_best", "position_worst"],
                    },
                    "days": {"type": "integer", "description": "時間範圍（天）", "default": 7},
                    "limit": {"type": "integer", "description": "回傳筆數", "default": 10},
                },
                "required": ["metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_ranking_changes",
            "description": "找出排名變化最大的關鍵字（上升或下降）",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "description": "升或降",
                        "enum": ["up", "down"],
                    },
                    "days": {"type": "integer", "description": "比較天數", "default": 7},
                    "limit": {"type": "integer", "description": "筆數", "default": 10},
                },
                "required": ["direction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_pipeline_runs",
            "description": "查詢最近的 Pipeline 執行記錄（狀態、成本、SEO 分數）",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "過濾狀態", "enum": ["completed", "failed", "running"]},
                    "limit": {"type": "integer", "description": "筆數", "default": 10},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_scheduler_health",
            "description": "查詢排程系統健康度：最近執行紀錄、失敗 job、下次排程時間",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_competitors",
            "description": "查詢競品排名追蹤數據",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "指定關鍵字（可選）"},
                    "days": {"type": "integer", "description": "天數範圍", "default": 14},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_content_calendar",
            "description": "查詢內容日曆排程",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "過濾狀態", "enum": ["planned", "in_progress", "completed"]},
                    "limit": {"type": "integer", "description": "筆數", "default": 15},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_learning_insights",
            "description": "查詢學習閉環資料：最近反思日誌、知識庫更新、寫作規範更新",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "天數範圍", "default": 14},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_article_decision",
            "description": "解釋某篇文章的 Agent 決策過程（為什麼選這個關鍵字、為什麼 SEO 分數是這樣）",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "文章 ID"},
                },
                "required": ["article_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_pipeline",
            "description": "觸發文章產生 Pipeline（需要指定關鍵字）",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "要產文的關鍵字"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trigger_refresh",
            "description": "觸發文章更新/刷新 Pipeline",
            "parameters": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "integer", "description": "要刷新的文章 ID"},
                },
                "required": ["article_id"],
            },
        },
    },
]

# ── Tool implementations ──────────────────────────────────────


def _tool_query_system_overview(**kwargs: Any) -> dict:
    with SessionLocal() as session:
        projects = session.query(Project).all()
        project_count = len(projects)
        project_names = [p.name for p in projects[:5]]

        status_counts = dict(
            session.query(Article.status, func.count())
            .group_by(Article.status).all()
        )
        total_articles = sum(status_counts.values())
        total_keywords = session.query(Keyword).count()

        recent_runs = (
            session.query(PipelineRun)
            .order_by(desc(PipelineRun.created_at))
            .limit(3).all()
        )
        runs_info = [
            {"run_id": r.run_id[:8], "status": r.status, "step": r.current_step,
             "seo": r.seo_score, "cost": f"${float(r.total_cost or 0):.3f}",
             "time": r.created_at.strftime("%m/%d %H:%M") if r.created_at else ""}
            for r in recent_runs
        ]

        recent_scheduler = (
            session.query(SchedulerLog)
            .order_by(desc(SchedulerLog.started_at))
            .limit(5).all()
        )
        scheduler_info = [
            {"job": s.job_name, "status": s.status,
             "time": s.started_at.strftime("%m/%d %H:%M") if s.started_at else ""}
            for s in recent_scheduler
        ]

        # 最近 7 天 GSC 總點擊 / 曝光
        week_ago = datetime.now(timezone.utc).date() - timedelta(days=7)
        gsc_agg = (
            session.query(
                func.sum(SEORanking.clicks),
                func.sum(SEORanking.impressions),
            )
            .filter(SEORanking.tracked_date >= week_ago)
            .first()
        )

    return {
        "projects": project_names,
        "project_count": project_count,
        "articles": {"total": total_articles, **status_counts},
        "keywords": total_keywords,
        "gsc_7d": {
            "clicks": int(gsc_agg[0] or 0) if gsc_agg else 0,
            "impressions": int(gsc_agg[1] or 0) if gsc_agg else 0,
        },
        "recent_pipeline_runs": runs_info,
        "recent_scheduler": scheduler_info,
    }


def _tool_query_articles(**kwargs: Any) -> dict:
    status = kwargs.get("status")
    keyword = kwargs.get("keyword")
    limit = min(kwargs.get("limit", 10), 30)
    sort_by = kwargs.get("sort_by", "updated_at")

    with SessionLocal() as session:
        q = session.query(Article)
        if status:
            q = q.filter(Article.status == status)
        if keyword:
            q = q.filter(
                (Article.title.ilike(f"%{keyword}%")) |
                (Article.primary_keyword.ilike(f"%{keyword}%"))
            )
        sort_col = getattr(Article, sort_by, Article.updated_at)
        q = q.order_by(desc(sort_col))
        articles = q.limit(limit).all()

    return {
        "count": len(articles),
        "articles": [
            {
                "id": a.id,
                "title": a.title,
                "keyword": a.primary_keyword,
                "status": a.status,
                "seo_score": a.seo_score,
                "published_at": a.published_at.strftime("%Y-%m-%d") if a.published_at else None,
                "updated_at": a.updated_at.strftime("%Y-%m-%d %H:%M") if a.updated_at else None,
            }
            for a in articles
        ],
    }


def _tool_query_article_detail(**kwargs: Any) -> dict:
    article_id = kwargs["article_id"]
    with SessionLocal() as session:
        a = session.get(Article, article_id)
        if not a:
            return {"error": f"找不到文章 ID={article_id}"}

        run = (
            session.query(PipelineRun)
            .filter(PipelineRun.run_id == a.slug)
            .order_by(desc(PipelineRun.created_at))
            .first()
        )

        rankings = (
            session.query(SEORanking)
            .filter(SEORanking.keyword == a.primary_keyword)
            .order_by(desc(SEORanking.tracked_date))
            .limit(5).all()
        )

    return {
        "id": a.id,
        "title": a.title,
        "keyword": a.primary_keyword,
        "status": a.status,
        "seo_score": a.seo_score,
        "meta_title": a.meta_title,
        "meta_description": a.meta_description,
        "publish_url": a.publish_url,
        "hero_image": a.hero_image_url,
        "content_length": len(a.draft_content or ""),
        "published_at": a.published_at.strftime("%Y-%m-%d") if a.published_at else None,
        "pipeline": {
            "cost": f"${float(run.total_cost or 0):.3f}" if run else None,
            "seo_score": run.seo_score if run else None,
            "status": run.status if run else None,
        },
        "recent_rankings": [
            {"date": r.tracked_date.isoformat(), "pos": r.position,
             "clicks": r.clicks, "impressions": r.impressions}
            for r in rankings
        ],
    }


def _tool_query_rankings(**kwargs: Any) -> dict:
    keyword = kwargs.get("keyword")
    days = kwargs.get("days", 28)
    limit = min(kwargs.get("limit", 20), 50)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with SessionLocal() as session:
        q = session.query(SEORanking).filter(SEORanking.tracked_date >= cutoff)
        if keyword:
            q = q.filter(SEORanking.keyword.ilike(f"%{keyword}%"))
        q = q.order_by(desc(SEORanking.tracked_date))
        rows = q.limit(limit).all()

    return {
        "count": len(rows),
        "rankings": [
            {
                "keyword": r.keyword,
                "position": r.position,
                "clicks": r.clicks,
                "impressions": r.impressions,
                "ctr": round(float(r.ctr or 0), 4),
                "date": r.tracked_date.isoformat() if r.tracked_date else "",
            }
            for r in rows
        ],
    }


def _tool_query_top_keywords(**kwargs: Any) -> dict:
    metric = kwargs["metric"]
    days = kwargs.get("days", 7)
    limit = min(kwargs.get("limit", 10), 30)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with SessionLocal() as session:
        q = (
            session.query(
                SEORanking.keyword,
                func.sum(SEORanking.clicks).label("total_clicks"),
                func.sum(SEORanking.impressions).label("total_imp"),
                func.avg(SEORanking.position).label("avg_pos"),
            )
            .filter(SEORanking.tracked_date >= cutoff)
            .group_by(SEORanking.keyword)
        )

        if metric == "clicks":
            q = q.order_by(desc("total_clicks"))
        elif metric == "impressions":
            q = q.order_by(desc("total_imp"))
        elif metric == "position_best":
            q = q.order_by("avg_pos")
        else:  # position_worst
            q = q.order_by(desc("avg_pos"))

        rows = q.limit(limit).all()

    return {
        "metric": metric,
        "days": days,
        "keywords": [
            {
                "keyword": r.keyword,
                "clicks": int(r.total_clicks or 0),
                "impressions": int(r.total_imp or 0),
                "avg_position": round(float(r.avg_pos or 0), 1),
            }
            for r in rows
        ],
    }


def _tool_query_ranking_changes(**kwargs: Any) -> dict:
    direction = kwargs["direction"]
    days = kwargs.get("days", 7)
    limit = min(kwargs.get("limit", 10), 30)

    now_date = datetime.now(timezone.utc).date()
    recent_start = now_date - timedelta(days=days)
    prev_start = recent_start - timedelta(days=days)

    with SessionLocal() as session:
        # Recent avg position
        recent = dict(
            session.query(
                SEORanking.keyword,
                func.avg(SEORanking.position).label("avg"),
            )
            .filter(SEORanking.tracked_date >= recent_start)
            .group_by(SEORanking.keyword).all()
        )
        # Previous avg position
        prev = dict(
            session.query(
                SEORanking.keyword,
                func.avg(SEORanking.position).label("avg"),
            )
            .filter(
                SEORanking.tracked_date >= prev_start,
                SEORanking.tracked_date < recent_start,
            )
            .group_by(SEORanking.keyword).all()
        )

    changes = []
    for kw, curr_pos in recent.items():
        if kw in prev:
            delta = float(prev[kw]) - float(curr_pos)  # positive = improved
            changes.append({"keyword": kw, "current": round(float(curr_pos), 1),
                           "previous": round(float(prev[kw]), 1), "change": round(delta, 1)})

    changes.sort(key=lambda x: x["change"], reverse=(direction == "up"))
    return {"direction": direction, "changes": changes[:limit]}


def _tool_query_pipeline_runs(**kwargs: Any) -> dict:
    status = kwargs.get("status")
    limit = min(kwargs.get("limit", 10), 30)

    with SessionLocal() as session:
        q = session.query(PipelineRun).order_by(desc(PipelineRun.created_at))
        if status:
            q = q.filter(PipelineRun.status == status)
        runs = q.limit(limit).all()

    return {
        "count": len(runs),
        "runs": [
            {
                "run_id": r.run_id[:8] if r.run_id else "",
                "status": r.status,
                "step": r.current_step,
                "seo_score": r.seo_score,
                "cost": f"${float(r.total_cost or 0):.3f}",
                "created": r.created_at.strftime("%m/%d %H:%M") if r.created_at else "",
            }
            for r in runs
        ],
    }


def _tool_query_scheduler_health(**kwargs: Any) -> dict:
    with SessionLocal() as session:
        recent = (
            session.query(SchedulerLog)
            .order_by(desc(SchedulerLog.started_at))
            .limit(15).all()
        )
        failed_24h = (
            session.query(SchedulerLog)
            .filter(
                SchedulerLog.status == "failed",
                SchedulerLog.started_at >= datetime.now(timezone.utc) - timedelta(hours=24),
            ).count()
        )

    return {
        "failed_24h": failed_24h,
        "recent_jobs": [
            {
                "job": s.job_name,
                "status": s.status,
                "duration": f"{s.duration_seconds:.1f}s" if s.duration_seconds else "?",
                "error": s.error_message[:100] if s.error_message else None,
                "time": s.started_at.strftime("%m/%d %H:%M") if s.started_at else "",
            }
            for s in recent
        ],
    }


def _tool_query_competitors(**kwargs: Any) -> dict:
    keyword = kwargs.get("keyword")
    days = kwargs.get("days", 14)
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)

    with SessionLocal() as session:
        q = session.query(CompetitorSnapshot).filter(
            CompetitorSnapshot.tracked_date >= cutoff
        )
        if keyword:
            q = q.filter(CompetitorSnapshot.keyword.ilike(f"%{keyword}%"))
        q = q.order_by(desc(CompetitorSnapshot.tracked_date))
        rows = q.limit(30).all()

    return {
        "count": len(rows),
        "snapshots": [
            {
                "keyword": r.keyword,
                "competitor_url": r.url,
                "competitor_pos": r.position,
                "our_pos": r.our_position,
                "date": r.tracked_date.isoformat() if r.tracked_date else "",
            }
            for r in rows
        ],
    }


def _tool_query_content_calendar(**kwargs: Any) -> dict:
    status = kwargs.get("status")
    limit = min(kwargs.get("limit", 15), 30)

    with SessionLocal() as session:
        q = session.query(ContentCalendar).order_by(desc(ContentCalendar.id))
        if status:
            q = q.filter(ContentCalendar.status == status)
        items = q.limit(limit).all()

    return {
        "count": len(items),
        "items": [
            {
                "id": c.id,
                "month": c.month,
                "week": c.week,
                "title": c.title,
                "keywords": c.keywords,
                "type": c.article_type,
                "status": c.status,
            }
            for c in items
        ],
    }


def _tool_query_learning_insights(**kwargs: Any) -> dict:
    days = kwargs.get("days", 14)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    with SessionLocal() as session:
        reflections = (
            session.query(ReflectionLog)
            .filter(ReflectionLog.created_at >= cutoff)
            .order_by(desc(ReflectionLog.created_at))
            .limit(10).all()
        )
        total_wr = sum(r.writing_rule_updates or 0 for r in reflections)
        total_kb = sum(r.knowledge_updates or 0 for r in reflections)

        recent_knowledge = (
            session.query(KnowledgeEntry)
            .filter(KnowledgeEntry.created_at >= cutoff)
            .order_by(desc(KnowledgeEntry.created_at))
            .limit(5).all()
        )

        writing_rules_count = session.query(WritingRule).count()

    return {
        "reflections": [
            {
                "type": r.reflection_type,
                "summary": (r.session_summary or "")[:200],
                "wr_updates": r.writing_rule_updates,
                "kb_updates": r.knowledge_updates,
                "date": r.created_at.strftime("%m/%d %H:%M") if r.created_at else "",
            }
            for r in reflections
        ],
        "total_writing_rule_updates": total_wr,
        "total_knowledge_updates": total_kb,
        "active_writing_rules": writing_rules_count,
        "recent_knowledge": [
            {"category": k.category, "pattern": k.pattern[:100],
             "confidence": k.confidence_level}
            for k in recent_knowledge
        ],
    }


def _tool_explain_article_decision(**kwargs: Any) -> dict:
    from ..models.database import AgentDecisionLog
    article_id = kwargs["article_id"]

    with SessionLocal() as session:
        article = session.get(Article, article_id)
        if not article:
            return {"error": f"找不到文章 ID={article_id}"}

        # Find pipeline run for this article
        run = (
            session.query(PipelineRun)
            .filter(PipelineRun.run_id.contains(str(article_id)))
            .order_by(desc(PipelineRun.created_at))
            .first()
        )

        decisions = []
        if run:
            decisions = (
                session.query(AgentDecisionLog)
                .filter(AgentDecisionLog.run_id == run.run_id)
                .order_by(AgentDecisionLog.id)
                .all()
            )

        # Check strategic plan that generated this article
        plan = (
            session.query(StrategicPlan)
            .filter(StrategicPlan.actions_json.contains(article.primary_keyword or ""))
            .order_by(desc(StrategicPlan.plan_date))
            .first()
        )

        # Recent reflection mentioning this article
        reflection = (
            session.query(ReflectionLog)
            .filter(ReflectionLog.article_id == article_id)
            .order_by(desc(ReflectionLog.created_at))
            .first()
        )

    return {
        "article": {"id": article.id, "title": article.title,
                     "keyword": article.primary_keyword, "status": article.status,
                     "seo_score": article.seo_score},
        "pipeline_decisions": [
            {"step": d.step, "decision": d.decision, "reason": d.reason,
             "confidence": d.confidence, "cost": f"${float(d.cost_usd or 0):.3f}"}
            for d in decisions
        ],
        "strategic_plan": {
            "date": plan.plan_date.isoformat() if plan and plan.plan_date else None,
            "summary": plan.summary[:300] if plan else "未找到相關策略計畫",
        },
        "reflection": {
            "summary": reflection.session_summary[:300] if reflection else "尚無反思記錄",
            "wr_updates": reflection.writing_rule_updates if reflection else 0,
        },
    }


def _tool_trigger_pipeline(**kwargs: Any) -> dict:
    """觸發文章產生（回傳任務 ID，實際執行在背景）。"""
    keyword = kwargs["keyword"]
    # 同步的部分：建立 Article + ContentCalendar 記錄
    with SessionLocal() as session:
        project = session.query(Project).first()
        if not project:
            return {"error": "尚無專案，請在設定頁建立"}

        existing = session.query(Article).filter(
            Article.primary_keyword == keyword).first()
        if existing:
            return {
                "error": f"已有相同關鍵字的文章 (ID={existing.id}, 狀態={existing.status})",
                "article_id": existing.id,
            }

        article = Article(
            project_id=project.id,
            primary_keyword=keyword,
            title=keyword,
            slug="",
            draft_content="",
            status="planned",
        )
        session.add(article)
        session.commit()
        session.refresh(article)
        article_id = article.id

    return {
        "success": True,
        "article_id": article_id,
        "message": f"已建立文章 (ID={article_id}) 並排入日曆。系統將在每日 Pipeline 中自動處理，"
                   f"或可至 Agent 執行中心手動觸發。",
    }


def _tool_trigger_refresh(**kwargs: Any) -> dict:
    """標記文章為需要刷新。"""
    article_id = kwargs["article_id"]
    with SessionLocal() as session:
        article = session.get(Article, article_id)
        if not article:
            return {"error": f"找不到文章 ID={article_id}"}
        if article.status not in ("published", "reviewing"):
            return {"error": f"文章狀態為 {article.status}，只有已發布或審核中的文章可以刷新"}

        article.status = "reviewing"
        session.commit()

    return {
        "success": True,
        "message": f"文章 ID={article_id}「{article.title}」已標記為需要刷新。"
                   f"系統將在下次 Refresh 排程中處理。",
    }


# ── Tool dispatcher ───────────────────────────────────────────

TOOL_MAP = {
    "query_system_overview": _tool_query_system_overview,
    "query_articles": _tool_query_articles,
    "query_article_detail": _tool_query_article_detail,
    "query_rankings": _tool_query_rankings,
    "query_top_keywords": _tool_query_top_keywords,
    "query_ranking_changes": _tool_query_ranking_changes,
    "query_pipeline_runs": _tool_query_pipeline_runs,
    "query_scheduler_health": _tool_query_scheduler_health,
    "query_competitors": _tool_query_competitors,
    "query_content_calendar": _tool_query_content_calendar,
    "query_learning_insights": _tool_query_learning_insights,
    "explain_article_decision": _tool_explain_article_decision,
    "trigger_pipeline": _tool_trigger_pipeline,
    "trigger_refresh": _tool_trigger_refresh,
}


def _execute_tool(name: str, arguments: dict) -> str:
    fn = TOOL_MAP.get(name)
    if not fn:
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
    try:
        result = fn(**arguments)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error(f"[ChatAgent] Tool {name} 執行失敗: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ── Main chat function ────────────────────────────────────────

async def chat(
    messages: list[dict],
    project_id: int | None = None,
) -> dict:
    """
    執行一輪對話。

    Args:
        messages: OpenAI 格式 messages [{"role": ..., "content": ...}, ...]
        project_id: 專案 ID（可選，用於 context）

    Returns:
        {"role": "assistant", "content": "...", "tool_calls_count": N}
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.llm_lite_model  # gpt-4o-mini — 快速且便宜

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    system_msg = SYSTEM_PROMPT.format(
        site_name=settings.site_name,
        now=now_str,
    )

    full_messages = [{"role": "system", "content": system_msg}] + messages

    tool_calls_count = 0
    max_rounds = 5  # 防止無限迴圈

    for _ in range(max_rounds):
        response = await client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=2048,
        )

        msg = response.choices[0].message

        if not msg.tool_calls:
            # 直接回答
            return {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls_count": tool_calls_count,
            }

        # 執行 tool calls
        full_messages.append(msg.model_dump())
        for tc in msg.tool_calls:
            tool_calls_count += 1
            args = json.loads(tc.function.arguments)
            logger.info(f"[ChatAgent] Calling {tc.function.name}({args})")
            result = _execute_tool(tc.function.name, args)
            full_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

    # 如果走完所有 rounds 還沒回答
    return {
        "role": "assistant",
        "content": "抱歉，查詢過程較為複雜。請嘗試更具體的問題。",
        "tool_calls_count": tool_calls_count,
    }
