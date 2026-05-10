"""測試 DB models + 多專案隔離 + excel_importer 基本邏輯"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from contentflow.db import _ensure_sqlite_columns, init_db
from contentflow.db_bootstrap import _bootstrap_mode
from contentflow.models.database import (
    Base, Project, Keyword, Article, ContentCalendar,
    LegalTerm, WritingRule, ContentStrategy, Competitor,
    Product, SEORanking, CategorySEO, Category, Changelog,
)
from contentflow.tools.excel_importer import (
    import_excel, _clear_existing_data, PROJECT_SCOPED_MODELS,
    import_articles,
)


# ── fixtures ──────────────────────────────────────────────────

@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()
    engine.dispose()


def _make_project(session, slug, name="Test"):
    p = Project(slug=slug, name=name, brand_name=name)
    session.add(p)
    session.commit()
    return p


# ── DB model 基礎 ─────────────────────────────────────────────

class TestDBModels:
    def test_project_creation(self, session):
        p = _make_project(session, "brand-a", "Brand A")
        assert p.id is not None
        assert p.slug == "brand-a"

    def test_keyword_with_project(self, session):
        p = _make_project(session, "kw-test")
        kw = Keyword(keyword="測試關鍵字", search_volume=100, project_id=p.id)
        session.add(kw)
        session.commit()
        assert kw.project_id == p.id

    def test_all_scoped_models_have_project_id(self):
        """所有 PROJECT_SCOPED_MODELS 都應有 project_id 欄位"""
        for model in PROJECT_SCOPED_MODELS:
            assert hasattr(model, "project_id"), f"{model.__name__} 缺少 project_id"

    def test_article_has_article_type_column(self):
        assert hasattr(Article, "article_type")


class TestSchemaPatches:
    def test_ensure_sqlite_columns_adds_article_type(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE articles (id INTEGER PRIMARY KEY, title VARCHAR)"))
            _ensure_sqlite_columns(conn)
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(articles)")).fetchall()
            }
        assert "article_type" in columns

    def test_ensure_sqlite_columns_adds_seo_fields(self):
        """_ensure_sqlite_columns 應新增 SEO 相關欄位"""
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE articles (id INTEGER PRIMARY KEY, title VARCHAR)"))
            _ensure_sqlite_columns(conn)
            columns = {
                row[1] for row in conn.execute(text("PRAGMA table_info(articles)")).fetchall()
            }
        for col in ("slug", "meta_title", "meta_description",
                     "faq_schema_json", "article_schema_json", "seo_score"):
            assert col in columns, f"migration 缺少 {col} 欄位"


class TestInitDbBootstrap:
    def test_postgres_init_db_does_not_create_tables(self):
        conn = MagicMock()
        ctx = MagicMock()
        ctx.__enter__.return_value = conn
        ctx.__exit__.return_value = False

        with patch("contentflow.db._db_url", "postgresql+psycopg2://contentflow:pw@db:5432/contentflow"), \
             patch("contentflow.db.engine.begin", return_value=ctx) as mock_begin, \
             patch("contentflow.db.Base.metadata.create_all") as mock_create_all:
            init_db()

        mock_begin.assert_called_once()
        mock_create_all.assert_not_called()
        conn.execute.assert_called_once()
        assert "SELECT 1" in str(conn.execute.call_args.args[0])

    def test_bootstrap_mode_for_empty_database(self):
        assert _bootstrap_mode(set()) == "create_and_stamp"

    def test_bootstrap_mode_for_pre_alembic_database(self):
        assert _bootstrap_mode({"articles", "projects"}) == "stamp"

    def test_bootstrap_mode_for_managed_database(self):
        assert _bootstrap_mode({"articles", "projects", "alembic_version"}) == "upgrade"


class TestArticleSEOColumns:
    """驗證 Article ORM model 包含六個 SEO 欄位"""

    def test_article_seo_columns_exist(self):
        for attr in ("slug", "meta_title", "meta_description",
                      "faq_schema_json", "article_schema_json", "seo_score"):
            assert hasattr(Article, attr), f"Article 缺少 {attr}"

    def test_article_seo_columns_round_trip(self, session):
        p = _make_project(session, "seo-rt")
        a = Article(
            seqno=1, primary_keyword="test", project_id=p.id,
            slug="test-slug", meta_title="Title", meta_description="Desc",
            faq_schema_json='{"mainEntity":[]}', article_schema_json='{}',
            seo_score=85,
        )
        session.add(a)
        session.commit()
        loaded = session.query(Article).filter(Article.id == a.id).one()
        assert loaded.slug == "test-slug"
        assert loaded.meta_title == "Title"
        assert loaded.meta_description == "Desc"
        assert loaded.faq_schema_json == '{"mainEntity":[]}'
        assert loaded.article_schema_json == '{}'
        assert loaded.seo_score == 85


# ── 多專案隔離 ─────────────────────────────────────────────────

class TestMultiProjectIsolation:
    def test_keywords_isolated_by_project(self, session):
        p1 = _make_project(session, "proj-1")
        p2 = _make_project(session, "proj-2")

        session.add(Keyword(keyword="關鍵字A", project_id=p1.id))
        session.add(Keyword(keyword="關鍵字B", project_id=p2.id))
        session.commit()

        q1 = session.query(Keyword).filter(Keyword.project_id == p1.id).all()
        q2 = session.query(Keyword).filter(Keyword.project_id == p2.id).all()
        assert len(q1) == 1 and q1[0].keyword == "關鍵字A"
        assert len(q2) == 1 and q2[0].keyword == "關鍵字B"

    def test_articles_isolated_by_project(self, session):
        p1 = _make_project(session, "art-1")
        p2 = _make_project(session, "art-2")

        session.add(Article(seqno=1, primary_keyword="kw1", project_id=p1.id))
        session.add(Article(seqno=1, primary_keyword="kw2", project_id=p2.id))
        session.commit()

        assert session.query(Article).filter(Article.project_id == p1.id).count() == 1
        assert session.query(Article).filter(Article.project_id == p2.id).count() == 1

    def test_legal_terms_isolated_by_project(self, session):
        p1 = _make_project(session, "lt-1")
        p2 = _make_project(session, "lt-2")

        session.add(LegalTerm(term_type="forbidden", content="禁用詞A", project_id=p1.id))
        session.add(LegalTerm(term_type="allowed", content="允許詞B", project_id=p2.id))
        session.commit()

        q1 = session.query(LegalTerm).filter(LegalTerm.project_id == p1.id).all()
        assert len(q1) == 1
        assert q1[0].content == "禁用詞A"


# ── _clear_existing_data ──────────────────────────────────────

class TestClearExistingData:
    def test_clear_scoped_to_project(self, session):
        """清除只應影響指定專案，不動其他專案"""
        p1 = _make_project(session, "clear-1")
        p2 = _make_project(session, "clear-2")

        session.add(Keyword(keyword="A", project_id=p1.id))
        session.add(Keyword(keyword="B", project_id=p2.id))
        session.add(Article(seqno=1, primary_keyword="kw", project_id=p1.id))
        session.add(Article(seqno=2, primary_keyword="kw", project_id=p2.id))
        session.commit()

        _clear_existing_data(session, project_id=p1.id)

        # p1 資料被清
        assert session.query(Keyword).filter(Keyword.project_id == p1.id).count() == 0
        assert session.query(Article).filter(Article.project_id == p1.id).count() == 0
        # p2 資料還在
        assert session.query(Keyword).filter(Keyword.project_id == p2.id).count() == 1
        assert session.query(Article).filter(Article.project_id == p2.id).count() == 1

    def test_clear_without_project_id_clears_all(self, session):
        """不指定 project_id 時清除所有內容資料"""
        p = _make_project(session, "clear-all")
        session.add(Keyword(keyword="X", project_id=p.id))
        session.commit()

        _clear_existing_data(session, project_id=None)
        assert session.query(Keyword).count() == 0

    def test_clear_preserves_projects_table(self, session):
        """清除不應刪除 projects 表本身"""
        p = _make_project(session, "preserve")
        session.add(Keyword(keyword="tmp", project_id=p.id))
        session.commit()

        _clear_existing_data(session, project_id=None)
        assert session.query(Project).count() == 1


# ── import_excel 簽名驗證 ─────────────────────────────────────

class TestImportExcelSignature:
    def test_accepts_project_id(self):
        """import_excel 必須接受 project_id 參數"""
        import inspect
        sig = inspect.signature(import_excel)
        assert "project_id" in sig.parameters
        assert "clear_existing" in sig.parameters

    def test_file_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            import_excel("/nonexistent/path.xlsx", project_id=1)


# ── import_articles 自動編號 ──────────────────────────────────

class _FakeWorksheet:
    """模擬 openpyxl worksheet 的 iter_rows"""
    def __init__(self, data):
        self._data = data

    def iter_rows(self, values_only=False):
        return iter(self._data)


class TestImportArticlesAutoSeqno:
    def test_skips_header_row(self, session):
        """第一列（標題列）應被跳過，不匯入"""
        p = _make_project(session, "hdr")
        ws = _FakeWorksheet([
            ("序號", "預估主關鍵字(搜量)", "副關鍵字", "架構"),
            (1, "膝蓋痛", "", ""),
        ])
        count = import_articles(ws, session, project_id=p.id)
        assert count == 1
        arts = session.query(Article).filter(Article.project_id == p.id).all()
        assert len(arts) == 1
        assert arts[0].primary_keyword == "膝蓋痛"

    def test_auto_assigns_seqno_when_missing(self, session):
        """無序號的行應自動取得 max+1 編號"""
        p = _make_project(session, "auto-seq")
        ws = _FakeWorksheet([
            ("序號", "主關鍵字", "副關鍵字", "架構"),
            (3, "關鍵字A", "", ""),
            (None, "關鍵字B", "", ""),
            (None, "關鍵字C", "", ""),
        ])
        import_articles(ws, session, project_id=p.id)
        arts = session.query(Article).filter(Article.project_id == p.id).order_by(Article.seqno).all()
        seqnos = [a.seqno for a in arts]
        assert seqnos == [3, 4, 5]
        assert all(s is not None for s in seqnos)

    def test_all_rows_missing_seqno(self, session):
        """全部行都無序號時，自動從 1 開始編號"""
        p = _make_project(session, "all-auto")
        ws = _FakeWorksheet([
            ("序號", "主關鍵字", "副關鍵字", "架構"),
            (None, "甲", "", ""),
            (None, "乙", "", ""),
        ])
        import_articles(ws, session, project_id=p.id)
        arts = session.query(Article).filter(Article.project_id == p.id).order_by(Article.seqno).all()
        assert [a.seqno for a in arts] == [1, 2]
