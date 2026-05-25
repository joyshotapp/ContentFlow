"""Admin 儀表：發布安全閘成效、意圖命中 → Refresh 優先佇列（Phase A，無模型訓練）。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from contentflow.models.database import Article, KnowledgeEntry, Project
from contentflow.utils.publish_safety import (
    article_has_factcheck_risk,
    can_auto_publish_article,
    parse_factcheck_flags,
)

INTENT_LOW_THRESHOLD = 45.0
INTENT_STALE_DAYS = 28


def _as_utc(dt: datetime | None) -> datetime | None:
    """PostgreSQL 可能回傳 naive datetime，統一為 UTC aware 再比較。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _project_threshold(project: Project | None) -> int:
    if not project:
        return 85
    return int(project.auto_publish_min_score or 85)


def build_publish_gate_snapshot(db: Session, project_id: int) -> dict[str, Any]:
    """彙總發布閘相關 KPI（規則層，非 LLM 機率）。"""
    project = db.get(Project, project_id)
    threshold = _project_threshold(project)
    auto_on = bool(project and project.auto_publish_enabled)

    base = db.query(Article).filter(Article.project_id == project_id)
    articles = base.all()

    status_counts: dict[str, int] = {}
    factcheck_risk_count = 0
    factcheck_flag_total = 0
    seo_below_threshold = 0
    approved_ready = 0
    blocked_if_auto: list[dict[str, Any]] = []

    for art in articles:
        st = (art.status or "unknown").strip()
        status_counts[st] = status_counts.get(st, 0) + 1

        flags = parse_factcheck_flags(art.factcheck_flags_json)
        if flags:
            factcheck_flag_total += len(flags)
        if article_has_factcheck_risk(art.factcheck_flags_json):
            factcheck_risk_count += 1

        score = art.seo_score or 0
        if score < threshold:
            seo_below_threshold += 1

        can_pub = can_auto_publish_article(
            pipeline_status=art.status,
            factcheck_flags_json=art.factcheck_flags_json,
            compliance_profile=getattr(project, "compliance_profile", None) if project else None,
            auto_publish_enabled=auto_on,
        )
        if can_pub:
            approved_ready += 1
        elif st in ("approved", "review_required") and (art.draft_content or "").strip():
            reason_parts = []
            if not auto_on:
                reason_parts.append("專案未開自動發布")
            if st != "approved":
                reason_parts.append(f"狀態={st}")
            if article_has_factcheck_risk(art.factcheck_flags_json):
                reason_parts.append("FactCheck 需審核")
            if st == "approved" and score < threshold:
                reason_parts.append(f"SEO {score} < 門檻 {threshold}")
            blocked_if_auto.append({
                "id": art.id,
                "title": (art.title or "")[:80],
                "status": st,
                "seo_score": score,
                "reason": " · ".join(reason_parts) or "未通過發布閘",
            })

    blocked_if_auto.sort(key=lambda x: (x["status"] != "review_required", x["seo_score"]))
    blocked_if_auto = blocked_if_auto[:25]

    intent_low_kb = (
        db.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.category == "intent_match_low",
            KnowledgeEntry.is_active.is_(True),
        )
        .count()
    )

    return {
        "project_name": project.name if project else "",
        "auto_publish_enabled": auto_on,
        "seo_threshold": threshold,
        "status_counts": status_counts,
        "review_required": status_counts.get("review_required", 0),
        "approved": status_counts.get("approved", 0),
        "published": status_counts.get("published", 0),
        "factcheck_risk_count": factcheck_risk_count,
        "factcheck_flag_total": factcheck_flag_total,
        "seo_below_threshold": seo_below_threshold,
        "approved_ready_to_auto_publish": approved_ready,
        "blocked_candidates": blocked_if_auto,
        "intent_low_knowledge_entries": intent_low_kb,
        "total_articles": len(articles),
    }


def build_intent_refresh_queue(db: Session, project_id: int, *, limit: int = 30) -> dict[str, Any]:
    """意圖低分與 Refresh 信號合併為優先佇列。"""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=INTENT_STALE_DAYS)

    published = (
        db.query(Article)
        .filter(Article.project_id == project_id, Article.status == "published")
        .order_by(Article.intent_match_score.asc().nullsfirst())
        .all()
    )

    queue: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    def _add(art: Article, priority: str, reason: str, score: float | None) -> None:
        if art.id in seen_ids:
            return
        seen_ids.add(art.id)
        queue.append({
            "id": art.id,
            "title": (art.title or "")[:80],
            "slug": art.slug or "",
            "primary_keyword": (art.primary_keyword or "")[:60],
            "intent_match_score": score,
            "intent_match_checked_at": art.intent_match_checked_at,
            "publish_url": art.publish_url or "",
            "priority": priority,
            "reason": reason,
        })

    for art in published:
        score = art.intent_match_score
        if score is not None and score < INTENT_LOW_THRESHOLD:
            _add(
                art,
                "high",
                f"意圖命中 {score} < {INTENT_LOW_THRESHOLD}",
                score,
            )

    for art in published:
        if art.id in seen_ids:
            continue
        score = art.intent_match_score
        checked = art.intent_match_checked_at
        published_at = _as_utc(art.published_at)
        checked_utc = _as_utc(checked)
        if score is None and published_at and published_at < stale_cutoff:
            _add(art, "medium", f"已發布逾 {INTENT_STALE_DAYS} 天未評分", None)
        elif score is None and (not checked_utc or checked_utc < stale_cutoff):
            _add(art, "medium", "尚未有意圖命中評分", None)

    kb_rows = (
        db.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.category.in_(("intent_match_low", "refresh_priority")),
            KnowledgeEntry.is_active.is_(True),
        )
        .order_by(KnowledgeEntry.evidence_count.desc())
        .limit(15)
        .all()
    )
    kb_hints = [
        {
            "title": (e.pattern or "")[:100],
            "category": e.category,
            "evidence_count": e.evidence_count or 0,
            "content_preview": (e.pattern or "")[:200],
        }
        for e in kb_rows
    ]

    priority_order = {"high": 0, "medium": 1, "low": 2}
    queue.sort(
        key=lambda x: (
            priority_order.get(x["priority"], 9),
            x["intent_match_score"] if x["intent_match_score"] is not None else 999,
        ),
    )
    queue = queue[:limit]

    scored = [a for a in published if a.intent_match_score is not None]
    avg_intent = round(sum(a.intent_match_score for a in scored) / len(scored), 1) if scored else None
    low_count = sum(
        1 for a in published
        if a.intent_match_score is not None and a.intent_match_score < INTENT_LOW_THRESHOLD
    )

    return {
        "queue": queue,
        "kb_hints": kb_hints,
        "published_count": len(published),
        "low_intent_count": low_count,
        "avg_intent_score": avg_intent,
        "intent_threshold": INTENT_LOW_THRESHOLD,
    }
