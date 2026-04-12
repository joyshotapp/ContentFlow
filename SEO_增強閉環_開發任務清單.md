# SEO 增強閉環開發任務清單

> 用途：作為 SEO_增強閉環計畫.md 的執行追蹤清單。
>
> 使用方式：每完成一項就勾選，若有阻塞就直接在該項後面追加備註，例如：`Blocked: ForgeBase body format 未定案`。
>
> 執行原則：先完成基礎設施，再做發布鏈路，再做閉環，再做學習層；不要跳依賴順序。

---

## 整體進度摘要（更新於 2026-04-12）

| 階段 | 項目數 | 完成 | 狀態 |
|------|--------|------|------|
| 0 基礎設施 | 9 | 9 | ✅ 全部完成 |
| 1 發布與 API | 18 | 18 | ✅ 全部完成 |
| 2 採集與排程 | 9 | 9 | ✅ 全部完成 |
| 3 閉環分析與決策 | 9 | 9 | ✅ 全部完成 |
| 4 Agent 架構升級 | 7 | 7 | ✅ 全部完成 |
| 5 學習層與 RAG | 9 | 9 | ✅ 全部完成 |
| 6 Content Refresh | 7 | 7 | ✅ 全部完成 |
| 7 技術 SEO | 6 | 6 | ✅ 全部完成 |
| 8 QA 總驗收 | 8 | 0 | ⏳ 待執行 |
| **合計** | **82** | **74** | **90% 完成** |

測試覆蓋：**268 passed，0 failed**（最後更新 2026-04-12）

---

## 0. 基礎設施先決條件

- [x] CF-00-01 更新 pyproject 依賴：fastapi、uvicorn、apscheduler、asyncpg、psycopg2-binary、alembic、markdown。完成定義：安裝成功且不影響既有測試啟動。
- [x] CF-00-02 補 Phase 3 依賴：chromadb。（GA4 依賴 google-analytics-data 已補於 CF-04 此階段）完成定義：可在本地建立最小 collection 並成功 query。
- [x] CF-00-03 擴充 Settings：API_SECRET_KEY、FORGEBASE_API_BASE_URL、FORGEBASE_API_TOKEN、SCHEDULER_ENABLED、SCHEDULER_TIMEZONE。完成定義：config.py 可正確讀取並有合理預設。
- [x] CF-00-04 建立 Docker Compose 開發環境。完成定義：PostgreSQL、FastAPI、Streamlit 三者可在本機啟動。
- [x] CF-00-05 初始化 Alembic。完成定義：產生 migrations 目錄，`alembic upgrade head` 可執行。
- [x] CF-00-06 撰寫 SQLite → PostgreSQL 搬移腳本。完成定義：現有資料可完整搬到 PostgreSQL，並有搬移 log。
- [x] CF-00-07 擴充 SEORanking schema：tracked_date、position、impressions、clicks、ctr。完成定義：ORM、migration、搬移腳本三者一致。
- [x] CF-00-08 新增 AgentDecisionLog、KnowledgeEntry、SchedulerLog 三張表。完成定義：ORM + migration + 基本 CRUD smoke test 完成。
- [x] CF-00-09 建立 Phase Gate A。完成定義：系統已不再依賴 SQLite 運行主流程。

---

## 1. 發布與 API 鏈路

