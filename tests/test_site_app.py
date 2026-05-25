from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from contentflow.site.app import _get_db, site_app
from contentflow.models.database import Base, Project


client = TestClient(site_app)


def test_head_requests_return_200_not_405():
    """P1：HEAD 應與 GET 同路由，不應回 405。"""
    for path in ("/health", "/robots.txt"):
        response = client.head(path)
        assert response.status_code != 405, path


def _make_threadsafe_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_about_page_uses_configured_contact_email():
    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def count(self):
            return 0

    class _FakeDB:
        def query(self, *args, **kwargs):
            return _FakeQuery()

        def close(self):
            return None

    def _override_session():
        yield _FakeDB()

    site_app.dependency_overrides[_get_db] = _override_session
    try:
        with patch("contentflow.site.app.settings.site_contact_email", "team@client-site.test"), \
             patch("contentflow.site.app.settings.site_name", "Client Knowledge Hub"):
            response = client.get("/about")
    finally:
        site_app.dependency_overrides.pop(_get_db, None)

    assert response.status_code == 200
    assert "team@client-site.test" in response.text
    assert "關於 Client Knowledge Hub" in response.text


def test_about_page_uses_project_site_profile_when_site_project_slug_is_set():
    session, engine = _make_threadsafe_session()
    try:
        project = Project(
            slug="client-hub",
            name="客戶站點",
            brand_name="Client Knowledge Hub",
            brand_url="https://client.example",
            brand_description="客戶站點的品牌描述",
        )
        session.add(project)
        session.commit()

        def _override_session():
            yield session

        site_app.dependency_overrides[_get_db] = _override_session
        with patch("contentflow.site.app.settings.site_project_slug", "client-hub"), \
             patch("contentflow.site.app.settings.site_name", "Fallback Site"), \
             patch("contentflow.site.app.settings.site_url", "https://fallback.example"), \
             patch("contentflow.site.app.settings.site_description", "Fallback Description"):
            response = client.get("/about")
    finally:
        site_app.dependency_overrides.pop(_get_db, None)
        session.close()
        engine.dispose()

    assert response.status_code == 200
    assert "關於 Client Knowledge Hub" in response.text
    assert "https://client.example/about" in response.text
    assert "客戶站點的品牌描述" in response.text


def test_public_route_returns_404_when_managed_site_disabled():
    with patch("contentflow.site.app.settings.managed_site_enabled", False):
        response = client.get("/about")

    assert response.status_code == 404
    assert response.text == "Not Found"


def test_health_exposes_platform_mode_flags():
    with patch("contentflow.site.app.settings.platform_mode", "control-plane"), \
         patch("contentflow.site.app.settings.managed_site_enabled", False):
        response = client.get("/health")

    assert response.status_code in {200, 503}
    payload = response.json()
    assert payload["platform_mode"] == "control-plane"
    assert payload["managed_site_enabled"] is False