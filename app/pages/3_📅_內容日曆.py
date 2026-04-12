"""📅 內容日曆 — 2026 年月度內容計劃"""

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
from contentflow.models.database import ContentCalendar

init_db()
st.set_page_config(page_title="內容日曆 | ContentFlow", page_icon="📅", layout="wide")
st.title("📅 內容日曆")
st.caption("月度內容排程總覽")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    # ── 篩選 ──
    col1, col2, col3 = st.columns(3)
    with col1:
        month_filter = st.selectbox(
            "月份", ["全部"] + [f"{m} 月" for m in range(1, 13)]
        )
    with col2:
        type_filter = st.selectbox("文章類型", ["全部", "知識", "情境", "節慶"])
    with col3:
        arch_filter = st.selectbox(
            "寫作架構",
            ["全部", "倒三角", "金字塔", "思維流程", "敘事型"],
        )

    query = session.query(ContentCalendar).order_by(
        ContentCalendar.month, ContentCalendar.week
    )
    if project_id:
        query = query.filter(ContentCalendar.project_id == project_id)
    if month_filter != "全部":
        m = int(month_filter.replace(" 月", ""))
        query = query.filter(ContentCalendar.month == m)
    if type_filter != "全部":
        query = query.filter(ContentCalendar.article_type == type_filter)
    if arch_filter != "全部":
        query = query.filter(ContentCalendar.writing_architecture.ilike(f"%{arch_filter}%"))

    entries = query.all()
    st.info(f"共 {len(entries)} 篇排程")

    # ── 月份摘要 ──
    if entries and month_filter == "全部":
        monthly_summary = {}
        for e in entries:
            key = f"{e.month}月"
            if key not in monthly_summary:
                monthly_summary[key] = {"知識": 0, "情境": 0, "節慶": 0, "其他": 0}
            t = e.article_type if e.article_type in ["知識", "情境", "節慶"] else "其他"
            monthly_summary[key][t] += 1

        df_summary = pd.DataFrame(monthly_summary).T
        df_summary.index.name = "月份"
        st.subheader("📊 月度文章類型分佈")
        st.bar_chart(df_summary)

    st.divider()

    # ── 日曆表格 ──
    if entries:
        for month_num in sorted(set(e.month for e in entries)):
            month_entries = [e for e in entries if e.month == month_num]
            st.subheader(f"📆 {month_num} 月 ({len(month_entries)} 篇)")

            df = pd.DataFrame([
                {
                    "週": e.week,
                    "類型": e.article_type,
                    "標題": e.title,
                    "關鍵字": (e.keywords or "")[:60],
                    "搜尋意圖": e.search_intent,
                    "受眾": (e.target_audience or "")[:40],
                    "架構": e.writing_architecture,
                    "狀態": e.status,
                }
                for e in month_entries
            ])
            st.dataframe(df, use_container_width=True, hide_index=True)

    # ── 文章詳情展開 ──
    st.divider()
    st.subheader("🔍 文章詳情")
    if entries:
        options = {
            f"M{e.month}W{e.week} — {e.title[:40]}": e.id
            for e in entries
        }
        selected = st.selectbox("選擇文章", list(options.keys()))
        entry = session.get(ContentCalendar, options[selected])

        if entry:
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown(f"**月份/週：** {entry.month}月 第{entry.week}週")
                st.markdown(f"**文章類型：** {entry.article_type}")
                st.markdown(f"**搜尋意圖：** {entry.search_intent}")
                st.markdown(f"**寫作架構：** {entry.writing_architecture}")
            with col_r:
                st.markdown(f"**關鍵字：** {entry.keywords}")
                st.markdown(f"**目標受眾：** {entry.target_audience}")

            if entry.faq_questions:
                st.markdown("**FAQ 問題：**")
                for q in entry.faq_questions.split("\n"):
                    q = q.strip()
                    if q:
                        st.markdown(f"- {q}")

            # 狀態更新
            new_status = st.selectbox(
                "更新狀態",
                ["planned", "researching", "writing", "published"],
                index=["planned", "researching", "writing", "published"].index(entry.status)
                if entry.status in ["planned", "researching", "writing", "published"]
                else 0,
                key="cal_status_update",
            )
            if st.button("💾 更新日曆狀態"):
                entry.status = new_status
                session.commit()
                st.success("已更新")
                st.rerun()

finally:
    session.close()