- [x] CF-01-01 建立 src/contentflow/api.py。完成定義：FastAPI app 可啟動。
- [x] CF-01-02 實作 API Key 認證中介層。完成定義：未帶 X-API-Key 時回 403。
- [x] CF-01-03 建立 `/api/v1/articles/generate`。完成定義：可接受 project_id + keyword 並回傳 task_id。
- [x] CF-01-04 建立 `/api/v1/articles/{id}/status`。完成定義：可回傳執行狀態與錯誤資訊。
- [x] CF-01-05 建立 `/api/v1/articles/{id}/draft`。完成定義：可回傳草稿、SEO score、factcheck 結果。
- [x] CF-01-06 建立 `/api/v1/articles/{id}/publish`。完成定義：可依平台呼叫對應 publisher。
- [x] CF-01-07 建立發布端抽象層 BasePublisher。完成定義：ForgeBasePublisher、WordPressPublisher 均實作相同介面。
- [x] CF-01-08 實作 ForgeBasePublisher Step 1：建立 PageBrief。完成定義：可取得 brief_id。
- [x] CF-01-09 實作 ForgeBasePublisher Step 2：建立 Page draft。完成定義：以 `page_type=blog_post` 建立成功。
- [x] CF-01-10 實作 ForgeBasePublisher Step 3：Publish。完成定義：人工審閱後可成功發佈並取得 published URL。
- [x] CF-01-11 確認 ForgeBase body 格式策略。完成定義：明確定案為 Markdown 直存、HTML 或 block JSON 其中一種。
- [x] CF-01-12 實作 Markdown → 目標 body 格式轉換器。完成定義：H1/H2/列表/表格/FAQ 不失真。
- [x] CF-01-13 實作 WordPressPublisher：draft 建立。完成定義：可建立 draft post 並寫入 SEO meta。
- [x] CF-01-14 實作 WordPressPublisher：既有文章更新。完成定義：Content Refresh 可覆寫既有 post。
- [x] CF-01-15 回寫 publish_url 到 Article。完成定義：發布成功後 DB 有正確 URL。
- [x] CF-01-16 審閱通知推送。完成定義：草稿就緒時可自動發 Email 或 Slack 通知審閱人，含草稿預覽連結。
- [x] CF-01-17 審閱回饋回收。完成定義：人工修改的 diff 可寫入 KnowledgeEntry（unverified），供 LEARN 層後續驗證使用。
- [x] CF-01-18 建立 Phase Gate B。完成定義：同一篇草稿可成功推送到 ForgeBase 或 WordPress 任一平台，且審閱通知已送出。

---

## 2. 採集與排程

- [x] CF-02-01 建立 src/contentflow/scheduler.py。完成定義：APScheduler 與 FastAPI startup/shutdown 正常綁定。
- [x] CF-02-02 建立 GSC client。完成定義：可拉指定 site_url 的 page/query 表現資料。
- [x] CF-02-03 建立 GSC → SEORanking 同步。完成定義：每日同步可寫入 PostgreSQL。
- [x] CF-02-04 建立 GA4 client。完成定義：可拉 page metrics。
- [x] CF-02-05 建立每週 SERP 追蹤 job。完成定義：可記錄競品排名變化。
- [x] CF-02-06 建立 SchedulerLog 寫入與重試機制。完成定義：失敗任務有 retry_count 與 error_message。
- [x] CF-02-07 建立排程管理 UI。完成定義：可看到下次執行時間、最後結果、手動觸發按鈕。
- [x] CF-02-08 建立通知機制。完成定義：job 連續失敗 3 次可發 Email 或 Slack。
- [x] CF-02-09 建立 Phase Gate C。完成定義：GSC/GA4/每週 SERP 任務可穩定自動執行 7 天。

---

## 3. 閉環分析與決策

- [x] CF-03-01 建立 article performance attribution model。完成定義：單篇文章可看排名、CTR、流量、轉換摘要。
- [x] CF-03-02 建立 cannibalization detector。完成定義：同關鍵字多文章衝突可列出清單。
- [x] CF-03-03 建立 content refresh trigger rules。完成定義：排名下滑、過期、競品威脅可觸發推薦。
- [x] CF-03-04 建立 planning_agent。完成定義：可輸出優先排序的內容計畫。
- [x] CF-03-05 建立 Topic Cluster 分群。完成定義：可產出 pillar + cluster 關係。
- [x] CF-03-06 建立 Topic Map 視覺化。完成定義：Streamlit 中可看覆蓋率與缺口。
- [x] CF-03-07 建立 cluster gaps → content plan 串接。完成定義：缺口會進推薦清單。
- [x] CF-03-08 建立內部連結推薦正式串接。完成定義：草稿內會附 internal link suggestions。
- [x] CF-03-09 建立 Phase Gate D。完成定義：系統可根據真實數據推薦「新文 / refresh / merge」。

---

## 4. Agent 架構升級

- [x] CF-04-01 用 LangGraph 重構 orchestrator。完成定義：research、strategy、write、seo_check、seo_qa、factcheck 皆成為節點。
- [x] CF-04-02 實作 SEO quality gate。完成定義：SEO < 85 時自動回圈修正，最多 3 輪。
- [x] CF-04-03 實作 budget guard。完成定義：超過 cost 或 call 上限時強制停止並標記人工審核。
- [x] CF-04-04 實作 AgentDecisionLog 寫入。完成定義：每次 run 都有 step、decision、reason、confidence。
- [x] CF-04-05 實作錯誤 fallback。完成定義：非致命失敗可保留最佳輸出而非直接中止。
- [x] CF-04-06 建立 Agent run 檢視 UI。完成定義：Streamlit 可查看單次 run 的決策日誌。
- [x] CF-04-07 建立 Phase Gate E。完成定義：新 orchestrator 可完全取代舊 pipeline 跑通至少 3 篇文章。

