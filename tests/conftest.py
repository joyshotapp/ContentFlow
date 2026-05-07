"""共用 fixtures — 提供 in-memory DB session & 測試用專案"""

import asyncio
import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 確保 src/ 在 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contentflow.models.database import Base, Project  # noqa: E402


def pytest_configure(config):
    if not config.pluginmanager.hasplugin("asyncio"):
        config.pluginmanager.import_plugin("pytest_asyncio.plugin")


class _AutoCreateEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    """Recreate a main-thread event loop on demand for sync-style tests."""

    def get_event_loop(self):  # type: ignore[override]
        loop = getattr(self._local, "_loop", None)  # type: ignore[attr-defined]
        if loop is None and threading.current_thread() is threading.main_thread():
            loop = self.new_event_loop()
            self.set_event_loop(loop)
        return super().get_event_loop()


asyncio.set_event_loop_policy(_AutoCreateEventLoopPolicy())


@pytest.fixture()
def db_session():
    """每個 test 拿到一個全新的 in-memory SQLite session"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def sample_project(db_session):
    """插入一個測試專案並回傳"""
    p = Project(
        slug="testbrand",
        name="測試品牌",
        brand_name="TestBrand",
        brand_url="https://test.example.com",
        brand_description="測試用品牌",
        industry="測試產業",
        writing_principles="談保養不談治療",
        locale="zh-tw",
        serp_gl="tw",
        serp_hl="zh-tw",
    )
    db_session.add(p)
    db_session.commit()
    return p
