"""📦 產品資訊 — 產品系列"""

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
from contentflow.models.database import Product

init_db()
st.set_page_config(page_title="產品資訊 | ContentFlow", page_icon="📦", layout="wide")
st.title("📦 產品資訊")
st.caption("品牌產品系列總覽")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    _prod_q = session.query(Product)
    if project_id:
        _prod_q = _prod_q.filter(Product.project_id == project_id)
    products = _prod_q.all()

    if not products:
        st.info("尚無產品資料。請先匯入 Excel。")
    else:
        for prod in products:
            with st.expander(f"📦 {prod.series_name}", expanded=True):
                if prod.description:
                    st.markdown(prod.description)
                if prod.target_symptoms:
                    st.markdown(f"**目標症狀：** {prod.target_symptoms}")
                if prod.inquiry_percentage:
                    st.markdown(f"**詢問熱度：** {prod.inquiry_percentage}")

        st.divider()

        # 動態產品系列表
        st.subheader("📋 產品系列快速參考")
        import pandas as pd
        df = pd.DataFrame([
            {
                "系列": p.series_name,
                "主攻方向": p.target_symptoms or "",
                "詢問佔比": p.inquiry_percentage or "",
            }
            for p in products
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

finally:
    session.close()
