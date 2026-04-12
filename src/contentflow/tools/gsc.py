"""Google Search Console Data API 串接（CF-02-02, CF-02-03）

認證方式：Service Account（與 Google Sheets 共用同一組 credentials）。
使用前需確認 Service Account 已取得該 GSC property 的 Read 權限。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from loguru import logger


@dataclass
class PagePerformance:
    query: str                  # 搜尋關鍵字
    page: str                   # 頁面 URL
    clicks: int
    impressions: int
    ctr: float                  # 點擊率（0.0 ~ 1.0）
    position: float             # 平均排名（越小越好）


@dataclass
class KeywordRanking:
    keyword: str
    position: float
    clicks: int
    impressions: int
    ctr: float
    page: str = ""


class GSCClient:
    """Google Search Console Data API（Search Analytics）串接。

    使用 Google Service Account 認證，讀取指定 site_url 的搜尋數據。
    """

    def __init__(self, credentials_file: str | None = None) -> None:
        from contentflow.config import settings as _s
        self._creds_file = credentials_file or _s.google_service_account_file
        self._service = None

    def _get_service(self):
        """懶加載 GSC API service。"""
        if self._service is not None:
            return self._service
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            scopes = ["https://www.googleapis.com/auth/webmasters.readonly"]
            creds = service_account.Credentials.from_service_account_file(
                self._creds_file, scopes=scopes
            )
            self._service = build("searchconsole", "v1", credentials=creds)
            return self._service
        except Exception as exc:
            raise RuntimeError(f"GSC Service Account 初始化失敗：{exc}") from exc

    async def get_page_performance(
        self,
        site_url: str,
        start_date: str | None = None,
        end_date: str | None = None,
        row_limit: int = 500,
    ) -> list[PagePerformance]:
        """取得頁面 × 關鍵字的搜尋表現（clicks / impressions / ctr / position）。

        Args:
            site_url:   GSC property URL，如 "https://example.com/"
            start_date: ISO 8601，預設 28 天前
            end_date:   ISO 8601，預設昨天
            row_limit:  最多回傳筆數

        Returns:
            PagePerformance 列表
        """
        import asyncio

        today = date.today()
        start = start_date or (today - timedelta(days=28)).isoformat()
        end = end_date or (today - timedelta(days=1)).isoformat()

        def _fetch() -> list[PagePerformance]:
            service = self._get_service()
            request = {
                "startDate": start,
                "endDate": end,
                "dimensions": ["query", "page"],
                "rowLimit": row_limit,
            }
            resp = (
                service.searchanalytics()
                .query(siteUrl=site_url, body=request)
                .execute()
            )
            rows = resp.get("rows", [])
            return [
                PagePerformance(
                    query=r["keys"][0],
                    page=r["keys"][1],
                    clicks=int(r.get("clicks", 0)),
                    impressions=int(r.get("impressions", 0)),
                    ctr=float(r.get("ctr", 0.0)),
                    position=float(r.get("position", 0.0)),
                )
                for r in rows
            ]

        return await asyncio.get_event_loop().run_in_executor(None, _fetch)

    async def get_keyword_rankings(
        self,
        site_url: str,
        keywords: list[str],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[KeywordRanking]:
        """取得指定關鍵字的排名清單。"""
        all_rows = await self.get_page_performance(
            site_url, start_date, end_date, row_limit=1000
        )
        keyword_set = {k.lower() for k in keywords}
        return [
            KeywordRanking(
                keyword=row.query,
                position=row.position,
                clicks=row.clicks,
                impressions=row.impressions,
                ctr=row.ctr,
                page=row.page,
            )
            for row in all_rows
            if row.query.lower() in keyword_set
        ]

    async def sync_to_db(
        self,
        project_id: int,
        site_url: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """將 GSC 數據同步到 SEORanking 表，回傳寫入筆數（CF-02-03）。"""
        from contentflow.db import SessionLocal
        from contentflow.models.database import SEORanking
        from datetime import date as _date

        rows = await self.get_page_performance(site_url, start_date, end_date)
        today = _date.today()

        written = 0
        with SessionLocal() as session:
            for row in rows:
                ranking = SEORanking(
                    project_id=project_id,
                    keyword=row.query,
                    position=row.position,
                    landing_page=row.page,
                    tracked_date=today,
                    impressions=row.impressions,
                    clicks=row.clicks,
                    ctr=row.ctr,
                )
                session.add(ranking)
                written += 1
            session.commit()

        logger.info(f"[GSCSync] project_id={project_id} 寫入 {written} 筆排名數據")
        return written
