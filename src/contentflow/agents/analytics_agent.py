"""Analytics Agent：文章表現歸因分析

職責：
- ArticlePerformance  單篇文章的表現歸因（排名 + CTR + 流量 + 轉換）
- AttributionEngine   查詢 SEORanking + Article ORM 計算表現
- CannibalizationDetector  偵測同關鍵字多文章競爭
- RefreshTriggerChecker    依規則判斷是否需要 Content Refresh
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy.orm import Session

from ..models.database import Article, SEORanking


# ── 資料結構 ──────────────────────────────────────────────────────────────

@dataclass
class ArticlePerformance:
    """單篇文章的表現歸因"""
    article_id: int
    url: str
    published_date: Optional[date]

    # GSC 數據
    target_keyword: str
    current_rank: float
    rank_change_7d: float           # 正 = 進步（排名數字降低），負 = 下滑
    impressions_28d: int
    clicks_28d: int
    ctr: float

    # GA4 / ForgeBase 數據（可選，未串接時為預設值）
    pageviews_28d: int = 0
    avg_engagement_time: float = 0.0
    bounce_rate: float = 0.0

    # 轉換數據
    conversions_28d: int = 0
    conversion_value: float = 0.0

    # AI 分析結果
    performance_grade: str = "C"              # A / B / C / D / F
    recommended_action: str = "maintain"      # maintain / refresh / rewrite / merge / deprioritize
    action_reason: str = ""


@dataclass
class CannibalizationPair:
    """一組互相 Cannibalize 的文章對"""
    keyword: str
    article_ids: list[int] = field(default_factory=list)
    article_titles: list[str] = field(default_factory=list)
    article_urls: list[str] = field(default_factory=list)
    positions: list[float] = field(default_factory=list)
    suggestion: str = ""


@dataclass
class RefreshRecommendation:
    """Content Refresh 推薦"""
    article_id: int
    article_title: str
    url: str
    trigger_reason: str
    priority: str                       # high / medium / low
    current_rank: Optional[float] = None
    previous_rank: Optional[float] = None


# ── 表現評分邏輯 ──────────────────────────────────────────────────────────

def _compute_grade(perf: ArticlePerformance) -> str:
    """
    根據排名 + CTR + 曝光計算表現等級

    A：排名 1–5 且 CTR > 8%
    B：排名 6–10 或 排名 1–5 但 CTR 偏低
    C：排名 11–20
    D：排名 21–50
    F：排名 > 50 或曝光 < 10
    """
    rank = perf.current_rank
    ctr = perf.ctr
    impressions = perf.impressions_28d

    if impressions < 10:
        return "F"
    if rank <= 5 and ctr >= 0.08:
        return "A"
    if rank <= 10:
        return "B"
    if rank <= 20:
        return "C"
    if rank <= 50:
        return "D"
    return "F"


def _compute_action(perf: ArticlePerformance) -> tuple[str, str]:
    """根據表現等級與趨勢決定推薦動作"""
    grade = perf.performance_grade
    rank = perf.current_rank
    rank_change = perf.rank_change_7d      # 正 = 進步

    if grade in ("A", "B"):
        return "maintain", "排名表現良好，維持現狀"

    if grade == "C":
        if rank_change < -5:
            return "refresh", f"排名近 7 天下滑 {abs(rank_change):.1f} 位，建議更新內容"
        return "refresh", "排名處於 P11–P20，Content Refresh 可推入前 10"

    if grade == "D":
        if rank <= 30:
            return "refresh", f"排名 P{rank:.0f}，有機會 Refresh 後進入前 20"
        return "rewrite", f"排名 P{rank:.0f}，舊內容可能已不符合當前 SERP 需求"

    # Grade F
    if perf.impressions_28d < 10:
        return "deprioritize", "搜尋曝光極低，優先處理其他關鍵字"
    return "rewrite", "表現過差，建議重新撰寫"


# ── AttributionEngine ─────────────────────────────────────────────────────

class AttributionEngine:
    """文章表現歸因引擎：整合 SEORanking + Article ORM 計算單篇表現"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def get_article_performance(
        self,
        article_id: int,
        lookback_days: int = 28,
    ) -> Optional[ArticlePerformance]:
        """
        查詢單篇文章的表現指標

        Returns:
            ArticlePerformance 或 None（若無 SEO 數據）
        """
        article = self._s.get(Article, article_id)
        if article is None:
            logger.warning(f"[AttributionEngine] Article {article_id} 不存在")
            return None

        cutoff = date.today() - timedelta(days=lookback_days)
        primary_kw = article.primary_keyword or ""

        recent_rows = (
            self._s.query(SEORanking)
            .filter(
                SEORanking.project_id == article.project_id,
                SEORanking.landing_page == (article.publish_url or ""),
                SEORanking.keyword == primary_kw,
                SEORanking.tracked_date >= cutoff,
            )
            .order_by(SEORanking.tracked_date.desc())
            .all()
        )

        if not recent_rows:
            logger.debug(f"[AttributionEngine] Article {article_id} 無 SEO 數據")
            return None

        latest = recent_rows[0]
        current_rank = latest.position or 0.0
        impressions_28d = sum(r.impressions or 0 for r in recent_rows)
        clicks_28d = sum(r.clicks or 0 for r in recent_rows)
        ctr = latest.ctr or 0.0

        # 7 天排名變化：latest vs 7 天前
        week_ago = date.today() - timedelta(days=7)
        week_ago_rows = [r for r in recent_rows if r.tracked_date <= week_ago]
        rank_change_7d = 0.0
        if week_ago_rows:
            prev_rank = week_ago_rows[0].position or 0.0
            rank_change_7d = prev_rank - current_rank

        published_date: Optional[date] = None
        if article.publish_date:
            try:
                from datetime import datetime as _dt
                published_date = _dt.strptime(article.publish_date, "%Y-%m-%d").date()
            except ValueError:
                pass

        perf = ArticlePerformance(
            article_id=article_id,
            url=article.publish_url or "",
            published_date=published_date,
            target_keyword=primary_kw,
            current_rank=current_rank,
            rank_change_7d=rank_change_7d,
            impressions_28d=impressions_28d,
            clicks_28d=clicks_28d,
            ctr=ctr,
        )
        perf.performance_grade = _compute_grade(perf)
        action, reason = _compute_action(perf)
        perf.recommended_action = action
        perf.action_reason = reason
        return perf

    def get_project_performance(
        self,
        project_id: int,
        lookback_days: int = 28,
    ) -> list[ArticlePerformance]:
        """取得專案內所有已發布文章的表現歸因"""
        articles = (
            self._s.query(Article)
            .filter(
                Article.project_id == project_id,
                Article.status == "published",
                Article.publish_url.isnot(None),
                Article.publish_url != "",
            )
            .all()
        )
        results: list[ArticlePerformance] = []
        for art in articles:
            perf = self.get_article_performance(art.id, lookback_days)
            if perf is not None:
                results.append(perf)
        return results


