"""
13 🧠 知識庫管理 — CF-05-07/08

功能：
- 查看本專案的所有知識條目（按 category / 信心等級篩選）
- 停用 / 重新啟用條目
- 人工推翻（覆蓋）並記錄理由（audit log）
- 觸發 L1 成功模式分析 / L2 策略優化
- 同步知識到 ChromaDB 向量庫
- 查看人工覆核歷史 (audit log)
"""

import json

import pandas as pd
import streamlit as st

st.set_page_config(page_title="知識庫管理", page_icon="🧠", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# 載入 session & 選擇專案
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def _get_session():
    from contentflow.db import SessionLocal
    return SessionLocal()


def _get_db():
    from contentflow.db import SessionLocal
    return SessionLocal()


from contentflow.models.database import KnowledgeEntry, KnowledgeAuditLog, Project

# 專案選擇
try:
    db = _get_db()
    projects = db.query(Project).order_by(Project.name).all()
except Exception as e:
    st.error(f"無法連接資料庫：{e}")
    st.stop()

if not projects:
    st.warning("尚無專案，請先在設定頁新增專案。")
    st.stop()

project_options = {f"{p.name} ({p.slug})": p.id for p in projects}
selected_label = st.sidebar.selectbox("選擇專案", list(project_options.keys()))
project_id = project_options[selected_label]

st.title("🧠 知識庫管理")
st.caption("查看 Agent 學習成果、管理知識條目、觸發學習分析")

# ─────────────────────────────────────────────────────────────────────────────
# 頂部指標
# ─────────────────────────────────────────────────────────────────────────────

all_entries = (
    db.query(KnowledgeEntry)
    .filter(KnowledgeEntry.project_id == project_id)
    .all()
)

active_entries = [e for e in all_entries if e.is_active]
universal_entries = [e for e in all_entries if e.confidence_level == "universal"]
verified_entries = [e for e in active_entries if e.confidence_level == "verified"]
unverified_entries = [e for e in active_entries if e.confidence_level == "unverified"]

col1, col2, col3, col4 = st.columns(4)
col1.metric("總知識條目", len(all_entries))
col2.metric("🟢 已驗證", len(verified_entries))
col3.metric("🌐 通用規則", len(universal_entries))
col4.metric("🔶 待驗證", len(unverified_entries))

st.divider()

# ─────────────────────────────────────────────────────────────────────────────
# Tab 1: 知識條目列表
# Tab 2: 觸發學習分析
# Tab 3: 人工覆核歷史
# ─────────────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["📋 知識條目", "🔬 觸發學習", "📜 審核歷史"])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1: 知識條目列表
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    # 篩選器
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        filter_status = st.selectbox("狀態", ["全部", "啟用中", "已停用"])
    with col_f2:
        categories = sorted({e.category for e in all_entries})
        filter_cat = st.selectbox("類別", ["全部"] + categories)
    with col_f3:
        filter_conf = st.selectbox("信心等級", ["全部", "universal", "verified", "unverified"])

    # 套用篩選
    filtered = all_entries
    if filter_status == "啟用中":
        filtered = [e for e in filtered if e.is_active]
    elif filter_status == "已停用":
        filtered = [e for e in filtered if not e.is_active]
    if filter_cat != "全部":
        filtered = [e for e in filtered if e.category == filter_cat]
    if filter_conf != "全部":
        filtered = [e for e in filtered if e.confidence_level == filter_conf]

    st.write(f"顯示 {len(filtered)} / {len(all_entries)} 條")

    if not filtered:
        st.info("無符合條件的知識條目。可先至『觸發學習』tab 執行分析。")
    else:
        for entry in sorted(filtered, key=lambda x: -x.evidence_count):
            conf_color = {"universal": "🌐", "verified": "🟢", "unverified": "🔶"}.get(
                entry.confidence_level, "⚪"
            )
            status_icon = "✅" if entry.is_active else "❌"
            label = f"{conf_color} {status_icon} **[{entry.category}]** {entry.pattern[:80]}"
            if len(entry.pattern) > 80:
                label += "..."

            with st.expander(label):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.markdown(f"**完整模式**：{entry.pattern}")
                    st.markdown(f"**支持數據**：{entry.evidence_count} 筆  "
                                f"**信心等級**：{entry.confidence_level}  "
                                f"**狀態**：{'啟用' if entry.is_active else '停用'}")

                    # 展示 metadata
                    meta_str = entry.metadata_json or "{}"
                    try:
                        meta = json.loads(meta_str)
                        if meta:
                            st.json(meta)
                    except (json.JSONDecodeError, TypeError):
                        pass

                with col_b:
                    st.markdown("**操作**")

                    # 停用 / 重新啟用
                    if entry.is_active:
                        reason = st.text_input("停用理由", key=f"reason_{entry.id}",
                                               placeholder="可選填原因...")
                        if st.button("🚫 停用", key=f"deactivate_{entry.id}"):
                            entry.is_active = False
                            audit = KnowledgeAuditLog(
                                entry_id=entry.id,
                                action="deactivate",
                                reason=reason or None,
                                old_value=json.dumps({"is_active": True}),
                                new_value=json.dumps({"is_active": False}),
                            )
                            db.add(audit)
                            db.commit()
                            st.success("已停用")
                            st.rerun()
                    else:
                        if st.button("▶️ 重新啟用", key=f"reactivate_{entry.id}"):
                            entry.is_active = True
                            audit = KnowledgeAuditLog(
                                entry_id=entry.id,
                                action="reactivate",
                                old_value=json.dumps({"is_active": False}),
                                new_value=json.dumps({"is_active": True}),
                            )
                            db.add(audit)
                            db.commit()
                            st.success("已重新啟用")
                            st.rerun()

                    # 人工推翻（override）
                    st.markdown("---")
                    override_reason = st.text_area(
                        "推翻理由", key=f"override_{entry.id}",
                        placeholder="說明為何這個模式不適用...", height=80
                    )
                    if st.button("⚠️ 人工推翻並停用", key=f"override_btn_{entry.id}"):
                        if not override_reason.strip():
                            st.error("請填寫推翻理由")
                        else:
                            old_val = json.dumps({
                                "is_active": entry.is_active,
                                "confidence_level": entry.confidence_level
                            })
                            entry.is_active = False
                            entry.confidence_level = "unverified"
                            audit = KnowledgeAuditLog(
                                entry_id=entry.id,
                                action="override",
                                reason=override_reason.strip(),
                                old_value=old_val,
                                new_value=json.dumps({"is_active": False,
                                                      "confidence_level": "unverified"}),
                            )
                            db.add(audit)
                            db.commit()
                            st.success("已推翻並停用")
                            st.rerun()

    # 匯出知識庫 CSV
    if filtered:
        st.divider()
        rows = [{
            "id": e.id, "category": e.category, "pattern": e.pattern,
            "evidence_count": e.evidence_count, "confidence_level": e.confidence_level,
            "is_active": e.is_active,
        } for e in filtered]
        df_export = pd.DataFrame(rows)
        csv = df_export.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ 匯出 CSV", data=csv, file_name="knowledge_base.csv",
                           mime="text/csv")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 2: 觸發學習分析
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("觸發學習分析")
    st.info(
        "點擊下方按鈕執行分析。分析會讀取已發布文章的 GSC 排名數據，"
        "找出成功模式並寫入知識庫。"
    )

    col_l1, col_l2, col_kb = st.columns(3)

    with col_l1:
        st.markdown("**L1 模式記憶**")
        st.caption("分析文章格式、字數、FAQ vs 排名/CTR 相關性")
        if st.button("🔬 執行 L1 分析", use_container_width=True):
            with st.spinner("分析中..."):
                try:
                    from contentflow.agents.learning_agent import analyze_success_patterns
                    report = analyze_success_patterns(project_id, db)
                    st.success(f"分析完成！分析 {report.analyzed_articles} 篇文章，"
                               f"發現 {len(report.patterns)} 個模式")
                    if report.patterns:
                        for p in report.patterns:
                            conf_icon = {"universal": "🌐", "verified": "🟢",
                                         "unverified": "🔶"}.get(p.confidence_level, "⚪")
                            st.markdown(f"- {conf_icon} {p.pattern_text} （{p.evidence_count} 篇）")
                    if report.low_performers:
                        st.warning(f"低表現文章（排名 > 20）：{len(report.low_performers)} 篇")
                except Exception as e:
                    st.error(f"L1 分析失敗：{e}")

    with col_l2:
        st.markdown("**L2 策略優化**")
        st.caption("分析 keyword ROI，輸出高/低 ROI 清單與 Refresh 建議")
        if st.button("📊 執行 L2 分析", use_container_width=True):
            with st.spinner("分析中..."):
                try:
                    from contentflow.agents.learning_agent import optimize_content_strategy
                    update = optimize_content_strategy(project_id, db)
                    st.success("L2 分析完成")

                    if update.high_roi_keywords:
                        st.markdown("**高 ROI（建議加碼）**")
                        for k in update.high_roi_keywords:
                            st.markdown(f"- [{k.recommendation.upper()}] `{k.keyword}` "
                                        f"ROI={k.roi_score:.1f} 排名={k.avg_position:.0f}")

                    if update.low_roi_keywords:
                        st.markdown("**低 ROI（建議停止）**")
                        for k in update.low_roi_keywords:
                            st.markdown(f"- `{k.keyword}` ROI={k.roi_score:.2f} "
                                        f"排名={k.avg_position:.0f}")

                    if update.refresh_candidates:
                        st.markdown("**優先 Refresh 候選**")
                        for rc in update.refresh_candidates[:5]:
                            st.markdown(f"- 《{rc.article_title}》排名 {rc.current_rank:.0f} "
                                        f"— {rc.reason}")

                    st.info(f"📌 資源配置建議：{update.resource_advice}")
                except Exception as e:
                    st.error(f"L2 分析失敗：{e}")

    with col_kb:
        st.markdown("**同步向量庫**")
        st.caption("將知識條目嵌入並同步到 ChromaDB，供 Strategy Agent RAG 查詢")
        if st.button("🔄 同步 ChromaDB", use_container_width=True):
            with st.spinner("同步中..."):
                try:
                    from contentflow.tools.knowledge_base import sync_project_knowledge
                    synced = sync_project_knowledge(db, project_id)
                    st.success(f"已同步 {synced} 條知識到 ChromaDB")
                except Exception as e:
                    st.error(f"同步失敗：{e}")

    # 跨專案通用規則升級
    st.divider()
    st.subheader("升級通用規則")
    st.caption("掃描所有專案，若同一模式在 2+ 個專案中均已驗證，自動升級為通用規則")
    if st.button("🌐 執行跨專案升級"):
        with st.spinner("掃描中..."):
            try:
                from contentflow.agents.learning_agent import upgrade_cross_project_entries
                upgraded = upgrade_cross_project_entries(db)
                st.success(f"升級了 {upgraded} 條條目為通用規則")
            except Exception as e:
                st.error(f"升級失敗：{e}")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3: 人工覆核歷史
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("📜 人工覆核歷史 (Audit Log)")

    # 取得該專案所有 entry_id
    entry_ids = [e.id for e in all_entries]
    if not entry_ids:
        st.info("本專案尚無知識條目。")
    else:
        audit_logs = (
            db.query(KnowledgeAuditLog)
            .filter(KnowledgeAuditLog.entry_id.in_(entry_ids))
            .order_by(KnowledgeAuditLog.created_at.desc())
            .limit(100)
            .all()
        )

        if not audit_logs:
            st.info("尚無人工操作紀錄。")
        else:
            entry_id_to_pattern = {e.id: e.pattern[:60] for e in all_entries}
            action_labels = {
                "deactivate": "🚫 停用",
                "reactivate": "▶️ 重新啟用",
                "override": "⚠️ 人工推翻",
                "note": "📝 備註",
            }
            rows = []
            for log in audit_logs:
                rows.append({
                    "時間": log.created_at.strftime("%Y-%m-%d %H:%M") if log.created_at else "",
                    "操作": action_labels.get(log.action, log.action),
                    "知識條目": entry_id_to_pattern.get(log.entry_id, f"#{log.entry_id}"),
                    "理由": log.reason or "",
                    "操作者": log.operator,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # CSV 匯出
            csv_audit = pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")
            st.download_button("⬇️ 匯出 Audit Log", data=csv_audit,
                               file_name="knowledge_audit_log.csv", mime="text/csv")
