from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from contentflow.models.database import (
    ActionOutcome,
    ActionOutcomeEvaluation,
    Article,
    ClusterMember,
    ContentCalendar,
    KnowledgeEntry,
    Project,
    ReflectionLog,
    SEORanking,
    TopicCluster,
)


def collect_project_context_impl(
    project_id: int,
    session,
    *,
    parse_business_goal_profile,
    is_viable_topic,
    normalize_url_path,
    candidate_article_paths,
    summarize_gsc_feedback_opportunities,
    build_action_outcome_stats,
    detect_seasonal_opportunities,
    calculate_generate_capacity,
    logger,
) -> dict[str, Any]:
    today = date.today()
    week_ago = today - timedelta(days=7)
    current_month = today.month
    current_week = (today.day - 1) // 7 + 1
    project = session.get(Project, project_id)
    business_goal_profile = parse_business_goal_profile(project.business_goals if project else "")

    planned_calendar = (
        session.query(ContentCalendar)
        .filter(
            ContentCalendar.project_id == project_id,
            ContentCalendar.status == "planned",
            ContentCalendar.month <= current_month,
        )
        .all()
    )
    calendar_items = []
    skipped_invalid_topics = 0
    for calendar_entry in planned_calendar:
        ok, _ = is_viable_topic(calendar_entry.title, calendar_entry.keywords or calendar_entry.title, project=project)
        if not ok:
            skipped_invalid_topics += 1
            continue
        calendar_items.append(
            {
                "calendar_id": calendar_entry.id,
                "title": calendar_entry.title,
                "keywords": calendar_entry.keywords,
                "month": calendar_entry.month,
                "week": calendar_entry.week,
                "article_id": calendar_entry.article_id,
            }
        )

    if skipped_invalid_topics:
        logger.warning(f"[StrategicAgent] 跳過 {skipped_invalid_topics} 個無效 planned 題目")

    min_calendar_buffer = 5
    if len(calendar_items) < min_calendar_buffer:
        from ..models.database import Keyword

        existing_kws = {
            kw[0]
            for kw in (
                session.query(Article.primary_keyword)
                .filter(
                    Article.project_id == project_id,
                    Article.status.in_(["published", "planned", "draft", "review_required", "approved"]),
                    Article.primary_keyword.isnot(None),
                )
                .all()
            )
            if kw[0]
        }
        candidate_keywords = (
            session.query(Keyword)
            .filter(
                Keyword.project_id == project_id,
                Keyword.search_volume > 0,
            )
            .order_by(
                Keyword.trend_direction.desc(),
                Keyword.trends_score.desc(),
                Keyword.search_volume.desc(),
            )
            .limit(50)
            .all()
        )
        needed = min_calendar_buffer - len(calendar_items)
        added = 0
        for kw_obj in candidate_keywords:
            if added >= needed:
                break
            if kw_obj.keyword in existing_kws:
                continue
            ok, _ = is_viable_topic(kw_obj.keyword, kw_obj.keyword, project=project)
            if not ok:
                continue
            new_art = Article(
                project_id=project_id,
                title=kw_obj.keyword,
                primary_keyword=kw_obj.keyword,
                status="planned",
            )
            session.add(new_art)
            session.flush()
            new_cal = ContentCalendar(
                project_id=project_id,
                title=kw_obj.keyword,
                keywords=kw_obj.keyword,
                month=current_month,
                week=current_week,
                status="planned",
                article_id=new_art.id,
            )
            session.add(new_cal)
            session.flush()
            calendar_items.append(
                {
                    "calendar_id": new_cal.id,
                    "title": kw_obj.keyword,
                    "keywords": kw_obj.keyword,
                    "month": current_month,
                    "week": current_week,
                    "article_id": new_art.id,
                }
            )
            existing_kws.add(kw_obj.keyword)
            added += 1
        if added > 0:
            session.commit()
            logger.info(
                f"[StrategicAgent] 自動補充日曆：從關鍵字庫新增 {added} 個待產出排程，"
                f"總 planned backlog = {len(calendar_items)}"
            )

    two_weeks_ago = today - timedelta(days=14)
    recent_rankings = (
        session.query(
            SEORanking.keyword,
            SEORanking.position,
            SEORanking.impressions,
            SEORanking.clicks,
            SEORanking.ctr,
            SEORanking.landing_page,
            SEORanking.tracked_date,
        )
        .filter(
            SEORanking.project_id == project_id,
            SEORanking.tracked_date >= two_weeks_ago,
        )
        .all()
    )

    rank_current: dict[str, list[float]] = {}
    rank_previous: dict[str, list[float]] = {}
    for ranking in recent_rankings:
        keyword = ranking.keyword
        position = ranking.position
        if position is None:
            continue
        if ranking.tracked_date and ranking.tracked_date >= week_ago:
            rank_current.setdefault(keyword, []).append(position)
        else:
            rank_previous.setdefault(keyword, []).append(position)

    ranking_changes = []
    for keyword in set(list(rank_current.keys()) + list(rank_previous.keys())):
        curr_avg = sum(rank_current.get(keyword, [99])) / max(len(rank_current.get(keyword, [99])), 1)
        prev_avg = sum(rank_previous.get(keyword, [99])) / max(len(rank_previous.get(keyword, [99])), 1)
        delta = curr_avg - prev_avg
        ranking_changes.append(
            {
                "keyword": keyword,
                "current_position": round(curr_avg, 1),
                "previous_position": round(prev_avg, 1),
                "delta": round(delta, 1),
            }
        )
    ranking_changes.sort(key=lambda item: item["delta"], reverse=True)

    latest_rank_by_path: dict[str, tuple[date | None, float]] = {}
    for row in recent_rankings:
        if row.position is None:
            continue
        path = normalize_url_path(row.landing_page or "")
        if not path:
            continue
        existing = latest_rank_by_path.get(path)
        if existing is None or (row.tracked_date and (existing[0] is None or row.tracked_date > existing[0])):
            latest_rank_by_path[path] = (row.tracked_date, row.position)

    rank_groups = {"A": [], "B": [], "C": [], "D": [], "E": [], "F": []}
    articles_with_rank = (
        session.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.status == "published",
        )
        .all()
    )
    for article in articles_with_rank:
        candidate_paths = candidate_article_paths(article)
        position = next(
            (latest_rank_by_path[path][1] for path in candidate_paths if path in latest_rank_by_path),
            None,
        )
        info = {"article_id": article.id, "title": article.title, "position": position}
        if position is None:
            rank_groups["F"].append(info)
        elif position <= 3:
            rank_groups["A"].append(info)
        elif position <= 10:
            rank_groups["B"].append(info)
        elif position <= 20:
            rank_groups["C"].append(info)
        elif position <= 50:
            rank_groups["D"].append(info)
        else:
            rank_groups["E"].append(info)

    gsc_meta_opportunities, gsc_query_opportunities = summarize_gsc_feedback_opportunities(
        articles_with_rank,
        recent_rankings,
    )

    refresh_candidates = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.category == "refresh_priority",
            KnowledgeEntry.is_active == True,
        )
        .all()
    )
    refresh_items = [{"pattern": item.pattern, "metadata": item.metadata_json} for item in refresh_candidates]

    last_reflection = (
        session.query(ReflectionLog)
        .filter(ReflectionLog.project_id == project_id)
        .order_by(ReflectionLog.created_at.desc())
        .first()
    )
    last_summary = last_reflection.session_summary if last_reflection else ""

    reviewing_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status.in_(["reviewing", "review_required"]))
        .count()
    )
    planned_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "planned")
        .count()
    )
    published_count = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "published")
        .count()
    )

    article_lookup = {
        article.id: {
            "title": article.title,
            "primary_keyword": article.primary_keyword,
            "slug": article.slug,
            "publish_path": normalize_url_path(article.publish_url or ""),
        }
        for article in session.query(Article)
        .filter(Article.project_id == project_id)
        .all()
    }

    recent_outcomes = (
        session.query(ActionOutcome)
        .filter(
            ActionOutcome.project_id == project_id,
            ActionOutcome.success_flag.isnot(None),
            ActionOutcome.success_flag != "too_early",
        )
        .order_by(ActionOutcome.action_date.desc())
        .limit(20)
        .all()
    )
    outcome_summary = []
    for outcome in recent_outcomes:
        outcome_summary.append(
            {
                "action_type": outcome.action_type,
                "keyword": outcome.primary_keyword,
                "action_date": outcome.action_date.isoformat() if outcome.action_date else None,
                "baseline_rank": outcome.baseline_rank,
                "rank_after_28d": outcome.rank_after_28d,
                "rank_delta": outcome.rank_delta,
                "success": outcome.success_flag,
                "confidence": outcome.learning_confidence,
            }
        )

    recent_evaluations = {}
    if recent_outcomes:
        recent_outcome_ids = [outcome.id for outcome in recent_outcomes if getattr(outcome, "id", None) is not None]
        if recent_outcome_ids:
            recent_evaluations = {
                row.action_outcome_id: row
                for row in session.query(ActionOutcomeEvaluation)
                .filter(ActionOutcomeEvaluation.action_outcome_id.in_(recent_outcome_ids))
                .all()
            }

    outcome_stats, action_policy_scores = build_action_outcome_stats(recent_outcomes, recent_evaluations)

    from .analytics_agent import CannibalizationDetector

    cannib_pairs = CannibalizationDetector(session).detect(project_id)
    cannibalization_summary = [
        {
            "keyword": pair.keyword,
            "competing_titles": pair.article_titles[:3],
            "suggestion": pair.suggestion,
        }
        for pair in cannib_pairs[:5]
    ]

    cluster_gaps_raw = (
        session.query(ClusterMember.keyword, TopicCluster.pillar_keyword)
        .join(TopicCluster, ClusterMember.cluster_id == TopicCluster.id)
        .filter(
            TopicCluster.project_id == project_id,
            ClusterMember.article_id == None,
        )
        .all()
    )
    cluster_gaps_summary = [
        {"pillar": row.pillar_keyword, "missing_keyword": row.keyword}
        for row in cluster_gaps_raw[:10]
    ]

    from ..models.database import Keyword

    trending_keywords = (
        session.query(Keyword.keyword, Keyword.trend_direction, Keyword.trends_score)
        .filter(
            Keyword.project_id == project_id,
            Keyword.trend_direction.isnot(None),
            Keyword.trend_direction != "stable",
        )
        .order_by(Keyword.trends_score.desc())
        .limit(10)
        .all()
    )
    keyword_trends_summary = [
        {"keyword": row.keyword, "direction": row.trend_direction, "score": row.trends_score}
        for row in trending_keywords
    ]

    seasonal_opportunities = detect_seasonal_opportunities(session, project_id, existing_kws=None)

    context_snapshot = {
        "today": today.isoformat(),
        "project_id": project_id,
        "project_name": project.name if project else "",
        "business_goal_profile": business_goal_profile,
        "article_lookup": article_lookup,
        "calendar_items": calendar_items,
        "ranking_changes_top10": ranking_changes[:10],
        "rank_groups_summary": {
            key: {"count": len(value), "articles": value[:3]}
            for key, value in rank_groups.items()
        },
        "gsc_meta_opportunities": gsc_meta_opportunities,
        "gsc_query_opportunities": gsc_query_opportunities,
        "refresh_candidates": refresh_items[:10],
        "last_session_summary": last_summary,
        "article_stats": {
            "planned": planned_count,
            "reviewing": reviewing_count,
            "published": published_count,
        },
        "action_outcome_history": outcome_summary[:10],
        "action_outcome_stats": outcome_stats,
        "action_policy_scores": action_policy_scores,
        "cannibalization_risks": cannibalization_summary,
        "cluster_gaps": cluster_gaps_summary,
        "keyword_trends": keyword_trends_summary,
        "seasonal_opportunities": seasonal_opportunities,
    }
    context_snapshot["generate_capacity"] = calculate_generate_capacity(context_snapshot)
    return context_snapshot