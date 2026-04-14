"""Reflective Loop Agent — 強化版 B 的「反思」層

Pipeline 完成後自動執行，分析結果 → 萃取學習 → 更新 Knowledge Base / Writing Rules。

三種反思模式：
1. post_pipeline — 每次 pipeline 完成後立即執行
2. weekly_review — 每週分析本週所有文章表現（Phase 7 §9.2 L1/L2）
3. human_edit — 人工修改草稿後差異分析（Phase 7 §9.3）

核心輸出：
- session_summary：壓縮摘要，供下次 Strategic Agent 讀取（對應 OpenClaw compaction 概念）
- Knowledge updates：自動寫入/更新 KnowledgeEntry
- Writing rule updates：自動更新 WritingRule（L1 規則學習）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from loguru import logger

from ..config import settings
from ..db import SessionLocal
from ..models.database import (
    AgentDecisionLog,
    Article,
    KnowledgeEntry,
    PipelineRun,
    ReflectionLog,
    SEORanking,
    WritingRule,
)


# ── Post-Pipeline 反思 ────────────────────────────────────────

async def reflect_on_pipeline(
    run_id: str,
    project_id: int,
    article_id: int | None = None,
) -> ReflectionLog | None:
    """Pipeline 完成後的反思：分析決策日誌 + 結果 → 產出洞察 + session 摘要。"""
    logger.info(f"[ReflectiveLoop] 啟動 post_pipeline 反思 run_id={run_id[:8]}")

    with SessionLocal() as session:
        # 收集本次 pipeline 的決策日誌
        decisions = (
            session.query(AgentDecisionLog)
            .filter(AgentDecisionLog.run_id == run_id)
            .order_by(AgentDecisionLog.created_at)
            .all()
        )
        decision_list = [
            {"step": d.step, "decision": d.decision, "reason": d.reason}
            for d in decisions
        ]

        # 收集文章資料
        article_info = {}
        if article_id:
            article = session.get(Article, article_id)
            if article:
                article_info = {
                    "title": article.title,
                    "primary_keyword": article.primary_keyword,
                    "seo_score": article.seo_score,
                    "status": article.status,
                    "word_count": len(article.draft_content or ""),
                }

        # 收集 pipeline run 資料
        pr = (
            session.query(PipelineRun)
            .filter(PipelineRun.run_id == run_id)
            .first()
        )
        pipeline_info = {}
        if pr:
            pipeline_info = {
                "total_llm_calls": pr.total_llm_calls,
                "total_cost": pr.total_cost,
                "seo_score": pr.seo_score,
                "status": pr.status,
            }

    context = {
        "run_id": run_id,
        "article": article_info,
        "pipeline": pipeline_info,
        "decisions": decision_list,
    }

    try:
        reflection = await _call_reflection_llm(context, "post_pipeline")
    except Exception as e:
        logger.error(f"[ReflectiveLoop] LLM 反思失敗：{e}")
        reflection = _fallback_reflection(context)

    insights = reflection.get("insights", [])
    summary = reflection.get("session_summary", "")
    knowledge_actions = reflection.get("knowledge_updates", [])
    rule_actions = reflection.get("writing_rule_updates", [])

    # 執行知識更新
    kb_updated = 0
    wr_updated = 0
    with SessionLocal() as session:
        kb_updated = _apply_knowledge_updates(session, project_id, knowledge_actions)
        wr_updated = _apply_writing_rule_updates(session, project_id, rule_actions)

        log = ReflectionLog(
            project_id=project_id,
            run_id=run_id,
            article_id=article_id,
            reflection_type="post_pipeline",
            insights_json=json.dumps(insights, ensure_ascii=False),
            knowledge_updates=kb_updated,
            writing_rule_updates=wr_updated,
            session_summary=summary,
        )
        session.add(log)
        session.commit()
        session.refresh(log)

    logger.info(
        f"[ReflectiveLoop] 完成：{len(insights)} 洞察 | "
        f"KB+{kb_updated} | WR+{wr_updated} | 摘要={len(summary)}字"
    )
    return log


# ── 每週反思 ──────────────────────────────────────────────────

async def reflect_weekly(project_id: int) -> ReflectionLog | None:
    """每週反思：分析本週所有 pipeline 產出 + 排名數據 → L1/L2 學習。"""
    logger.info(f"[ReflectiveLoop] 啟動 weekly_review project={project_id}")

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    with SessionLocal() as session:
        # 本週完成的文章
        recent_articles = (
            session.query(Article)
            .filter(
                Article.project_id == project_id,
                Article.updated_at >= week_ago,
                Article.status.in_(["reviewing", "review_required", "published"]),
            )
            .all()
        )
        articles_summary = [
            {
                "title": a.title,
                "seo_score": a.seo_score,
                "status": a.status,
                "keyword": a.primary_keyword,
                "word_count": len(a.draft_content or ""),
            }
            for a in recent_articles
        ]

        # 本週排名變化（已發布的文章）
        published = (
            session.query(Article)
            .filter(
                Article.project_id == project_id,
                Article.status == "published",
            )
            .all()
        )
        ranking_summary = []
        for art in published[:20]:
            latest = (
                session.query(SEORanking)
                .filter(
                    SEORanking.project_id == project_id,
                    SEORanking.landing_page.contains(art.slug) if art.slug else False,
                )
                .order_by(SEORanking.tracked_date.desc())
                .first()
            )
            if latest:
                ranking_summary.append({
                    "title": art.title,
                    "keyword": art.primary_keyword,
                    "position": latest.position,
                    "impressions": latest.impressions,
                    "clicks": latest.clicks,
                })

        # 現有知識庫（避免重複學習）
        existing_kb = (
            session.query(KnowledgeEntry)
            .filter(
                KnowledgeEntry.project_id == project_id,
                KnowledgeEntry.is_active == True,  # noqa: E712
            )
            .all()
        )
        kb_summary = [
            {"category": k.category, "pattern": k.pattern[:100]}
            for k in existing_kb[:20]
        ]

    context = {
        "period": "weekly",
        "articles_this_week": articles_summary,
        "ranking_performance": ranking_summary,
        "existing_knowledge": kb_summary,
    }

    try:
        reflection = await _call_reflection_llm(context, "weekly_review")
    except Exception as e:
        logger.error(f"[ReflectiveLoop/weekly] LLM 失敗：{e}")
        return None

    insights = reflection.get("insights", [])
    summary = reflection.get("session_summary", "")
    knowledge_actions = reflection.get("knowledge_updates", [])
    rule_actions = reflection.get("writing_rule_updates", [])

    kb_updated = 0
    wr_updated = 0
    with SessionLocal() as session:
        kb_updated = _apply_knowledge_updates(session, project_id, knowledge_actions)
        wr_updated = _apply_writing_rule_updates(session, project_id, rule_actions)

        log = ReflectionLog(
            project_id=project_id,
            run_id=None,
            article_id=None,
            reflection_type="weekly_review",
            insights_json=json.dumps(insights, ensure_ascii=False),
            knowledge_updates=kb_updated,
            writing_rule_updates=wr_updated,
            session_summary=summary,
        )
        session.add(log)
        session.commit()
        session.refresh(log)

    logger.info(
        f"[ReflectiveLoop/weekly] 完成：{len(insights)} 洞察 | KB+{kb_updated} | WR+{wr_updated}"
    )
    return log


# ── 人工修改反思 ──────────────────────────────────────────────

async def reflect_on_human_edit(
    project_id: int,
    article_id: int,
    original_content: str,
    edited_content: str,
) -> ReflectionLog | None:
    """人工修改草稿後的反思：Diff 分析 → 萃取修改原因 → 寫入知識庫。

    對應 §9.3：人工審閱的知識萃取。
    """
    if original_content == edited_content:
        return None

    logger.info(f"[ReflectiveLoop/human_edit] 分析人工修改 article={article_id}")

    # 簡易 diff：找出差異行
    orig_lines = set(original_content.splitlines())
    edit_lines = set(edited_content.splitlines())
    removed = orig_lines - edit_lines
    added = edit_lines - orig_lines

    if not removed and not added:
        return None

    context = {
        "article_id": article_id,
        "removed_lines": list(removed)[:20],
        "added_lines": list(added)[:20],
        "total_removed": len(removed),
        "total_added": len(added),
    }

    try:
        reflection = await _call_reflection_llm(context, "human_edit")
    except Exception as e:
        logger.error(f"[ReflectiveLoop/human_edit] LLM 失敗：{e}")
        return None

    insights = reflection.get("insights", [])
    knowledge_actions = reflection.get("knowledge_updates", [])
    rule_actions = reflection.get("writing_rule_updates", [])

    kb_updated = 0
    wr_updated = 0
    with SessionLocal() as session:
        kb_updated = _apply_knowledge_updates(session, project_id, knowledge_actions)
        wr_updated = _apply_writing_rule_updates(session, project_id, rule_actions)

        log = ReflectionLog(
            project_id=project_id,
            run_id=None,
            article_id=article_id,
            reflection_type="human_edit",
            insights_json=json.dumps(insights, ensure_ascii=False),
            knowledge_updates=kb_updated,
            writing_rule_updates=wr_updated,
            session_summary=reflection.get("session_summary", ""),
        )
        session.add(log)
        session.commit()
        session.refresh(log)

    logger.info(
        f"[ReflectiveLoop/human_edit] 完成：{len(insights)} 洞察 | KB+{kb_updated} | WR+{wr_updated}"
    )
    return log


# ── LLM 呼叫 ─────────────────────────────────────────────────

REFLECTION_PROMPTS = {
    "post_pipeline": """你是 ContentFlow 的 Reflective Loop Agent，負責在 Pipeline 完成後分析結果。

