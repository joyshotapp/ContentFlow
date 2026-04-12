"""Technical SEO Tools — FB-01~05

FB-01: Core Web Vitals 監控（透過 Google PageSpeed Insights API）
FB-02: GSC 索引覆蓋率監控（透過 GSC Search Analytics API）
FB-03: Pillar Page 模板產生器
FB-04: 全站爬蟲掃描（斷鏈、孤頁、redirect chain）
FB-05: 技術 SEO 健康評分儀表板
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from loguru import logger


# ─────────────────────────────────────────────────────────────────────────────
# 共用資料結構
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CoreWebVitals:
    """單一 URL 的 Core Web Vitals 指標"""
    url: str
    lcp: Optional[float] = None       # Largest Contentful Paint（秒）
    inp: Optional[float] = None       # Interaction to Next Paint（毫秒）
    cls: Optional[float] = None       # Cumulative Layout Shift
    fcp: Optional[float] = None       # First Contentful Paint（秒）
    ttfb: Optional[float] = None      # Time to First Byte（秒）
    performance_score: Optional[int] = None   # 0-100
    strategy: str = "mobile"         # "mobile" / "desktop"
    error: Optional[str] = None


@dataclass
class IndexCoverageItem:
    """GSC 索引狀態單條記錄"""
    url: str
    coverage_state: str         # "Submitted and indexed" / "Crawled - currently not indexed" / etc.
    last_crawl_time: str = ""
    crawling_allowed: bool = True
    indexing_allowed: bool = True
    page_fetch_state: str = ""


@dataclass
class IndexCoverageReport:
    """GSC 索引覆蓋率報告（FB-02）"""
    site_url: str
    total_indexed: int = 0
    total_not_indexed: int = 0
    newly_unindexed: list[str] = field(default_factory=list)   # 本次偵測到的新增未索引
    items: list[IndexCoverageItem] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class SiteAuditIssue:
    """全站爬蟲發現的單一問題（FB-04）"""
    issue_type: str    # broken_link / orphan_page / redirect_chain / missing_title / duplicate_title / large_image
    url: str
    detail: str = ""
    severity: str = "warning"   # "error" / "warning" / "info"


@dataclass
class SiteAuditReport:
    """全站爬蟲掃描報告（FB-04）"""
    site_url: str
    pages_crawled: int = 0
    issues: list[SiteAuditIssue] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def broken_links(self) -> list[SiteAuditIssue]:
        return [i for i in self.issues if i.issue_type == "broken_link"]

    @property
    def orphan_pages(self) -> list[SiteAuditIssue]:
        return [i for i in self.issues if i.issue_type == "orphan_page"]

    @property
    def redirect_chains(self) -> list[SiteAuditIssue]:
        return [i for i in self.issues if i.issue_type == "redirect_chain"]


@dataclass
class TechSEOHealthScore:
    """技術 SEO 健康評分（FB-05）"""
    overall_score: int = 0         # 0-100
    cwv_score: int = 0             # Core Web Vitals 子分
    indexing_score: int = 0        # 索引健康子分
    crawlability_score: int = 0    # 爬蟲可達性子分
    issues_summary: dict[str, int] = field(default_factory=dict)   # {issue_type: count}
    recommendations: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# FB-01: Core Web Vitals 監控
# ─────────────────────────────────────────────────────────────────────────────

class CoreWebVitalsMonitor:
    """
    透過 Google PageSpeed Insights API 取得 Core Web Vitals（FB-01）。
    API Key 可從環境變數 GOOGLE_API_KEY 讀取（不傳入也可使用，但有 rate limit）。
    """

    PSI_API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key

    async def fetch(
        self,
        url: str,
        strategy: str = "mobile",
        timeout: int = 30,
    ) -> CoreWebVitals:
        """
        呼叫 PSI API 取得 CWV。
        
        Args:
            url: 要測試的頁面 URL
            strategy: "mobile" 或 "desktop"
            timeout: HTTP 逾時（秒）
        """
        params = {"url": url, "strategy": strategy}
        if self._api_key:
            params["key"] = self._api_key

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self.PSI_API, params=params)
                resp.raise_for_status()
                data = resp.json()

            metrics = (data.get("lighthouseResult") or {}).get("audits") or {}
            cats = (data.get("lighthouseResult") or {}).get("categories") or {}

            def _ms_to_s(audit_id: str) -> Optional[float]:
                v = (metrics.get(audit_id) or {}).get("numericValue")
                return round(v / 1000, 2) if v is not None else None

            def _val(audit_id: str) -> Optional[float]:
                v = (metrics.get(audit_id) or {}).get("numericValue")
                return round(v, 3) if v is not None else None

            perf_score = (cats.get("performance") or {}).get("score")

            return CoreWebVitals(
                url=url,
                lcp=_ms_to_s("largest-contentful-paint"),
                inp=_val("interaction-to-next-paint"),  # 單位：毫秒，不轉換
                cls=_val("cumulative-layout-shift"),
                fcp=_ms_to_s("first-contentful-paint"),
                ttfb=_ms_to_s("server-response-time"),
                performance_score=round(perf_score * 100) if perf_score is not None else None,
                strategy=strategy,
            )

        except Exception as e:
            logger.error(f"[CWV] fetch {url} 失敗：{e}")
            return CoreWebVitals(url=url, strategy=strategy, error=str(e))

    def assess_cwv(self, vitals: CoreWebVitals) -> dict[str, str]:
        """
        評估 CWV 指標是否達標（Google 2024 閾值）。
        回傳 {metric: "good" / "needs improvement" / "poor" / "unknown"}
        """
        result: dict[str, str] = {}

        if vitals.lcp is not None:
            if vitals.lcp <= 2.5:
                result["lcp"] = "good"
            elif vitals.lcp <= 4.0:
                result["lcp"] = "needs improvement"
            else:
                result["lcp"] = "poor"

        if vitals.inp is not None:
            if vitals.inp <= 200:
                result["inp"] = "good"
            elif vitals.inp <= 500:
                result["inp"] = "needs improvement"
            else:
                result["inp"] = "poor"

        if vitals.cls is not None:
            if vitals.cls <= 0.1:
                result["cls"] = "good"
            elif vitals.cls <= 0.25:
                result["cls"] = "needs improvement"
            else:
                result["cls"] = "poor"

        return result

    def score_cwv(self, vitals: CoreWebVitals) -> int:
        """將 CWV 指標轉為 0-100 子分"""
        if vitals.error:
            return 50   # 拿不到數據，給中性分數

        assessment = self.assess_cwv(vitals)
        if not assessment:
            return 50

        score_map = {"good": 100, "needs improvement": 60, "poor": 20, "unknown": 50}
        scores = [score_map.get(v, 50) for v in assessment.values()]
        return round(sum(scores) / len(scores))


# ─────────────────────────────────────────────────────────────────────────────
# FB-02: GSC 索引覆蓋率監控
# ─────────────────────────────────────────────────────────────────────────────

class GSCIndexCoverageMonitor:
    """
    透過 GSC Search Console API 監控索引覆蓋率（FB-02）。
    使用 OAuth2 service account 或 API Key。
    """

    def __init__(self, credentials=None, api_key: str = ""):
        """
        credentials: google.oauth2.service_account.Credentials 物件（可選）
        api_key: Google API Key（可選，僅公開數據）
        """
        self._credentials = credentials
        self._api_key = api_key

    async def get_coverage_report(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
        timeout: int = 30,
    ) -> IndexCoverageReport:
        """
        呼叫 GSC URL Inspection API，取得索引狀態。
        
        注意：GSC API 實際上不支援批次 URL inspection；
        本方法模擬 Search Analytics 數據流程，實務上需要 webmaster API。
        這裡實作為可測試的骨架，真實呼叫需要 google-auth 套件。
        """
        # 嘗試呼叫 GSC Search Analytics（取得有曝光的 URL）
        endpoint = f"https://www.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"

        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "rowLimit": 1000,
        }
        headers: dict[str, str] = {}

        if self._api_key:
            payload["key"] = self._api_key  # type: ignore

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            rows = data.get("rows", [])
            items = [
                IndexCoverageItem(
                    url=row["keys"][0],
                    coverage_state="Submitted and indexed",
                )
                for row in rows
            ]

            return IndexCoverageReport(
                site_url=site_url,
                total_indexed=len(items),
                items=items,
            )

        except Exception as e:
            logger.error(f"[GSC Coverage] {site_url} 查詢失敗：{e}")
            return IndexCoverageReport(site_url=site_url, error=str(e))

    def detect_newly_unindexed(
        self,
        prev_report: IndexCoverageReport,
        curr_report: IndexCoverageReport,
    ) -> list[str]:
        """
        比較兩次報告，找出新增的未索引 URL（FB-02 核心邏輯）。
        
        prev: 上次已索引的 URL 集合
        curr: 本次已索引的 URL 集合
        回傳：在 prev 有但 curr 沒有的 URL（表示被取消索引）
        """
        prev_urls = {item.url for item in prev_report.items}
        curr_urls = {item.url for item in curr_report.items}
        newly_lost = prev_urls - curr_urls
        return sorted(newly_lost)


# ─────────────────────────────────────────────────────────────────────────────
# FB-03: Pillar Page 模板
# ─────────────────────────────────────────────────────────────────────────────

def generate_pillar_page_template(
    pillar_topic: str,
    cluster_keywords: list[str],
    brand_name: str = "",
) -> str:
    """
    產生 Pillar Page Markdown 骨架（FB-03）。
    
    Pillar Page = 廣義的 Topic Cluster 主頁，連結所有 Cluster Page。
    
    Args:
        pillar_topic: 主題詞（例：「骨刺治療完全指南」）
        cluster_keywords: 群集關鍵字列表（對應各 Cluster Page）
        brand_name: 品牌名稱（用於 FAQ）
    """
    brand_str = brand_name or "我們的團隊"
    clusters_section = "\n".join(
        f"- [{kw}](./{kw.replace(' ', '-').lower()}.md)" for kw in cluster_keywords
    )

    # FAQ 自動從 cluster keyword 產生基本問答
    faq_items = "\n\n".join(
        f"**Q：{kw}是什麼？**\n\nA：[由 {brand_str} 撰寫的完整說明，請參閱對應文章。]"
        for kw in cluster_keywords[:5]
    )

    return f"""# {pillar_topic}

