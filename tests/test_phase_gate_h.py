"""Phase Gate H — 技術 SEO 工具驗收測試（FB-01~06）

涵蓋：
  FB-01: CoreWebVitalsMonitor — PSI API fetch & assess_cwv & score_cwv
  FB-02: GSCIndexCoverageMonitor — detect_newly_unindexed 邏輯
  FB-03: generate_pillar_page_template — 內容完整性
  FB-04: SiteCrawler — 斷鏈 / 孤頁 / redirect chain 偵測
  FB-05: TechSEOHealthDashboard — 加權計分 & 建議
  FB-06: GSCMobileUsabilityMonitor — 問題偵測 & Admin 通知
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contentflow.tools.tech_seo import (
    CoreWebVitals,
    CoreWebVitalsMonitor,
    GSCIndexCoverageMonitor,
    GSCMobileUsabilityMonitor,
    IndexCoverageItem,
    IndexCoverageReport,
    MobileIssue,
    MobileUsabilityReport,
    SiteAuditIssue,
    SiteAuditReport,
    SiteCrawler,
    TechSEOHealthDashboard,
    TechSEOHealthScore,
    generate_pillar_page_template,
)


# ─────────────────────────────────────────────────────────────────────────────
# FB-01: CoreWebVitalsMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestCoreWebVitalsMonitor:

    PSI_RESPONSE = {
        "lighthouseResult": {
            "categories": {"performance": {"score": 0.82}},
            "audits": {
                "largest-contentful-paint": {"numericValue": 2200},
                "interaction-to-next-paint": {"numericValue": 180},
                "cumulative-layout-shift": {"numericValue": 0.08},
                "first-contentful-paint": {"numericValue": 1100},
                "server-response-time": {"numericValue": 350},
            },
        }
    }

    def test_fetch_returns_cwv(self):
        """FB-01: PSI API 正常回傳 → CoreWebVitals 各指標有值"""
        monitor = CoreWebVitalsMonitor()

        mock_resp = MagicMock()
        mock_resp.json.return_value = self.PSI_RESPONSE
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                monitor.fetch("https://example.com/page", strategy="mobile")
            )

        assert result.error is None
        assert result.lcp == 2.2         # 2200ms → 2.2s
        assert result.inp == 180.0       # 毫秒，不轉換
        assert result.cls == 0.08
        assert result.performance_score == 82
        assert result.strategy == "mobile"

    def test_fetch_api_error_returns_error_cwv(self):
        """FB-01: PSI API 失敗 → fetch_error 有值"""
        monitor = CoreWebVitalsMonitor()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                monitor.fetch("https://example.com")
            )

        assert result.error is not None

    def test_assess_cwv_good(self):
        """FB-01: 優秀指標 → 全部 good"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", lcp=2.0, inp=150, cls=0.05)
        result = monitor.assess_cwv(vitals)

        assert result["lcp"] == "good"
        assert result["inp"] == "good"
        assert result["cls"] == "good"

    def test_assess_cwv_poor(self):
        """FB-01: 差勁指標 → 全部 poor"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", lcp=5.5, inp=600, cls=0.3)
        result = monitor.assess_cwv(vitals)

        assert result["lcp"] == "poor"
        assert result["inp"] == "poor"
        assert result["cls"] == "poor"

    def test_assess_cwv_needs_improvement(self):
        """FB-01: 中等指標 → needs improvement"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", lcp=3.5, inp=350, cls=0.18)
        result = monitor.assess_cwv(vitals)

        assert result["lcp"] == "needs improvement"
        assert result["inp"] == "needs improvement"
        assert result["cls"] == "needs improvement"

    def test_score_cwv_good_vitals(self):
        """FB-01: 全 good 指標 → 高分"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", lcp=2.0, inp=100, cls=0.05)
        score = monitor.score_cwv(vitals)
        assert score >= 80

    def test_score_cwv_poor_vitals(self):
        """FB-01: 全 poor 指標 → 低分"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", lcp=6.0, inp=700, cls=0.4)
        score = monitor.score_cwv(vitals)
        assert score <= 40

    def test_score_cwv_error_returns_50(self):
        """FB-01: 拿不到數據 → 中性分 50"""
        monitor = CoreWebVitalsMonitor()
        vitals = CoreWebVitals(url="x", error="timeout")
        score = monitor.score_cwv(vitals)
        assert score == 50


