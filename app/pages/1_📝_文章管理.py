"""📝 文章管理 — 文章規劃 Pipeline"""

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
from contentflow.models.database import Article

init_db()
st.set_page_config(page_title="文章管理 | ContentFlow", page_icon="📝", layout="wide")
st.title("📝 文章管理")
st.caption("管理文章規劃、追蹤進度、啟動 AI 流程")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

try:
    # ── 篩選列 ──
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        status_filter = st.selectbox(
            "狀態篩選",
            ["全部", "planned", "researching", "writing", "reviewing", "published"],
        )
    with col_f2:
        search_kw = st.text_input("搜尋關鍵字 / 標題", "")
    with col_f3:
        sort_by = st.selectbox("排序", ["序號", "搜尋量 (高→低)", "搜尋量 (低→高)"])

    # ── 查詢 ──
    query = session.query(Article)
    if project_id:
        query = query.filter(Article.project_id == project_id)
    if status_filter != "全部":
        query = query.filter(Article.status == status_filter)
    if search_kw:
        like = f"%{search_kw}%"
        query = query.filter(
            (Article.title.ilike(like))
            | (Article.primary_keyword.ilike(like))
            | (Article.outline.ilike(like))
        )
    if sort_by == "序號":
        query = query.order_by(Article.seqno)
    elif sort_by == "搜尋量 (高→低)":
        query = query.order_by(Article.primary_keyword_volume.desc())
    else:
        query = query.order_by(Article.primary_keyword_volume.asc())

    articles = query.all()
    st.info(f"共 {len(articles)} 篇文章")

    if articles:
        df = pd.DataFrame([
            {
                "序號": a.seqno or "-",
                "標題": a.title or "(未命名)",
                "主關鍵字": a.primary_keyword,
                "搜尋量": int(a.primary_keyword_volume),
                "副關鍵字": (a.secondary_keywords or "")[:50],
                "狀態": a.status,
                "Google Doc": a.google_doc_url or "",
            }
            for a in articles
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    # ── 快速入口 ──
    st.info("💡 **SOP 提醒：** 選好文章後 → 前往 **[🔬 AI 研究](/AI研究)** 執行研究 → AI 寫文 → 事實查核")

    # ── 文章詳情 ──
    st.subheader("📄 文章詳情")
    # 依序號排序，無序號的排到最後
    sorted_articles = sorted(articles, key=lambda a: (a.seqno is None, a.seqno or 0))
    article_options = {
        f"#{a.seqno or '?'} — {a.title or a.primary_keyword}": a.id
        for a in sorted_articles
    }
    if article_options:
        selected_label = st.selectbox("選擇文章", list(article_options.keys()))
        selected_id = article_options[selected_label]
        article = session.query(Article).get(selected_id)

        if article:
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**主關鍵字：** {article.primary_keyword}")
                st.markdown(f"**搜尋量：** {int(article.primary_keyword_volume)}")
                st.markdown(f"**副關鍵字：** {article.secondary_keywords or '無'}")

                # 狀態更新
                new_status = st.selectbox(
                    "更新狀態",
                    ["planned", "researching", "writing", "reviewing", "published"],
                    index=["planned", "researching", "writing", "reviewing", "published"].index(article.status)
                    if article.status in ["planned", "researching", "writing", "reviewing", "published"]
                    else 0,
                    key="status_update",
                )
                if st.button("💾 儲存狀態"):
                    article.status = new_status
                    session.commit()
                    st.success(f"已更新為 {new_status}")
                    st.rerun()

            with col2:
                if article.google_doc_url:
                    st.markdown(f"[📄 Google Doc 連結]({article.google_doc_url})")
                if article.publish_url:
                    st.markdown(f"[🌐 已發佈連結]({article.publish_url})")

                st.divider()
                st.markdown("**▶ AI 產文流程**")
                has_research = bool(article.research_report_json)
                has_draft = bool(article.draft_content)

                col_s1, col_s2, col_s3 = st.columns(3)
                with col_s1:
                    icon = "✅" if has_research else "⭕"
                    st.markdown(f"{icon} 研究")
                with col_s2:
                    icon = "✅" if has_draft else "⭕"
                    st.markdown(f"{icon} 寫文")
                with col_s3:
                    icon = "✅" if article.status == "reviewing" else "⭕"
                    st.markdown(f"{icon} 查核")

                st.link_button("🚀 前往 AI 產文中心", "/AI研究", type="primary")

            # 文章大綱
            if article.outline:
                st.subheader("📋 文章架構")
                st.text(article.outline)

            # AI 研究報告
            if article.research_report_json:
                st.subheader("🔬 AI 研究報告")
                try:
                    import json as _json
                    _rpt = _json.loads(article.research_report_json)
                    _pubmed_count = sum(len(q.get("articles", [])) for q in _rpt.get("pubmed_results", []))
                    _kw_count = len(_rpt.get("suggested_keywords", []))
                    _serp_count = len(_rpt.get("serp_analysis", {}).get("top_results", []))
                    st.success(
                        f"✅ 研究已完成｜PubMed 文獻 **{_pubmed_count}** 篇｜"
                        f"關鍵字建議 **{_kw_count}** 個｜競品分析 **{_serp_count}** 筆"
                    )
                    st.caption("完整研究報告請至 🔬 AI 研究 → 選題研究 Tab 查看")
                except Exception:
                    st.success("✅ 研究報告已存在")

            # 文章內容
            if article.draft_content:
                st.subheader("📃 文章草稿")
                st.markdown(article.draft_content)

    # ── 新增文章 ──
    st.divider()
    with st.expander("➕ 新增文章", expanded=False):
        with st.form("add_article"):
            new_title = st.text_input("文章標題")
            new_kw = st.text_input("主關鍵字")
            new_vol = st.number_input("搜尋量", min_value=0, value=0)
            new_secondary = st.text_input("副關鍵字（逗號分隔）")
            new_outline = st.text_area("文章架構（選填）", height=200)

            if st.form_submit_button("新增"):
                if new_title or new_kw:
                    _max_q = session.query(Article.seqno)
                    if project_id:
                        _max_q = _max_q.filter(Article.project_id == project_id)
                    max_seq = _max_q.order_by(Article.seqno.desc()).first()
                    next_seq = (max_seq[0] or 0) + 1 if max_seq and max_seq[0] else 1

                    new_article = Article(
                        seqno=next_seq,
                        title=new_title,
                        primary_keyword=new_kw,
                        primary_keyword_volume=new_vol,
                        secondary_keywords=new_secondary,
                        outline=new_outline,
                        status="planned",
                        project_id=project_id,
                    )
                    session.add(new_article)
                    session.commit()
                    st.success(f"已新增文章 #{next_seq}: {new_title}")
                    st.rerun()
                else:
                    st.warning("請填入標題或主關鍵字")

finally:
    session.close()
