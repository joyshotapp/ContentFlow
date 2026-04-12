"""Learning Agent — 三層學習機制

CF-05-01: L1 成功模式分析器 (analyze_success_patterns)
CF-05-02: KnowledgeEntry 寫入邏輯 (_upsert_knowledge_entry, 信心等級升級)
CF-05-06: L2 ROI 分析 (optimize_content_strategy)

架構：
  analyze_success_patterns(project_id, session) -> LearningReport
    ├── 分析文章屬性（字數、FAQ、article_type、SEO 分數）vs GSC 排名
    ├── 計算各類別的統計模式
    └── 寫入 / 升級 KnowledgeEntry（unverified → verified → universal）

  optimize_content_strategy(project_id, session) -> StrategyUpdate
    ├── 計算每個 keyword 的 ROI（排名提升 × 曝光量）
    ├── 找出高 ROI / 低 ROI keyword
    └── 輸出 Content Refresh 優先排序建議
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import mean, stdev
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from ..models.database import Article, KnowledgeEntry, SEORanking

# ─────────────────────────────────────────────────────────────────────────────
# 信心等級門檻
# ─────────────────────────────────────────────────────────────────────────────
_VERIFIED_THRESHOLD = 5      # evidence_count >= 5 → verified
_UNIVERSAL_THRESHOLD = 10    # evidence_count >= 10 且跨專案 → universal

# 知識庫分類
CAT_FORMAT_PATTERN = "format_pattern"       # 文章格式 vs 排名
CAT_SEO_SCORE = "seo_score_impact"          # SEO 分數 vs 排名
CAT_FAQ_IMPACT = "faq_impact"               # FAQ 數量 vs CTR
CAT_WORD_COUNT = "word_count_pattern"       # 字數 vs 排名
CAT_TITLE_FORMAT = "title_format"           # Title 格式 vs CTR
CAT_KEYWORD_ROI = "keyword_roi"             # keyword 投入產出分析
CAT_REFRESH_PRIORITY = "refresh_priority"   # Content Refresh 優先建議

# ─────────────────────────────────────────────────────────────────────────────
# 資料結構
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PatternResult:
    """單一發現的成功模式"""
    category: str
    pattern_text: str          # 人類可讀描述
    evidence_count: int
    metadata: dict = field(default_factory=dict)
    confidence_level: str = "unverified"


@dataclass
class LearningReport:
    """L1 模式記憶的完整報告"""
    project_id: int
    analyzed_articles: int
    patterns: list[PatternResult] = field(default_factory=list)
    low_performers: list[dict] = field(default_factory=list)
    generated_at: date = field(default_factory=date.today)


@dataclass
class KeywordROI:
    """單個 keyword 的 ROI 指標"""
    keyword: str
    total_impressions: int
    avg_position: float
    best_position: float
    ctr: float
    roi_score: float             # 純量化分數（越高越值得投入）
    recommendation: str          # invest / maintain / deprioritize


@dataclass
class RefreshCandidate:
    """應優先 Refresh 的文章"""
    article_id: int
    article_title: str
    url: str
    current_rank: float
    priority_score: float        # 越高越優先
    reason: str


@dataclass
class StrategyUpdate:
    """L2 策略優化輸出"""
    project_id: int
    high_roi_keywords: list[KeywordROI] = field(default_factory=list)
    low_roi_keywords: list[KeywordROI] = field(default_factory=list)
    refresh_candidates: list[RefreshCandidate] = field(default_factory=list)
    resource_advice: str = ""   # 新文 vs 更新舊文的比例建議
    generated_at: date = field(default_factory=date.today)


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeEntry 寫入 / 升級工具（CF-05-02）
# ─────────────────────────────────────────────────────────────────────────────

def _compute_confidence(evidence_count: int, is_cross_project: bool = False) -> str:
    """根據 evidence_count 和跨專案一致性計算信心等級"""
    if evidence_count >= _UNIVERSAL_THRESHOLD and is_cross_project:
        return "universal"
    if evidence_count >= _VERIFIED_THRESHOLD:
        return "verified"
    return "unverified"


def upsert_knowledge_entry(
    session: Session,
    *,
    project_id: Optional[int],
    category: str,
    pattern: str,
    evidence_count: int,
    metadata: dict,
    is_cross_project: bool = False,
) -> KnowledgeEntry:
    """
    新增或更新 KnowledgeEntry，並根據 evidence_count 自動升級信心等級。

    同一 (project_id, category, pattern) 的條目若已存在，
    則更新 evidence_count 和 metadata_json（取較大的 evidence_count）。
    """
    existing = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.category == category,
            KnowledgeEntry.pattern == pattern,
        )
        .first()
    )

    if existing:
        # 取較大的 evidence_count（防止數據退步）
        new_count = max(existing.evidence_count, evidence_count)
        existing.evidence_count = new_count
        existing.confidence_level = _compute_confidence(new_count, is_cross_project)
        existing.metadata_json = json.dumps(metadata, ensure_ascii=False)
        session.commit()
        return existing
    else:
        entry = KnowledgeEntry(
            project_id=project_id,
            category=category,
            pattern=pattern,
            evidence_count=evidence_count,
            confidence_level=_compute_confidence(evidence_count, is_cross_project),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            is_active=True,
        )
        session.add(entry)
        session.commit()
        return entry


def upgrade_cross_project_entries(session: Session) -> int:
    """
    掃描所有 verified 條目，若同一 (category, pattern) 在 2+ 個專案都出現，
    且合計 evidence_count >= UNIVERSAL_THRESHOLD，升級為 universal。

    回傳升級的條目數量。
    """
    from sqlalchemy import func

    # 找出 2+ 個 project 都有的 (category, pattern) 組合
    subq = (
        session.query(
            KnowledgeEntry.category,
            KnowledgeEntry.pattern,
            func.count(KnowledgeEntry.project_id.distinct()).label("project_count"),
            func.sum(KnowledgeEntry.evidence_count).label("total_evidence"),
        )
        .filter(KnowledgeEntry.is_active.is_(True))
        .group_by(KnowledgeEntry.category, KnowledgeEntry.pattern)
        .subquery()
    )

    candidates = session.execute(
        session.query(subq).filter(
            subq.c.project_count >= 2,
            subq.c.total_evidence >= _UNIVERSAL_THRESHOLD,
        )
    ).all()

    upgraded = 0
    for row in candidates:
        entries = session.query(KnowledgeEntry).filter(
            KnowledgeEntry.category == row.category,
            KnowledgeEntry.pattern == row.pattern,
            KnowledgeEntry.confidence_level != "universal",
        ).all()
        for e in entries:
            e.confidence_level = "universal"
            upgraded += 1
    if upgraded:
        session.commit()
    return upgraded


# ─────────────────────────────────────────────────────────────────────────────
# 輔助：從 Article ORM 衍生可量化特徵
# ─────────────────────────────────────────────────────────────────────────────

def _word_count(text: str) -> int:
    """估算中文字數（含英文 token）"""
    if not text:
        return 0
    chinese = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_words = len(re.findall(r'\b[a-zA-Z]+\b', text))
    return chinese + english_words * 2


def _faq_count(text: str) -> int:
    """計算 Markdown / JSON-LD 中的 FAQ 數量"""
    if not text:
        return 0
    # JSON-LD schema 中的 FAQ
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            questions = data.get("mainEntity") or data.get("acceptedAnswer", [])
            if isinstance(questions, list):
                return len(questions)
    except (json.JSONDecodeError, TypeError):
        pass
    # Markdown 中 Q: / ## FAQ 後的問題數
    return len(re.findall(r'(?:^|\n)\s*#+\s*Q[：:]|(?:^|\n)\s*\*\*Q[：:]', text))


def _has_number_in_title(title: str) -> bool:
    return bool(re.search(r'\d', title))


def _infer_article_format(outline: str) -> str:
    """從 outline 推測文章格式"""
    if not outline:
        return "unknown"
    outline_lower = outline.lower()
    if any(k in outline for k in ["怎麼", "如何", "步驟", "怎樣", "how to"]):
        return "how-to"
    if any(k in outline for k in ["幾種", "幾個", "排名", "推薦", "清單", "list"]):
        return "listicle"
    if any(k in outline for k in ["比較", "vs", "差異", "哪個好"]):
        return "comparison"
    if any(k in outline for k in ["是什麼", "介紹", "了解", "what is"]):
        return "informational"
    return "other"


# ─────────────────────────────────────────────────────────────────────────────
# CF-05-01: L1 成功模式分析器
# ─────────────────────────────────────────────────────────────────────────────

def analyze_success_patterns(project_id: int, session: Session) -> LearningReport:
    """
    L1 模式記憶：分析所有已發布文章的表現數據，找出成功因子並寫入知識庫。

    分析維度：
    - SEO 分數 vs 排名（已有 seo_score 欄位）
    - 文章格式（How-to / Listicle / 比較文）vs 排名
    - FAQ 數量 vs CTR
    - 文章字數 vs 排名
    - Title 含數字 vs CTR
    """
    cutoff = date.today() - timedelta(days=90)

    articles = (
        session.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.status == "published",
        )
        .all()
    )

    if not articles:
        logger.info(f"[LearningAgent] project={project_id} 無已發布文章，跳過 L1 分析")
        return LearningReport(project_id=project_id, analyzed_articles=0)

    logger.info(f"[LearningAgent] project={project_id} 開始分析 {len(articles)} 篇文章")

    # ── 拉取 SEORanking 資料 ──────────────────────────────────────────
    url_to_rankings: dict[str, list[SEORanking]] = defaultdict(list)
    all_rankings = (
        session.query(SEORanking)
        .filter(
            SEORanking.project_id == project_id,
            SEORanking.tracked_date >= cutoff,
        )
        .all()
    )
    for r in all_rankings:
        if r.landing_page:
            url_to_rankings[r.landing_page].append(r)

    # ── 計算每篇文章的衍生特徵 ─────────────────────────────────────
    enriched: list[dict] = []
    for art in articles:
        rankings = url_to_rankings.get(art.publish_url, [])
        if not rankings:
            continue  # 無排名資料，跳過

        avg_pos = mean(r.position for r in rankings if r.position)
        avg_ctr = mean(r.ctr for r in rankings if r.ctr is not None and r.ctr > 0) if any(r.ctr for r in rankings) else 0.0
        total_impr = sum(r.impressions or 0 for r in rankings)

        enriched.append({
            "article_id": art.id,
            "title": art.title,
            "url": art.publish_url,
            "seo_score": art.seo_score or 0,
            "article_type": art.article_type or "unknown",
            "article_format": _infer_article_format(art.outline or ""),
            "word_count": _word_count(art.draft_content or ""),
            "faq_count": _faq_count(art.faq_schema_json or ""),
            "has_number_in_title": _has_number_in_title(art.title or ""),
            "avg_position": avg_pos,
            "avg_ctr": avg_ctr,
            "total_impressions_90d": total_impr,
        })

    if not enriched:
        logger.info(f"[LearningAgent] project={project_id} 無有 GSC 數據的文章，跳過統計")
        return LearningReport(project_id=project_id, analyzed_articles=len(articles))

    patterns: list[PatternResult] = []

    # ── 模式 1：SEO 分數分組 vs 平均排名 ──────────────────────────
    seo_groups: dict[str, list[float]] = defaultdict(list)
    for d in enriched:
        if d["seo_score"] >= 85:
            seo_groups["高 SEO 分數（≥85）"].append(d["avg_position"])
        elif d["seo_score"] >= 70:
            seo_groups["中 SEO 分數（70-84）"].append(d["avg_position"])
        elif d["seo_score"] > 0:
            seo_groups["低 SEO 分數（<70）"].append(d["avg_position"])

    for label, positions in seo_groups.items():
        if len(positions) < 2:
            continue
        avg = mean(positions)
        p = PatternResult(
            category=CAT_SEO_SCORE,
            pattern_text=f"{label} 的文章平均排名 {avg:.1f}",
            evidence_count=len(positions),
            metadata={"label": label, "avg_position": avg, "count": len(positions)},
        )
        p.confidence_level = _compute_confidence(p.evidence_count)
        patterns.append(p)
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_SEO_SCORE,
            pattern=p.pattern_text,
            evidence_count=p.evidence_count,
            metadata=p.metadata,
        )

    # ── 模式 2：文章格式 vs 排名 ─────────────────────────────────
    format_groups: dict[str, list[float]] = defaultdict(list)
    for d in enriched:
        if d["article_format"] != "unknown":
            format_groups[d["article_format"]].append(d["avg_position"])

    for fmt, positions in format_groups.items():
        if len(positions) < 2:
            continue
        avg = mean(positions)
        format_map = {"how-to": "How-to 格式", "listicle": "Listicle 格式",
                      "comparison": "比較文", "informational": "知識介紹文"}
        label = format_map.get(fmt, fmt)
        p = PatternResult(
            category=CAT_FORMAT_PATTERN,
            pattern_text=f"{label} 的文章平均排名 {avg:.1f}（{len(positions)} 篇）",
            evidence_count=len(positions),
            metadata={"format": fmt, "avg_position": avg, "count": len(positions)},
        )
        p.confidence_level = _compute_confidence(p.evidence_count)
        patterns.append(p)
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_FORMAT_PATTERN,
            pattern=p.pattern_text,
            evidence_count=p.evidence_count,
            metadata=p.metadata,
        )

    # ── 模式 3：FAQ 有無 vs CTR ───────────────────────────────────
    with_faq = [d["avg_ctr"] for d in enriched if d["faq_count"] > 0 and d["avg_ctr"] > 0]
    without_faq = [d["avg_ctr"] for d in enriched if d["faq_count"] == 0 and d["avg_ctr"] > 0]

    if len(with_faq) >= 2 and len(without_faq) >= 2:
        diff_pct = ((mean(with_faq) - mean(without_faq)) / (mean(without_faq) + 1e-9)) * 100
        direction = "高" if diff_pct > 0 else "低"
        p = PatternResult(
            category=CAT_FAQ_IMPACT,
            pattern_text=f"有 FAQ 的文章 CTR 比沒有 FAQ 的{direction} {abs(diff_pct):.0f}%",
            evidence_count=len(with_faq) + len(without_faq),
            metadata={
                "avg_ctr_with_faq": mean(with_faq),
                "avg_ctr_without_faq": mean(without_faq),
                "diff_pct": diff_pct,
            },
        )
        p.confidence_level = _compute_confidence(p.evidence_count)
        patterns.append(p)
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_FAQ_IMPACT,
            pattern=p.pattern_text,
            evidence_count=p.evidence_count,
            metadata=p.metadata,
        )

    # ── 模式 4：字數分組 vs 排名 ─────────────────────────────────
    short = [d["avg_position"] for d in enriched if 0 < d["word_count"] < 800]
    medium = [d["avg_position"] for d in enriched if 800 <= d["word_count"] < 1800]
    long = [d["avg_position"] for d in enriched if d["word_count"] >= 1800]

    for label, group in [("短文（< 800 字）", short), ("中篇（800-1800 字）", medium), ("長文（≥ 1800 字）", long)]:
        if len(group) < 2:
            continue
        avg = mean(group)
        p = PatternResult(
            category=CAT_WORD_COUNT,
            pattern_text=f"{label} 平均排名 {avg:.1f}（{len(group)} 篇）",
            evidence_count=len(group),
            metadata={"label": label, "avg_position": avg, "count": len(group)},
        )
        p.confidence_level = _compute_confidence(p.evidence_count)
        patterns.append(p)
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_WORD_COUNT,
            pattern=p.pattern_text,
            evidence_count=p.evidence_count,
            metadata=p.metadata,
        )

    # ── 模式 5：Title 含數字 vs CTR ──────────────────────────────
    with_num = [d["avg_ctr"] for d in enriched if d["has_number_in_title"] and d["avg_ctr"] > 0]
    without_num = [d["avg_ctr"] for d in enriched if not d["has_number_in_title"] and d["avg_ctr"] > 0]

    if len(with_num) >= 2 and len(without_num) >= 2:
        diff_pct = ((mean(with_num) - mean(without_num)) / (mean(without_num) + 1e-9)) * 100
        direction = "高" if diff_pct > 0 else "低"
        p = PatternResult(
            category=CAT_TITLE_FORMAT,
            pattern_text=f"Title 含數字的文章 CTR 比不含數字的{direction} {abs(diff_pct):.0f}%",
            evidence_count=len(with_num) + len(without_num),
            metadata={
                "avg_ctr_with_num": mean(with_num),
                "avg_ctr_without_num": mean(without_num),
                "diff_pct": diff_pct,
            },
        )
        p.confidence_level = _compute_confidence(p.evidence_count)
        patterns.append(p)
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_TITLE_FORMAT,
            pattern=p.pattern_text,
            evidence_count=p.evidence_count,
            metadata=p.metadata,
        )

    # ── 低表現文章（排名 > 20, 曝光 > 50）────────────────────────
    low_performers = [
        {"article_id": d["article_id"], "title": d["title"],
         "avg_position": d["avg_position"], "avg_ctr": d["avg_ctr"]}
        for d in enriched
        if d["avg_position"] > 20 and d["total_impressions_90d"] >= 50
    ]

    logger.info(f"[LearningAgent] project={project_id} 發現 {len(patterns)} 個模式，"
                f"{len(low_performers)} 篇低表現文章")

    return LearningReport(
        project_id=project_id,
        analyzed_articles=len(enriched),
        patterns=patterns,
        low_performers=low_performers,
    )


# ─────────────────────────────────────────────────────────────────────────────
# CF-05-06: L2 策略優化
# ─────────────────────────────────────────────────────────────────────────────

_ESTIMATED_COST_PER_ARTICLE = 0.05   # USD，用於 ROI 計算的預估值

def optimize_content_strategy(project_id: int, session: Session) -> StrategyUpdate:
    """
    L2 策略優化：分析投入產出比，給出 keyword 加碼/停止和 Refresh 建議。

    ROI 公式：roi_score = (impressions_28d × (best_position > 10 ? 10 / best_position : 1)) / 1000
    """
    cutoff = date.today() - timedelta(days=28)

    rankings = (
        session.query(SEORanking)
        .filter(
            SEORanking.project_id == project_id,
            SEORanking.tracked_date >= cutoff,
        )
        .all()
    )

    if not rankings:
        logger.info(f"[LearningAgent] project={project_id} 無 28 天內 GSC 數據，跳過 L2 分析")
        return StrategyUpdate(project_id=project_id)

    # ── 按 keyword 匯總 ─────────────────────────────────────────
    kw_data: dict[str, dict] = defaultdict(lambda: {
        "positions": [], "impressions": [], "ctrs": [],
    })
    for r in rankings:
        if not r.keyword:
            continue
        kd = kw_data[r.keyword]
        if r.position:
            kd["positions"].append(r.position)
        if r.impressions:
            kd["impressions"].append(r.impressions)
        if r.ctr:
            kd["ctrs"].append(r.ctr)

    keyword_rois: list[KeywordROI] = []
    for kw, data in kw_data.items():
        if not data["positions"]:
            continue
        avg_pos = mean(data["positions"])
        best_pos = min(data["positions"])
        total_impr = sum(data["impressions"]) if data["impressions"] else 0
        avg_ctr = mean(data["ctrs"]) if data["ctrs"] else 0.0

        # ROI score：曝光量 × 排名修正係數
        rank_factor = min(10 / best_pos, 1.0) if best_pos > 0 else 0.0
        roi_score = (total_impr * rank_factor) / 1000

        # 推薦策略
        if roi_score > 5 and best_pos <= 10:
            recommendation = "maintain"
        elif roi_score > 2 and best_pos > 10:
            recommendation = "invest"   # 有曝光但排名未入前 10，值得加碼
        elif roi_score < 0.5:
            recommendation = "deprioritize"
        else:
            recommendation = "maintain"

        keyword_rois.append(KeywordROI(
            keyword=kw,
            total_impressions=total_impr,
            avg_position=avg_pos,
            best_position=best_pos,
            ctr=avg_ctr,
            roi_score=roi_score,
            recommendation=recommendation,
        ))

        # 寫入知識庫
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_KEYWORD_ROI,
            pattern=f"關鍵字「{kw}」ROI={roi_score:.2f}，建議：{recommendation}",
            evidence_count=len(data["positions"]),
            metadata={"roi_score": roi_score, "recommendation": recommendation,
                      "avg_position": avg_pos, "total_impressions": total_impr},
        )

    # ── 找出排名 11-20 的高優先 Refresh 候選 ─────────────────────
    articles = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "published")
        .all()
    )
    url_to_article = {a.publish_url: a for a in articles}

    refresh_candidates: list[RefreshCandidate] = []
    for r in rankings:
        if not r.landing_page or not r.position:
            continue
        # 排名 11-20：最有 Refresh 價值（接近 P1 但還差一步）
        if 11 <= r.position <= 20 and r.impressions and r.impressions >= 100:
            art = url_to_article.get(r.landing_page)
            if art:
                # priority_score：曝光越多、排名越接近 10，越優先
                priority = (r.impressions / 100) * (10 / (r.position - 9))
                refresh_candidates.append(RefreshCandidate(
                    article_id=art.id,
                    article_title=art.title,
                    url=r.landing_page,
                    current_rank=r.position,
                    priority_score=priority,
                    reason=f"排名 {r.position:.0f}，曝光 {r.impressions}/月，Refresh 可推入前 10",
                ))

    # 去重（同文章取最高 priority）
    seen_ids: dict[int, RefreshCandidate] = {}
    for c in refresh_candidates:
        if c.article_id not in seen_ids or c.priority_score > seen_ids[c.article_id].priority_score:
            seen_ids[c.article_id] = c
    refresh_candidates = sorted(seen_ids.values(), key=lambda x: -x.priority_score)[:10]

    for rc in refresh_candidates:
        upsert_knowledge_entry(
            session,
            project_id=project_id,
            category=CAT_REFRESH_PRIORITY,
            pattern=f"優先 Refresh：《{rc.article_title}》（排名 {rc.current_rank:.0f}，{rc.reason}）",
            evidence_count=1,
            metadata={"article_id": rc.article_id, "current_rank": rc.current_rank,
                      "priority_score": rc.priority_score},
        )

    high_roi = sorted([k for k in keyword_rois if k.recommendation in ("invest", "maintain")
                       and k.roi_score > 1], key=lambda x: -x.roi_score)[:5]
    low_roi = sorted([k for k in keyword_rois if k.recommendation == "deprioritize"],
                     key=lambda x: x.roi_score)[:5]

    # ── 資源配置建議 ─────────────────────────────────────────────
    refresh_count = len(refresh_candidates)
    total_articles = len(articles)
    if refresh_count == 0:
        resource_advice = "目前無高優先 Refresh 候選，建議持續拓展新主題關鍵字。"
    elif refresh_count >= 5:
        resource_advice = f"有 {refresh_count} 篇文章可 Refresh 進前 10，建議 60% 資源投入更新、40% 新文。"
    else:
        resource_advice = f"有 {refresh_count} 篇 Refresh 候選，建議 40% 資源更新、60% 新文。"

    logger.info(f"[LearningAgent] L2 分析完成：高 ROI {len(high_roi)} 個，"
                f"低 ROI {len(low_roi)} 個，Refresh 候選 {len(refresh_candidates)} 篇")

    return StrategyUpdate(
        project_id=project_id,
        high_roi_keywords=high_roi,
        low_roi_keywords=low_roi,
        refresh_candidates=refresh_candidates,
        resource_advice=resource_advice,
    )