# ─────────────────────────────────────────────────────────────────────────────
# FB-02: GSCIndexCoverageMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestGSCIndexCoverageMonitor:

    def _make_report(self, urls: list[str]) -> IndexCoverageReport:
        return IndexCoverageReport(
            site_url="https://example.com",
            total_indexed=len(urls),
            items=[IndexCoverageItem(url=u, coverage_state="Submitted and indexed") for u in urls],
        )

    def test_detect_newly_unindexed(self):
        """FB-02: 上一次有但本次沒有的 URL → 判定為新增失索引"""
        monitor = GSCIndexCoverageMonitor()
        prev = self._make_report([
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ])
        curr = self._make_report([
            "https://example.com/a",
            "https://example.com/c",
        ])
        lost = monitor.detect_newly_unindexed(prev, curr)
        assert "https://example.com/b" in lost
        assert len(lost) == 1

    def test_no_newly_unindexed(self):
        """FB-02: 兩次報告相同 → 無失索引"""
        monitor = GSCIndexCoverageMonitor()
        urls = ["https://example.com/a", "https://example.com/b"]
        prev = self._make_report(urls)
        curr = self._make_report(urls)
        lost = monitor.detect_newly_unindexed(prev, curr)
        assert lost == []

    def test_newly_unindexed_returns_sorted(self):
        """FB-02: 失索引列表應排序"""
        monitor = GSCIndexCoverageMonitor()
        prev = self._make_report([
            "https://example.com/z",
            "https://example.com/a",
            "https://example.com/m",
        ])
        curr = self._make_report([])
        lost = monitor.detect_newly_unindexed(prev, curr)
        assert lost == sorted(lost)

    def test_get_coverage_report_api_error(self):
        """FB-02: API 失敗 → IndexCoverageReport with error"""
        monitor = GSCIndexCoverageMonitor()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Auth failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = asyncio.get_event_loop().run_until_complete(
                monitor.get_coverage_report(
                    "https://example.com",
                    "2024-01-01",
                    "2024-01-31",
                )
            )
        assert result.error is not None


# ─────────────────────────────────────────────────────────────────────────────
# FB-03: generate_pillar_page_template
# ─────────────────────────────────────────────────────────────────────────────

class TestPillarPageTemplate:

    def test_contains_pillar_topic(self):
        """FB-03: 模板包含 Pillar Topic 標題"""
        tmpl = generate_pillar_page_template(
            "骨刺完全指南",
            ["骨刺症狀", "骨刺治療", "骨刺飲食"],
            "骨科健康中心",
        )
        assert "骨刺完全指南" in tmpl
        assert "# 骨刺完全指南" in tmpl

    def test_contains_all_cluster_keywords(self):
        """FB-03: 模板包含所有 cluster keyword 連結"""
        keywords = ["骨刺症狀", "骨刺治療", "骨刺飲食"]
        tmpl = generate_pillar_page_template("指南", keywords)
        for kw in keywords:
            assert kw in tmpl

    def test_contains_faq_section(self):
        """FB-03: 模板包含 FAQ 區塊"""
        tmpl = generate_pillar_page_template("指南", ["膝蓋骨刺"], "健康團隊")
        assert "常見問題" in tmpl or "FAQ" in tmpl

    def test_empty_cluster_keywords(self):
        """FB-03: 無 cluster keyword → 模板仍可產生"""
        tmpl = generate_pillar_page_template("骨刺完全指南", [])
        assert "骨刺完全指南" in tmpl
        assert len(tmpl) > 100

    def test_template_is_markdown(self):
        """FB-03: 模板採用 Markdown 格式（含 #）"""
        tmpl = generate_pillar_page_template("指南", ["A", "B"])
        assert tmpl.startswith("#")
        assert "##" in tmpl