# ── CannibalizationDetector ──────────────────────────────────────────────

class CannibalizationDetector:
    """偵測同一 project 中互相 Cannibalize 的文章"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def detect(self, project_id: int) -> list[CannibalizationPair]:
        """
        偵測規則：
        同一個 project 下，2+ 篇文章在同一關鍵字上都有 impressions
        且排名都在 P10+（position > 10）→ 標記為 Cannibalization

        Returns:
            list of CannibalizationPair（每組互競關鍵字為一個 Pair）
        """
        from collections import defaultdict

        cutoff = date.today() - timedelta(days=28)
        rows = (
            self._s.query(SEORanking)
            .filter(
                SEORanking.project_id == project_id,
                SEORanking.tracked_date >= cutoff,
                SEORanking.impressions > 0,
                SEORanking.position > 10,
            )
            .all()
        )

        # 按 keyword 分組，找到有多個 landing_page 的關鍵字
        kw_pages: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row.keyword and row.landing_page:
                kw_pages[row.keyword].add(row.landing_page)

        pairs: list[CannibalizationPair] = []
        for kw, pages in kw_pages.items():
            if len(pages) < 2:
                continue

            ids, titles, urls, positions = [], [], [], []
            for url in pages:
                art = (
                    self._s.query(Article)
                    .filter(
                        Article.project_id == project_id,
                        Article.publish_url == url,
                    )
                    .first()
                )
                ids.append(art.id if art else -1)
                titles.append(art.title if art else url)
                urls.append(url)

                latest_rank = (
                    self._s.query(SEORanking.position)
                    .filter(
                        SEORanking.project_id == project_id,
                        SEORanking.keyword == kw,
                        SEORanking.landing_page == url,
                        SEORanking.tracked_date >= cutoff,
                    )
                    .order_by(SEORanking.tracked_date.desc())
                    .scalar()
                ) or 0.0
                positions.append(latest_rank)

            suggestion = (
                f"關鍵字「{kw}」有 {len(pages)} 篇文章互相競爭（排名均 > P10）。"
                "建議合併為一篇或重新分配各文章的目標關鍵字焦點。"
            )
            pairs.append(
                CannibalizationPair(
                    keyword=kw,
                    article_ids=ids,
                    article_titles=titles,
                    article_urls=urls,
                    positions=positions,
                    suggestion=suggestion,
                )
            )

        logger.info(f"[CannibalizationDetector] project={project_id}，偵測到 {len(pairs)} 組競爭")
        return pairs


# ── RefreshTriggerChecker ────────────────────────────────────────────────

class RefreshTriggerChecker:
    """依 §7.2 規則判斷哪些文章需要 Content Refresh"""

    RANK_DROP_THRESHOLD: int = 5           # 排名下滑 > 5 位
    CONSECUTIVE_DAYS: int = 14             # 連續 2 週
    STALE_MONTHS: int = 6                  # 發布超過 6 個月
    STALE_RANK_LOW: int = 10
    STALE_RANK_HIGH: int = 30

    def __init__(self, session: Session) -> None:
        self._s = session

    def check_project(self, project_id: int) -> list[RefreshRecommendation]:
        """
        檢查整個 project 的 Content Refresh 觸發條件（任一條件成立 → 推薦）

        觸發條件：
        1. 排名下滑 > 5 個位置（連續 2 週）
        2. 發布超過 6 個月且排名 P10–P30
        3. 文章 CTR 低於該位置應有的平均值 × 50%
        """
        today = date.today()
        cutoff_28 = today - timedelta(days=28)
        cutoff_14 = today - timedelta(days=14)
        stale_cutoff = today - timedelta(days=self.STALE_MONTHS * 30)

        recommendations: list[RefreshRecommendation] = []

        articles = (
            self._s.query(Article)
            .filter(
                Article.project_id == project_id,
                Article.status == "published",
                Article.publish_url.isnot(None),
                Article.publish_url != "",
            )
            .all()
        )

        for art in articles:
            url = art.publish_url or ""
            primary_kw = art.primary_keyword or ""
            if not url or not primary_kw:
                continue

            rows = (
                self._s.query(SEORanking)
                .filter(
                    SEORanking.project_id == project_id,
                    SEORanking.keyword == primary_kw,
                    SEORanking.landing_page == url,
                    SEORanking.tracked_date >= cutoff_28,
                )
                .order_by(SEORanking.tracked_date.desc())
                .all()
            )
            if not rows:
                continue

            latest = rows[0]
            current_rank = latest.position or 0.0
            current_ctr = latest.ctr or 0.0

            # 觸發條件 1：排名下滑 > RANK_DROP_THRESHOLD，連續 2 週
            recent_rows = [r for r in rows if r.tracked_date >= cutoff_14]
            old_rows = [r for r in rows if r.tracked_date < cutoff_14]
            if recent_rows and old_rows:
                recent_rank = recent_rows[-1].position or 0.0
                old_rank = old_rows[0].position or 0.0
                rank_drop = recent_rank - old_rank      # 正 = 排名數字變大 = 變差
                if rank_drop > self.RANK_DROP_THRESHOLD:
                    recommendations.append(RefreshRecommendation(
                        article_id=art.id,
                        article_title=art.title,
                        url=url,
                        trigger_reason=(
                            f"排名近 14 天下滑 {rank_drop:.1f} 位"
                            f"（P{old_rank:.0f} → P{recent_rank:.0f}）"
                        ),
                        priority="high",
                        current_rank=current_rank,
                        previous_rank=old_rank,
                    ))
                    continue

            # 觸發條件 2：發布 > 6 個月且排名 P10–P30
            pub_date: Optional[date] = None
            if art.publish_date:
                try:
                    from datetime import datetime as _dt
                    pub_date = _dt.strptime(art.publish_date, "%Y-%m-%d").date()
                except ValueError:
                    pass

            if pub_date and pub_date <= stale_cutoff:
                if self.STALE_RANK_LOW < current_rank <= self.STALE_RANK_HIGH:
                    recommendations.append(RefreshRecommendation(
                        article_id=art.id,
                        article_title=art.title,
                        url=url,
                        trigger_reason=(
                            f"發布超過 {self.STALE_MONTHS} 個月（{pub_date}），"
                            f"目前排名 P{current_rank:.0f}，Refresh 有機會進入前 10"
                        ),
                        priority="medium",
                        current_rank=current_rank,
                    ))
                    continue

            # 觸發條件 3：CTR 低於位置應有均值的 50%
            expected_ctr = _expected_ctr(current_rank)
            if expected_ctr and current_ctr < expected_ctr * 0.5:
                recommendations.append(RefreshRecommendation(
                    article_id=art.id,
                    article_title=art.title,
                    url=url,
                    trigger_reason=(
                        f"CTR {current_ctr:.1%} 低於 P{current_rank:.0f}"
                        f" 應有均值 {expected_ctr:.1%}，建議優化 Title/Meta Description"
                    ),
                    priority="medium",
                    current_rank=current_rank,
                ))

        logger.info(
            f"[RefreshTriggerChecker] project={project_id}，"
            f"觸發 {len(recommendations)} 篇 Refresh 推薦"
        )
        return recommendations


def _expected_ctr(position: float) -> float:
    """估算特定 Google 排名的預期 CTR"""
    if position <= 1:
        return 0.25
    if position <= 2:
        return 0.15
    if position <= 3:
        return 0.10
    if position <= 5:
        return 0.06
    if position <= 10:
        return 0.03
    if position <= 20:
        return 0.01
    return 0.005
