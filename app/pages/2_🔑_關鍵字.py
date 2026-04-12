"""🔑 關鍵字資料庫 — 動態查詢、篩選、分析"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
_app_root = Path(__file__).resolve().parent.parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from contentflow.db import get_db, init_db
from contentflow.models.database import Keyword

init_db()
st.set_page_config(page_title="關鍵字資料庫 | ContentFlow", page_icon="🔑", layout="wide")
st.title("🔑 關鍵字資料庫")
st.caption("搜尋、篩選、排序 — 完整取代 Excel 關鍵字表")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    # ── 篩選列 ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        search = st.text_input("🔍 搜尋關鍵字", "")
    with col2:
        priority_filter = st.selectbox("優先順序", ["全部", "⭐ 高優先 (無X)", "🟡 中優先 (綠X)", "⬇️ 低優先 (黑X)"])
    with col3:
        min_vol = st.number_input("最低搜尋量", min_value=0, value=0, step=100)
    with col4:
        max_diff = st.number_input("最高 SEO 難度", min_value=0, max_value=100, value=100)

    # ── 查詢 ──
    query = session.query(Keyword)
    if project_id:
        query = query.filter(Keyword.project_id == project_id)
    if search:
        query = query.filter(Keyword.keyword.ilike(f"%{search}%"))
    if priority_filter == "⭐ 高優先 (無X)":
        query = query.filter((Keyword.priority == "") | (Keyword.priority.is_(None)))
    elif priority_filter == "🟡 中優先 (綠X)":
        query = query.filter(Keyword.priority == "green_x")
    elif priority_filter == "⬇️ 低優先 (黑X)":
        query = query.filter(Keyword.priority == "X")
    if min_vol > 0:
        query = query.filter(Keyword.search_volume >= min_vol)
    if max_diff < 100:
        query = query.filter(Keyword.seo_difficulty <= max_diff)

    # 排序
    sort_col = st.radio(
        "排序依據",
        ["搜尋量 ↓", "搜尋量 ↑", "SEO 難度 ↓", "SEO 難度 ↑", "CPC ↓"],
        horizontal=True,
    )
    sort_map = {
        "搜尋量 ↓": Keyword.search_volume.desc(),
        "搜尋量 ↑": Keyword.search_volume.asc(),
        "SEO 難度 ↓": Keyword.seo_difficulty.desc(),
        "SEO 難度 ↑": Keyword.seo_difficulty.asc(),
        "CPC ↓": Keyword.cpc.desc(),
    }
    query = query.order_by(sort_map[sort_col])

    keywords = query.all()
    st.info(f"共 {len(keywords)} 組關鍵字")

    if keywords:
        df = pd.DataFrame([
            {
                "關鍵字": kw.keyword,
                "搜尋量": int(kw.search_volume),
                "CPC (USD)": round(kw.cpc, 2),
                "付費難度": int(kw.paid_difficulty),
                "SEO 難度": int(kw.seo_difficulty),
                "優先順序": "⬇️ 低" if kw.priority == "X" else ("🟡 中" if kw.priority == "green_x" else "⭐ 高"),
                "Steve 註記": kw.steve_note or "",
            }
            for kw in keywords
        ])
        st.dataframe(df, use_container_width=True, hide_index=True, height=600)

        # ── 統計摘要 ──
        st.divider()
        st.subheader("📊 關鍵字統計")
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            total_vol = sum(kw.search_volume for kw in keywords)
            avg_vol = total_vol / len(keywords) if keywords else 0
            st.metric("總搜尋量", f"{int(total_vol):,}")
            st.metric("平均搜尋量", f"{int(avg_vol):,}")
        with col_s2:
            avg_diff = sum(kw.seo_difficulty for kw in keywords) / len(keywords) if keywords else 0
            low_diff = len([kw for kw in keywords if kw.seo_difficulty <= 20])
            st.metric("平均 SEO 難度", f"{avg_diff:.1f}")
            st.metric("低難度 (≤20)", f"{low_diff} 組")
        with col_s3:
            avg_cpc = sum(kw.cpc for kw in keywords) / len(keywords) if keywords else 0
            high_cpc = len([kw for kw in keywords if kw.cpc > 10])
            st.metric("平均 CPC", f"${avg_cpc:.2f}")
            st.metric("高 CPC (>$10)", f"{high_cpc} 組")

        # ── 搜尋量分佈圖 ──
        st.subheader("📈 搜尋量分佈")
        vol_ranges = {"0-100": 0, "101-500": 0, "501-1000": 0, "1001-5000": 0, "5000+": 0}
        for kw in keywords:
            v = kw.search_volume
            if v <= 100:
                vol_ranges["0-100"] += 1
            elif v <= 500:
                vol_ranges["101-500"] += 1
            elif v <= 1000:
                vol_ranges["501-1000"] += 1
            elif v <= 5000:
                vol_ranges["1001-5000"] += 1
            else:
                vol_ranges["5000+"] += 1
        df_vol = pd.DataFrame(list(vol_ranges.items()), columns=["搜尋量區間", "數量"])
        st.bar_chart(df_vol.set_index("搜尋量區間"))

    # ── 新增關鍵字 ──
    st.divider()
    with st.expander("➕ 新增關鍵字", expanded=False):
        with st.form("add_keyword"):
            new_kw = st.text_input("關鍵字")
            c1, c2, c3 = st.columns(3)
            with c1:
                new_vol = st.number_input("搜尋量", min_value=0, value=0)
            with c2:
                new_cpc = st.number_input("CPC", min_value=0.0, value=0.0, step=0.1)
            with c3:
                new_diff = st.number_input("SEO 難度", min_value=0, max_value=100, value=0)
            new_note = st.text_input("備註")

            if st.form_submit_button("新增"):
                if new_kw:
                    kw_obj = Keyword(
                        keyword=new_kw,
                        search_volume=new_vol,
                        cpc=new_cpc,
                        seo_difficulty=new_diff,
                        steve_note=new_note,
                        project_id=project_id,
                    )
                    session.add(kw_obj)
                    session.commit()
                    st.success(f"已新增: {new_kw}")
                    st.rerun()

finally:
    session.close()