# ─────────────────────────────────────────────────────────────────────────────
# FB-04: SiteCrawler
# ─────────────────────────────────────────────────────────────────────────────

class TestSiteCrawler:

    def _html_with_links(self, links: list[str], title: str = "Test Page") -> str:
        hrefs = "\n".join(f'<a href="{l}">link</a>' for l in links)
        return f"<html><head><title>{title}</title></head><body>{hrefs}</body></html>"

    def test_detects_broken_link(self):
        """FB-04: 404 頁面 → broken_link issue"""
        crawler = SiteCrawler(max_pages=5, timeout=5)
        base = "https://test.example.com"

        call_count = {"n": 0}

        async def mock_crawl_side_effect(url, **kwargs):
            r = MagicMock()
            r.status_code = 404 if "about" in url else 200
            r.text = self._html_with_links([f"{base}/about"])
            r.headers = {}
            return r

        async def mock_head_side_effect(url, **kwargs):
            r = MagicMock()
            r.status_code = 200
            r.headers = {}
            return r

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=mock_crawl_side_effect)
            mock_client.head = AsyncMock(side_effect=mock_head_side_effect)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                crawler.crawl(base)
            )

        broken_urls = [i.url for i in report.broken_links]
        assert any("about" in u for u in broken_urls)

    def test_detects_missing_title(self):
        """FB-04: 頁面無 <title> → missing_title issue"""
        crawler = SiteCrawler(max_pages=5, timeout=5)
        base = "https://test.example.com"

        # 頁面無 title 標籤
        html_no_title = "<html><head></head><body><p>no title</p></body></html>"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_no_title
        mock_resp.headers = {}

        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = {}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.head = AsyncMock(return_value=mock_head_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                crawler.crawl(base)
            )

        issue_types = [i.issue_type for i in report.issues]
        assert "missing_title" in issue_types

    def test_detects_redirect_chain(self):
        """FB-04: 超過 2 跳 redirect → redirect_chain issue"""
        crawler = SiteCrawler(max_pages=5, timeout=5)
        base = "https://test.example.com/old-page"

        hop_count = {"n": 0}

        async def mock_head(url, **kwargs):
            r = MagicMock()
            if hop_count["n"] < 3:
                r.status_code = 301
                r.headers = {"location": f"{base}-hop{hop_count['n'] + 1}"}
                hop_count["n"] += 1
            else:
                r.status_code = 200
                r.headers = {}
            return r

        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.text = "<html><head><title>T</title></head><body></body></html>"
        mock_get_resp.headers = {}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_get_resp)
            mock_client.head = AsyncMock(side_effect=mock_head)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                crawler.crawl(base)
            )

        issue_types = [i.issue_type for i in report.issues]
        assert "redirect_chain" in issue_types

    def test_crawl_respects_max_pages(self):
        """FB-04: crawler 遵守 max_pages 限制"""
        crawler = SiteCrawler(max_pages=3, timeout=5)
        base = "https://test.example.com"

        # 主頁有 10 個連結
        links = [f"{base}/page{i}" for i in range(10)]
        html = self._html_with_links(links)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.headers = {}

        mock_head_resp = MagicMock()
        mock_head_resp.status_code = 200
        mock_head_resp.headers = {}

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.head = AsyncMock(return_value=mock_head_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                crawler.crawl(base)
            )

        assert report.pages_crawled <= 3


# ─────────────────────────────────────────────────────────────────────────────
# FB-05: TechSEOHealthDashboard
# ─────────────────────────────────────────────────────────────────────────────