分析以下 pipeline 執行數據，產出：
1. **insights** — 觀察到的洞察（有什麼值得記錄的模式？）
2. **knowledge_updates** — 要寫入知識庫的條目（category + pattern）
3. **writing_rule_updates** — 要更新的撰寫規範（如有的話）
4. **session_summary** — 用 3-5 句話壓縮本次執行的重要資訊，供下次 Agent 讀取

重點關注：
- SEO 分數偏低的原因（<85 的通常有特定模式）
- 需要人工審核的項目代表什麼
- 成本效率（LLM calls vs 品質）
- 可以改善的寫作策略

輸出嚴格 JSON：
```json
{
  "insights": [{"type": "pattern|issue|suggestion", "observation": "...", "confidence": "high|medium|low"}],
  "knowledge_updates": [{"category": "...", "pattern": "..."}],
  "writing_rule_updates": [{"rule_type": "principle|tone|architecture", "name": "...", "content": "..."}],
  "session_summary": "..."
}
```""",

    "weekly_review": """你是 ContentFlow 的 Reflective Loop Agent，負責每週分析文章表現。

分析以下本週數據，執行 L1（規則學習）和 L2（模板學習）：
- L1：觀察用字、格式、CTR 的相關性 → 更新寫作規則
- L2：觀察哪種文章格式/長度/主題表現好 → 更新知識庫

