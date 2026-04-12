"""共用 fixtures — 提供 in-memory DB session & 測試用專案"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 確保 src/ 在 path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from contentflow.models.database import Base, Project  # noqa: E402


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
