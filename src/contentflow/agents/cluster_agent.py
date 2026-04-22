"""Cluster Agent：Topic Cluster 主題叢集分析

職責：
- 語意分群關鍵字 → Pillar + Cluster 架構
- 計算覆蓋率與缺口
- 內部連結建議
- 將結果儲存到 DB（TopicCluster、ClusterMember）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from ..config import settings
from ..models.database import Article, ClusterMember, TopicCluster as TopicClusterModel


# ── 資料結構 ──────────────────────────────────────────────────────────────

@dataclass
class TopicClusterResult:
    """主題叢集分析結果（runtime 使用，區分於 ORM TopicCluster）"""
    pillar_keyword: str
    pillar_title: str
    cluster_keywords: list[str] = field(default_factory=list)
    cluster_articles: list[int] = field(default_factory=list)   # 已有文章的 IDs
    coverage_rate: float = 0.0          # 已覆蓋 / 總叢集關鍵字
    gaps: list[str] = field(default_factory=list)               # 尚未有文章的關鍵字
    db_id: Optional[int] = None         # save 後填入


@dataclass
class InternalLinkSuggestion:
    """內部連結建議"""
    source_article_id: int
    source_title: str
    target_article_id: int
    target_title: str
    target_url: str
    anchor_text: str
    reason: str


@dataclass
class ClusterGap:
    """叢集缺口"""
    cluster_pillar: str
    missing_keyword: str
    estimated_volume: float
    priority: str       # high / medium / low


# ── 主要函式 ─────────────────────────────────────────────────────────────

async def build_topic_clusters(
    project_id: int,
    session: Session,
) -> list[TopicClusterResult]:
    """
    從關鍵字庫自動建立 Topic Cluster 架構

    流程：
    1. 讀取所有關鍵字 → AI 語意分群
    2. 每群中搜尋量最高者 → Pillar
    3. 其餘 → Cluster keywords
    4. 比對現有文章 → 計算覆蓋率
    5. 找出缺口
    6. 儲存到 DB
    """
    from ..models.database import Keyword

    keywords = (
        session.query(Keyword)
        .filter(
            Keyword.project_id == project_id,
            Keyword.search_volume > 0,
        )
        .all()
    )

    if not keywords:
        logger.info(f"[ClusterAgent] project={project_id} 無關鍵字資料")
        return []

    kw_list = [{"keyword": k.keyword, "volume": k.search_volume} for k in keywords]

    # AI 語意分群
    clusters_raw = await _llm_cluster_keywords(kw_list)

    # 取得已有文章（以主關鍵字為 key）
    published_articles = (
        session.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.status == "published",
        )
        .all()
    )
    article_kw_map: dict[str, Article] = {
        a.primary_keyword.lower(): a
        for a in published_articles
        if a.primary_keyword
    }

    # 關鍵字搜尋量映射（供 _save_cluster_to_db 使用）
    all_keywords_obj = keywords

    results: list[TopicClusterResult] = []
    for group in clusters_raw:
        pillar_kw: str = group["pillar"]
        cluster_kws: list[str] = group.get("cluster_keywords", [])
        all_kws = [pillar_kw] + cluster_kws

        covered_articles: list[int] = []
        gaps: list[str] = []
        for kw in all_kws:
            art = article_kw_map.get(kw.lower())
            if art:
                covered_articles.append(art.id)
            else:
                gaps.append(kw)

        coverage = len(covered_articles) / len(all_kws) if all_kws else 0.0

        tc = TopicClusterResult(
            pillar_keyword=pillar_kw,
            pillar_title=group.get("pillar_title", pillar_kw),
            cluster_keywords=cluster_kws,
            cluster_articles=covered_articles,
            coverage_rate=coverage,
            gaps=gaps,
        )
        results.append(tc)

        _save_cluster_to_db(tc, project_id, session, article_kw_map)

    session.commit()
    logger.info(f"[ClusterAgent] project={project_id}，建立 {len(results)} 個 Topic Cluster")
    return results


async def detect_cluster_gaps(
    project_id: int,
    session: Session,
) -> list[ClusterGap]:
    """偵測每個 Topic Cluster 的缺口，推薦新文章選題"""
    clusters = await build_topic_clusters(project_id, session)

    from ..models.database import Keyword
    kw_vol_map: dict[str, float] = {
        k.keyword.lower(): k.search_volume
        for k in session.query(Keyword).filter(Keyword.project_id == project_id).all()
    }

    gaps: list[ClusterGap] = []
    for tc in clusters:
        for missing_kw in tc.gaps:
            vol = kw_vol_map.get(missing_kw.lower(), 0.0)
            priority = "high" if vol >= 1000 else ("medium" if vol >= 200 else "low")
            gaps.append(ClusterGap(
                cluster_pillar=tc.pillar_keyword,
                missing_keyword=missing_kw,
                estimated_volume=vol,
                priority=priority,
            ))

    gaps.sort(key=lambda g: g.estimated_volume, reverse=True)
    return gaps


async def suggest_internal_links(
    article_id: int,
    project_id: int,
    session: Session,
) -> list[InternalLinkSuggestion]:
    """
    針對一篇文章，推薦連結到同 Cluster 的其他已發布文章

    Returns:
        list of InternalLinkSuggestion（可為空）
    """
    article = session.get(Article, article_id)
    if not article:
        return []

    primary_kw = (article.primary_keyword or "").lower()

    # 查此文章所在的 Cluster
    member = (
        session.query(ClusterMember)
        .filter(ClusterMember.keyword == primary_kw)
        .first()
    )
    if not member:
        logger.debug(f"[ClusterAgent] Article {article_id} 未分群（keyword='{primary_kw}'）")
        return []

    # 同 Cluster 的其他已發布成員
    siblings = (
        session.query(ClusterMember)
        .filter(
            ClusterMember.cluster_id == member.cluster_id,
            ClusterMember.article_id.isnot(None),
            ClusterMember.article_id != article_id,
        )
        .all()
    )

    suggestions: list[InternalLinkSuggestion] = []
    for sibling in siblings:
        sibling_art = session.get(Article, sibling.article_id)
        if sibling_art and sibling_art.publish_url:
            suggestions.append(InternalLinkSuggestion(
                source_article_id=article_id,
                source_title=article.title,
                target_article_id=sibling.article_id,
                target_title=sibling_art.title,
                target_url=sibling_art.publish_url,
                anchor_text=sibling.keyword,
                reason=f"同屬 Cluster「{primary_kw}」，互相連結可提升主題深度",
            ))

    return suggestions


# ── LLM 語意分群（私有） ─────────────────────────────────────────────────

async def _llm_cluster_keywords(
    kw_list: list[dict],
    max_clusters: int = 20,
) -> list[dict]:
    """
    使用 LLM 對關鍵字進行語意分群

    Returns:
        list of {"pillar": str, "pillar_title": str, "cluster_keywords": list[str]}
    """
    if not kw_list:
        return []

    try:
        from ..llm_client import achat

        kw_text = "\n".join(
            f"- {item['keyword']} (搜尋量: {item['volume']:.0f})"
            for item in kw_list[:200]
        )

        prompt = (
            f"以下是 SEO 關鍵字清單，請依語意相似度分成最多 {max_clusters} 個主題叢集（Topic Cluster）。\n\n"
            f"關鍵字清單：\n{kw_text}\n\n"
            "分群規則：\n"
            "1. 每群中搜尋量最高的關鍵字為 Pillar（支柱關鍵字）\n"
            "2. 其餘為 Cluster keywords（衛星關鍵字）\n"
            "3. 語意相近、搜尋意圖相同的歸為同群\n"
            "4. Pillar 應是最廣泛的概念，Cluster 是更具體的細節\n\n"
            "請以 JSON 格式輸出（不要包含其他說明文字）：\n"
            "[\n"
            '  {"pillar": "主要關鍵字", "pillar_title": "支柱頁建議標題", '
            '"cluster_keywords": ["衛星關鍵字1", "衛星關鍵字2"]}\n'
            "]"
        )

        raw = await achat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )

        raw = raw.strip()
        if raw.startswith("```"):
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else raw
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())

    except Exception as e:
        logger.warning(f"[ClusterAgent] LLM 分群失敗，使用 fallback 方案：{e}")
        return _fallback_cluster(kw_list)


def _fallback_cluster(kw_list: list[dict]) -> list[dict]:
    """Fallback：無 LLM 時，每個關鍵字自成一群（取搜尋量最高的前 20 個）"""
    return [
        {
            "pillar": item["keyword"],
            "pillar_title": item["keyword"],
            "cluster_keywords": [],
        }
        for item in sorted(kw_list, key=lambda x: x["volume"], reverse=True)[:20]
    ]


# ── DB 儲存（私有） ──────────────────────────────────────────────────────

def _save_cluster_to_db(
    tc: TopicClusterResult,
    project_id: int,
    session: Session,
    article_kw_map: dict[str, Article],
) -> None:
    """儲存 TopicClusterResult 到 DB（upsert by project_id + pillar_keyword）"""
    pillar_art = article_kw_map.get(tc.pillar_keyword.lower())
    pillar_art_id = pillar_art.id if pillar_art else None

    existing = (
        session.query(TopicClusterModel)
        .filter(
            TopicClusterModel.project_id == project_id,
            TopicClusterModel.pillar_keyword == tc.pillar_keyword,
        )
        .first()
    )

    if existing:
        existing.pillar_title = tc.pillar_title
        existing.pillar_article_id = pillar_art_id
        cluster_db = existing
    else:
        cluster_db = TopicClusterModel(
            project_id=project_id,
            pillar_keyword=tc.pillar_keyword,
            pillar_title=tc.pillar_title,
            pillar_article_id=pillar_art_id,
            status="building",
        )
        session.add(cluster_db)
        session.flush()     # 取得 DB ID

    tc.db_id = cluster_db.id

    # 刪除舊的 ClusterMember 並重建
    session.query(ClusterMember).filter(
        ClusterMember.cluster_id == cluster_db.id
    ).delete()

    # Pillar 自身
    session.add(ClusterMember(
        cluster_id=cluster_db.id,
        keyword=tc.pillar_keyword,
        article_id=pillar_art_id,
        link_to_pillar=False,
    ))

    # 衛星成員
    for cluster_kw in tc.cluster_keywords:
        art = article_kw_map.get(cluster_kw.lower())
        session.add(ClusterMember(
            cluster_id=cluster_db.id,
            keyword=cluster_kw,
            article_id=art.id if art else None,
            link_to_pillar=bool(art),
        ))
