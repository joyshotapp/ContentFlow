"""⚖️ 法規合規 — 用詞合規檢查"""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
_app_root = Path(__file__).resolve().parent.parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from contentflow.db import get_db, init_db
from contentflow.models.database import LegalTerm

init_db()
st.set_page_config(page_title="法規合規 | ContentFlow", page_icon="⚖️", layout="wide")
st.title("⚖️ 用詞合規檢查")
st.caption("根據專案法規資料庫 — 確保內容合規")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    # ── 合規檢查器 ──
    st.subheader("🔍 用詞合規檢查")
    check_text = st.text_area(
        "貼上文章內容，檢查是否含有違規用詞",
        height=200,
        placeholder="將文章內容貼在這裡..."
    )

    if check_text and st.button("🔎 開始檢查"):
        _terms_q = session.query(LegalTerm)
        if project_id:
            _terms_q = _terms_q.filter(LegalTerm.project_id == project_id)
        terms = _terms_q.all()

        # 從資料庫動態載入禁用詞
        forbidden_words = []
        for t in terms:
            if t.term_type == "forbidden":
                # 從法規內容中提取關鍵詞（每行一個或逗號分隔）
                for line in t.content.split("\n"):
                    line = line.strip().lstrip("-•·").strip()
                    if line and len(line) <= 10:
                        forbidden_words.append(line)

        forbidden_found = []
        for word in forbidden_words:
            if word in check_text:
                forbidden_found.append(word)

        if forbidden_found:
            st.error(f"⚠️ 發現 {len(forbidden_found)} 個可能違規用詞!")
            for w in forbidden_found:
                st.markdown(f"- ❌ **{w}**")
            st.warning("建議：請檢查上下文並考慮替換為安全用詞。")
        elif not forbidden_words:
            st.warning("尚未設定禁用詞清單。請先匯入法規資料。")
        else:
            st.success("✅ 未發現明顯違規用詞！")

    st.divider()

    # ── 法規資料庫 ──
    st.subheader("📚 法規資料庫")
    _all_terms_q = session.query(LegalTerm)
    if project_id:
        _all_terms_q = _all_terms_q.filter(LegalTerm.project_id == project_id)
    terms = _all_terms_q.all()

    if terms:
        # 分類顯示
        tabs = st.tabs(["🚫 涉及醫療效能", "⚠️ 涉及誇張/易誤解", "✅ 可使用詞句", "📋 完整規定"])

        with tabs[0]:
            st.markdown("**以下用詞涉及醫療效能，不得使用於食品廣告：**")
            forbidden = [t for t in terms if t.term_type == "forbidden"]
            for t in forbidden:
                st.markdown(t.content)

        with tabs[1]:
            st.markdown("**以下用詞涉及誇張或易生誤解：**")
            caution = [t for t in terms if t.term_type == "caution"]
            for t in caution:
                st.markdown(t.content)

        with tabs[2]:
            st.markdown("**以下用詞可安全使用：**")
            allowed = [t for t in terms if t.term_type == "allowed"]
            for t in allowed:
                st.markdown(t.content)

        with tabs[3]:
            st.markdown("**完整法規參考：**")
            for t in terms:
                with st.expander(f"[{t.term_type}] {t.content[:50]}..."):
                    st.markdown(t.content)
                    if t.source:
                        st.markdown(f"來源: {t.source}")
    else:
        st.info("尚無法規資料。請先匯入 Excel。")

    st.divider()

    # ── 安全用詞速查 ──
    st.subheader("✅ 安全用詞速查")
    allowed = [t for t in terms if t.term_type == "allowed"]
    if allowed:
        for t in allowed:
            st.markdown(t.content)
    else:
        st.info("尚無安全用詞資料。")

finally:
    session.close()