重點關注：
- 高排名文章有什麼共同特徵
- 低排名文章的問題模式
- 哪些關鍵字值得加大投入
- 避免寫入已存在的知識（見 existing_knowledge）

輸出嚴格 JSON（同 post_pipeline 格式）。""",

    "human_edit": """你是 ContentFlow 的 Reflective Loop Agent，負責從人工修改中學習。

人工編輯者修改了 AI 草稿。分析被刪除和新增的內容，回答：
1. 修改的原因類別（語氣/精準度/E-E-A-T/可讀性/法規合規）
2. 這個修改是否反映了一個通用規則（應寫入 WritingRule）
3. 是否反映了專業知識（應寫入 KnowledgeEntry）

§9.3 範例：人工把「建議就醫」改成「建議諮詢骨科醫師」→ 類別=語氣規範，pattern=「具體科別比籠統用語更符合 E-E-A-T」

輸出嚴格 JSON（同 post_pipeline 格式）。""",
}


async def _call_reflection_llm(context: dict, reflection_type: str) -> dict:
    """呼叫 LLM 進行反思分析。"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    system = REFLECTION_PROMPTS.get(reflection_type, REFLECTION_PROMPTS["post_pipeline"])
    user_msg = f"以下是需要反思的數據：\n\n```json\n{json.dumps(context, ensure_ascii=False, indent=2)}\n```"

    response = await client.chat.completions.create(
        model=settings.llm_lite_model or "gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _fallback_reflection(context: dict) -> dict:
    """LLM 不可用時的 fallback。"""
    seo = context.get("pipeline", {}).get("seo_score") or context.get("article", {}).get("seo_score")
    insights = []
    if seo and seo < 85:
        insights.append({
            "type": "issue",
            "observation": f"SEO 分數 {seo} 未達 85 門檻",
            "confidence": "high",
        })
    return {
        "insights": insights,
        "knowledge_updates": [],
        "writing_rule_updates": [],
        "session_summary": f"Pipeline 完成，SEO={seo}，狀態={context.get('article', {}).get('status', 'unknown')}",
    }


# ── 知識庫與規則更新 ─────────────────────────────────────────

def _apply_knowledge_updates(session, project_id: int, updates: list[dict]) -> int:
    """將反思洞察寫入 KnowledgeEntry。去重：相同 category + pattern 前 50 字不重複。"""
    count = 0
    for upd in updates:
        category = upd.get("category", "reflection")
        pattern = upd.get("pattern", "")
        if not pattern:
            continue

        # 去重
        existing = (
            session.query(KnowledgeEntry)
            .filter(
                KnowledgeEntry.project_id == project_id,
                KnowledgeEntry.category == category,
                KnowledgeEntry.pattern.contains(pattern[:50]),
            )
            .first()
        )
        if existing:
            existing.evidence_count = (existing.evidence_count or 0) + 1
            if existing.evidence_count >= 5 and existing.confidence_level == "unverified":
                existing.confidence_level = "verified"
        else:
            session.add(KnowledgeEntry(
                project_id=project_id,
                category=category,
                pattern=pattern,
                evidence_count=1,
                confidence_level="unverified",
            ))
            count += 1

    session.commit()
    return count


def _apply_writing_rule_updates(session, project_id: int, updates: list[dict]) -> int:
    """將反思中的寫作規則建議寫入 WritingRule。去重：相同 name 不重複。"""
    count = 0
    for upd in updates:
        rule_type = upd.get("rule_type", "principle")
        name = upd.get("name", "")
        content = upd.get("content", "")
        if not name or not content:
            continue

        existing = (
            session.query(WritingRule)
            .filter(
                WritingRule.project_id == project_id,
                WritingRule.name == name,
            )
            .first()
        )
        if existing:
            # 有同名規則 → 追加內容（不覆蓋）
            if content not in (existing.content or ""):
                existing.content = (existing.content or "") + f"\n- {content}"
        else:
            max_order = (
                session.query(WritingRule)
                .filter(WritingRule.project_id == project_id)
                .count()
            )
            session.add(WritingRule(
                project_id=project_id,
                rule_type=rule_type,
                name=name,
                content=content,
                order_num=max_order + 1,
            ))
            count += 1

    session.commit()
    return count
