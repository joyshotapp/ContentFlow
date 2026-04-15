"""🕐 排程管理 — 查看排程狀態、最近執行記錄、手動觸發（CF-02-07）"""

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
from contentflow.models.database import SchedulerLog

init_db()
st.set_page_config(page_title="排程管理 | ContentFlow", page_icon="🕐", layout="wide")
st.title("🕐 排程管理")
st.caption("查看自動化任務排程狀態、最近執行記錄，及手動觸發功能。")

session = get_db()

# ── 排程定義（對應 scheduler.py 的 job id）──────────────────────────────
JOBS = [
    {"id": "gsc_sync",        "name": "GSC 排名同步",              "cron": "每日 03:00"},
    {"id": "ga4_sync",        "name": "GA4 頁面指標同步",          "cron": "每日 03:30"},
    {"id": "trends_sync",     "name": "關鍵字趨勢同步",            "cron": "每月 1 號 03:45"},
    {"id": "outcome_backfill","name": "行動成效回填",              "cron": "每日 04:00"},
    {"id": "sched_publish",   "name": "排程發布文章",              "cron": "每日 04:05"},
    {"id": "competitor_serp", "name": "競品 SERP 追蹤",            "cron": "每週一 04:30"},
    {"id": "attribution",     "name": "文章表現歸因分析",          "cron": "每週一 05:00"},
    {"id": "refresh_check",   "name": "Content Refresh 觸發檢查",  "cron": "每週二 04:00"},
    {"id": "l1_learn",        "name": "L1 成功模式學習",           "cron": "每月 1 號 06:00"},
    {"id": "l2_learn",        "name": "L2 ROI 分析",               "cron": "每月 1 號 07:00"},
    {"id": "auto_pipeline",   "name": "自動產文 Pipeline",         "cron": "每日 08:00"},
    {"id": "render_verify",   "name": "已發布頁面 SEO 渲染驗證",   "cron": "每日 10:00"},
]


def _get_latest_logs() -> dict[str, SchedulerLog]:
    """取各 job 的最近一筆執行記錄。"""
    latest: dict[str, SchedulerLog] = {}
    for job in JOBS:
        log = (
            session.query(SchedulerLog)
            .filter(SchedulerLog.job_id == job["id"])
            .order_by(SchedulerLog.started_at.desc())
            .first()
        )
        if log:
            latest[job["id"]] = log
    return latest


def _get_recent_logs(job_id: str, limit: int = 10) -> list[SchedulerLog]:
    return (
        session.query(SchedulerLog)
        .filter(SchedulerLog.job_id == job_id)
        .order_by(SchedulerLog.started_at.desc())
        .limit(limit)
        .all()
    )


# ── 排程狀態概覽 ──────────────────────────────────────────────────────────
st.subheader("📋 排程任務一覽")

latest_logs = _get_latest_logs()

try:
    # 嘗試取 APScheduler 下次執行時間
    from contentflow.scheduler import scheduler as _aps
    aps_available = _aps.running if hasattr(_aps, "running") else False
except Exception:
    aps_available = False


cols_head = st.columns([2, 2, 1.5, 1.5, 1])
cols_head[0].markdown("**任務名稱**")
cols_head[1].markdown("**排程週期**")
cols_head[2].markdown("**最近執行**")
cols_head[3].markdown("**狀態**")
cols_head[4].markdown("**手動觸發**")
st.divider()

for job in JOBS:
    jid = job["id"]
    log = latest_logs.get(jid)

    # 手動觸發函式（best-effort，不阻塞 UI）
    def _make_trigger(job_id):
        async def _trigger():
            from contentflow import scheduler as _sched_mod
            fn_map = {
                "gsc_sync": _sched_mod.sync_gsc_all_projects,
                "ga4_sync": _sched_mod.sync_ga4_all_projects,
                "competitor_serp": _sched_mod.run_competitor_serp_check,
                "attribution": _sched_mod.run_attribution_engine,
                "refresh_check": _sched_mod.check_refresh_triggers,
                "l1_learn": _sched_mod.run_l1_pattern_analysis,
                "l2_learn": _sched_mod.run_l2_roi_analysis,
            }
            fn = fn_map.get(job_id)
            if fn:
                import asyncio
                asyncio.create_task(fn())
        return _trigger

    c0, c1, c2, c3, c4 = st.columns([2, 2, 1.5, 1.5, 1])
    c0.markdown(job["name"])
    c1.markdown(f"<small>{job['cron']}</small>", unsafe_allow_html=True)

    if log:
        ts = log.started_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - ts
        age_str = (
            f"{int(age.total_seconds() // 3600)}h 前" if age.total_seconds() >= 3600
            else f"{int(age.total_seconds() // 60)}m 前"
        )
        c2.markdown(f"<small>{age_str}</small>", unsafe_allow_html=True)

        if log.status == "success":
            c3.success("✅ 成功")
        elif log.status == "failed":
            c3.error("❌ 失敗")
        else:
            c3.warning(f"⏳ {log.status}")
    else:
        c2.markdown("<small>尚未執行</small>", unsafe_allow_html=True)
        c3.markdown("—")

    if c4.button("▶", key=f"trigger_{jid}", help=f"手動觸發「{job['name']}」"):
        st.toast(f"已發送觸發指令：{job['name']}（需 Scheduler 服務運行中）", icon="▶️")


# ── 執行歷程詳細記錄 ──────────────────────────────────────────────────────
st.divider()
st.subheader("📊 近期執行記錄")

selected_job = st.selectbox(
    "查詢任務",
    options=[j["id"] for j in JOBS],
    format_func=lambda jid: next(j["name"] for j in JOBS if j["id"] == jid),
)

recent = _get_recent_logs(selected_job, limit=20)

if not recent:
    st.info("尚無執行記錄。")
else:
    import pandas as pd

    rows = []
    for log in recent:
        rows.append({
            "開始時間": log.started_at.strftime("%Y-%m-%d %H:%M:%S") if log.started_at else "—",
            "狀態": log.status,
            "耗時(s)": f"{log.duration_seconds:.1f}" if log.duration_seconds else "—",
            "重試次數": log.retry_count,
            "錯誤訊息": (log.error_message or "")[:80],
        })
    df = pd.DataFrame(rows)

    def _color_status(val):
        color = {"success": "green", "failed": "red"}.get(val, "orange")
        return f"color: {color}; font-weight: bold"

    st.dataframe(
        df.style.applymap(_color_status, subset=["狀態"]),
        use_container_width=True,
        hide_index=True,
    )

    # 統計摘要
    success_count = sum(1 for r in recent if r.status == "success")
    fail_count = sum(1 for r in recent if r.status == "failed")
    m1, m2, m3 = st.columns(3)
    m1.metric("成功次數", success_count)
    m2.metric("失敗次數", fail_count)
    avg_dur = [r.duration_seconds for r in recent if r.duration_seconds]
    m3.metric("平均耗時", f"{sum(avg_dur)/len(avg_dur):.1f}s" if avg_dur else "—")