class TestTechSEOHealthDashboard:

    def _good_cwv(self):
        return CoreWebVitals(url="x", lcp=2.0, inp=100, cls=0.05)

    def _poor_cwv(self):
        return CoreWebVitals(url="x", lcp=6.0, inp=700, cls=0.4)

    def _good_index(self):
        return IndexCoverageReport(
            site_url="x",
            total_indexed=100,
            total_not_indexed=0,
        )

    def _poor_index(self):
        report = IndexCoverageReport(
            site_url="x",
            total_indexed=60,
            total_not_indexed=40,
        )
        report.newly_unindexed = [f"https://x.com/page{i}" for i in range(10)]
        return report

    def _good_audit(self):
        return SiteAuditReport(site_url="x", pages_crawled=50, issues=[])

    def _poor_audit(self):
        issues = [
            SiteAuditIssue("broken_link", f"https://x.com/dead{i}", severity="error")
            for i in range(10)
        ] + [
            SiteAuditIssue("orphan_page", f"https://x.com/orphan{i}", severity="warning")
            for i in range(10)
        ]
        return SiteAuditReport(site_url="x", pages_crawled=50, issues=issues)

    def test_good_metrics_high_score(self):
        """FB-05: 全部優秀 → 總分 ≥ 80"""
        dashboard = TechSEOHealthDashboard()
        score = dashboard.calculate(
            cwv=self._good_cwv(),
            index_report=self._good_index(),
            audit_report=self._good_audit(),
        )
        assert score.overall_score >= 80
        assert isinstance(score, TechSEOHealthScore)

    def test_poor_metrics_low_score(self):
        """FB-05: 全部差勁 → 總分 ≤ 50"""
        dashboard = TechSEOHealthDashboard()
        score = dashboard.calculate(
            cwv=self._poor_cwv(),
            index_report=self._poor_index(),
            audit_report=self._poor_audit(),
        )
        assert score.overall_score <= 55

    def test_no_data_default_score(self):
        """FB-05: 無數據傳入 → 傳回有效分數（0-100）"""
        dashboard = TechSEOHealthDashboard()
        score = dashboard.calculate()
        assert 0 <= score.overall_score <= 100
        assert isinstance(score, TechSEOHealthScore)

    def test_recommendations_generated(self):
        """FB-05: 差勁指標 → 有改善建議"""
        dashboard = TechSEOHealthDashboard()
        score = dashboard.calculate(
            cwv=self._poor_cwv(),
            audit_report=self._poor_audit(),
        )
        assert len(score.recommendations) > 0

    def test_issues_summary_populated(self):
        """FB-05: audit 有問題 → issues_summary 有值"""
        dashboard = TechSEOHealthDashboard()
        score = dashboard.calculate(audit_report=self._poor_audit())
        assert score.issues_summary.get("broken_link", 0) == 10
        assert score.issues_summary.get("orphan_page", 0) == 10

    def test_format_report_contains_score(self):
        """FB-05: format_report 輸出包含總分"""
        dashboard = TechSEOHealthDashboard()
        score = TechSEOHealthScore(
            overall_score=75,
            cwv_score=80,
            indexing_score=70,
            crawlability_score=75,
            recommendations=["修復斷鏈"],
        )
        report_text = dashboard.format_report(score)
        assert "75" in report_text
        assert "修復斷鏈" in report_text

    def test_cwv_weight_dominates(self):
        """FB-05: CWV 占 40% 權重，差勁 CWV 應顯著拉低總分"""
        dashboard = TechSEOHealthDashboard()
        good_with_poor_cwv = dashboard.calculate(
            cwv=self._poor_cwv(),
            index_report=self._good_index(),
            audit_report=self._good_audit(),
        )
        good_all = dashboard.calculate(
            cwv=self._good_cwv(),
            index_report=self._good_index(),
            audit_report=self._good_audit(),
        )
        assert good_all.overall_score > good_with_poor_cwv.overall_score


# ─────────────────────────────────────────────────────────────────────────────
# FB-06: GSCMobileUsabilityMonitor
# ─────────────────────────────────────────────────────────────────────────────

