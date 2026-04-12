"""
SQLite → PostgreSQL 資料搬移腳本

使用方式：
  1. 啟動 PostgreSQL（docker compose up -d db）
  2. 跑完 alembic upgrade head 建好 schema
  3. 執行本腳本：python scripts/migrate_sqlite_to_pg.py

可用環境變數：
  SQLITE_URL   - 來源 SQLite 路徑，預設 sqlite:///./data/contentflow.db
  DATABASE_URL - 目標 PostgreSQL URL（psycopg2 sync），若為 asyncpg 格式會自動轉換
"""

import sys
import os
import logging
from datetime import date, datetime, timezone

# ── 路徑設定 ──────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# ── 連線設定 ──────────────────────────────────────────────────
SQLITE_URL = os.environ.get("SQLITE_URL", "sqlite:///./data/contentflow.db")
PG_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://contentflow:changeme@localhost:5432/contentflow",
).replace("postgresql+asyncpg://", "postgresql+psycopg2://")

# 各表搬移順序（父表在前，子表在後，避免 FK 衝突）
TABLE_ORDER = [
    "projects",
    "keywords",
    "categories",
    "articles",           # content_calendar.article_id FK → 必須在 articles 之後
    "content_calendar",
    "writing_rules",
    "content_strategy",
    "competitors",
    "products",
    "legal_terms",
    "seo_rankings",
    "category_seo",
    "changelog",
    "topic_clusters",     # cluster_members.cluster_id FK → 必須在 topic_clusters 之後
    "cluster_members",
    # 其餘新表（通常為空）
    "agent_decision_logs",
    "knowledge_entries",
    "scheduler_logs",
]

# ── SEORanking 欄位轉換 helpers ───────────────────────────────

def _parse_date(val: str | None) -> date | None:
    """嘗試將字串解析為 date，失敗回傳 None 並記 warning。"""
    if not val:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    log.warning("無法解析 SEORanking.tracked_date 值：%r，寫入 null", val)
    return None


# ── 通用搬移邏輯 ──────────────────────────────────────────────

def _get_columns(engine, table_name: str) -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT 0"))
        return list(result.keys())


def migrate_table(src_engine, dst_engine, table_name: str) -> int:
    """將單張表從 src 搬移到 dst，返回搬移筆數。"""
    src_cols = _get_columns(src_engine, table_name)
    dst_cols = _get_columns(dst_engine, table_name)

    # 取交集（舊欄位），PostgreSQL 的新欄位以 null 填充
    common_cols = [c for c in src_cols if c in dst_cols]
    removed_cols = [c for c in src_cols if c not in dst_cols]
    if removed_cols:
        log.info("  [%s] 舊欄位已移除，跳過：%s", table_name, removed_cols)

    cols_sql = ", ".join(common_cols)
    col_placeholders = ", ".join(f":{c}" for c in common_cols)

    with src_engine.connect() as src_conn:
        rows = src_conn.execute(text(f"SELECT {cols_sql} FROM {table_name}")).mappings().all()

    if not rows:
        log.info("  [%s] 空表，跳過", table_name)
        return 0

    # SEORanking 特殊轉換
    if table_name == "seo_rankings":
        transformed = []
        for row in rows:
            r = dict(row)
            # rank → position（舊欄位 rank 不在 common_cols，要另外讀）
            if "rank" in src_cols and "rank" not in dst_cols and "position" in dst_cols:
                with src_engine.connect() as sc:
                    rank_row = sc.execute(
                        text(f"SELECT rank FROM seo_rankings WHERE id = :id"), {"id": r["id"]}
                    ).first()
                    r["position"] = float(rank_row[0]) if rank_row and rank_row[0] is not None else None
                # 把 position 加入 common_cols（如果還不在）
                if "position" not in common_cols:
                    common_cols.append("position")
                    col_placeholders = ", ".join(f":{c}" for c in common_cols)
                    cols_sql = ", ".join(common_cols)
            # tracked_date String → Date
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


# ── 主流程 ────────────────────────────────────────────────────

def main() -> None:
    log.info("╔══ SQLite → PostgreSQL 資料搬移 ══╗")
    log.info("來源：%s", SQLITE_URL)
    log.info("目標：%s", PG_URL.replace(PG_URL.split("@")[0].split("//")[1], "***"))

    if not os.path.exists(SQLITE_URL.replace("sqlite:///", "")):
        log.error("找不到 SQLite 檔案，請確認路徑：%s", SQLITE_URL)
        sys.exit(1)

    src_engine = create_engine(SQLITE_URL)
    dst_engine = create_engine(PG_URL)

    total = 0
    errors = []
    for table in TABLE_ORDER:
        try:
            n = migrate_table(src_engine, dst_engine, table)
            if n:
                log.info("  ✅  %-25s %d 筆", table, n)
            total += n
        except Exception as exc:
            log.error("  ❌  %-25s 失敗：%s", table, exc)
            errors.append((table, str(exc)))

    log.info("╠══ 搬移完成：共 %d 筆 ══╣", total)

    if errors:
        log.warning("以下表格搬移失敗，請手動確認：")
        for tbl, msg in errors:
            log.warning("  %s: %s", tbl, msg)
        sys.exit(1)
    else:
        log.info("╚══ 全部成功，可切換 DATABASE_URL 至 PostgreSQL ══╝")


if __name__ == "__main__":
    main()
