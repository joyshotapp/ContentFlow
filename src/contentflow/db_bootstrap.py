"""Bootstrap PostgreSQL schema for fresh or pre-Alembic databases."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import inspect

from contentflow.db import engine
from contentflow.models.database import Base

_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _ROOT / "alembic.ini"
_MIGRATIONS_DIR = _ROOT / "migrations"


def _bootstrap_mode(table_names: set[str]) -> str:
    if not table_names:
        return "create_and_stamp"
    if "alembic_version" not in table_names:
        return "stamp"
    return "upgrade"


def _make_alembic_config() -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config


def bootstrap_schema() -> str:
    with engine.connect() as conn:
        table_names = set(inspect(conn).get_table_names())

    mode = _bootstrap_mode(table_names)
    config = _make_alembic_config()

    if mode == "create_and_stamp":
        Base.metadata.create_all(bind=engine)
        command.stamp(config, "head")
    elif mode == "stamp":
        command.stamp(config, "head")
    else:
        command.upgrade(config, "head")

    logger.info(f"DB bootstrap mode={mode}")
    return mode


def main() -> None:
    bootstrap_schema()


if __name__ == "__main__":
    main()