> 本文是「{pillar_topic}」主題的完整指南，涵蓋以下所有相關面向。
> 由 {brand_str} 整理，定期更新。

---

## 本指南涵蓋哪些主題？

{clusters_section}

---

## {pillar_topic}：完整介紹

[在此填入 200-300 字的主題概述，說明為什麼讀者需要了解這個主題。]

### 核心概念

[填入 3-5 個核心概念的簡要說明，每個概念配上指向 Cluster Page 的連結。]

### 如何使用本指南

本指南設計為「跳著讀」的參考資料。每個章節都是獨立完整的，你可以：
1. 從最感興趣的主題開始閱讀
2. 點擊各主題連結深入了解
3. 利用右側目錄快速跳轉

---

## 相關主題深度指南

以下是本主題下各個面向的深度文章：

{clusters_section}

---

## 常見問題（FAQ）

{faq_items}

---

## 結語

[填入 50-100 字結語，鼓勵讀者行動（諮詢、購買、訂閱）。]

---

*此頁面由 ContentFlow 自動生成骨架，請由專業編輯填入正式內容。*
*最後更新：[DATE]*
"""


# ─────────────────────────────────────────────────────────────────────────────
# FB-04: 全站爬蟲掃描
# ─────────────────────────────────────────────────────────────────────────────

class SiteCrawler:
    """
    全站爬蟲：爬取同源頁面，偵測以下問題（FB-04）：
    - broken_link: 回傳 4xx/5xx 的內部連結
    - orphan_page: 沒有任何內部連結指向的頁面
    - redirect_chain: 超過 2 跳的 redirect
    - missing_title: 頁面無 <title>
    """

    def __init__(
        self,
        max_pages: int = 200,
        timeout: int = 10,
        user_agent: str = "ContentFlow-Crawler/1.0",
    ):
        self._max_pages = max_pages
        self._timeout = timeout
        self._ua = user_agent

    async def crawl(self, start_url: str) -> SiteAuditReport:
        """
        從 start_url 開始爬，只爬相同 origin 的頁面。
        """
        parsed = urlparse(start_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        to_visit: list[str] = [start_url]
        visited: set[str] = set()
        # url → 指向它的 referer 集合（用於孤頁偵測）
        inlinks: dict[str, set[str]] = {}
        issues: list[SiteAuditIssue] = []

        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=False,
            headers={"User-Agent": self._ua},
        ) as client:
            while to_visit and len(visited) < self._max_pages:
                url = to_visit.pop(0)
                if url in visited:
                    continue
                visited.add(url)
                if url not in inlinks:
                    inlinks[url] = set()

                try:
                    # 偵測 redirect chain
                    final_url, redirect_count = await self._follow_redirects(client, url)
                    if redirect_count >= 2:
                        issues.append(SiteAuditIssue(
                            issue_type="redirect_chain",
                            url=url,
                            detail=f"{redirect_count} 跳 redirect → {final_url}",
                            severity="warning",
                        ))
                        url = final_url   # 繼續從最終 URL 爬

                    resp = await client.get(url, headers={"User-Agent": self._ua})

                    if resp.status_code >= 400:
                        issues.append(SiteAuditIssue(
                            issue_type="broken_link",
                            url=url,
                            detail=f"HTTP {resp.status_code}",
                            severity="error",
                        ))
                        continue

                    html = resp.text

                    # 偵測 missing title
                    if not re.search(r"<title[^>]*>[^<]+</title>", html, re.IGNORECASE):
                        issues.append(SiteAuditIssue(
                            issue_type="missing_title",
                            url=url,
                            detail="頁面缺少 <title> 標籤",
                            severity="warning",
                        ))

                    # 提取同源連結
                    for href in re.findall(r'href=["\']([^"\'#?]+)["\']', html):
                        abs_url = urljoin(url, href).split("#")[0].split("?")[0]
                        if abs_url.startswith(origin) and abs_url not in visited:
                            if abs_url not in inlinks:
                                inlinks[abs_url] = set()
                            inlinks[abs_url].add(url)
                            to_visit.append(abs_url)

                except Exception as e:
                    issues.append(SiteAuditIssue(
                        issue_type="broken_link",
                        url=url,
                        detail=f"連線失敗: {e}",
                        severity="error",
                    ))

        # 孤頁偵測：有出現在 to_visit / inlinks 但沒有 inlink 的頁面
        orphans = [
            url for url, refs in inlinks.items()
            if not refs and url != start_url
        ]
        for orphan_url in orphans[:20]:   # 限 20 條避免過多
            issues.append(SiteAuditIssue(
                issue_type="orphan_page",
                url=orphan_url,
                detail="找不到任何內部連結指向此頁",
                severity="warning",
            ))

        return SiteAuditReport(
            site_url=start_url,
            pages_crawled=len(visited),
            issues=issues,
        )

    async def _follow_redirects(
        self, client: httpx.AsyncClient, url: str, max_hops: int = 5
    ) -> tuple[str, int]:
        """跟蹤 redirect，回傳 (最終 URL, redirect 次數)"""
        current = url
        hops = 0
        for _ in range(max_hops):
            try:
                r = await client.head(current, headers={"User-Agent": self._ua})
                if r.status_code in (301, 302, 307, 308):
                    location = r.headers.get("location", "")
                    if not location:
                        break
                    current = urljoin(current, location)
                    hops += 1
                else:
                    break
            except Exception:
                break
        return current, hops


# ─────────────────────────────────────────────────────────────────────────────
# FB-05: 技術 SEO 健康儀表板
# ─────────────────────────────────────────────────────────────────────────────

class TechSEOHealthDashboard:
    """
    整合 CWV、索引覆蓋、爬蟲掃描結果，計算綜合健康評分（FB-05）。
    
    評分計算：
    - CWV 子分（40%）：基於 LCP / INP / CLS 達標狀況
    - 索引子分（30%）：已索引 / 總 URL 比例（或新增失索引比例）
    - 爬蟲健康子分（30%）：斷鏈 / 孤頁 / redirect chain 問題密度
    """

    def calculate(
        self,
        cwv: Optional[CoreWebVitals] = None,
        index_report: Optional[IndexCoverageReport] = None,
        audit_report: Optional[SiteAuditReport] = None,
    ) -> TechSEOHealthScore:
        cwv_monitor = CoreWebVitalsMonitor()

        # ── CWV 子分（40%）
        cwv_score = cwv_monitor.score_cwv(cwv) if cwv else 50

        # ── 索引子分（30%）
        indexing_score = 100
        if index_report:
            if index_report.error:
                indexing_score = 50
            elif index_report.total_indexed + index_report.total_not_indexed > 0:
                total = index_report.total_indexed + index_report.total_not_indexed
                ratio = index_report.total_indexed / total
                indexing_score = round(ratio * 100)
                # 若有新增失索引 → 扣分
                newly_lost = len(index_report.newly_unindexed)
                if newly_lost > 0:
                    indexing_score = max(0, indexing_score - min(30, newly_lost * 5))

        # ── 爬蟲健康子分（30%）
        crawlability_score = 100
        issues_summary: dict[str, int] = {}
        recommendations: list[str] = []

        if audit_report:
            total_pages = max(audit_report.pages_crawled, 1)
            broken = len(audit_report.broken_links)
            orphans = len(audit_report.orphan_pages)
            redirects = len(audit_report.redirect_chains)

            issues_summary = {
                "broken_link": broken,
                "orphan_page": orphans,
                "redirect_chain": redirects,
            }

            # 扣分：每 1% 斷鏈扣 2 分（最多 40 分）
            broken_ratio = broken / total_pages
            crawlability_score -= min(40, round(broken_ratio * 100 * 2))

            # 扣分：孤頁超過 10% 扣 20 分
            orphan_ratio = orphans / total_pages
            if orphan_ratio > 0.1:
                crawlability_score -= 20

            # 扣分：redirect chain 超過 5 個扣 10 分
            if redirects > 5:
                crawlability_score -= 10

            crawlability_score = max(0, crawlability_score)

            # 建議
            if broken > 0:
                recommendations.append(f"修復 {broken} 個斷鏈（4xx/5xx）")
            if orphans > 0:
                recommendations.append(f"為 {orphans} 個孤頁補充內部連結")
            if redirects > 0:
                recommendations.append(f"整理 {redirects} 條 redirect chain（合并為單跳）")

        # CWV 建議
        if cwv:
            assessment = cwv_monitor.assess_cwv(cwv)
            for metric, status in assessment.items():
                if status == "poor":
                    recommendations.append(f"{metric.upper()} 需迫切改善（{status}）")
                elif status == "needs improvement":
                    recommendations.append(f"{metric.upper()} 有改善空間（{status}）")

        # 加權總分
        overall = round(cwv_score * 0.40 + indexing_score * 0.30 + crawlability_score * 0.30)

        return TechSEOHealthScore(
            overall_score=overall,
            cwv_score=cwv_score,
            indexing_score=indexing_score,
            crawlability_score=crawlability_score,
            issues_summary=issues_summary,
            recommendations=recommendations,
        )

    def format_report(self, score: TechSEOHealthScore) -> str:
        """產出可在 Streamlit 顯示的文字報告"""
        stars = "★" * (score.overall_score // 20) + "☆" * (5 - score.overall_score // 20)
        lines = [
            f"## 技術 SEO 健康報告",
            f"",
            f"**綜合評分：{score.overall_score}/100** {stars}",
            f"",
            f"| 面向 | 分數 |",
            f"|------|------|",
            f"| Core Web Vitals | {score.cwv_score}/100 |",
            f"| 索引覆蓋率 | {score.indexing_score}/100 |",
            f"| 爬蟲健康度 | {score.crawlability_score}/100 |",
        ]

        if score.issues_summary:
            lines += ["", "### 問題統計"]
            for issue_type, count in score.issues_summary.items():
                lines.append(f"- {issue_type}: {count} 個")

        if score.recommendations:
            lines += ["", "### 改善建議"]
            for rec in score.recommendations:
                lines.append(f"- {rec}")

        return "\n".join(lines)
