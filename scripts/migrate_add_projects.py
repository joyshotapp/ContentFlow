"""
Migration: 新增 projects 表並為所有資料表加入 project_id
============================================================
將漢本三代現有資料歸屬到 default project，讓系統成為多專案平台。

Usage:
    python scripts/migrate_add_projects.py
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

DB_PATH = ROOT / "data" / "contentflow.db"

# 需要加 project_id 的資料表（不含 projects 本身）
TABLES_NEED_PROJECT_ID = [
    "keywords",
    "categories",
    "content_calendar",
    "articles",
    "writing_rules",
    "content_strategy",
    "competitors",
    "products",
    "legal_terms",
    "seo_rankings",
    "category_seo",
    "changelog",
]

TABLE_COLUMN_PATCHES = {
    "articles": {
        "article_type": 'ALTER TABLE articles ADD COLUMN article_type TEXT DEFAULT ""',
    },
}

# 預設專案（漢本三代）
DEFAULT_PROJECT = {
    "slug": "hanben",
    "name": "漢本三代",
    "brand_name": "漢本三代",
    "brand_url": "blog.hanben.com.tw",
    "brand_description": "漢方保健品牌，主打龜鹿二仙膠相關產品",
    "industry": "保健食品",
    "writing_principles": "談族群不談病名、談感受不談症狀、談保養不談治療",
    "locale": "zh-tw",
    "serp_gl": "tw",
    "serp_hl": "zh-tw",
}


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(c[1] == column_name for c in cols)


def migrate():
    if not DB_PATH.exists():
        print(f"[SKIP] 資料庫不存在: {DB_PATH}")
        print("       首次啟動時 init_db() 會自動建立完整 schema。")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # ── Step 1: 建立 projects 表 ─────────────────────────
        if not _table_exists(conn, "projects"):
            print("[1/4] 建立 projects 表...")
            conn.execute("""
                CREATE TABLE projects (
                    id INTEGER PRIMARY KEY,
                    slug TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    brand_name TEXT DEFAULT '',
                    brand_url TEXT DEFAULT '',
                    brand_description TEXT DEFAULT '',
                    industry TEXT DEFAULT '',
                    writing_principles TEXT DEFAULT '',
                    locale TEXT DEFAULT 'zh-tw',
                    serp_gl TEXT DEFAULT 'tw',
                    serp_hl TEXT DEFAULT 'zh-tw',
                    created_at DATETIME,
                    updated_at DATETIME
                )
            """)
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_slug ON projects(slug)")
            print("       ✓ projects 表已建立")
        else:
            print("[1/4] projects 表已存在，跳過")

        # ── Step 2: 插入預設專案 ─────────────────────────────
        existing = conn.execute(
            "SELECT id FROM projects WHERE slug = ?", (DEFAULT_PROJECT["slug"],)
        ).fetchone()

        if not existing:
            print("[2/4] 插入預設專案: 漢本三代...")
            conn.execute(
                """INSERT INTO projects
                   (slug, name, brand_name, brand_url, brand_description,
                    industry, writing_principles, locale, serp_gl, serp_hl)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    DEFAULT_PROJECT["slug"],
                    DEFAULT_PROJECT["name"],
                    DEFAULT_PROJECT["brand_name"],
                    DEFAULT_PROJECT["brand_url"],
                    DEFAULT_PROJECT["brand_description"],
                    DEFAULT_PROJECT["industry"],
                    DEFAULT_PROJECT["writing_principles"],
                    DEFAULT_PROJECT["locale"],
                    DEFAULT_PROJECT["serp_gl"],
                    DEFAULT_PROJECT["serp_hl"],
                ),
            )
            project_id = conn.execute(
                "SELECT id FROM projects WHERE slug = ?", (DEFAULT_PROJECT["slug"],)
            ).fetchone()[0]
            print(f"       ✓ 預設專案 id={project_id}")
        else:
            project_id = existing[0]
            print(f"[2/4] 預設專案已存在 id={project_id}，跳過")

        # ── Step 3: 為每個表加 project_id 欄位與必要 schema patch ──
        print("[3/4] 為資料表新增 project_id 欄位...")
        added = 0
        for table in TABLES_NEED_PROJECT_ID:
            if not _table_exists(conn, table):
                print(f"       · {table}: 表不存在，跳過")
                continue
            if _column_exists(conn, table, "project_id"):
                print(f"       · {table}: project_id 已存在，跳過")
                continue

            conn.execute(f"ALTER TABLE {table} ADD COLUMN project_id INTEGER")
            added += 1
            print(f"       ✓ {table}: 已新增 project_id")

        if added == 0:
            print("       所有表都已有 project_id")

        patched = 0
        for table, columns in TABLE_COLUMN_PATCHES.items():
            if not _table_exists(conn, table):
                continue
            for column_name, ddl in columns.items():
                if _column_exists(conn, table, column_name):
                    continue
                conn.execute(ddl)
                patched += 1
                print(f"       ✓ {table}: 已新增 {column_name}")
        if patched == 0:
            print("       無額外 schema patch 需要套用")

        # ── Step 4: 回填 project_id ─────────────────────────
        print(f"[4/4] 回填所有 NULL project_id → {project_id}...")
        updated_total = 0
        for table in TABLES_NEED_PROJECT_ID:
            if not _table_exists(conn, table):
                continue
            if not _column_exists(conn, table, "project_id"):
                continue

            result = conn.execute(
                f"UPDATE {table} SET project_id = ? WHERE project_id IS NULL",
                (project_id,),
            )
            if result.rowcount > 0:
                updated_total += result.rowcount
                print(f"       ✓ {table}: 更新 {result.rowcount} 筆")

        if updated_total == 0:
            print("       所有記錄都已有 project_id")

        conn.commit()
        print(f"\n✅ Migration 完成！共更新 {updated_total} 筆記錄。")

    except Exception as e:
        conn.rollback()
        print(f"\n❌ Migration 失敗: {e}")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


if __name__ == "__main__":
    migrate()