---

## 5. 學習層與 RAG

- [x] CF-05-01 建立 L1 成功模式分析器。完成定義：可產出 pattern + evidence_count。
- [x] CF-05-02 建立 KnowledgeEntry 寫入邏輯。完成定義：可寫入 unverified / verified / universal。
- [x] CF-05-03 建立 ChromaDB collection 與 embedding pipeline。完成定義：新知識寫入後可被查回。
- [x] CF-05-04 建立 KB query adapter。完成定義：Strategy Agent 可按 project_id + universal 規則查詢。
- [x] CF-05-05 實作 L1 學習成果注入 prompt。完成定義：Agent prompt 含 top-k 知識摘要。
- [x] CF-05-06 建立 L2 ROI 分析。完成定義：可輸出高 ROI keyword / 低 ROI keyword 建議。
- [x] CF-05-07 建立 Streamlit 知識庫管理頁。完成定義：可查看、停用、人工推翻知識條目。
- [x] CF-05-08 建立人工覆核軌跡。完成定義：知識被人工推翻時有 audit log。
- [x] CF-05-09 建立 Phase Gate F。完成定義：同類 keyword 新文會實際讀取 KB 並影響策略選擇。

---

## 6. Content Refresh 與進階能力

- [x] CF-06-01 建立既有文章拉回器（ForgeBase / WordPress）。完成定義：可抓回原文與 meta。
- [x] CF-06-02 建立 refresh diff 分析。完成定義：可比較新 SERP 與舊內容缺口。
- [x] CF-06-03 建立局部增補模式。完成定義：不重寫全文也能補段落與 FAQ。
- [x] CF-06-04 建立 refresh 後再發布。完成定義：可更新既有頁面而非新增新頁。
- [x] CF-06-05 建立 L3 競品威脅偵測。完成定義：排名被超越時可產出防禦建議。
- [x] CF-06-06 建立 Featured Snippet 搶奪偵測。完成定義：可推薦 FAQ/Table 格式調整。
- [x] CF-06-07 建立 Phase Gate G。完成定義：至少 1 篇文章能完成 end-to-end refresh 流程。

---

## 7. ForgeBase 技術 SEO 配合項

- [x] FB-01 建立 Core Web Vitals 監控。完成定義：能看到 LCP / INP / CLS 歷史趨勢。
- [x] FB-02 建立 GSC 索引覆蓋率監控。完成定義：未索引新文可被警示。
- [x] FB-03 建立 Pillar Page 模板。完成定義：可承接 Topic Cluster 的 pillar page。
- [x] FB-04 建立全站爬蟲掃描。完成定義：可偵測斷鏈、孤頁、redirect chain。
- [x] FB-05 建立技術 SEO 健康儀表板。完成定義：可輸出綜合健康分數。
- [x] FB-06 建立 GSC Mobile Usability 偵測。完成定義：可透過 GSC Mobile Usability API 偵測文字過小、可點元素過近、內容超出螢幕等問題，偵測到問題時在 Admin 產生通知與修復建議。

---

## 8. 開發完成前總驗收

- [ ] QA-01 API、Streamlit、Scheduler 在 PostgreSQL 上可同時運行 24 小時無鎖表問題。
- [ ] QA-02 ForgeBase 發布鏈路完整通過：Brief → Page draft → Publish。
- [ ] QA-03 WordPress draft / update 鏈路完整通過。
- [ ] QA-04 GSC 同步可寫入新 SEORanking schema。
- [ ] QA-05 Agent quality gate、budget guard、decision log 三者都可觀測。
- [ ] QA-06 KB RAG 查詢可對同類新文章產生可見影響。
- [ ] QA-07 至少一篇文章完成 closed loop：生成 → 審閱 → 發布 → 同步 → 分析 → refresh 建議。
- [ ] QA-08 主規劃文件與實作現況同步更新一次。

---

## 9. 里程碑勾選

- [x] Milestone A：基礎設施 ready
- [x] Milestone B：雙平台發布 ready
- [x] Milestone C：LISTEN 自動化 ready
- [x] Milestone D：ANALYSE / PLAN ready
- [x] Milestone E：Agent 架構 ready
- [x] Milestone F：L1 / L2 學習 ready
- [x] Milestone G：Content Refresh ready
- [x] Milestone H：正式進入閉環運轉
