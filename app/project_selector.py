"""共用專案選擇器 — 在 Sidebar 中顯示專案切換下拉"""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parent.parent
if str(_root / "src") not in sys.path:
    sys.path.insert(0, str(_root / "src"))

from contentflow.db import get_db
from contentflow.models.database import Project


def get_current_project_id() -> int | None:
    """取得目前選中的 project_id，並在 sidebar 顯示專案選擇器。"""
    session = get_db()
    try:
        projects = session.query(Project).order_by(Project.id).all()
        if not projects:
            st.sidebar.warning("尚未建立任何專案")
            return None

        options = {p.name: p.id for p in projects}
        # 還原上次選擇
        default_idx = 0
        prev = st.session_state.get("_project_id")
        if prev:
            ids = [p.id for p in projects]
            if prev in ids:
                default_idx = ids.index(prev)

        selected_name = st.sidebar.selectbox(
            "📂 目前專案",
            list(options.keys()),
            index=default_idx,
            key="_project_selector",
        )
        project_id = options[selected_name]
        st.session_state["_project_id"] = project_id
        return project_id
    finally:
        session.close()
