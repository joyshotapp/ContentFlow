"""🤖 Agent Run 檢視 — 查看單次 orchestrator run 的完整決策日誌（CF-04-06）"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))
_app_root = Path(__file__).resolve().parent.parent
if str(_app_root) not in sys.path:
    sys.path.insert(0, str(_app_root))

from contentflow.db import get_db, init_db
from contentflow.models.database import AgentDecisionLog, Article

init_db()
st.set_page_config(page_title="Agent Run 檢視 | ContentFlow", page_icon="🤖", layout="wide")
st.title("🤖 Agent Run 決策日誌")
st.caption("查看 Orchestrator 每次 run 的節點決策軌跡、SEO 分數變化、預算消耗。")

from project_selector import get_current_project_id
project_id = get_current_project_id()

session = get_db()

# ── 文章選擇 ──────────────────────────────────────────────────────────────

articles_with_logs = (
    session.query(Article)
    .join(AgentDecisionLog, AgentDecisionLog.article_id == Article.id, isouter=False)
    .filter(Article.project_id == project_id)
    .distinct()
    .order_by(Article.updated_at.desc())
    .limit(50)
    .all()
)

if not articles_with_logs:
    st.info(
        "目前尚無 Agent Run 記錄。\n\n"
        "請前往「🔬 AI 研究」頁面執行一次 AI 產文，完成後記錄將顯示於此。"
    )
    st.stop()

article_options = {f"{a.title} (#{a.id})": a.id for a in articles_with_logs}
selected_label = st.selectbox("選擇文章", options=list(article_options.keys()))
selected_article_id = article_options[selected_label]

# ── 取此文章的所有 run_id（可能有多次 run）────────────────────────────────

run_ids = (
    session.query(AgentDecisionLog.run_id)
    .filter(AgentDecisionLog.article_id == selected_article_id)
    .distinct()
    .order_by(AgentDecisionLog.created_at.desc())
    .all()
)
run_id_list = [r[0] for r in run_ids]

if len(run_id_list) > 1:
    selected_run = st.selectbox(
        "Run ID（多次執行）",
        options=run_id_list,
        format_func=lambda rid: f"{rid[:8]}…",
    )
else:
    selected_run = run_id_list[0]
    st.markdown(f"**Run ID**: `{selected_run[:12]}…`")

# ── 讀取此 run 的所有決策 ─────────────────────────────────────────────────

logs: list[AgentDecisionLog] = (
    session.query(AgentDecisionLog)
    .filter(
        AgentDecisionLog.article_id == selected_article_id,
        AgentDecisionLog.run_id == selected_run,
    )
    .order_by(AgentDecisionLog.created_at)
    .all()
)

if not logs:
    st.warning("找不到此 Run 的決策記錄。")
    st.stop()

# ── 概覽指標 ──────────────────────────────────────────────────────────────

seo_check_logs = [l for l in logs if l.step == "seo_check"]
latest_seo = seo_check_logs[-1] if seo_check_logs else None
budget_log = next((l for l in reversed(logs) if "budget" in l.step.lower()), None)
total_steps = len(logs)

m1, m2, m3, m4 = st.columns(4)
m1.metric("決策步驟數", total_steps)

if latest_seo:
    import re
    score_match = re.search(r"(\d+)/100", latest_seo.decision or "")
    if score_match:
        m2.metric("最終 SEO 分數", f"{score_match.group(1)}/100")
    else:
        m2.metric("最終 SEO 分數", "—")
else:
    m2.metric("最終 SEO 分數", "—")

seo_retries = len([l for l in logs if "seo_qa_retry" in l.step])
m3.metric("SEO 重試次數", seo_retries)

if budget_log:
    if "budget" in (budget_log.decision or "").lower():
        m4.metric("預算狀態", "⚠️ 超限", delta="需人工審核", delta_color="inverse")
    else:
        m4.metric("預算狀態", "✅ 正常")
else:
    m4.metric("預算狀態", "—")

st.divider()

# ── 決策時間軸 ────────────────────────────────────────────────────────────

st.subheader("📋 節點決策時間軸")

STEP_ICONS = {
    "research": "🔍",
    "strategy": "🧠",
    "writing": "✍️",
    "seo_check": "📊",
    "seo_gate": "🚦",
    "factcheck": "✅",
    "budget_guard": "💰",
}
CONFIDENCE_COLORS = {
    "data": "#27ae60",
    "rule": "#2980b9",
    "heuristic": "#8e44ad",
    "verified": "#e67e22",
}

for log in logs:
    icon = STEP_ICONS.get(log.step.split("_retry_")[0], "🔷")
    conf_color = CONFIDENCE_COLORS.get(log.confidence, "#7f8c8d")
    ts = log.created_at
    if ts and ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_str = ts.strftime("%H:%M:%S") if ts else ""

    with st.container():
        c_icon, c_main = st.columns([0.05, 0.95])
        c_icon.markdown(f"<div style='font-size:1.4em;text-align:center;margin-top:8px'>{icon}</div>",
                        unsafe_allow_html=True)
        with c_main:
            st.markdown(
                f"**{log.step}** "
                f"<span style='background:{conf_color};color:white;"
                f"border-radius:4px;padding:1px 6px;font-size:0.75em'>"
                f"{log.confidence}</span> "
                f"<small style='color:#888'>{ts_str}</small>",
                unsafe_allow_html=True,
            )
            st.markdown(f"📌 **決策**：{log.decision}")
            if log.reason:
                st.markdown(f"<small style='color:#555'>💡 {log.reason}</small>",
                            unsafe_allow_html=True)
    st.markdown("<hr style='margin:4px 0;opacity:0.3'>", unsafe_allow_html=True)

# ── SEO 分數走勢 ──────────────────────────────────────────────────────────

if len(seo_check_logs) > 1:
    st.divider()
    st.subheader("📈 SEO 分數走勢")
    import re, pandas as pd

    seo_data = []
    for i, sl in enumerate(seo_check_logs, 1):
        m = re.search(r"(\d+)/100", sl.decision or "")
        if m:
            seo_data.append({"輪次": f"第{i}次", "SEO 分數": int(m.group(1))})

    if seo_data:
        df = pd.DataFrame(seo_data)
        st.bar_chart(df.set_index("輪次"))

# ── 原始 JSON 展開 ────────────────────────────────────────────────────────

with st.expander("🔧 原始決策記錄（JSON）", expanded=False):
    import json
    raw = [
        {
            "step": l.step,
            "decision": l.decision,
            "reason": l.reason,
            "confidence": l.confidence,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]
    st.json(raw)
