"""ContentFlow AI — SEO 文章自動化平台"""

import sys
from pathlib import Path

import streamlit as st

# 確保 src 在 path 中
_root = Path(__file__).resolve().parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
_app_root = Path(__file__).resolve().parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from contentflow.db import get_db, init_db
from contentflow.models.database import (
    Article,
    ContentCalendar,
    Keyword,
)

st.set_page_config(
    page_title="ContentFlow AI",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 初始化 DB
init_db()


def main():
    st.title("🚀 ContentFlow AI")
    st.caption("SEO 文章自動化系統")
    st.divider()

    from project_selector import get_current_project_id
    project_id = get_current_project_id()

    session = get_db()
    try:
        # KPI 卡片
        kw_q = session.query(Keyword)
        art_q = session.query(Article)
        cal_q = session.query(ContentCalendar)
        if project_id:
            kw_q = kw_q.filter(Keyword.project_id == project_id)
            art_q = art_q.filter(Article.project_id == project_id)
            cal_q = cal_q.filter(ContentCalendar.project_id == project_id)
        kw_count = kw_q.count()
        article_count = art_q.count()
        calendar_count = cal_q.count()
        published = art_q.filter(Article.status == "published").count()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🔑 關鍵字庫", f"{kw_count} 組")
        col2.metric("📝 文章規劃", f"{article_count} 篇")
        col3.metric("📅 內容日曆", f"{calendar_count} 篇")
        col4.metric("✅ 已發佈", f"{published} 篇")

        st.divider()

        # 文章狀態分佈
        col_left, col_right = st.columns(2)

        with col_left:
            st.subheader("📊 文章狀態分佈")
            # 直接統計
            status_data = {}
            _art_q = session.query(Article)
            if project_id:
                _art_q = _art_q.filter(Article.project_id == project_id)
            articles = _art_q.all()
            for a in articles:
                status_data[a.status] = status_data.get(a.status, 0) + 1

            if status_data:
                import pandas as pd
                df_status = pd.DataFrame(
                    list(status_data.items()),
                    columns=["狀態", "數量"]
                )
                st.bar_chart(df_status.set_index("狀態"))
            else:
                st.info("尚無文章資料。請至「⚙️ 設定」頁匯入 Excel。")

        with col_right:
            st.subheader("📅 月度內容計劃")
            _cal_q = session.query(ContentCalendar)
            if project_id:
                _cal_q = _cal_q.filter(ContentCalendar.project_id == project_id)
            calendars = _cal_q.all()
            if calendars:
                import pandas as pd
                monthly = {}
                for c in calendars:
                    monthly[c.month] = monthly.get(c.month, 0) + 1
                df_monthly = pd.DataFrame(
                    sorted(monthly.items()),
                    columns=["月份", "文章數"]
                )
                st.bar_chart(df_monthly.set_index("月份"))
            else:
                st.info("尚無內容日曆資料。")

        st.divider()

        # 熱門關鍵字
        st.subheader("🔥 高搜尋量關鍵字 Top 10")
        _kw_top_q = session.query(Keyword)
        if project_id:
            _kw_top_q = _kw_top_q.filter(Keyword.project_id == project_id)
        top_kws = _kw_top_q.order_by(Keyword.search_volume.desc()).limit(10).all()
        if top_kws:
            import pandas as pd
            df_kw = pd.DataFrame([
                {
                    "關鍵字": kw.keyword,
                    "搜尋量": int(kw.search_volume),
                    "CPC": kw.cpc,
                    "SEO 難度": int(kw.seo_difficulty),
                    "優先順序": kw.priority or "⭐ 高",
                }
                for kw in top_kws
            ])
            st.dataframe(df_kw, use_container_width=True, hide_index=True)
        else:
            st.info("尚無關鍵字資料。")

        # 近期待撰寫文章
        st.subheader("📝 待處理文章")
        _pending_q = session.query(Article).filter(Article.status.in_(["planned", "researching"]))
        if project_id:
            _pending_q = _pending_q.filter(Article.project_id == project_id)
        pending = _pending_q.order_by(Article.seqno).limit(5).all()
        if pending:
            import pandas as pd
            df_pending = pd.DataFrame([
                {
                    "#": a.seqno or "-",
                    "標題": a.title or a.primary_keyword,
                    "主關鍵字": a.primary_keyword,
                    "搜尋量": int(a.primary_keyword_volume),
                    "狀態": a.status,
                }
                for a in pending
            ])
            st.dataframe(df_pending, use_container_width=True, hide_index=True)

    finally:
        session.close()


main()
