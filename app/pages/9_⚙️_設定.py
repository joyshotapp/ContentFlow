"""⚙️ 設定 — Excel 匯入、API 狀態、系統設定"""

import sys
import tempfile
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
_app_root = Path(__file__).resolve().parent.parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from contentflow.db import get_db, init_db
from contentflow.models.database import (
    Article,
    Category,
    CategorySEO,
    Changelog,
    Competitor,
    ContentCalendar,
    ContentStrategy,
    Keyword,
    LegalTerm,
    Product,
    SEORanking,
    WritingRule,
)

init_db()
st.set_page_config(page_title="設定 | ContentFlow", page_icon="⚙️", layout="wide")
st.title("⚙️ 系統設定")

from project_selector import get_current_project_id
project_id = get_current_project_id()


def _project_count(session, model, project_id: int) -> int:
    query = session.query(model)
    if hasattr(model, "project_id"):
        query = query.filter(model.project_id == project_id)
    return query.count()

# ── Excel 匯入 ──
st.subheader("📥 Excel 資料匯入")
st.markdown("上傳 **SEO 專案管理表 Excel** 以匯入/更新所有資料。")

uploaded_file = st.file_uploader("選擇 Excel 檔案", type=["xlsx"])

if uploaded_file:
    st.info(f"已選擇: {uploaded_file.name} ({uploaded_file.size / 1024:.0f} KB)")

    clear = st.checkbox("清除目前專案既有資料後重新匯入", value=False)

    if st.button("🚀 開始匯入", type="primary"):
        # 暫存上傳檔案
        suffix = Path(uploaded_file.name).suffix or ".xlsx"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_path = Path(tmp_file.name)
        tmp_path.write_bytes(uploaded_file.getvalue())

        with st.spinner("正在匯入 Excel 資料至資料庫..."):
            try:
                from contentflow.tools.excel_importer import import_excel

                results = import_excel(str(tmp_path), clear_existing=clear, project_id=project_id)

                st.success("✅ 匯入完成！")
                st.markdown("### 匯入結果")
                for sheet, count in results.items():
                    icon = "✅" if isinstance(count, int) and count > 0 else "⚠️"
                    st.markdown(f"- {icon} **{sheet}**: {count}")

            except Exception as e:
                st.error(f"匯入失敗: {e}")
            finally:
                tmp_path.unlink(missing_ok=True)

# 也支援檔案路徑匯入（開發用）
with st.expander("🛠 從本機路徑匯入（開發模式）"):
    local_path = st.text_input(
        "Excel 檔案路徑",
        value="",
        placeholder="/path/to/your_seo_project.xlsx",
    )
    if st.button("從路徑匯入"):
        if Path(local_path).exists():
            with st.spinner("匯入中..."):
                try:
                    from contentflow.tools.excel_importer import import_excel
                    results = import_excel(local_path, clear_existing=False, project_id=project_id)
                    st.success("✅ 匯入完成！")
                    for sheet, count in results.items():
                        st.markdown(f"- **{sheet}**: {count}")
                except Exception as e:
                    st.error(f"匯入失敗: {e}")
        else:
            st.error(f"找不到檔案: {local_path}")

st.divider()

# ── 資料庫統計 ──
st.subheader("📊 資料庫統計")
session = get_db()
try:
    tables = [
        ("🔑 關鍵字", Keyword),
        ("📁 分類/標籤", Category),
        ("📅 內容日曆", ContentCalendar),
        ("📝 文章規劃", Article),
        ("📜 撰寫規範", WritingRule),
        ("🎯 內容策略", ContentStrategy),
        ("🏢 競品資料", Competitor),
        ("📦 產品資訊", Product),
        ("⚖️ 法規用詞", LegalTerm),
        ("📈 SEO 排名", SEORanking),
        ("🔗 分類 SEO", CategorySEO),
        ("🔧 Changelog", Changelog),
    ]

    cols = st.columns(4)
    for i, (label, model) in enumerate(tables):
        count = _project_count(session, model, project_id)
        cols[i % 4].metric(label, count)

finally:
    session.close()

st.divider()

# ── API 金鑰狀態 ──
st.subheader("🔐 API 金鑰狀態")
try:
    from contentflow.config import settings

    apis = [
        ("OpenAI", bool(settings.openai_api_key)),
        ("Anthropic", bool(settings.anthropic_api_key)),
        ("NCBI / PubMed", bool(settings.ncbi_api_key)),
        ("Serper.dev", bool(settings.serper_api_key)),
        ("SerpAPI", bool(settings.serpapi_key)),
    ]

    for name, configured in apis:
        status = "✅ 已設定" if configured else "❌ 未設定"
        st.markdown(f"- **{name}**: {status}")

except Exception as e:
    st.warning(f"無法讀取設定: {e}")

st.divider()

# ── 資料庫備份/重置 ──
st.subheader("🗄️ 資料庫管理")
col1, col2 = st.columns(2)
with col1:
    if st.button("📋 匯出資料庫統計"):
        session = get_db()
        try:
            report_lines = ["# ContentFlow 資料庫統計\n"]
            for label, model in tables:
                count = _project_count(session, model, project_id)
                report_lines.append(f"- {label}: {count} 筆")
            st.code("\n".join(report_lines))
        finally:
            session.close()

with col2:
    st.warning("⚠️ 危險操作")
    if st.button("🗑️ 清除所有資料", type="secondary"):
        if st.checkbox("我確認要清除所有資料", key="confirm_delete"):
            session = get_db()
            try:
                from contentflow.models.database import Base
                for table in reversed(Base.metadata.sorted_tables):
                    session.execute(table.delete())
                session.commit()
                st.success("已清除所有資料")
                st.rerun()
            finally:
                session.close()
