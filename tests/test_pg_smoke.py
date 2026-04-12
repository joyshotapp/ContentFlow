"""PostgreSQL 連線模式 smoke test

驗證：
1. psycopg2 URL 可被同步 create_engine 接受（URL 格式解析，無需真實 DB）
2. asyncpg URL 不應被同步 create_engine 使用（診斷用）
3. docker-compose.yml 中不再包含 asyncpg URL
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


# ── URL 格式相容性 ─────────────────────────────────────────────────────────

def test_psycopg2_url_is_sync_compatible():
    """psycopg2 URL 的 drivername 應為 postgresql+psycopg2"""
    url = "postgresql+psycopg2://user:pw@localhost:5432/db"
    parsed = make_url(url)
    assert parsed.drivername == "postgresql+psycopg2"
    # 同步引擎應能接受此 URL（不需真實連線）
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql"
    engine.dispose()


def test_asyncpg_url_has_different_driver():
    """asyncpg URL 的 drivername 包含 asyncpg，與同步 create_engine 不兼容"""
    url = "postgresql+asyncpg://user:pw@localhost:5432/db"
    parsed = make_url(url)
    assert "asyncpg" in parsed.drivername


# ── docker-compose.yml 不再含 asyncpg ─────────────────────────────────────

def test_docker_compose_uses_psycopg2_not_asyncpg():
    """docker-compose.yml 的 DATABASE_URL 應使用 psycopg2（同步引擎），不應再有 asyncpg"""
    compose_file = Path(__file__).parent.parent / "docker-compose.yml"
    if not compose_file.exists():
        pytest.skip("docker-compose.yml 不存在")
    content = compose_file.read_text()
    assert "postgresql+asyncpg://" not in content, (
        "docker-compose.yml 仍含 asyncpg URL，與 db.py 同步引擎不兼容"
    )
    assert "postgresql+psycopg2://" in content, (
        "docker-compose.yml 應使用 postgresql+psycopg2:// URL"
    )


# ── migrate 腳本 TABLE_ORDER FK 順序 ──────────────────────────────────────

def test_migrate_table_order_articles_before_content_calendar():
    """migrate 腳本中 articles 必須在 content_calendar 之前"""
    migrate_file = (
        Path(__file__).parent.parent / "scripts" / "migrate_sqlite_to_pg.py"
    )
    if not migrate_file.exists():
        pytest.skip("migrate_sqlite_to_pg.py 不存在")
    content = migrate_file.read_text()

    # 找出 TABLE_ORDER 字串內容
    match = re.search(r"TABLE_ORDER\s*=\s*\[(.*?)\]", content, re.DOTALL)
    assert match, "找不到 TABLE_ORDER 定義"
    order_block = match.group(1)

    # 收集表格名稱順序（忽略註解行）
    names = re.findall(r'"(\w+)"', order_block)
    assert "articles" in names, "TABLE_ORDER 缺少 articles"
    assert "content_calendar" in names, "TABLE_ORDER 缺少 content_calendar"
    assert names.index("articles") < names.index("content_calendar"), (
        f"articles({names.index('articles')}) 必須在 "
        f"content_calendar({names.index('content_calendar')}) 之前"
    )
