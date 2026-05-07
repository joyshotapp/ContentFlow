"""Migrate data from SQLite to PostgreSQL.

Usage:
    1. Start PostgreSQL: docker compose up -d db
    2. Run migrations: alembic upgrade head
    3. Execute this script: python scripts/migrate_sqlite_to_pg.py

Environment variables:
    SQLITE_URL   - source SQLite URL, default sqlite:///./data/contentflow.db
    DATABASE_URL - target PostgreSQL URL; asyncpg URLs are rewritten to psycopg2
"""

import sys
import os
import logging
from datetime import date, datetime, timezone

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Connection setup
SQLITE_URL = os.environ.get("SQLITE_URL", "sqlite:///./data/contentflow.db")
PG_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://contentflow:changeme@localhost:5432/contentflow",
).replace("postgresql+asyncpg://", "postgresql+psycopg2://")

# Migration order: parent tables first, child tables after.
TABLE_ORDER = [
    "projects",
    "keywords",
    "categories",
    "articles",           # content_calendar.article_id depends on this table
    "content_calendar",
    "writing_rules",
    "content_strategy",
    "competitors",
    "products",
    "legal_terms",
    "seo_rankings",
    "category_seo",
    "changelog",
    "topic_clusters",     # cluster_members.cluster_id depends on this table
    "cluster_members",
    # Newer tables, usually empty during the first migration.
    "agent_decision_logs",
    "knowledge_entries",
    "scheduler_logs",
]

# SEORanking field conversion helpers

def _parse_date(val: str | None) -> date | None:
    """Parse a date string; return None when parsing fails."""
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    log.warning("Unable to parse SEORanking.tracked_date value %r; writing null", val)
    return None


# Generic migration helpers

def _get_columns(engine, table_name: str) -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 0"))
        return list(result.keys())


def migrate_table(src_engine, dst_engine, table_name: str) -> int:
    """Move one table from src to dst and return migrated row count."""
    src_cols = _get_columns(src_engine, table_name)
    dst_cols = _get_columns(dst_engine, table_name)

    # Keep only shared columns; new PostgreSQL-only columns stay null.
    common_cols = [c for c in src_cols if c in dst_cols]
    removed_cols = [c for c in src_cols if c not in dst_cols]
    if removed_cols:
        log.info("  [%s] Skipping removed legacy columns: %s", table_name, removed_cols)

    cols_sql = ", ".join(common_cols)
    col_placeholders = ", ".join(f":{c}" for c in common_cols)

    with src_engine.connect() as src_conn:
        rows = src_conn.execute(text(f"SELECT {cols_sql} FROM {table_name}")).mappings().all()

    if not rows:
        log.info("  [%s] Empty table, skipping", table_name)
        return 0

    # SEORanking specific conversion
    if table_name == "seo_rankings":
        transformed = []
        for row in rows:
            r = dict(row)
            # rank -> position for legacy schemas.
            if "rank" in src_cols and "rank" not in dst_cols and "position" in dst_cols:
                with src_engine.connect() as sc:
                    rank_row = sc.execute(
                        text(f"SELECT rank FROM seo_rankings WHERE id = :id"), {"id": r["id"]}
                    ).first()
                    r["position"] = float(rank_row[0]) if rank_row and rank_row[0] is not None else None
                # Add position to the insert list when needed.
                if "position" not in common_cols:
                    common_cols.append("position")
                    col_placeholders = ", ".join(f":{c}" for c in common_cols)
                    cols_sql = ", ".join(common_cols)
            # tracked_date string -> date
            if "tracked_date" in r:
                r["tracked_date"] = _parse_date(r["tracked_date"])
            transformed.append(r)
        rows_to_write = transformed
    else:
        rows_to_write = [dict(r) for r in rows]

    insert_sql = text(
        f"INSERT INTO {table_name} ({', '.join(common_cols)}) "
        f"VALUES ({', '.join(f':{c}' for c in common_cols)}) "
        f"ON CONFLICT (id) DO NOTHING"
    )

    with dst_engine.begin() as dst_conn:
        dst_conn.execute(insert_sql, rows_to_write)

    return len(rows_to_write)


# Main entry point

def main() -> None:
    log.info("Starting SQLite -> PostgreSQL migration")
    log.info("Source: %s", SQLITE_URL)
    log.info("Target: %s", PG_URL.replace(PG_URL.split("@")[0].split("//")[1], "***"))

    if not os.path.exists(SQLITE_URL.replace("sqlite:///", "")):
        log.error("SQLite file not found: %s", SQLITE_URL)
        sys.exit(1)

    src_engine = create_engine(SQLITE_URL)
    dst_engine = create_engine(PG_URL)

    total = 0
    errors = []
    for table in TABLE_ORDER:
        try:
            n = migrate_table(src_engine, dst_engine, table)
            if n:
                log.info("  OK  %-25s %d rows", table, n)
            total += n
        except Exception as exc:
            log.error("  FAIL %-25s %s", table, exc)
            errors.append((table, str(exc)))

    log.info("Migration finished: %d total rows", total)

    if errors:
        log.warning("The following tables failed and require manual review:")
        for tbl, msg in errors:
            log.warning("  %s: %s", tbl, msg)
        sys.exit(1)
    else:
        log.info("Migration completed successfully. DATABASE_URL can be switched to PostgreSQL.")


if __name__ == "__main__":
    main()
