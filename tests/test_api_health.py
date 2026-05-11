"""tests/test_api_health.py

測試 GET /health（api.py 根層匿名探針）。

覆蓋重點：
- 不需任何認證即可存取
- 回傳 JSON 含 service / db / scheduler / status / build_commit / platform_mode
- DB 正常時 → 200 ok
- DB 異常時 → 503 degraded
- platform_mode / managed_site_enabled 值正確反映
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# --------------------------------------------------------------------------
# 建立一個輕量級 TestClient，避免拉起完整 lifespan（scheduler、init_db）
# --------------------------------------------------------------------------

def _make_client():
    """建立 api.app 的 TestClient，停用 lifespan 以隔離副作用。"""
    from contentflow.api import app
    return TestClient(app, raise_server_exceptions=True)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture()
def _mock_db_ok():
    """模擬 SessionLocal 可正常執行 func.now()。"""
    mock_session = MagicMock()
    mock_session.execute.return_value = MagicMock()
    with patch("contentflow.api.health_check.__globals__", {}):
        pass  # not needed — use module-level patch below
    with patch("contentflow.db.SessionLocal", return_value=mock_session):
        yield mock_session


@pytest.fixture()
def _mock_scheduler_running():
    """模擬 scheduler.running = True。"""
    mock_scheduler = MagicMock()
    mock_scheduler.running = True
    with patch("contentflow.scheduler.scheduler", mock_scheduler):
        yield mock_scheduler


# --------------------------------------------------------------------------
# 核心測試
# --------------------------------------------------------------------------

def test_health_no_auth_required():
    """GET /health 不需 X-API-Key。"""
    from contentflow.api import app

    mock_session = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("contentflow.db.SessionLocal", return_value=mock_session), \
         patch("contentflow.scheduler.scheduler", mock_scheduler), \
         patch("contentflow.config.settings.scheduler_enabled", True):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    # 不需任何 header
    assert response.status_code in {200, 503}


def test_health_returns_expected_fields():
    """JSON 回應包含所有必要欄位。"""
    from contentflow.api import app

    mock_session = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("contentflow.db.SessionLocal", return_value=mock_session), \
         patch("contentflow.scheduler.scheduler", mock_scheduler), \
         patch("contentflow.config.settings.scheduler_enabled", True):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    payload = response.json()
    for field in ("service", "db", "scheduler", "status", "platform_mode",
                  "managed_site_enabled", "build_commit"):
        assert field in payload, f"缺少欄位: {field}"
    assert payload["service"] == "contentflow"


def test_health_200_when_db_ok():
    """DB 正常時應回傳 HTTP 200，status=ok。"""
    from contentflow.api import app

    mock_session = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("contentflow.db.SessionLocal", return_value=mock_session), \
         patch("contentflow.scheduler.scheduler", mock_scheduler), \
         patch("contentflow.config.settings.scheduler_enabled", True):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db"] == "ok"


def test_health_503_when_db_error():
    """DB 連線失敗時應回傳 HTTP 503，status=degraded。"""
    from contentflow.api import app

    broken_session = MagicMock()
    broken_session.execute.side_effect = Exception("connection refused")
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("contentflow.db.SessionLocal", return_value=broken_session), \
         patch("contentflow.scheduler.scheduler", mock_scheduler), \
         patch("contentflow.config.settings.scheduler_enabled", True):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert "error" in payload["db"]


def test_health_reflects_platform_mode():
    """platform_mode 與 managed_site_enabled 應反映設定值。"""
    from contentflow.api import app

    mock_session = MagicMock()
    mock_scheduler = MagicMock()
    mock_scheduler.running = True

    with patch("contentflow.db.SessionLocal", return_value=mock_session), \
         patch("contentflow.scheduler.scheduler", mock_scheduler), \
         patch("contentflow.config.settings.scheduler_enabled", True), \
         patch("contentflow.config.settings.platform_mode", "control-plane"), \
         patch("contentflow.config.settings.managed_site_enabled", False):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    payload = response.json()
    assert payload["platform_mode"] == "control-plane"
    assert payload["managed_site_enabled"] is False


def test_health_scheduler_disabled_still_ok():
    """scheduler_enabled=False 時，scheduler=disabled 不影響整體 status=ok。"""
    from contentflow.api import app

    mock_session = MagicMock()

    with patch("contentflow.db.SessionLocal", return_value=mock_session), \
         patch("contentflow.config.settings.scheduler_enabled", False):
        client = TestClient(app, raise_server_exceptions=True)
        response = client.get("/health")

    payload = response.json()
    assert payload["scheduler"] == "disabled"
    assert response.status_code == 200
    assert payload["status"] == "ok"
