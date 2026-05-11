from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from contentflow.config import settings
from contentflow.db import SessionLocal
from contentflow.models.database import Project, ProjectIntegration
from contentflow.utils.secret_crypto import decrypt_secret_value


WORDPRESS = "wordpress"
FORGEBASE = "forgebase"


@dataclass(frozen=True)
class SiteProfile:
    project_id: int | None
    project_slug: str
    site_url: str
    site_name: str
    site_description: str
    site_contact_email: str
    blog_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_slug": self.project_slug,
            "site_url": self.site_url,
            "site_name": self.site_name,
            "site_description": self.site_description,
            "site_contact_email": self.site_contact_email,
            "blog_path": self.blog_path,
        }


@dataclass(frozen=True)
class IntegrationSettings:
    integration_type: str
    base_url: str
    username: str = ""
    secret_value: str = ""
    seo_plugin: str = "yoast"
    publish_mode: str = "publish"
    is_enabled: bool = False
    source: str = "settings"

    @property
    def configured(self) -> bool:
        if self.integration_type == WORDPRESS:
            return bool(self.base_url and self.username and self.secret_value)
        if self.integration_type == FORGEBASE:
            return bool(self.base_url and self.secret_value)
        return False


@dataclass(frozen=True)
class IntegrationDiagnostic:
    integration_type: str
    status: str
    checked_url: str
    message: str
    source: str
    configured: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "integration_type": self.integration_type,
            "status": self.status,
            "checked_url": self.checked_url,
            "message": self.message,
            "source": self.source,
            "configured": self.configured,
        }


def _normalize_blog_path(raw_value: str | None) -> str:
    value = (raw_value or "").strip()
    if not value:
        value = settings.site_blog_path
    if value in {"/", ""}:
        return ""
    return "/" + value.strip("/")


def _open_session_if_needed(db: Session | None) -> tuple[Session, bool]:
    if db is not None:
        return db, False
    return SessionLocal(), True


def resolve_project(db: Session, project_id: int | None = None, project_slug: str | None = None) -> Project | None:
    if project_id:
        return db.query(Project).filter(Project.id == project_id).first()

    slug = (project_slug or settings.site_project_slug or "").strip()
    if slug:
        return db.query(Project).filter(Project.slug == slug).first()
    return None


def resolve_site_profile(
    db: Session | None = None,
    project_id: int | None = None,
    project_slug: str | None = None,
) -> SiteProfile:
    session, should_close = _open_session_if_needed(db)
    try:
        project = resolve_project(session, project_id=project_id, project_slug=project_slug)
        site_url = (project.brand_url if project and project.brand_url else settings.site_url).rstrip("/")
        site_name = (
            project.brand_name
            if project and project.brand_name
            else project.name
            if project and project.name
            else settings.site_name
        )
        site_description = (
            project.brand_description
            if project and project.brand_description
            else settings.site_description
        )
        site_contact_email = (
            project.site_contact_email
            if project and project.site_contact_email
            else settings.site_contact_email
        )
        blog_path = _normalize_blog_path(project.site_blog_path if project else settings.site_blog_path)
        return SiteProfile(
            project_id=project.id if project else None,
            project_slug=project.slug if project else "",
            site_url=site_url,
            site_name=site_name,
            site_description=site_description,
            site_contact_email=site_contact_email,
            blog_path=blog_path,
        )
    finally:
        if should_close:
            session.close()


def build_site_url(path: str = "", site_profile: SiteProfile | None = None) -> str:
    profile = site_profile or resolve_site_profile()
    base = profile.site_url.rstrip("/")
    return f"{base}{path}" if path else base


def build_native_publish_url(
    slug: str,
    db: Session | None = None,
    project_id: int | None = None,
    project_slug: str | None = None,
) -> str:
    profile = resolve_site_profile(db=db, project_id=project_id, project_slug=project_slug)
    if profile.blog_path:
        return f"{profile.site_url.rstrip('/')}{profile.blog_path}/{slug}"
    return f"{profile.site_url.rstrip('/')}/{slug}"


def get_project_integrations(db: Session, project_id: int | None) -> dict[str, ProjectIntegration]:
    if not project_id:
        return {}
    rows = (
        db.query(ProjectIntegration)
        .filter(ProjectIntegration.project_id == project_id)
        .order_by(ProjectIntegration.integration_type)
        .all()
    )
    return {row.integration_type: row for row in rows}


def resolve_wordpress_settings(
    db: Session | None = None,
    project_id: int | None = None,
) -> IntegrationSettings:
    session, should_close = _open_session_if_needed(db)
    try:
        row = get_project_integrations(session, project_id).get(WORDPRESS)
        if row is not None:
            secret_value = decrypt_secret_value(row.secret_value)
            return IntegrationSettings(
                integration_type=WORDPRESS,
                base_url=(row.base_url or "").rstrip("/"),
                username=row.username or "",
                secret_value=secret_value,
                seo_plugin=row.seo_plugin if row.seo_plugin else "yoast",
                publish_mode=row.publish_mode if row.publish_mode else "publish",
                is_enabled=bool(row.is_enabled),
                source="project",
            )
        return IntegrationSettings(
            integration_type=WORDPRESS,
            base_url=settings.wordpress_site_url.rstrip("/"),
            username=settings.wordpress_username,
            secret_value=settings.wordpress_app_password,
            seo_plugin="yoast",
            publish_mode="publish",
            is_enabled=bool(settings.wordpress_site_url),
            source="settings",
        )
    finally:
        if should_close:
            session.close()


