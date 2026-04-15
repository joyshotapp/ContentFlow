"""GA4 Data API 串接（CF-02-04）

認證方式：Service Account（與 GSC 共用）。
使用前需在 GA4 Property 中授予 Service Account「Viewer」角色。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from loguru import logger


@dataclass
class PageMetrics:
    page_path: str
    active_users: int
    sessions: int
    avg_engagement_time_sec: float
    bounce_rate: float          # 0.0 ~ 1.0
    conversions: int            # 表單提交 / 轉換事件次數


class GA4Client:
    """Google Analytics 4 Data API 串接。

    使用 google-analytics-data 套件（需安裝 google-analytics-data>=0.18.0）。
    """

    def __init__(
        self,
        property_id: str | None = None,
        credentials_file: str | None = None,
    ) -> None:
        from contentflow.config import settings as _s
        self._property_id = property_id or _s.ga4_property_id or ""
        self._creds_file = credentials_file or _s.google_service_account_file
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            from google.analytics.data_v1beta import BetaAnalyticsDataClient
            from google.oauth2 import service_account

            creds = service_account.Credentials.from_service_account_file(
                self._creds_file,
                scopes=["https://www.googleapis.com/auth/analytics.readonly"],
            )
            self._client = BetaAnalyticsDataClient(credentials=creds)
            return self._client
        except ImportError:
            raise RuntimeError(
                "請安裝 google-analytics-data：pip install google-analytics-data"
            )
        except Exception as exc:
            raise RuntimeError(f"GA4 Client 初始化失敗：{exc}") from exc

    async def get_page_metrics(
        self,
        property_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        row_limit: int = 500,
    ) -> list[PageMetrics]:
        """取得頁面指標（活躍用戶 / 會話 / 參與時間 / 跳出率 / 轉換）。

        Args:
            property_id: "properties/123456789"，空則用初始化時的值
            start_date:  ISO 8601，預設 28 天前
            end_date:    ISO 8601，預設昨天
        """
        import asyncio
        from google.analytics.data_v1beta.types import (
            RunReportRequest, DateRange, Dimension, Metric
        )

        prop_id = property_id or self._property_id
        if not prop_id:
            raise ValueError("GA4 property_id 未設定")

        today = date.today()
        start = start_date or (today - timedelta(days=28)).isoformat()
        end = end_date or (today - timedelta(days=1)).isoformat()

        def _fetch() -> list[PageMetrics]:
            client = self._get_client()
            all_results: list[PageMetrics] = []
            offset = 0
            while True:
                request = RunReportRequest(
                    property=f"properties/{prop_id}" if not prop_id.startswith("properties/") else prop_id,
                    dimensions=[Dimension(name="pagePath")],
                    metrics=[
                        Metric(name="activeUsers"),
                        Metric(name="sessions"),
                        Metric(name="averageSessionDuration"),
                        Metric(name="bounceRate"),
                        Metric(name="conversions"),
                    ],
                    date_ranges=[DateRange(start_date=start, end_date=end)],
                    limit=row_limit,
                    offset=offset,
                )
                response = client.run_report(request)
                batch: list[PageMetrics] = []
                for row in response.rows:
                    dims = [d.value for d in row.dimension_values]
                    vals = [m.value for m in row.metric_values]
                    batch.append(PageMetrics(
                        page_path=dims[0],
                        active_users=int(vals[0] or 0),
                        sessions=int(vals[1] or 0),
                        avg_engagement_time_sec=float(vals[2] or 0.0),
                        bounce_rate=float(vals[3] or 0.0),
                        conversions=int(vals[4] or 0),
                    ))
                all_results.extend(batch)
                if len(batch) < row_limit:
                    break
                offset += row_limit
            return all_results

        return await asyncio.get_running_loop().run_in_executor(None, _fetch)
