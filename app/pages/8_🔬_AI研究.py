"""🔬 AI 產文中心 — 研究 → 寫文 → 查核，一站完成"""

import asyncio
import json
import re
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
from contentflow.models.database import Article, ContentCalendar, Keyword
from contentflow.models.schemas import ResearchReport

init_db()
st.set_page_config(page_title="AI 產文中心 | ContentFlow", page_icon="🔬", layout="wide")
st.title("🔬 AI 產文中心")
st.caption("選題 → 研究 → 寫文 → 查核，全流程一鍵完成（GPT-4o-mini 低成本）")

from project_selector import get_current_project_id
project_id = get_current_project_id()

# ── 步驟進度條 ──
_c1, _c2, _c3, _c4, _c5 = st.columns(5)
with _c1:
    st.markdown("""
    <div style='text-align:center; padding:10px; background:#1a6fe8; border-radius:8px; color:white;'>
    <b>① 選題研究</b><br/><small>PubMed + SERP</small>
    </div>
    """, unsafe_allow_html=True)
with _c2:
    st.markdown("""
    <div style='text-align:center; padding:10px; background:#6366f1; border-radius:8px; color:white;'>
    <b>② AI 策略</b><br/><small>意圖 + 架構 + FAQ</small>
    </div>
    """, unsafe_allow_html=True)
with _c3:
    st.markdown("""
    <div style='text-align:center; padding:10px; background:#e8a21a; border-radius:8px; color:white;'>
    <b>③ AI 寫文</b><br/><small>GPT-4o-mini 產文</small>
    </div>
    """, unsafe_allow_html=True)
with _c4:
    st.markdown("""
    <div style='text-align:center; padding:10px; background:#27ae60; border-radius:8px; color:white;'>
    <b>④ 事實查核</b><br/><small>法規合規驗證</small>
    </div>
    """, unsafe_allow_html=True)
with _c5:
    st.markdown("""
    <div style='text-align:center; padding:10px; background:#8e44ad; border-radius:8px; color:white;'>
    <b>⑤ 取得成果</b><br/><small>下載 / 複製全文</small>
    </div>
    """, unsafe_allow_html=True)
st.markdown("")

session = get_db()

