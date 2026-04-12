"""📜 撰寫規範 — 四大架構 + 內容定位 + 法規合規"""

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
from contentflow.models.database import ContentStrategy, WritingRule

init_db()
st.set_page_config(page_title="撰寫規範 | ContentFlow", page_icon="📜", layout="wide")
st.title("📜 撰寫規範 & 內容定位")
st.caption("Writing Agent 的核心規則參考 — 四大架構、撰寫策略、合法用詞")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    # ── 撰寫規範 ──
    st.subheader("📝 文章架構指南")
    _rules_q = session.query(WritingRule).order_by(WritingRule.order_num)
    if project_id:
        _rules_q = _rules_q.filter(WritingRule.project_id == project_id)
    rules = _rules_q.all()

    if rules:
        for rule in rules:
            with st.expander(f"📖 {rule.name}", expanded=True):
                st.markdown(rule.content)
    else:
        st.info("尚無撰寫規範資料。請先匯入 Excel。")

    st.divider()

    # ── 內容定位（策略） ──
    st.subheader("🎯 部落格內容定位")
    _strat_q = session.query(ContentStrategy).order_by(ContentStrategy.order_num)
    if project_id:
        _strat_q = _strat_q.filter(ContentStrategy.project_id == project_id)
    strategies = _strat_q.all()

    if strategies:
        # 分組顯示
        sections = {}
        for s in strategies:
            key = s.section or "其他"
            if key not in sections:
                sections[key] = []
            sections[key].append(s)

        tabs = st.tabs(list(sections.keys()))
        for tab, (section_name, items) in zip(tabs, sections.items()):
            with tab:
                for item in items:
                    if item.title and item.title != section_name:
                        st.markdown(f"**{item.title}**")
                    st.markdown(item.content)
                    st.markdown("---")
    else:
        st.info("尚無內容定位資料。")

    st.divider()

    # ── 快速參考卡 ──
    st.subheader("⚡ 架構快速對照")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        **🔺 倒三角架構** — 知識類文章
        - 結論先行 → 佐證 → 延伸
        - 適合 SEO 權威文

        **🏔 金字塔 SCQA** — 情境類文章
        - 情境 → 衝突 → 反思 → 解答
        - 故事感，引起共鳴
        """)
    with col2:
        st.markdown("""
        **🧠 思維流程型** — 深度分析文
        - 問題 → 分析 → 解決方案
        - 邏輯權威，適合專業內容

        **📖 敘事型** — 節慶孝親文
        - 起 → 承 → 轉 → 合
        - 溫暖感性，品牌溫度
        """)

    st.divider()

    # ── 撰寫策略核心原則 ──
    st.subheader("🛡️ 撰寫策略核心原則")
    if strategies:
        st.info("以下原則來自專案的內容策略設定，請至「設定」頁匹入 Excel 或直接編輯資料庫修改。")
    else:
        st.info("尚無撰寫策略資料。請先匯入 Excel。")

finally:
    session.close()
