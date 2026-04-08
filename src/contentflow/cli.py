"""CLI 入口：contentflow research <title> --keywords ..."""

from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from loguru import logger

# 調整日誌格式
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level="INFO",
)


def main() -> None:
    """CLI 主入口"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="contentflow",
        description="ContentFlow AI — SEO 文章自動化 Agent",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── research 子命令 ──────────────────────────────────────
    research_cmd = subparsers.add_parser(
        "research",
        help="執行 Research Agent，產出研究報告",
    )
    research_cmd.add_argument("title", help="文章標題")
    research_cmd.add_argument(
        "--ingredients", "-i",
        nargs="+",
        default=[],
        help="成分英文關鍵字（可多個）",
    )
    research_cmd.add_argument(
        "--conditions", "-c",
        nargs="+",
        default=[],
        help="病症/功效關鍵字（可多個）",
    )
    research_cmd.add_argument(
        "--output", "-o",
        default=None,
        help="輸出 Markdown 檔案路徑（預設：outputs/<title>.md）",
    )

    args = parser.parse_args()

    if args.command == "research":
        asyncio.run(_run_research(args))


async def _run_research(args) -> None:
    from .agents import run_research_agent
    from .utils.report_renderer import render_research_report

    report = await run_research_agent(
        article_title=args.title,
        ingredient_keywords=args.ingredients,
        condition_keywords=args.conditions,
    )

    md = render_research_report(report)

    output_path = args.output
    if output_path is None:
        safe_name = args.title.replace(" ", "_").replace("/", "-")[:50]
        output_path = f"outputs/{safe_name}.md"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(md, encoding="utf-8")
    logger.info(f"研究報告已儲存：{output_path}")
    print(md)


if __name__ == "__main__":
    main()
