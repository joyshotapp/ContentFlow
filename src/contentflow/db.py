"""資料庫引擎、Session 管理"""

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from contentflow.config import settings
from contentflow.models.database import Base

# 確保 data/ 目錄存在
_db_url = settings.database_url
if _db_url.startswith("sqlite:///"):
    db_path = Path(_db_url.replace("sqlite:///", ""))
    db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(_db_url, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
_SCHEMA_LOCK_KEY = 2026042201


def _ensure_sqlite_columns(conn) -> None:
    """為既有 SQLite 資料庫補上新欄位，避免舊 schema 直接炸掉。"""
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
    }

    for table_name, columns in tables.items():
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
        if not rows:          # table doesn't exist yet — skip
            continue
        existing_cols = {row[1] for row in rows}
        for column_name, ddl in columns.items():
            if column_name not in existing_cols:
                conn.execute(text(ddl))


def init_db():
    """建立所有資料表（若尚不存在）"""
    if _db_url.startswith("postgresql"):
        # 多 worker 啟動時，用 DB advisory lock 序列化 DDL，避免 create_all 競態。
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _SCHEMA_LOCK_KEY})
            Base.metadata.create_all(bind=conn)
    else:
        Base.metadata.create_all(engine)
    if _db_url.startswith("sqlite:///"):
        with engine.begin() as conn:
            _ensure_sqlite_columns(conn)


def get_session():
    """取得 DB session（搭配 with 使用）"""
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
    """直接取得 session 實例（Streamlit 用）"""
    return SessionLocal()