def resolve_forgebase_settings(
    db: Session | None = None,
    project_id: int | None = None,
) -> IntegrationSettings:
    session, should_close = _open_session_if_needed(db)
    try:
        row = get_project_integrations(session, project_id).get(FORGEBASE)
        if row is not None:
            secret_value = decrypt_secret_value(row.secret_value)
            return IntegrationSettings(
                integration_type=FORGEBASE,
                base_url=(row.base_url or "").rstrip("/"),
                secret_value=secret_value,
                publish_mode=row.publish_mode if row.publish_mode else "publish",
                is_enabled=bool(row.is_enabled),
                source="project",
            )
        return IntegrationSettings(
            integration_type=FORGEBASE,
            base_url=settings.forgebase_api_base_url.rstrip("/"),
            secret_value=settings.forgebase_api_token,
            publish_mode="publish",
            is_enabled=bool(settings.forgebase_api_base_url),
            source="settings",
        )
    finally:
        if should_close:
            session.close()


def resolve_publish_platform(
    db: Session | None = None,
    project_id: int | None = None,
) -> str:
    wp = resolve_wordpress_settings(db=db, project_id=project_id)
    if wp.is_enabled and wp.configured:
        return WORDPRESS

    fb = resolve_forgebase_settings(db=db, project_id=project_id)
    if fb.is_enabled and fb.configured:
        return FORGEBASE

    return "native"


def build_wordpress_publisher(db: Session | None = None, project_id: int | None = None):
    from contentflow.publishers.wordpress import WordPressPublisher

    cfg = resolve_wordpress_settings(db=db, project_id=project_id)
    return WordPressPublisher(
        site_url=cfg.base_url,
        username=cfg.username,
        app_password=cfg.secret_value,
        seo_plugin=cfg.seo_plugin,
    )


def build_forgebase_publisher(db: Session | None = None, project_id: int | None = None):
    from contentflow.publishers.forgebase import ForgeBasePublisher

    cfg = resolve_forgebase_settings(db=db, project_id=project_id)
    return ForgeBasePublisher(
        api_base_url=cfg.base_url,
        api_token=cfg.secret_value,
    )


async def run_integration_diagnostic(
    integration_type: str,
    db: Session | None = None,
    project_id: int | None = None,
) -> IntegrationDiagnostic:
    normalized_type = (integration_type or "").strip().lower()
    if normalized_type == WORDPRESS:
        cfg = resolve_wordpress_settings(db=db, project_id=project_id)
        if not cfg.is_enabled:
            return IntegrationDiagnostic(WORDPRESS, "disabled", "", "Connector 未啟用", cfg.source, cfg.configured)
        if not cfg.configured:
            return IntegrationDiagnostic(WORDPRESS, "misconfigured", cfg.base_url, "缺少 WordPress 站點、帳號或密碼", cfg.source, cfg.configured)

        endpoint = f"{cfg.base_url.rstrip('/')}/wp-json/wp/v2/posts?per_page=1&_fields=id"
        token = base64.b64encode(f"{cfg.username}:{cfg.secret_value}".encode()).decode()
        headers = {"Authorization": f"Basic {token}"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            return IntegrationDiagnostic(WORDPRESS, "healthy", endpoint, "WordPress API 連線成功", cfg.source, cfg.configured)
        except Exception as exc:
            return IntegrationDiagnostic(WORDPRESS, "error", endpoint, f"WordPress API 測試失敗：{exc}", cfg.source, cfg.configured)

    if normalized_type == FORGEBASE:
        cfg = resolve_forgebase_settings(db=db, project_id=project_id)
        if not cfg.is_enabled:
            return IntegrationDiagnostic(FORGEBASE, "disabled", "", "Connector 未啟用", cfg.source, cfg.configured)
        if not cfg.configured:
            return IntegrationDiagnostic(FORGEBASE, "misconfigured", cfg.base_url, "缺少 ForgeBase Base URL 或 API Token", cfg.source, cfg.configured)

        endpoint = f"{cfg.base_url.rstrip('/')}/api/v1/content/pages?limit=1"
        headers = {"X-API-Key": cfg.secret_value}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            return IntegrationDiagnostic(FORGEBASE, "healthy", endpoint, "ForgeBase API 連線成功", cfg.source, cfg.configured)
        except Exception as exc:
            return IntegrationDiagnostic(FORGEBASE, "error", endpoint, f"ForgeBase API 測試失敗：{exc}", cfg.source, cfg.configured)

    return IntegrationDiagnostic(normalized_type or "unknown", "unsupported", "", "不支援的 integration 類型", "settings", False)