"""🗺️ Topic Map — Topic Cluster 覆蓋率與缺口視覺化（CF-03-06）"""

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
from contentflow.models.database import Article, ClusterMember, TopicCluster

init_db()
st.set_page_config(page_title="Topic Map | ContentFlow", page_icon="🗺️", layout="wide")
st.title("🗺️ Topic Map")
st.caption("Topic Cluster 主題架構、關鍵字覆蓋率與內容缺口視覺化。")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

# ── 讀取資料 ──────────────────────────────────────────────────────────────

clusters = (
    session.query(TopicCluster)
    .filter(TopicCluster.project_id == project_id)
    .order_by(TopicCluster.pillar_keyword)
    .all()
)


def _get_members(cluster_id: int) -> list[ClusterMember]:
    return (
        session.query(ClusterMember)
        .filter(ClusterMember.cluster_id == cluster_id)
        .all()
    )


def _get_article_title(article_id: int | None) -> str:
    if not article_id:
        return ""
    a = session.get(Article, article_id)
    return a.title if a else f"Article#{article_id}"


# ── 頂部指標 ──────────────────────────────────────────────────────────────

total_clusters = len(clusters)
all_members = []
for c in clusters:
    all_members.extend(_get_members(c.id))

total_kws = len(all_members)
covered_kws = sum(1 for m in all_members if m.article_id is not None)
gap_kws = total_kws - covered_kws
coverage_pct = round(covered_kws / total_kws * 100, 1) if total_kws else 0.0

m1, m2, m3, m4 = st.columns(4)
m1.metric("Topic Clusters", total_clusters)
m2.metric("總關鍵字數", total_kws)
m3.metric("已覆蓋", covered_kws, help="有對應文章的關鍵字")
m4.metric("覆蓋率", f"{coverage_pct}%", delta=f"{gap_kws} 缺口" if gap_kws else None,
          delta_color="inverse")

st.divider()

# ── 重建 / 更新叢集按鈕 ───────────────────────────────────────────────────

with st.expander("🔄 重新分群", expanded=False):
    st.info(
        "點擊下方按鈕可呼叫 ClusterAgent 對目前所有關鍵字重新進行 LLM 語意分群。"
        "此操作會消耗 LLM 呼叫次數，請確認後再執行。"
    )
    if st.button("🚀 重新分群（呼叫 LLM）", type="primary"):
        import asyncio
        with st.spinner("ClusterAgent 執行中..."):
            try:
                from contentflow.agents.cluster_agent import build_topic_clusters
                results = asyncio.get_event_loop().run_until_complete(
                    build_topic_clusters(project_id, session)
                )
                st.success(f"分群完成！共 {len(results)} 個 Topic Cluster。")
                st.rerun()
            except Exception as e:
                st.error(f"分群失敗：{e}")

st.divider()

# ── Cluster 卡片展示 ──────────────────────────────────────────────────────

if not clusters:
    st.info(
        "尚無 Topic Cluster 資料。\n\n"
        "請先至「🔬 AI 研究」匯入關鍵字，或展開上方「重新分群」執行叢集建立。"
    )
    st.stop()

# 顯示模式切換
view_mode = st.radio("顯示模式", ["全部叢集", "僅顯示缺口"], horizontal=True)

tab_overview, tab_gaps = st.tabs(["📊 叢集覽表", "🔍 缺口清單"])

# ── TAB 1：叢集覽表 ────────────────────────────────────────────────────────

with tab_overview:
    for cluster in clusters:
        members = _get_members(cluster.id)
        covered = [m for m in members if m.article_id is not None]
        gaps = [m for m in members if m.article_id is None]
        cov_rate = round(len(covered) / len(members) * 100, 0) if members else 0.0

        # 跳過沒有缺口的（僅顯示缺口模式）
        if view_mode == "僅顯示缺口" and not gaps:
            continue

        with st.expander(
            f"{'🟢' if cov_rate == 100 else '🟡' if cov_rate >= 60 else '🔴'} "
            f"**{cluster.pillar_keyword}** — 覆蓋 {int(cov_rate)}% "
            f"（{len(covered)}/{len(members)} 已有文章）",
            expanded=(len(gaps) > 0),
        ):
            # 支柱文章
            pillar_title = _get_article_title(cluster.pillar_article_id)
            if pillar_title:
                st.markdown(f"🏛️ **支柱文章**：{pillar_title}")
            else:
                st.markdown("🏛️ **支柱文章**：—（尚未建立）")

            c_covered, c_gaps = st.columns(2)

            with c_covered:
                st.markdown("**✅ 已覆蓋關鍵字**")
                for m in covered:
                    art_title = _get_article_title(m.article_id)
                    st.markdown(f"- `{m.keyword}` → [{art_title}]")

            with c_gaps:
                st.markdown("**❌ 缺口關鍵字**")
                for m in gaps:
                    kw_lower = (m.keyword or "").lower()
                    st.markdown(f"- `{m.keyword}` <span style='color:red'>未有文章</span>",
                                unsafe_allow_html=True)

            # 覆蓋率進度條
            st.progress(int(cov_rate) / 100, text=f"覆蓋率 {int(cov_rate)}%")

# ── TAB 2：缺口清單（彙整） ───────────────────────────────────────────────

with tab_gaps:
    gap_rows = []
    for cluster in clusters:
        members = _get_members(cluster.id)
        for m in members:
            if m.article_id is None:
                gap_rows.append({
                    "Cluster 支柱": cluster.pillar_keyword,
                    "缺口關鍵字": m.keyword,
                    "建議動作": "new_article",
                })

    if not gap_rows:
        st.success("所有 Topic Cluster 均已完整覆蓋，無缺口！👏")
    else:
        import pandas as pd

        df = pd.DataFrame(gap_rows)
        st.markdown(f"共 **{len(gap_rows)}** 個關鍵字缺口，建議新增文章：")
        st.dataframe(df, use_container_width=True, hide_index=True)

        if st.button("📥 匯出缺口清單（CSV）"):
            csv_data = df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                "下載 CSV",
                data=csv_data.encode("utf-8-sig"),
                file_name="topic_cluster_gaps.csv",
                mime="text/csv",
            )

        # 快捷：一鍵加入文章規劃
        st.divider()
        st.markdown("**⚡ 快速加入文章規劃**")
        selected_gaps = st.multiselect(
            "選擇要新增規劃的缺口關鍵字",
            options=[r["缺口關鍵字"] for r in gap_rows],
            max_selections=10,
        )
        if selected_gaps and st.button("➕ 建立文章草稿（規劃狀態）", type="primary"):
            from contentflow.models.database import Article
            from contentflow.models.schemas import ArticleStatus

            added = 0
            for kw in selected_gaps:
                exists = (
                    session.query(Article)
                    .filter(Article.project_id == project_id)
                    .filter(Article.primary_keyword == kw)
                    .first()
                )
                if not exists:
                    session.add(Article(
                        project_id=project_id,
                        title=kw,
                        primary_keyword=kw,
                        status=ArticleStatus.PLANNED.value,
                    ))
                    added += 1
            session.commit()
            st.success(f"已建立 {added} 篇文章規劃。")
            st.rerun()
