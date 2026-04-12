"""🏢 競品分析 — 競業市場研究"""

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
from contentflow.models.database import Competitor

init_db()
st.set_page_config(page_title="競品分析 | ContentFlow", page_icon="🏢", layout="wide")
st.title("🏢 競品分析")
st.caption("競業市場研究 — 競品的內容策略對照")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    _comp_q = session.query(Competitor)
    if project_id:
        _comp_q = _comp_q.filter(Competitor.project_id == project_id)
    competitors = _comp_q.all()

    if not competitors:
        st.info("尚無競品資料。請先匯入 Excel。")
    else:
        # ── 概覽表 ──
        st.subheader("📊 競品概覽")
        import pandas as pd
        df = pd.DataFrame([
            {
                "品牌": c.brand_name,
                "網站": c.website,
                "販售產品": c.sells_products,
            }
            for c in competitors
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()

        # ── 各品牌詳情 ──
        tabs = st.tabs([c.brand_name for c in competitors])
        for tab, comp in zip(tabs, competitors):
            with tab:
                col1, col2 = st.columns(2)
                with col1:
                    if comp.website:
                        st.markdown(f"🌐 [{comp.website}]({comp.website})")
                    st.markdown("**📌 特色：**")
                    st.markdown(comp.features or "無資料")
                with col2:
                    st.markdown("**📊 內容經營分析：**")
                    st.markdown(comp.content_analysis or "無資料")

                if comp.recommendation:
                    st.markdown("**💡 模仿建議：**")
                    st.success(comp.recommendation)

finally:
    session.close()
