import json
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from contentflow.admin.app import admin_app
from contentflow.models.database import StrategicPlan


client = TestClient(admin_app)


def test_chat_api_requires_login():
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 403


def test_chat_api_returns_chat_agent_response_when_logged_in():
    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.agents.chat_agent.chat", new=AsyncMock(return_value={
             "role": "assistant",
             "content": "ok",
             "tool_calls_count": 0,
         })):
        response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})

    assert response.status_code == 200
    assert response.json()["content"] == "ok"


def test_strategic_plans_page_renders_evidence_card_when_logged_in():
    plan = StrategicPlan(
        project_id=1,
        plan_date=date.today(),
        plan_type="daily",
        actions_json=json.dumps([
            {
                "action": "refresh",
                "keyword": "膝蓋骨刺",
                "priority": 2,
                "reason": "排名下滑",
                "evidence": {
                    "summary": "排名下滑且存在 GSC query gap",
                    "primary_signals": [{"label": "排名變化", "value": "P8 -> P15"}],
                    "thresholds_triggered": ["排名下滑 >= 5 位"],
                    "counter_signals": [],
                    "expected_outcome": "28 天內改善排名或 CTR",
                    "confidence": "high",
                },
            }
        ], ensure_ascii=False),
        context_snapshot=json.dumps({}, ensure_ascii=False),
        total_count=1,
        executed_count=0,
        status="pending",
    )
    plan.id = 1

    class _FakeQuery:
        def __init__(self, rows=None, count_value=0):
            self._rows = rows or []
            self._count_value = count_value

        def order_by(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def count(self):
            return self._count_value

    class _FakeDB:
        def query(self, *entities):
            if len(entities) == 1 and entities[0] is StrategicPlan:
                return _FakeQuery([plan], 1)
            return _FakeQuery([], 0)

        def close(self):
            return None

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()):
        response = client.get("/strategic-plans")

    assert response.status_code == 200
    assert "查看 evidence card" in response.text
    assert "排名下滑且存在 GSC query gap" in response.text


def test_health_page_renders_operations_dashboard_when_logged_in():
    class _FakeQuery:
        def __init__(self, rows=None, count_value=0, scalar_value=0):
            self._rows = rows or []
            self._count_value = count_value
            self._scalar_value = scalar_value

        def order_by(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def group_by(self, *args, **kwargs):
            return self

        def limit(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

        def count(self):
            return self._count_value

        def scalar(self):
            return self._scalar_value

    class _FakeDB:
        def query(self, *entities):
            return _FakeQuery([], 0, 0)

        def close(self):
            return None

    operations_health = {
        "summary_cards": [
            type("Card", (), {"title": "資料新鮮度異常", "value": 2, "tone": "danger"})(),
            type("Card", (), {"title": "Scheduler 7d 成功率", "value": "80%", "tone": "warning"})(),
        ],
        "freshness_items": [
            type("Item", (), {
                "name": "GSC 同步",
                "detail": "2026-05-09",
                "metric": "72h",
                "tone": "danger",
                "label": "異常",
            })(),
        ],
        "execution_items": [
            type("Item", (), {
                "name": "Scheduler 7d 成功率",
                "detail": "成功 8 / 失敗 2",
                "metric": "80%",
                "tone": "warning",
                "label": "注意",
            })(),
        ],
        "outcome_items": [
            type("Item", (), {
                "name": "refresh",
                "detail": "improved 1 / stable 0 / declined 2",
                "metric": "33%",
                "tone": "danger",
                "label": "異常",
            })(),
        ],
        "alerts": [
            type("Alert", (), {"level": "critical", "message": "GSC 同步 超過新鮮度門檻：2026-05-09"})(),
        ],
    }

    with patch("contentflow.admin.app._check_login", return_value=True), \
         patch("contentflow.admin.app._db", return_value=_FakeDB()), \
         patch("contentflow.admin.app._get_agent_cost_metrics", return_value={
             "avg_run_cost": None,
             "monthly_cost": 0,
             "total_cost": 0,
             "run_costs": {},
         }), \
         patch("contentflow.admin.app._build_operations_health", return_value=operations_health), \
         patch("contentflow.admin.app.datetime") as mock_datetime:
        mock_datetime.now.return_value = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
        response = client.get("/health")

    assert response.status_code == 200
    assert "Operations Dashboard" in response.text
    assert "Active Alerts" in response.text
    assert "GSC 同步 超過新鮮度門檻" in response.text
    assert "成效健康" in response.text