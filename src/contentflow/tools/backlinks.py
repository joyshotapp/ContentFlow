"""DataForSEO 反向連結 API 整合工具

使用 DataForSEO Backlinks Summary Live API（v3）取得網站的反向連結摘要數據。
API 文件：https://docs.dataforseo.com/v3/backlinks/summary/live/

憑證從 settings.dataforseo_login / settings.dataforseo_password 讀取。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import httpx
from loguru import logger

from ..config import settings

_BACKLINKS_SUMMARY_URL = "https://api.dataforseo.com/v3/backlinks/summary/live"


@dataclass
class BacklinkSummary:
    """DataForSEO 反向連結摘要結果"""
    target_url: str
    total_backlinks: int = 0
    referring_domains: int = 0
    new_backlinks: int = 0           # 最近 1 個月新增
    lost_backlinks: int = 0          # 最近 1 個月失去
    domain_rank: Optional[float] = None   # DataForSEO Domain Rank（0-100）
    broken_backlinks: int = 0        # 指向 4xx/5xx 的反向連結
    nofollow_backlinks: int = 0
    dofollow_backlinks: int = 0
    top_anchors: list[dict] = field(default_factory=list)          # [{anchor, count}] 前 10 名
    top_referring_domains: list[dict] = field(default_factory=list) # [{domain, rank, backlinks}] 前 10 名
    tracked_date: Optional[date] = None
    error: Optional[str] = None

    @property
    def has_error(self) -> bool:
        return self.error is not None


class DataForSEOBacklinksClient:
    """
    呼叫 DataForSEO Backlinks Summary Live API。
    
    使用 HTTP Basic Auth（login:password Base64）。
    """

    def __init__(self) -> None:
        login = settings.dataforseo_login
        password = settings.dataforseo_password
        raw = f"{login}:{password}".encode()
        self._auth_header = f"Basic {base64.b64encode(raw).decode()}"

    async def get_backlink_summary(
        self,
        target: str,
        include_subdomains: bool = True,
        backlinks_status_type: str = "live",
        timeout: int = 30,
    ) -> BacklinkSummary:
        """
        取得目標網域的反向連結摘要。

        Args:
            target: 目標域名，例：example.com（不含 https://）
            include_subdomains: 是否包含子域名的反向連結
            backlinks_status_type: "live"（現有）/ "lost"（已失去）/ "all"
            timeout: HTTP 逾時（秒）

        Returns:
            BacklinkSummary 物件
        """
        # 清理 target：移除 scheme、trailing slash
        target = (
            target.replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )

        payload = [
            {
                "target": target,
                "include_subdomains": include_subdomains,
                "backlinks_status_type": backlinks_status_type,
                "include_indirect_links": True,
            }
        ]

        headers = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    _BACKLINKS_SUMMARY_URL,
                    headers=headers,
                    content=json.dumps(payload),
                )
                resp.raise_for_status()
                data = resp.json()

            return self._parse_response(target, data)

        except httpx.HTTPStatusError as e:
            logger.error(f"[Backlinks] DataForSEO API 錯誤 {e.response.status_code}: {e}")
            return BacklinkSummary(target_url=target, error=f"http_{e.response.status_code}")
        except Exception as e:
            logger.error(f"[Backlinks] 反向連結查詢失敗 target={target}: {e}")
            return BacklinkSummary(target_url=target, error=str(e))

    def _parse_response(self, target: str, data: dict) -> BacklinkSummary:
        """解析 DataForSEO API 回應"""
        today = date.today()

        try:
            tasks = data.get("tasks") or []
            if not tasks:
                return BacklinkSummary(target_url=target, error="empty_response", tracked_date=today)

            task = tasks[0]
            status_code = task.get("status_code", 0)
            if status_code != 20000:
                msg = task.get("status_message", "unknown_error")
                logger.warning(f"[Backlinks] DataForSEO task 失敗 target={target}: {msg}")
                return BacklinkSummary(target_url=target, error=msg, tracked_date=today)

            result_list = task.get("result") or []
            if not result_list:
                return BacklinkSummary(target_url=target, error="empty_result", tracked_date=today)

            r = result_list[0]

            def _normalize_top_items(raw: object, key_name: str) -> list[dict]:
                """將 DataForSEO 的 list / dict 聚合欄位轉成前 10 名清單。"""
                if isinstance(raw, list):
                    items = []
                    for item in raw[:10]:
                        if isinstance(item, dict):
                            items.append(item)
                    return items
                if isinstance(raw, dict):
                    ordered = sorted(raw.items(), key=lambda item: item[1], reverse=True)
                    return [{key_name: name, "count": count} for name, count in ordered[:10]]
                return []

            # Summary API 可能回傳聚合 object，而不是明細 list；避免把整數欄位當陣列切片。
            anchors_raw = r.get("anchors") or r.get("referring_links_types") or {}
            top_anchors = _normalize_top_items(anchors_raw, "anchor")

            top_domains = []
            referring_countries = r.get("referring_links_countries") or {}
            for item in _normalize_top_items(referring_countries, "domain"):
                top_domains.append(
                    {
                        "domain": item.get("domain", ""),
                        "rank": 0,
                        "backlinks": item.get("count", 0),
                    }
                )

            return BacklinkSummary(
                target_url=target,
                total_backlinks=r.get("backlinks", 0) or 0,
                referring_domains=r.get("referring_domains", 0) or 0,
                new_backlinks=r.get("new_backlinks", 0) or 0,
                lost_backlinks=r.get("lost_backlinks", 0) or 0,
                domain_rank=r.get("rank"),
                broken_backlinks=r.get("broken_backlinks", 0) or 0,
                nofollow_backlinks=r.get("nofollow", 0) or 0,
                dofollow_backlinks=r.get("dofollow", 0) or 0,
                top_anchors=top_anchors,
                top_referring_domains=top_domains,
                tracked_date=today,
            )

        except Exception as e:
            logger.error(f"[Backlinks] 解析回應失敗 target={target}: {e}")
            return BacklinkSummary(target_url=target, error=f"parse_error: {e}", tracked_date=today)

    def format_summary(self, summary: BacklinkSummary) -> str:
        """格式化為可讀報告（用於 KnowledgeEntry 記錄）"""
        if summary.has_error:
            return f"反向連結查詢失敗：{summary.error}"

        lines = [
            f"**反向連結摘要** — {summary.target_url} ({summary.tracked_date})",
            f"",
            f"| 指標 | 數值 |",
            f"|------|------|",
            f"| 總反向連結數 | {summary.total_backlinks:,} |",
            f"| 引薦域名數 | {summary.referring_domains:,} |",
            f"| 本月新增 | +{summary.new_backlinks} |",
            f"| 本月失去 | -{summary.lost_backlinks} |",
            f"| Domain Rank | {summary.domain_rank or 'N/A'} |",
            f"| Dofollow | {summary.dofollow_backlinks:,} |",
            f"| Nofollow | {summary.nofollow_backlinks:,} |",
            f"| 指向 4xx/5xx | {summary.broken_backlinks} |",
        ]

        if summary.top_anchors:
            lines += ["", "**前 5 錨文字：**"]
            for a in summary.top_anchors[:5]:
                lines.append(f"- `{a['anchor']}` × {a['count']}")

        if summary.top_referring_domains:
            lines += ["", "**前 5 引薦域名：**"]
            for d in summary.top_referring_domains[:5]:
                lines.append(f"- {d['domain']} (DR={d['rank']}, {d['backlinks']} links)")

        return "\n".join(lines)
