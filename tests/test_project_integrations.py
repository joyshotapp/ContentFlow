import asyncio
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, patch

from contentflow.models.database import Base, Project, ProjectIntegration
from contentflow.project_integrations import (
    build_native_publish_url,
    run_integration_diagnostic,
    resolve_publish_platform,
    resolve_site_profile,
    resolve_wordpress_settings,
)
from contentflow.utils.secret_crypto import (
    backfill_plaintext_project_integration_secrets,
    encrypt_secret_value,
)


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def test_site_profile_uses_project_specific_contact_and_blog_path():
    session, engine = _make_session()
    try:
        project = Project(
            slug="client-hub",
            name="Client Hub",
            brand_name="Client Knowledge Hub",
            brand_url="https://client.example",
            brand_description="Client site description",
            site_contact_email="team@client.example",
            site_blog_path="/insights",
        )
        session.add(project)
        session.commit()

        profile = resolve_site_profile(db=session, project_id=project.id)
        publish_url = build_native_publish_url("seo-strategy", db=session, project_id=project.id)

        assert profile.site_contact_email == "team@client.example"
        assert profile.blog_path == "/insights"
        assert publish_url == "https://client.example/insights/seo-strategy"
    finally:
        session.close()
        engine.dispose()


def test_publish_platform_prefers_project_wordpress_connector():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            seo_plugin="rankmath",
            is_enabled=True,
        ))
        session.commit()

        cfg = resolve_wordpress_settings(db=session, project_id=project.id)
        platform = resolve_publish_platform(db=session, project_id=project.id)

        assert cfg.base_url == "https://wp.client.example"
        assert cfg.username == "editor"
        assert cfg.seo_plugin == "rankmath"
        assert platform == "wordpress"
    finally:
        session.close()
        engine.dispose()


def test_run_integration_diagnostic_reports_misconfigured_wordpress_connector():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="",
            secret_value="",
            is_enabled=True,
        ))
        session.commit()

        diagnostic = asyncio.get_event_loop().run_until_complete(
            run_integration_diagnostic("wordpress", db=session, project_id=project.id)
        )

        assert diagnostic.status == "misconfigured"
        assert "缺少 WordPress" in diagnostic.message
    finally:
        session.close()
        engine.dispose()


def test_project_wordpress_connector_does_not_fallback_to_global_settings():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="",
            secret_value="",
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.project_integrations.settings.wordpress_site_url", "https://global.example"), \
             patch("contentflow.project_integrations.settings.wordpress_username", "global-user"), \
             patch("contentflow.project_integrations.settings.wordpress_app_password", "global-pass"):
            cfg = resolve_wordpress_settings(db=session, project_id=project.id)
            platform = resolve_publish_platform(db=session, project_id=project.id)

        assert cfg.source == "project"
        assert cfg.base_url == "https://wp.client.example"
        assert cfg.username == ""
        assert cfg.secret_value == ""
        assert cfg.configured is False
        assert platform == "native"
    finally:
        session.close()
        engine.dispose()


def test_project_integration_schema_enforces_one_row_per_type():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            is_enabled=True,
        ))
        session.commit()

        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.second.example",
            username="editor-2",
            secret_value="app-pass-2",
            is_enabled=True,
        ))

        try:
            session.commit()
            raise AssertionError("expected duplicate connector insert to fail")
        except IntegrityError:
            session.rollback()
    finally:
        session.close()
        engine.dispose()


def test_run_integration_diagnostic_reports_healthy_wordpress_connector():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            is_enabled=True,
        ))
        session.commit()

        class _Response:
            def raise_for_status(self):
                return None

        with patch("contentflow.project_integrations.httpx.AsyncClient.get", new=AsyncMock(return_value=_Response())):
            diagnostic = asyncio.get_event_loop().run_until_complete(
                run_integration_diagnostic("wordpress", db=session, project_id=project.id)
            )

        assert diagnostic.status == "healthy"
        assert diagnostic.checked_url.endswith("/wp-json/wp/v2/posts?per_page=1&_fields=id")
    finally:
        session.close()
        engine.dispose()


def test_encrypted_connector_secret_is_decrypted_by_resolver():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", "connector-test-key"):
            encrypted_secret = encrypt_secret_value("app-pass")

        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value=encrypted_secret,
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", "connector-test-key"), \
             patch("contentflow.project_integrations.settings.connector_secret_key", "connector-test-key"):
            cfg = resolve_wordpress_settings(db=session, project_id=project.id)

        assert cfg.secret_value == "app-pass"
        assert cfg.configured is True
    finally:
        session.close()
        engine.dispose()


def test_encrypted_connector_secret_fails_closed_without_key():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", "connector-test-key"):
            encrypted_secret = encrypt_secret_value("app-pass")

        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value=encrypted_secret,
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", ""), \
             patch("contentflow.project_integrations.settings.connector_secret_key", ""):
            cfg = resolve_wordpress_settings(db=session, project_id=project.id)

        assert cfg.secret_value == ""
        assert cfg.configured is False
    finally:
        session.close()
        engine.dispose()


def test_backfill_plaintext_project_integration_secrets_encrypts_existing_rows():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", "connector-test-key"):
            with engine.begin() as conn:
                updated = backfill_plaintext_project_integration_secrets(conn)

        session.expire_all()
        row = session.query(ProjectIntegration).filter(ProjectIntegration.project_id == project.id).first()
        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", "connector-test-key"), \
             patch("contentflow.project_integrations.settings.connector_secret_key", "connector-test-key"):
            cfg = resolve_wordpress_settings(db=session, project_id=project.id)

        assert updated == 1
        assert row is not None
        assert row.secret_value.startswith("cfsec:v1:")
        assert cfg.secret_value == "app-pass"
    finally:
        session.close()
        engine.dispose()


def test_backfill_plaintext_project_integration_secrets_requires_key():
    session, engine = _make_session()
    try:
        project = Project(slug="client-hub", name="Client Hub")
        session.add(project)
        session.flush()
        session.add(ProjectIntegration(
            project_id=project.id,
            integration_type="wordpress",
            base_url="https://wp.client.example",
            username="editor",
            secret_value="app-pass",
            is_enabled=True,
        ))
        session.commit()

        with patch("contentflow.utils.secret_crypto.settings.connector_secret_key", ""), \
             patch("contentflow.utils.secret_crypto.settings.api_secret_key", ""):
            try:
                with engine.begin() as conn:
                    backfill_plaintext_project_integration_secrets(conn)
                raise AssertionError("expected plaintext secret backfill to require an encryption key")
            except RuntimeError as exc:
                assert "CONNECTOR_SECRET_KEY" in str(exc)
    finally:
        session.close()
        engine.dispose()