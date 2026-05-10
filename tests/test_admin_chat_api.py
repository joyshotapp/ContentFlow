from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from contentflow.admin.app import admin_app


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