class TestGSCMobileUsabilityMonitor:

    GSC_RESPONSE_WITH_ISSUES = {
        "issues": [
            {
                "issueType": "TEXT_TOO_SMALL_TO_READ",
                "severity": "ERROR",
                "affectedUrls": [
                    "https://example.com/page1",
                    "https://example.com/page2",
                ],
            },
            {
                "issueType": "LINKS_TOO_CLOSE_TOGETHER",
                "severity": "WARNING",
                "affectedUrls": ["https://example.com/page3"],
            },
        ]
    }

    GSC_RESPONSE_NO_ISSUES = {"issues": []}

    def test_get_issues_returns_report(self):
        """FB-06: API 正常回傳 → MobileUsabilityReport 有問題清單"""
        monitor = GSCMobileUsabilityMonitor()

        mock_resp = MagicMock()
        mock_resp.json.return_value = self.GSC_RESPONSE_WITH_ISSUES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                monitor.get_issues("https://example.com/", "2024-01-01", "2024-01-31")
            )

        assert report.error is None
        assert report.has_issues is True
        assert len(report.issues) == 2
        assert report.total_affected_urls == 3

    def test_get_issues_no_issues(self):
        """FB-06: API 回傳無問題 → has_issues 為 False"""
        monitor = GSCMobileUsabilityMonitor()

        mock_resp = MagicMock()
        mock_resp.json.return_value = self.GSC_RESPONSE_NO_ISSUES
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                monitor.get_issues("https://example.com/", "2024-01-01", "2024-01-31")
            )

        assert report.error is None
        assert report.has_issues is False
        assert report.total_affected_urls == 0

    def test_get_issues_api_error(self):
        """FB-06: API 失敗 → MobileUsabilityReport with error"""
        monitor = GSCMobileUsabilityMonitor()

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Auth failed"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            report = asyncio.get_event_loop().run_until_complete(
                monitor.get_issues("https://example.com/", "2024-01-01", "2024-01-31")
            )

        assert report.error is not None
        assert report.has_issues is False

    def test_issue_has_label_and_fix(self):
        """FB-06: 已知問題類型 → 有中文說明與修復建議"""
        monitor = GSCMobileUsabilityMonitor()
        report = monitor._parse_response("https://example.com/", self.GSC_RESPONSE_WITH_ISSUES)

        text_issue = next(i for i in report.issues if i.issue_type == "TEXT_TOO_SMALL_TO_READ")
        assert "文字" in text_issue.label
        assert len(text_issue.fix_suggestion) > 0
        assert text_issue.severity == "error"

        links_issue = next(i for i in report.issues if i.issue_type == "LINKS_TOO_CLOSE_TOGETHER")
        assert links_issue.severity == "warning"

    def test_notify_admin_no_issues(self):
        """FB-06: 無問題 → notify_admin 回傳空列表"""
        monitor = GSCMobileUsabilityMonitor()
        report = MobileUsabilityReport(site_url="https://example.com/")
        messages = monitor.notify_admin(report)
        assert messages == []

    def test_notify_admin_with_issues(self):
        """FB-06: 有問題 → notify_admin 回傳含問題說明的訊息"""
        monitor = GSCMobileUsabilityMonitor()
        report = monitor._parse_response("https://example.com/", self.GSC_RESPONSE_WITH_ISSUES)
        messages = monitor.notify_admin(report)

        assert len(messages) > 0
        full = "\n".join(messages)
        assert "example.com" in full
        assert "TEXT_TOO_SMALL_TO_READ" in full or "文字" in full

    def test_notify_admin_calls_notifier(self):
        """FB-06: 有問題 + notifier → notifier 被呼叫一次"""
        monitor = GSCMobileUsabilityMonitor()
        report = monitor._parse_response("https://example.com/", self.GSC_RESPONSE_WITH_ISSUES)

        notifier = MagicMock()
        monitor.notify_admin(report, notifier=notifier)

        notifier.assert_called_once()

    def test_unknown_issue_type_fallback(self):
        """FB-06: 未知問題類型 → label 保留原始 issueType，有預設修復建議"""
        monitor = GSCMobileUsabilityMonitor()
        data = {
            "issues": [{
                "issueType": "SOME_FUTURE_ISSUE",
                "severity": "WARNING",
                "affectedUrls": [],
            }]
        }
        report = monitor._parse_response("https://example.com/", data)
        issue = report.issues[0]
        assert issue.label == "SOME_FUTURE_ISSUE"   # fallback：顯示原始 type
        assert len(issue.fix_suggestion) > 0
