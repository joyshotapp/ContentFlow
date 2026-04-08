"""研究報告 Markdown 格式輸出工具"""

from __future__ import annotations
from datetime import datetime
from ..models import ResearchReport


def render_research_report(report: ResearchReport) -> str:
    """將 ResearchReport 轉換為 Markdown 字串"""
    lines: list[str] = []

    lines.append(f"# 研究報告：{report.article_title}")
    lines.append(f"\n> 生成時間：{report.created_at.strftime('%Y-%m-%d %H:%M')}\n")

    # ── 關鍵字 ───────────────────────────────────────────────
    lines.append("## 目標關鍵字\n")
    lines.append(", ".join(f"`{k}`" for k in report.keywords))
    lines.append("")

    # ── 建議 SEO 關鍵字 ──────────────────────────────────────
    if report.suggested_keywords:
        lines.append("## 建議 SEO 關鍵字\n")
        lines.append(", ".join(f"`{k}`" for k in report.suggested_keywords[:20]))
        lines.append("")

    # ── PAA 問題 ─────────────────────────────────────────────
    if report.paa_questions:
        lines.append("## People Also Ask\n")
        for q in report.paa_questions:
            lines.append(f"- {q}")
        lines.append("")

    # ── 競品標題 ─────────────────────────────────────────────
    if report.competitor_headings:
        lines.append("## 競品文章標題（前 10 名）\n")
        for i, h in enumerate(report.competitor_headings[:10], 1):
            lines.append(f"{i}. {h}")
        lines.append("")

    # ── PubMed 期刊摘要 ──────────────────────────────────────
    lines.append("## PubMed 期刊佐證\n")
    for result in report.pubmed_results:
        lines.append(f"### 查詢：{result.query}（共 {result.total_found} 篇）\n")
        for a in result.articles[:5]:  # 每組最多顯示 5 篇
            year = a.pub_year or "N/A"
            lines.append(f"**{a.title}** ({year})")
            lines.append(f"*{a.journal}*")
            if a.abstract:
                lines.append(f"\n{a.abstract[:400]}{'...' if len(a.abstract) > 400 else ''}")
            lines.append(f"\n[PubMed 連結]({a.url})\n")
            lines.append("---")
        lines.append("")

    return "\n".join(lines)
