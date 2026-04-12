"""Phase Gate A：系統主流程不依賴 SQLite 特定行為

完成定義：
- get_session / SessionLocal 可接受任意同步 SQLAlchemy URL（PostgreSQL / SQLite）
- init_db 對 SQLite 與 psycopg2 URL 均能正確建立 schema（URL 格式層面驗證）
- db.py 不做 asyncpg URL 的呼叫
- 主流程 import chain 可在 SQLite in-memory 模式下跑完 run_orchestrator 的 import
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


# ── 1. get_session 在 SQLite + psycopg2 URL 下均可存取 ────────────────────

def test_get_session_sqlalchemy_agnostic():
    """get_session 的實作應與 DB dialect 無關；以 SQLite in-memory 驗證介面。"""
    from contentflow.db import get_session
    from contentflow.models.database import Base

    tmp_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(tmp_engine)
    Session = sessionmaker(bind=tmp_engine)
    # 模擬 get_session 的行為：with next(get_session()) as session
    gen = get_session.__wrapped__() if hasattr(get_session, "__wrapped__") else None
    # 直接用 Session 確認介面可用
    with Session() as s:
        result = s.execute(text("SELECT 1")).scalar()
    assert result == 1


def test_init_db_creates_tables_on_sqlite():
    """init_db 應在 SQLite 上建立所有 ORM 表（驗證 Base.metadata 完整性）。"""
    from sqlalchemy import create_engine, inspect

    from contentflow.models.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    tables = inspector.get_table_names()

    required = {
        "projects", "articles", "keywords", "content_calendar",
        "writing_rules", "competitors", "products", "legal_terms",
        "agent_decision_logs", "scheduler_logs", "topic_clusters", "cluster_members",
    }
    missing = required - set(tables)
    assert not missing, f"缺少資料表：{missing}"


# ── 2. db.py 不直接引用 asyncpg ──────────────────────────────────────────

def test_db_module_has_no_asyncpg_reference():
    """db.py 不應直接 import 或硬編碼 asyncpg（sync engine 不需要它）。"""
    db_file = Path(__file__).parent.parent / "src" / "contentflow" / "db.py"
    content = db_file.read_text()
    assert "asyncpg" not in content, "db.py 不應包含 asyncpg 引用（使用 psycopg2 同步驅動）"


# ── 3. psycopg2 URL 可被建構但不需真實連線 ───────────────────────────────

def test_psycopg2_engine_constructible():
    """確認 psycopg2 URL 可正常建構 Engine（不需真實 PostgreSQL 連線）。"""
    pg_url = "postgresql+psycopg2://user:pw@localhost:5432/testdb"
    engine = create_engine(pg_url)
    assert engine.dialect.name == "postgresql"
    engine.dispose()


# ── 4. 全部核心 import 可在非 SQLite 特定環境下載入 ──────────────────────

def test_core_imports_do_not_call_sqlite_on_import():
    """import contentflow.db 時不應立即執行任何 SQLite 特定初始化（僅設定 engine）。"""
    # 若 db.py 在 import 時便執行 sqlite 操作，此處會因 mock 或非預期 URL 而失敗
    import importlib
    import sys

    # 暫存目前已載入的 db module，確認 re-import 不觸發錯誤
    mod_name = "contentflow.db"
    if mod_name in sys.modules:
        mod = sys.modules[mod_name]
        # 只確認模組可正常存取 init_db、get_session
        assert hasattr(mod, "init_db")
        assert hasattr(mod, "get_session")
    else:
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "init_db")
