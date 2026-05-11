"""Database engine and session management."""

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from contentflow.config import settings
from contentflow.models.database import Base

# Ensure the data directory exists for SQLite files.
_db_url = settings.database_url
if _db_url.startswith("sqlite:///"):
    db_path = Path(_db_url.replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(_db_url, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _ensure_sqlite_columns(conn) -> None:
    """Patch legacy SQLite databases with required columns."""
    tables = {
        "articles": {
            "article_type": 'ALTER TABLE articles ADD COLUMN article_type VARCHAR DEFAULT ""',
            "slug": 'ALTER TABLE articles ADD COLUMN slug VARCHAR DEFAULT ""',
            "meta_title": 'ALTER TABLE articles ADD COLUMN meta_title VARCHAR DEFAULT ""',
            "meta_description": 'ALTER TABLE articles ADD COLUMN meta_description TEXT DEFAULT ""',
            "faq_schema_json": 'ALTER TABLE articles ADD COLUMN faq_schema_json TEXT DEFAULT ""',
            "article_schema_json": 'ALTER TABLE articles ADD COLUMN article_schema_json TEXT DEFAULT ""',
            "seo_score": 'ALTER TABLE articles ADD COLUMN seo_score INTEGER',
            "old_slugs": 'ALTER TABLE articles ADD COLUMN old_slugs TEXT DEFAULT "[]"',
            "content_format_override": 'ALTER TABLE articles ADD COLUMN content_format_override VARCHAR DEFAULT ""',
            "reviewer_required_override": 'ALTER TABLE articles ADD COLUMN reviewer_required_override BOOLEAN',
            "custom_disclaimer": 'ALTER TABLE articles ADD COLUMN custom_disclaimer TEXT DEFAULT ""',
            "extra_schema_types_override_json": 'ALTER TABLE articles ADD COLUMN extra_schema_types_override_json TEXT DEFAULT "[]"',
        },
        "seo_rankings": {
            "keyword": 'ALTER TABLE seo_rankings ADD COLUMN keyword VARCHAR DEFAULT ""',
            "position": 'ALTER TABLE seo_rankings ADD COLUMN position FLOAT',
            "landing_page": 'ALTER TABLE seo_rankings ADD COLUMN landing_page VARCHAR DEFAULT ""',
            "search_engine": 'ALTER TABLE seo_rankings ADD COLUMN search_engine VARCHAR DEFAULT "Google"',
            "tracked_date": 'ALTER TABLE seo_rankings ADD COLUMN tracked_date DATE',
            "impressions": 'ALTER TABLE seo_rankings ADD COLUMN impressions INTEGER',
            "clicks": 'ALTER TABLE seo_rankings ADD COLUMN clicks INTEGER',
            "ctr": 'ALTER TABLE seo_rankings ADD COLUMN ctr FLOAT',
        },
        "projects": {
            "site_contact_email": 'ALTER TABLE projects ADD COLUMN site_contact_email VARCHAR DEFAULT ""',
            "site_blog_path": 'ALTER TABLE projects ADD COLUMN site_blog_path VARCHAR DEFAULT "/blog"',
            "domain_profile": 'ALTER TABLE projects ADD COLUMN domain_profile VARCHAR DEFAULT "general"',
            "compliance_profile": 'ALTER TABLE projects ADD COLUMN compliance_profile VARCHAR DEFAULT "general"',
            "default_content_format": 'ALTER TABLE projects ADD COLUMN default_content_format VARCHAR DEFAULT "knowledge"',
            "reviewer_role_label": 'ALTER TABLE projects ADD COLUMN reviewer_role_label VARCHAR DEFAULT ""',
            "disclaimer_template": 'ALTER TABLE projects ADD COLUMN disclaimer_template TEXT DEFAULT ""',
            "evidence_policy": 'ALTER TABLE projects ADD COLUMN evidence_policy VARCHAR DEFAULT "default"',
            "image_style_override": 'ALTER TABLE projects ADD COLUMN image_style_override TEXT DEFAULT ""',
            "extra_schema_types_json": 'ALTER TABLE projects ADD COLUMN extra_schema_types_json TEXT DEFAULT "[]"',
            "factcheck_mode_override": 'ALTER TABLE projects ADD COLUMN factcheck_mode_override VARCHAR DEFAULT ""',
        },
        "authors": {
            "reviewer_role": 'ALTER TABLE authors ADD COLUMN reviewer_role VARCHAR DEFAULT ""',
        },
    }

    for table_name, columns in tables.items():
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        if not rows:          # table does not exist yet
            continue
        existing_cols = {row[1] for row in rows}
        for column_name, ddl in columns.items():
            if column_name not in existing_cols:
                conn.execute(text(ddl))


def init_db():
    """Initialize database access.

    SQLite keeps the legacy create_all bootstrap for local/test workflows.
    PostgreSQL schema is owned by Alembic migrations and must not be created
    implicitly at app startup.
    """
    if _db_url.startswith("postgresql"):
        with engine.begin() as conn:
            conn.execute(text("SELECT 1"))
        return

    Base.metadata.create_all(engine)
    if _db_url.startswith("sqlite:///"):
        with engine.begin() as conn:
            _ensure_sqlite_columns(conn)


def get_session():
    """Yield a database session for request-scoped use."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """Return a database session instance for direct callers."""
    return SessionLocal()