try:
    # ═══════════════════════════════════════════════════════════
    # TAB 分頁
    # ═══════════════════════════════════════════════════════════
    tab1, tab_strat, tab_write, tab_fc, tab_kw = st.tabs([
        "📝 選題研究", "🧠 AI 策略分析", "✍️ AI 寫文", "✅ 事實查核", "💡 推薦關鍵字"
    ])

    # ═══════════════════════════════════════════════════════════
    # TAB 1: 研究
    # ═══════════════════════════════════════════════════════════
    with tab1:
        st.subheader("📝 從文章規劃啟動研究")
        _art_q = session.query(Article).filter(Article.status.in_(["planned", "researching"])).filter(Article.seqno.isnot(None))
        if project_id:
            _art_q = _art_q.filter(Article.project_id == project_id)
        articles = _art_q.order_by(Article.seqno).all()

        if articles:
            options = {
                f"#{a.seqno or '?'} — {a.primary_keyword} (vol: {int(a.primary_keyword_volume)})": a.id
                for a in articles
            }
            selected = st.selectbox("選擇待研究的文章", list(options.keys()))
            article = session.get(Article, options[selected])

            if article:
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**主關鍵字：** {article.primary_keyword}")
                    st.markdown(f"**標題：** {article.title or '(未命名)'}")
                with col2:
                    if article.secondary_keywords:
                        st.markdown(f"**副關鍵字：** {article.secondary_keywords[:100]}")
                    st.markdown(f"**狀態：** {article.status}")

                if st.button("🚀 啟動 AI 研究", key="research_article"):
                    with st.spinner("研究中...（PubMed + Google SERP + 關鍵字分析）"):
                        try:
                            from contentflow.agents.research_agent import run_research_agent

                            title = article.title or article.primary_keyword
                            ingredients = [kw.strip() for kw in (article.secondary_keywords or "").split(",") if kw.strip()][:3]

                            report = asyncio.run(run_research_agent(
                                article_title=title,
                                search_keywords=ingredients or [article.primary_keyword],
                            ))

                            article.status = "researching"
                            article.research_report_json = report.model_dump_json(indent=2)
                            session.commit()

                            pubmed_count = sum(len(r.articles) for r in report.pubmed_results)
                            st.success(f"研究完成！{pubmed_count} 篇 PubMed 文獻、{len(report.suggested_keywords)} 組推薦關鍵字")

                            with st.expander("📋 查看研究報告", expanded=True):
                                st.json(json.loads(report.model_dump_json()))

                        except Exception as e:
                            st.error(f"研究失敗: {e}")
        else:
            st.info("目前沒有待研究的文章。請先在「文章管理」頁新增文章。")

        st.divider()

        # 內容日曆
        st.subheader("📅 從內容日曆啟動研究")
        _cal_q = session.query(ContentCalendar).filter(ContentCalendar.status == "planned")
        if project_id:
            _cal_q = _cal_q.filter(ContentCalendar.project_id == project_id)
        calendars = _cal_q.order_by(ContentCalendar.month, ContentCalendar.week).limit(20).all()
        if calendars:
            cal_options = {
                f"M{c.month}W{c.week} [{c.article_type}] {c.title[:40]}": c.id
                for c in calendars
            }
            cal_selected = st.selectbox("選擇排程文章", list(cal_options.keys()))
            cal_entry = session.get(ContentCalendar, cal_options[cal_selected])

            if cal_entry:
                st.markdown(f"**標題：** {cal_entry.title}")
                st.markdown(f"**關鍵字：** {cal_entry.keywords} | **架構：** {cal_entry.writing_architecture}")

                if st.button("🚀 啟動日曆文章研究", key="research_calendar"):
                    with st.spinner("研究中..."):
                        try:
                            from contentflow.agents.research_agent import run_research_agent

                            kw_list = [kw.strip() for kw in (cal_entry.keywords or "").split("、") if kw.strip()]
                            report = asyncio.run(run_research_agent(
                                article_title=cal_entry.title,
                                search_keywords=kw_list[:6] or [cal_entry.title[:10]],
                            ))

                            # 建立或取出對應的 Article
                            existing = session.query(Article).filter(
                                Article.title == cal_entry.title,
                                Article.project_id == project_id,
                            ).first()
                            if existing:
                                art = existing
                            else:
                                art = Article(
                                    title=cal_entry.title,
                                    primary_keyword=(kw_list[0] if kw_list else cal_entry.title[:10]),
                                    status="researching",
                                    project_id=project_id,
                                )
                                session.add(art)

                            art.status = "researching"
                            art.research_report_json = report.model_dump_json(indent=2)
                            cal_entry.status = "researching"
                            session.flush()
                            cal_entry.article_id = art.id
                            session.commit()

                            st.success("研究完成！已存入文章庫，可到「AI 寫文」Tab 繼續產文。")
                            with st.expander("📋 查看研究報告"):
                                st.json(json.loads(report.model_dump_json()))
                        except Exception as e:
                            st.error(f"研究失敗: {e}")

        st.divider()

        # 自訂研究
        st.subheader("🔧 自訂研究")
        with st.form("custom_research"):
            custom_title = st.text_input("研究標題", "")
            custom_ingredients = st.text_input("研究關鍵字（逗號分隔）", "")
            custom_conditions = st.text_input("補充關鍵字（逗號分隔，可留空）", "")

            if st.form_submit_button("🚀 執行自訂研究"):
                if custom_title:
                    with st.spinner("研究中..."):
                        try:
                            from contentflow.agents.research_agent import run_research_agent

                            ingredients = [k.strip() for k in custom_ingredients.split(",") if k.strip()]
                            conditions = [k.strip() for k in custom_conditions.split(",") if k.strip()]

                            report = asyncio.run(run_research_agent(
                                article_title=custom_title,
                                search_keywords=ingredients + conditions,
                            ))

                            st.success("研究完成！")
                            with st.expander("📋 查看研究報告", expanded=True):
                                st.json(json.loads(report.model_dump_json()))
                        except Exception as e:
                            st.error(f"研究失敗: {e}")
                else:
                    st.warning("請輸入研究標題")

    # ═══════════════════════════════════════════════════════════
    # TAB: AI 寫文
    # ═══════════════════════════════════════════════════════════
    with tab_write:
        st.subheader("✍️ 從研究報告生成 SEO 文章")
        st.info("💰 使用 GPT-4o-mini，每篇約 NT 1 到 2 元（0.02 至 0.05 USD）")

        # 找已有研究報告的文章
        _res_q = session.query(Article).filter(Article.research_report_json != "").filter(Article.research_report_json.isnot(None))
        if project_id:
            _res_q = _res_q.filter(Article.project_id == project_id)
        researched = _res_q.order_by(Article.seqno).all()

        if researched:
            write_options = {
                f"#{a.seqno or '?'} — {a.primary_keyword} [{a.status}]": a.id
                for a in researched
            }
            write_selected = st.selectbox("選擇有研究報告的文章", list(write_options.keys()), key="write_select")
            write_article = session.get(Article, write_options[write_selected])

            if write_article:
                st.markdown(f"**主關鍵字：** {write_article.primary_keyword}")
                st.markdown(f"**現有狀態：** {write_article.status}")

                # 載入 SEO 策略指引
                strategy_context = None
                cal_entry = write_article.calendar_entry
                if not cal_entry:
                    # fallback: 依關鍵字搜尋 calendar 的 title 或 keywords
                    kw = write_article.primary_keyword or ""
                    if kw:
                        cal_entry = (
                            session.query(ContentCalendar)
                            .filter(ContentCalendar.project_id == project_id)
                            .filter(
                                (ContentCalendar.title.contains(kw)) |
                                (ContentCalendar.keywords.contains(kw))
                            )
                            .first()
                        )
                    if not cal_entry and len(kw) > 3:
                        core = kw[1:-1]
                        cal_entry = (
                            session.query(ContentCalendar)
                            .filter(ContentCalendar.project_id == project_id)
                            .filter(
                                (ContentCalendar.title.contains(core)) |
                                (ContentCalendar.keywords.contains(core))
                            )
                            .first()
                        )
                    if not cal_entry and len(kw) >= 4:
                        import re as _re
                        core2 = _re.sub(r'^(長|膝蓋|右|左)', '', kw)
                        core2 = _re.sub(r'(怎麼辦|原因|症狀|可以|不能|會好嗎)$', '', core2)
                        if core2 and core2 != kw:
                            cal_entry = (
                                session.query(ContentCalendar)
                                .filter(ContentCalendar.project_id == project_id)
                                .filter(
                                    (ContentCalendar.title.contains(core2)) |
                                    (ContentCalendar.keywords.contains(core2))
                                )
                                .first()
                            )
                if cal_entry:
                    _sc = {}
                    if cal_entry.search_intent:
                        _sc["search_intent"] = cal_entry.search_intent
                    if cal_entry.target_audience:
                        _sc["target_audience"] = cal_entry.target_audience
                    if cal_entry.writing_architecture:
                        _sc["writing_architecture"] = cal_entry.writing_architecture
                    if cal_entry.faq_questions:
                        _sc["faq_questions"] = cal_entry.faq_questions
                    if _sc:
                        strategy_context = _sc

                if strategy_context:
                    with st.expander("📋 SEO 策略指引（來自 SEO 專員）", expanded=False):
                        for k, v in strategy_context.items():
                            labels = {
                                "search_intent": "搜尋意圖",
                                "target_audience": "讀者切入點（痛點）",
                                "writing_architecture": "架構策略",
                                "faq_questions": "建議 FAQ",
                            }
                            st.markdown(f"**{labels.get(k, k)}：** {v}")

                # 如果 Tab 5 有產生 AI 策略，優先使用
                _applied = st.session_state.get("applied_strategy")
                if _applied and not strategy_context:
                    strategy_context = _applied
                    st.info("🧠 已套用 AI 策略分析結果（來自「AI 策略分析」Tab）")

                if write_article.draft_content:
                    st.warning("⚠️ 此文章已有草稿。重新生成會覆蓋現有內容。")

                col_w1, col_w2 = st.columns(2)
                with col_w1:
                    word_count = st.slider("目標字數", 1200, 3000, 1800, 100, key="word_count")
                with col_w2:
                    arch = st.selectbox(
                        "寫作架構",
                        ["自動選擇", "倒三角架構", "金字塔架構 (SCQA)", "思維流程型", "敘事型"],
                        key="arch_select"
                    )
                    arch_value = "" if arch == "自動選擇" else arch

                if st.button("✍️ 開始 AI 寫文", key="start_writing", type="primary"):
                    try:
                        report = ResearchReport.model_validate_json(write_article.research_report_json)
                    except Exception:
                        st.error("研究報告格式錯誤，請重新執行研究")
                        st.stop()

                    progress = st.progress(0, text="載入品牌知識...")

                    try:
                        from contentflow.agents.writing_agent import run_writing_agent
                        from contentflow.agents.seo_check_agent import run_seo_check_agent
                        from contentflow.agents.seo_qa_agent import run_seo_qa_agent

                        progress.progress(10, text="Step 1/4 — 生成大綱...")

                        draft = asyncio.run(run_writing_agent(
                            report=report,
                            target_word_count=word_count,
                            writing_architecture=arch_value,
                            strategy_context=strategy_context,
                            project_id=project_id,
                        ))

                        progress.progress(60, text="Step 2/5 — 文章生成完成...")
                        progress.progress(65, text="Step 3/5 — SEO 初檢...")

                        secondary_kwds = [
                            part.strip() for part in re.split(r'[,，\n]+', write_article.secondary_keywords or "") if part.strip()
                        ]

                        # SEO 初檢 → 找出失敗項目 → 定向修正 → 複檢
                        pre_seo = run_seo_check_agent(
                            draft=draft,
                            primary_keyword=write_article.primary_keyword or "",
                            secondary_keywords=secondary_kwds,
                        )
                        failed_checks = [c for c in pre_seo["checks"] if not c["passed"]]

                        progress.progress(75, text=f"Step 4/5 — SEO QA 定向修正（{len(failed_checks)} 項待修）...")

                        draft = asyncio.run(run_seo_qa_agent(
                            draft=draft,
                            report=report,
                            primary_keyword=write_article.primary_keyword or "",
                            secondary_keywords=secondary_kwds,
                            failed_checks=failed_checks,
                            project_id=project_id,
                        ))
                        seo_report = run_seo_check_agent(
                            draft=draft,
                            primary_keyword=write_article.primary_keyword or "",
                            secondary_keywords=secondary_kwds,
                        )
                        progress.progress(90, text="Step 5/5 — 儲存文章草稿...")

                        # 儲存到 DB
                        write_article.status = "writing"
                        write_article.title = draft.title
                        write_article.draft_content = draft.content_markdown
                        write_article.slug = draft.slug or ""
                        write_article.meta_title = draft.meta_title or ""
                        write_article.meta_description = draft.meta_description or ""
                        write_article.faq_schema_json = draft.faq_schema_json or ""
                        write_article.article_schema_json = draft.article_schema_json or ""
                        write_article.seo_score = seo_report.get("score")
                        session.commit()

                        progress.progress(100, text="完成！")
                        st.success(f"文章生成完成！「{draft.title}」— {draft.word_count} 字")

                        # ── Meta 資訊 ──────────────────────────────
                        col_m1, col_m2 = st.columns([1, 2])
                        with col_m1:
                            st.markdown(f"**URL Slug：** `{draft.slug or '(未生成)'}`")
                        with col_m2:
                            st.markdown(f"**Meta Title：** {draft.meta_title}")
                        st.markdown(f"**Meta Description：** {draft.meta_description}")

                        st.divider()
                        st.subheader("SEO 檢查")
                        score = seo_report["score"]
                        if score >= 85:
                            st.success(f"SEO 分數：{score} 分（{seo_report['passed_count']}/{seo_report['total_count']}）")
                        elif score >= 70:
                            st.warning(f"SEO 分數：{score} 分（{seo_report['passed_count']}/{seo_report['total_count']}）")
                        else:
                            st.error(f"SEO 分數：{score} 分（{seo_report['passed_count']}/{seo_report['total_count']}）")

                        _new_rule_labels = {
                            "keyword_density_ok": "關鍵字密度",
                            "h2_has_primary_keyword": "H2 含主關鍵字",
                        }
                        for check in seo_report["checks"]:
                            _label = _new_rule_labels.get(check["name"], "")
                            _badge = f" 🆕{_label}" if _label else ""
                            if check["passed"]:
                                st.markdown(f"- ✅{_badge} {check['detail']}")
                            else:
                                st.markdown(f"- ⚠️{_badge} {check['detail']}")

                        # ── FAQ JSON-LD ────────────────────────────
                        if draft.faq_schema_json:
                            st.divider()
                            _faq_data = json.loads(draft.faq_schema_json)
                            _faq_count = len(_faq_data.get("mainEntity", []))
                            with st.expander(f"🏷️ FAQ Structured Data（{_faq_count} 個問答）— 貼入 CMS `<head>`", expanded=False):
                                st.caption("複製下方 JSON-LD，貼入 WordPress SEO 外掛的「Schema/Head」欄位，即可在 Google 出現 FAQ Rich Result。")
                                _schema_tag = f'<script type="application/ld+json">\n{draft.faq_schema_json}\n</script>'
                                st.code(_schema_tag, language="html")
                                st.download_button(
                                    "💾 下載 FAQ Schema",
                                    data=_schema_tag,
                                    file_name=f"{draft.slug or 'faq'}_schema.html",
                                    mime="text/html",
                                    use_container_width=True,
                                )
                        else:
                            st.info("💡 FAQ JSON-LD：文章完成後若偵測到 FAQ 段落，這裡會顯示可直接貼入 CMS 的結構化資料。")

                        st.divider()

                        # 顯示文章內容
                        st.subheader("📄 文章預覽")
                        st.markdown(draft.content_markdown)

                        # 下載按鈕
                        _md_frontmatter = f"""---
title: {draft.title}
slug: {draft.slug or ''}
meta_title: {draft.meta_title}
meta_description: {draft.meta_description}
---

{draft.content_markdown}
"""
                        st.download_button(
                            "💾 下載 Markdown（含 frontmatter）",
                            data=_md_frontmatter,
                            file_name=f"{draft.slug or draft.title}.md",
                            mime="text/markdown",
                        )

                    except Exception as e:
                        progress.empty()
                        st.error(f"寫文失敗: {e}")
                        import traceback
                        st.code(traceback.format_exc())

                # 如果已有草稿，顯示它
                if write_article.draft_content and not st.session_state.get("_writing"):
                    st.divider()
                    st.subheader("📄 現有草稿")
                    st.markdown(write_article.draft_content)
        else:
            st.warning("目前沒有已完成研究的文章。請先到「選題研究」Tab 執行研究。")

    # ═══════════════════════════════════════════════════════════
    # TAB: 事實查核
    # ═══════════════════════════════════════════════════════════
    with tab_fc:
        st.subheader("✅ 事實查核 & 法規合規")
        st.info("💰 使用 GPT-4o-mini，每次約 NT 0.2 元（0.005 USD）")

        # 找有草稿的文章
        _dft_q = session.query(Article).filter(Article.draft_content != "").filter(Article.draft_content.isnot(None))
        if project_id:
            _dft_q = _dft_q.filter(Article.project_id == project_id)
        drafted = _dft_q.order_by(Article.seqno).all()

        if drafted:
            fc_options = {
                f"#{a.seqno or '?'} — {a.title or a.primary_keyword} [{a.status}]": a.id
                for a in drafted
            }
            fc_selected = st.selectbox("選擇待查核的文章", list(fc_options.keys()), key="fc_select")
            fc_article = session.get(Article, fc_options[fc_selected])

            if fc_article:
                st.markdown(f"**標題：** {fc_article.title}")
                st.markdown(f"**字數：** {len(fc_article.draft_content)} 字")

                if st.button("🔍 啟動事實查核", key="start_factcheck", type="primary"):
                    with st.spinner("查核中...（比對 PubMed 文獻 + 法規用詞）"):
                        try:
                            from contentflow.agents.factcheck_agent import run_factcheck_agent
                            from contentflow.agents.writing_agent import _get_client
                            from contentflow.models.schemas import ArticleDraft, ArticleStatus

                            # 建立 draft 物件
                            draft = ArticleDraft(
                                title=fc_article.title or fc_article.primary_keyword,
                                content_markdown=fc_article.draft_content,
                                word_count=len(fc_article.draft_content),
                                status=ArticleStatus.WRITING,
                            )

                            # 載入研究報告
                            report = None
                            if fc_article.research_report_json:
                                try:
                                    report = ResearchReport.model_validate_json(fc_article.research_report_json)
                                except Exception:
                                    pass

                            if not report:
                                report = ResearchReport(article_title=fc_article.title or "", keywords=[fc_article.primary_keyword])

                            # 執行查核
                            checked_draft = asyncio.run(run_factcheck_agent(draft, report, project_id=project_id))

                            # 顯示結果
                            st.success(f"查核完成！{len(checked_draft.fact_check_items)} 項檢查結果")

                            if checked_draft.fact_check_items:
                                needs_review = [i for i in checked_draft.fact_check_items if i.needs_review]
                                safe_items = [i for i in checked_draft.fact_check_items if not i.needs_review]

                                if needs_review:
                                    st.error(f"⚠️ {len(needs_review)} 項需要人工審核")
                                    for item in needs_review:
                                        with st.expander(f"🔴 {item.claim[:80]}", expanded=True):
                                            st.markdown(f"**信心度：** {item.confidence.value}")
                                            if item.supporting_evidence:
                                                st.markdown(f"**證據：** {', '.join(item.supporting_evidence)}")
                                            st.markdown(f"**建議：** {item.reviewer_note}")

                                if safe_items:
                                    st.success(f"✅ {len(safe_items)} 項通過查核")
                                    for item in safe_items:
                                        with st.expander(f"🟢 {item.claim[:80]}"):
                                            st.markdown(f"**信心度：** {item.confidence.value}")
                                            if item.supporting_evidence:
                                                st.markdown(f"**證據：** {', '.join(item.supporting_evidence)}")

                                # 更新狀態（將 Pydantic 狀態映射到 DB 狀態）
                                _status_map = {"review_required": "reviewing", "approved": "reviewing"}
                                fc_article.status = _status_map.get(checked_draft.status.value, "reviewing")
                                session.commit()

                                # ── 取得成果區塊 ──
                                st.divider()
                                st.subheader("④ 取得成果")

                                # 內部連結建議（查詢已發布文章）
                                try:
                                    from contentflow.agents.seo_check_agent import suggest_internal_links
                                    from contentflow.models.database import Article as _ArticleModel
                                    _published_q = session.query(_ArticleModel).filter(
                                        _ArticleModel.project_id == project_id,
                                        _ArticleModel.status == "published",
                                        _ArticleModel.publish_url.isnot(None),
                                        _ArticleModel.publish_url != "",
                                    ).all()
                                    _il_data = [
                                        {
                                            "title": a.title, "url": a.publish_url,
                                            "primary_keyword": a.primary_keyword or "",
                                            "secondary_keywords": a.secondary_keywords or "",
                                        }
                                        for a in _published_q
                                    ]
                                    _il_suggestions = suggest_internal_links(
                                        fc_article.draft_content,
                                        fc_article.primary_keyword or "",
                                        _il_data,
                                    )
                                    if _il_suggestions:
                                        with st.expander(f"🔗 內部連結建議（{len(_il_suggestions)} 條）", expanded=True):
                                            st.caption("在文章中為以下錨文字加上超連結，有助於 Topical Authority。")
                                            for _il in _il_suggestions:
                                                st.markdown(
                                                    f"- **錨文字：**「{_il['anchor_text']}」 → "
                                                    f"[{_il['target_title']}]({_il['target_url']})"
                                                )
                                    else:
                                        st.info("🔗 內部連結：尚無已發布文章可配對（文章發布後即可自動配對）。")
                                except Exception:
                                    pass

                                col_out1, col_out2 = st.columns(2)
                                with col_out1:
                                    st.download_button(
                                        "💾 下載 Markdown",
                                        data=fc_article.draft_content,
                                        file_name=f"{fc_article.title or 'article'}.md",
                                        mime="text/markdown",
                                        use_container_width=True,
                                    )
                                with col_out2:
                                    if st.button("📋 複製全文到剪貼簿", use_container_width=True, key="copy_btn"):
                                        st.session_state["show_copybox"] = True

                                if st.session_state.get("show_copybox"):
                                    st.text_area(
                                        "全文內容（請全選 Ctrl+A 後 Ctrl+C）",
                                        value=fc_article.draft_content,
                                        height=300,
                                        key="copy_content",
                                    )
                            else:
                                st.success("✅ 沒有發現任何問題！")

                        except Exception as e:
                            st.error(f"查核失敗: {e}")
                            import traceback
                            st.code(traceback.format_exc())
        else:
            st.warning("目前沒有待查核的文章草稿。請先到「AI 寫文」Tab 生成文章。")

    # ═══════════════════════════════════════════════════════════
    # TAB: 推薦關鍵字
    # ═══════════════════════════════════════════════════════════
    with tab_kw:
        st.subheader("💡 高價值切入關鍵字")
        st.markdown("**篩選條件：低 SEO 難度 + 高搜尋量 = 最佳切入點**")

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            max_difficulty = st.slider("最高 SEO 難度", 5, 50, 25, key="rec_diff")
        with col_r2:
            min_volume = st.number_input("最低搜尋量", 50, 10000, 200, 50, key="rec_vol")

        _kw_q = session.query(Keyword).filter(Keyword.seo_difficulty <= max_difficulty).filter(Keyword.search_volume >= min_volume)
        if project_id:
            _kw_q = _kw_q.filter(Keyword.project_id == project_id)
        recommended = _kw_q.order_by(Keyword.search_volume.desc()).limit(20).all()
        if recommended:
            df_rec = pd.DataFrame([
                {
                    "關鍵字": kw.keyword,
                    "搜尋量": int(kw.search_volume),
                    "SEO 難度": int(kw.seo_difficulty),
                    "CPC": f"${kw.cpc:.2f}",
                    "優先": "⭐" if not kw.priority else ("🟡" if kw.priority == "green_x" else "⬇️"),
                }
                for kw in recommended
            ])
            st.dataframe(df_rec, use_container_width=True, hide_index=True)
            st.metric("符合條件", f"{len(recommended)} 組關鍵字")
        else:
            st.info("沒有符合條件的關鍵字，請調整篩選條件。")

    # ═══════════════════════════════════════════════════════════
    # TAB: AI 策略分析
    # ═══════════════════════════════════════════════════════════
    with tab_strat:
        st.subheader("🧠 AI 策略分析")
        st.caption("自動分析關鍵字的搜尋意圖、讀者痛點、文章架構、FAQ 建議 — 取代 SEO 專員的策略規劃")

        _strat_mode = st.radio(
            "分析來源",
            ["從已有研究的文章", "手動輸入關鍵字"],
            horizontal=True,
            key="strat_mode",
        )

        _strat_keyword = ""
        _strat_secondary = []
        _strat_serp = None
        _strat_paa = []
        _strat_article = None

        if _strat_mode == "從已有研究的文章":
            _sa_q = session.query(Article).filter(Article.research_report_json != "").filter(Article.research_report_json.isnot(None))
            if project_id:
                _sa_q = _sa_q.filter(Article.project_id == project_id)
            strat_articles = _sa_q.order_by(Article.seqno).all()
            if strat_articles:
                strat_options = {
                    f"#{a.seqno or '?'} — {a.primary_keyword} [{a.status}]": a.id
                    for a in strat_articles
                }
                strat_selected = st.selectbox("選擇文章", list(strat_options.keys()), key="strat_article_select")
                _strat_article = session.get(Article, strat_options[strat_selected])
                if _strat_article:
                    _strat_keyword = _strat_article.primary_keyword or ""
                    _strat_secondary = [
                        kw.strip() for kw in re.split(r'[,，\n]+', _strat_article.secondary_keywords or "") if kw.strip()
                    ]
                    # 嘗試從研究報告載入 SERP + PAA
                    try:
                        _report = ResearchReport.model_validate_json(_strat_article.research_report_json)
                        _strat_serp = _report.serp_analysis
                        _strat_paa = _report.paa_questions or []
                    except Exception:
                        pass
                    st.markdown(f"**主關鍵字：** `{_strat_keyword}`")
                    if _strat_secondary:
                        st.markdown(f"**副關鍵字：** {', '.join(_strat_secondary[:5])}")
                    if _strat_serp:
                        st.markdown(f"**SERP 資料：** {len(_strat_serp.top_results)} 筆競品 ✅ （免重新查詢）")
            else:
                st.info("目前沒有已完成研究的文章。請先到「選題研究」Tab 執行研究，或手動輸入關鍵字。")
        else:
            _strat_keyword = st.text_input("主關鍵字", placeholder="例如：右腳底板麻", key="strat_kw_input")
            _strat_secondary_raw = st.text_input("副關鍵字（逗號分隔，可留空）", placeholder="例如：腳底麻原因, 腳底發麻看什麼科", key="strat_sec_input")
            _strat_secondary = [kw.strip() for kw in _strat_secondary_raw.split(",") if kw.strip()] if _strat_secondary_raw else []

        # 先顯示既有的人工策略（如果有）
        if _strat_article:
            _existing_cal = _strat_article.calendar_entry
            if not _existing_cal:
                kw = _strat_article.primary_keyword or ""
                if kw:
                    _existing_cal = session.query(ContentCalendar).filter(
                        ContentCalendar.project_id == project_id,
                        (ContentCalendar.title.contains(kw)) | (ContentCalendar.keywords.contains(kw))
                    ).first()
            if _existing_cal and any([_existing_cal.search_intent, _existing_cal.target_audience, _existing_cal.writing_architecture]):
                with st.expander("📋 現有人工策略（來自 SEO 專員）", expanded=False):
                    if _existing_cal.search_intent:
                        st.markdown(f"**搜尋意圖：** {_existing_cal.search_intent}")
                    if _existing_cal.target_audience:
                        st.markdown(f"**讀者痛點：** {_existing_cal.target_audience}")
                    if _existing_cal.writing_architecture:
                        st.markdown(f"**架構策略：** {_existing_cal.writing_architecture}")
                    if _existing_cal.faq_questions:
                        st.markdown(f"**建議 FAQ：** {_existing_cal.faq_questions}")

        if st.button("🧠 啟動 AI 策略分析", key="run_strategy", type="primary", disabled=not _strat_keyword):
            with st.spinner(f"分析「{_strat_keyword}」的搜尋意圖與策略…（約 10~20 秒）"):
                try:
                    from contentflow.agents.strategy_agent import run_strategy_agent

                    strategy_report = asyncio.run(run_strategy_agent(
                        keyword=_strat_keyword,
                        secondary_keywords=_strat_secondary,
                        serp=_strat_serp,
                        paa_questions=_strat_paa,
                        project_id=project_id,
                    ))

                    st.session_state["last_strategy_report"] = strategy_report
                    st.success(f"策略分析完成！信心度：{strategy_report.confidence}")

                except Exception as e:
                    st.error(f"策略分析失敗: {e}")
                    import traceback
                    st.code(traceback.format_exc())

        # 顯示策略分析結果
        _sr = st.session_state.get("last_strategy_report")
        if _sr:
            st.divider()
            st.markdown("### 📊 策略分析報告")

            # 6 維度卡片顯示
            _dim_col1, _dim_col2 = st.columns(2)
            with _dim_col1:
                st.markdown(f"""
                <div style="background:#eff6ff; border-left:4px solid #2563eb; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#1e3a8a;">🎯 搜尋意圖</b><br/>
                    <span>{_sr.search_intent}</span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                <div style="background:#fef3c7; border-left:4px solid #d97706; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#92400e;">🏗️ 文章架構建議</b><br/>
                    <span>{_sr.writing_architecture}</span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                <div style="background:#fce7f3; border-left:4px solid #db2777; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#9d174d;">💡 內容角度</b><br/>
                    <span>{_sr.content_angle}</span>
                </div>
                """, unsafe_allow_html=True)

            with _dim_col2:
                st.markdown(f"""
                <div style="background:#f0fdf4; border-left:4px solid #16a34a; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#166534;">👤 目標讀者 / 痛點</b><br/>
                    <span>{_sr.target_audience}</span>
                </div>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                <div style="background:#faf5ff; border-left:4px solid #9333ea; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#581c87;">🔍 競品差異化</b><br/>
                    <span>{_sr.competitor_gap}</span>
                </div>
                """, unsafe_allow_html=True)

                # FAQ 區塊
                _faq_html = "<br/>".join(f"• {q}" for q in _sr.faq_questions) if _sr.faq_questions else "（無建議）"
                st.markdown(f"""
                <div style="background:#ecfdf5; border-left:4px solid #059669; padding:12px 16px; border-radius:6px; margin-bottom:12px;">
                    <b style="color:#065f46;">❓ FAQ 建議（{len(_sr.faq_questions)} 題）</b><br/>
                    <span>{_faq_html}</span>
                </div>
                """, unsafe_allow_html=True)

            # 信心度指標
            _conf_val = _sr.confidence if isinstance(_sr.confidence, (int, float)) else 0.5
            _conf_color = "#16a34a" if _conf_val >= 0.8 else "#d97706" if _conf_val >= 0.6 else "#dc2626"
            _conf_label = f"{_conf_val:.0%}" if isinstance(_sr.confidence, (int, float)) else str(_sr.confidence)
            st.markdown(f"""
            <div style="text-align:center; margin:16px 0;">
                <span style="background:{_conf_color}; color:white; padding:6px 16px; border-radius:20px; font-weight:bold;">
                    信心度：{_conf_label}
                </span>
            </div>
            """, unsafe_allow_html=True)

            # 操作按鈕區
            st.divider()
            _act_col1, _act_col2 = st.columns(2)
            with _act_col1:
                # 下載策略報告 JSON
                _display = _sr.to_display_dict()
                st.download_button(
                    "💾 下載策略報告 (JSON)",
                    data=json.dumps(_display, ensure_ascii=False, indent=2),
                    file_name=f"strategy_{_sr.keyword}.json",
                    mime="application/json",
                    use_container_width=True,
                )
            with _act_col2:
                if st.button("➡️ 套用至 AI 寫文", key="apply_strategy", use_container_width=True):
                    st.session_state["applied_strategy"] = _sr.to_strategy_context()
                    st.success("已儲存策略！請切換至「✍️ AI 寫文」Tab 使用。")

finally:
    session.close()
