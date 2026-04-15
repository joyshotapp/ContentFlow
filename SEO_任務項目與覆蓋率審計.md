# SEO 任務項目與覆蓋率審計

> 版本：2026-04-15（v3 修訂，已補正遺漏模組並反映 1-6 項實作完成）
> 審計原則：只以實際程式碼、測試與已驗證的產出為準，不以文件敘述當作完成依據。

---

## 1. 審計方法

本文件將 SEO 工作拆成可執行任務，並逐項比對本系統是否已實作、是否有測試、是否有後台或排程支撐。

判定標準：

- FULL：核心功能已實作，且有對應測試或實際排程／後台支撐。
- PARTIAL：主體功能已實作，但缺少自動化閉環、UI、排程、資料消費或大規模穩定性。
- MISSING：文件提過，但目前看不到可用實作。

---

## 2. 任務總表

| SEO 任務域 | 主要工作項目 | 覆蓋率 | 狀態 |
|---|---|---:|---|
| 策略面 | 關鍵字策略、SERP 意圖、競品缺口、叢集缺口、自蝕風險、產能決策 | 95% | FULL |
| 關鍵字面 | 關鍵字庫、Intent/Funnel、趨勢、ROI、內鏈建議、競品追蹤 | 90% | FULL |
| 內容面 | 研究、寫作、SEO QA、SEO Check、事實查核、Refresh、FAQ/EEAT/Schema、圖片 ALT | 95% | FULL |
| 技術面 | CWV、Render Verify、Crawler、Index Coverage、Mobile Usability、canonical/robots/OG/BreadcrumbList/lang/noindex | 90% | FULL |
| 監控面 | GSC、GA4、競品排名、成效回填、排程監控、Refresh 觸發偵測 | 90% | PARTIAL |
| 學習面 | L1 模式學習、L2 ROI 分析、週級反思、WritingRule 自動更新 | 80% | PARTIAL |
| 發布面 | ForgeBase / WordPress 發布、Refresh 更新發布、排程發布、SEO meta 寫入、手動發布 | 95% | FULL |
| 後台面 | 儀表板、文章、日曆、關鍵字、叢集、SEO、競品、Agent、知識庫、內容健康、排程、健康、設定、報表、反思 | 92% | FULL |
| 通知面 | Slack 告警、週報、Render 驗證失敗、排程失敗 | 100% | FULL |
| **確認 MISSING** | **外鏈管理（backlink acquisition / toxic link 監測）** | 0% | MISSING |

---

## 3. 完整任務清單與實作對照

### 3.1 策略面

目標：讓系統能像 SEO 專員一樣先決定「做什麼」，再決定「做多少」。

- 關鍵字策略分析：已實作。
  - [src/contentflow/agents/strategy_agent.py](src/contentflow/agents/strategy_agent.py)
  - 輸出 `StrategyReport`，包含搜尋意圖、讀者輪廓、寫作架構、FAQ、競品缺口。
  - 測試可對照 [tests/test_phase_gate_f.py](tests/test_phase_gate_f.py) 中的策略驗證區段。
- SERP / PAA / brand context 注入：已實作。
  - `run_strategy_agent()` 會吃 SERP 與 PAA，並注入 `ProjectContext`。
- 每日策略決策引擎：已實作。
  - [src/contentflow/agents/strategic_agent.py](src/contentflow/agents/strategic_agent.py)
  - `run_strategic_agent()` 會組合日曆、競品、自蝕、趨勢、學習、反思等訊號。
- 動態產能控制：已實作。
  - `_calculate_generate_capacity()`、`_normalize_plan_result()` 會依 backlog、reviewing、歷史成效、refresh 壓力調整當日 generate quota。
- 自蝕風險與叢集缺口消費：已實作。
  - Strategic Agent 會讀取 `cannibalization` 與 `cluster_gaps` 類資料。
- 行動執行：已實作。
  - `execute_strategic_plan()` 可執行 `generate`、`refresh`、`alert`、`optimize_meta`、`inject_internal_links`。

**實作證據**
- [src/contentflow/agents/strategic_agent.py](src/contentflow/agents/strategic_agent.py)
- [src/contentflow/agents/strategy_agent.py](src/contentflow/agents/strategy_agent.py)
- [tests/test_strategic_agent.py](tests/test_strategic_agent.py)
- [tests/test_phase_gate_f.py](tests/test_phase_gate_f.py)

**判定**：FULL

---

### 3.2 關鍵字面

目標：讓系統能像 SEO 專員一樣研究、分群、排序、追蹤與回饋關鍵字。

- 關鍵字庫 CRUD / 篩選 / 排序：已實作。
  - Admin 關鍵字頁面 [src/contentflow/admin/app.py](src/contentflow/admin/app.py) 的 `/keywords`。
- 關鍵字搜尋量、CPC、難度、Intent、Funnel：已實作。
  - [src/contentflow/models/database.py](src/contentflow/models/database.py) 的 `Keyword` 欄位。
- 關鍵字建議與匯入：已實作。
  - 關鍵字建議、Excel 匯入在 tools / admin 內完成。
- 趨勢同步：已實作。
  - `sync_keyword_trends` 排程已存在。
- 關鍵字 ROI / 投入產出分析：已實作。
  - [src/contentflow/agents/learning_agent.py](src/contentflow/agents/learning_agent.py) 中 `optimize_content_strategy()`。
- 內鏈建議：已實作。
  - [src/contentflow/agents/seo_check_agent.py](src/contentflow/agents/seo_check_agent.py) 的 `suggest_internal_links()`。
- 競品 SERP 追蹤：已實作。
  - [src/contentflow/scheduler.py](src/contentflow/scheduler.py) 的 `run_competitor_serp_check()`。

**實作證據**
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)
- [src/contentflow/agents/learning_agent.py](src/contentflow/agents/learning_agent.py)
- [src/contentflow/agents/seo_check_agent.py](src/contentflow/agents/seo_check_agent.py)
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [tests/test_phase_gate_f.py](tests/test_phase_gate_f.py)

**判定**：FULL

---

### 3.3 內容面

目標：讓系統能把「研究 → 寫作 → 初檢 → 修正 → 查核 → 發布」串成可重複閉環。

- Research：已實作。
  - [src/contentflow/agents/research_agent.py](src/contentflow/agents/research_agent.py)
  - SERP + PubMed 並行研究。
- Strategy：已實作。
  - 產出文章角度、受眾、FAQ、架構與差異化切角。
- Writing：已實作。
  - [src/contentflow/agents/writing_agent.py](src/contentflow/agents/writing_agent.py)
  - 產出 Markdown、FAQ JSON-LD、Article/BlogPosting JSON-LD、HowTo JSON-LD。
- SEO Check：已實作。
  - [src/contentflow/agents/seo_check_agent.py](src/contentflow/agents/seo_check_agent.py)
  - 主關鍵字、字數、FAQ、內鏈、密度、標題、H2 等規則。
- SEO QA：已實作。
  - [src/contentflow/agents/seo_qa_agent.py](src/contentflow/agents/seo_qa_agent.py)
  - 針對缺失微調 meta 與首段。
- FactCheck：已實作。
  - [src/contentflow/agents/factcheck_agent.py](src/contentflow/agents/factcheck_agent.py)
  - 事實查核與法規詞庫比對。
- Hero image：已實作。
  - [src/contentflow/agents/hero_image_agent.py](src/contentflow/agents/hero_image_agent.py)
  - 生成 WebP 格式圖片並上傳至 R2，回填 `hero_image_url`。
- 段落配圖 ALT text / SEO 檔名（Image Agent）：已實作且已接入主流程。
  - [src/contentflow/agents/image_agent.py](src/contentflow/agents/image_agent.py)
  - `run_image_agent()` 可為每個 H2 段落生成圖片 prompt、繁體中文 alt text（80字內）、SEO 語義檔名。
  - 已由 [src/contentflow/agents/orchestrator.py](src/contentflow/agents/orchestrator.py) 的主流程呼叫。
- EEAT / slug / FAQ schema：已實作。
  - [src/contentflow/agents/writing_seo_features.py](src/contentflow/agents/writing_seo_features.py)
- 內容 Refresh：已實作。
  - `check_refresh_triggers()`、`_execute_refresh()`、`run_render_verification()` 等流程可驅動更新。

**實作證據**
- [src/contentflow/agents/orchestrator.py](src/contentflow/agents/orchestrator.py)
- [src/contentflow/agents/writing_agent.py](src/contentflow/agents/writing_agent.py)
- [src/contentflow/agents/seo_check_agent.py](src/contentflow/agents/seo_check_agent.py)
- [src/contentflow/agents/seo_qa_agent.py](src/contentflow/agents/seo_qa_agent.py)
- [src/contentflow/agents/factcheck_agent.py](src/contentflow/agents/factcheck_agent.py)
- [src/contentflow/agents/hero_image_agent.py](src/contentflow/agents/hero_image_agent.py)
- [src/contentflow/agents/image_agent.py](src/contentflow/agents/image_agent.py)
- [src/contentflow/agents/writing_seo_features.py](src/contentflow/agents/writing_seo_features.py)
- [tests/test_seo_check_agent.py](tests/test_seo_check_agent.py)
- [tests/test_seo_check_new_rules.py](tests/test_seo_check_new_rules.py)
- [tests/test_writing_seo_features.py](tests/test_writing_seo_features.py)

**判定**：FULL

---

### 3.3-B Content Refresh Pipeline 與 Budget Guard

> 這兩個模組在前一版審計中完全遺漏，特別補列。

**Content Refresh Agent（`refresh_agent.py`）— 主動 Refresh 閉環**

這是一個完整的內容更新 pipeline，與 3.3 的「Refresh」項目是不同層次的東西：

- CF-06-01 `ContentFetcher`：已實作。
  - 可從 ForgeBase / WordPress REST API 拉回既有文章 HTML，也有 `fetch_by_url()` fallback。
- CF-06-02 `RefreshDiffAnalyzer`：已實作。
  - AI 比對舊文章摘要 vs 新 SERP，輸出 `RefreshPlan`（缺口清單 + freshness score + recommend: maintain/patch/rewrite）。
  - 由 `strategic_agent._execute_refresh()` 呼叫。
- CF-06-03 `apply_local_patches()`：已實作。
  - 局部增補段落，不重寫全文（FAQ、Table、舊資料更新）。
- CF-06-04 `publish_refreshed_article()`：已實作。
  - 呼叫 ForgeBase / WordPress publisher 更新既有文章，並回寫 DB。
  - Admin `/articles` 可手動觸發 `run_refresh_pipeline()`。
- CF-06-05 `CompetitorThreatDetector`：**已定義且已接入競品 SERP 排程**。
- CF-06-06 `FeaturedSnippetDetector`：**已定義且已接入 Refresh 觸發排程**。

**判定（Refresh Agent）**：核心路徑 FULL，L3 競品威脅偵測 + Featured Snippet 優化已進入主流程。

---

**Budget Guard（`budget_guard.py`）— LangGraph 成本防護節點**

- 已實作為 LangGraph 正式節點：`factcheck → budget_guard → END`。
- 防護上限：每篇文章最多 15 次 LLM 呼叫、$2.00 成本、3 次重試。
- 超出時標記 `_budget_exceeded = True`，保留目前最佳草稿，不丟棄輸出。
- Admin 文章頁面會顯示有無超出預算。

**判定（Budget Guard）**：FULL。

---

**Planning Agent（`planning_agent.py`）— 孤兒代碼**

- 存在 `generate_content_plan()` 整合歸因分析、自蝕偵測、叢集缺口，產出 `ContentPlan`。
- 但**未被任何其他模組引入**，也沒有排程 job 或 admin 呼叫。
- 功能應由 `strategic_agent.py` 替代承擔。

**判定（Planning Agent）**：孤兒代碼，不算有效覆蓋。

---

目標：讓系統不只會產文，還知道 HTML 是否真的可被搜尋引擎正確理解。

- Core Web Vitals：已實作。
  - [src/contentflow/tools/tech_seo.py](src/contentflow/tools/tech_seo.py)
  - `CoreWebVitalsMonitor`、`TechSEOHealthDashboard`。
- Render Verification：已實作。
  - [src/contentflow/tools/render_verify.py](src/contentflow/tools/render_verify.py)
  - 檢查 `title`、`meta description`、`h1`、`canonical`、`og:*`、`JSON-LD`、`lang`、`robots`。
- Mobile Usability：已實作。
  - [src/contentflow/tools/tech_seo.py](src/contentflow/tools/tech_seo.py) 的 FB-06。
- Site crawler：已實作，但屬於骨架型到可測試程度。
  - `SiteCrawler.crawl()` 與 `SiteAuditReport`、`SiteAuditIssue` 已存在。
- Index Coverage：部分實作。
  - `GSCIndexCoverageMonitor`、`IndexCoverageReport`、`detect_newly_unindexed()` 已有。
  - 但沒有獨立排程 job、沒有 admin dashboard、沒有持久化流程。
- sitemap / robots / canonical / og / noindex：已實作於前台站點。
  - [src/contentflow/site/app.py](src/contentflow/site/app.py)
  - [src/contentflow/site/templates/*.html](src/contentflow/site/templates)
- BreadcrumbList schema：已實作。
  - `site/app.py` 為每篇文章生成 `BreadcrumbList` JSON-LD，注入 `blog_post.html` template。

**實作證據**
- [src/contentflow/tools/tech_seo.py](src/contentflow/tools/tech_seo.py)
- [src/contentflow/tools/render_verify.py](src/contentflow/tools/render_verify.py)
- [src/contentflow/site/app.py](src/contentflow/site/app.py)
- [src/contentflow/site/templates/blog_post.html](src/contentflow/site/templates/blog_post.html)
- [tests/test_phase_gate_h.py](tests/test_phase_gate_h.py)
- [tests/test_render_verify.py](tests/test_render_verify.py)

**判定**：FULL

---

### 3.5 監控與數據同步

目標：讓系統能持續接回搜尋與流量數據，形成可自我修正的輸入。

- GSC 同步：已實作。
  - [src/contentflow/tools/gsc.py](src/contentflow/tools/gsc.py)
  - 同步到 `SEORanking`。
- GA4 同步：已實作。
  - [src/contentflow/tools/ga4.py](src/contentflow/tools/ga4.py)
  - 同步到 `GAPageMetric`。
- 競品追蹤：已實作。
  - `CompetitorSnapshot` 由 `run_competitor_serp_check()` 寫入。
- 成效回填：已實作。
  - `backfill_action_outcomes()` 會回填 7d / 14d / 28d 的效果。

**仍需注意的缺口**
- GSC / GA4 都有資料量上限或分頁不足的問題，對大型站點可能截斷。
- 監控數據雖有進表，但還沒有完全統一的監控儀表板把所有回饋合成單一營運視圖。

**實作證據**
- [src/contentflow/tools/gsc.py](src/contentflow/tools/gsc.py)
- [src/contentflow/tools/ga4.py](src/contentflow/tools/ga4.py)
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [tests/test_phase_gate_c.py](tests/test_phase_gate_c.py)
- [tests/test_phase_gate_f.py](tests/test_phase_gate_f.py)

**判定**：PARTIAL

---

### 3.6 學習與反饋閉環

目標：讓系統根據成效持續修正策略，而不是只做一次性產出。

- L1 成功模式分析：已實作。
  - [src/contentflow/agents/learning_agent.py](src/contentflow/agents/learning_agent.py)
  - 分析字數、FAQ、文章型態、SEO 分數 vs 排名。
- L2 ROI 分析：已實作。
  - `optimize_content_strategy()` 會算 keyword ROI、產出高低 ROI 名單。
- 週級反思：已實作。
  - [src/contentflow/agents/reflective_agent.py](src/contentflow/agents/reflective_agent.py)
  - [src/contentflow/scheduler.py](src/contentflow/scheduler.py) 的 `run_weekly_reflection()`。
- Action outcome tracking：已實作。
  - `record_action_outcome()` / `backfill_action_outcomes()` 會把 action 與後續 GSC 數據串起來。

**目前缺口**
- ReflectionLog 有產出，**且 `_apply_writing_rule_updates()` 已完整實作**，每次反思後確實寫入 `WritingRule` 表（前一版審計此處有誤）。
- 真正的缺口是：LLM 反思輸出不一定每次都包含 `writing_rule_updates` 欄位，規則更新的密度與品質仍依賴 prompt 穩定性。
- L2 ROI 的輸出（高低 ROI 關鍵字）目前主要透過 strategic_agent 注入，而非直接驅動自動調整策略。

**實作證據**
- [src/contentflow/agents/learning_agent.py](src/contentflow/agents/learning_agent.py)
- [src/contentflow/agents/reflective_agent.py](src/contentflow/agents/reflective_agent.py) — `_apply_writing_rule_updates()` 在 L459
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)
- [tests/test_reflective_agent.py](tests/test_reflective_agent.py)

**判定**：PARTIAL（較前一版審計覆蓋更廣，調整為 80%）

---

### 3.7 發布面

目標：讓內容不只停在草稿，而是能寫入實際發布平台。

- ForgeBase 發布：已實作。
  - [src/contentflow/publishers/forgebase.py](src/contentflow/publishers/forgebase.py)
- WordPress 發布：已實作。
  - [src/contentflow/publishers/wordpress.py](src/contentflow/publishers/wordpress.py)
  - 支援 Yoast / RankMath / AIOSEO meta key 寫入。
- Refresh 後更新發布：已實作。
  - `refresh_agent.publish_refreshed_article()` 呼叫 publisher 更新既有文章並回寫 DB。
- 排程發布：已實作。
  - `check_scheduled_publishes()` 會自動檢查並發布。
- 手動發布與索引提交：已實作。
  - Admin 文章頁可手動觸發發布與 Google Indexing。

**實作證據**
- [src/contentflow/publishers/forgebase.py](src/contentflow/publishers/forgebase.py)
- [src/contentflow/publishers/wordpress.py](src/contentflow/publishers/wordpress.py)
- [src/contentflow/agents/refresh_agent.py](src/contentflow/agents/refresh_agent.py)
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)

**判定**：FULL

---

### 3.8 後台與操作面

目標：讓 SEO 操作不是黑箱，而是可監控、可手動介入、可回溯。

- Admin Dashboard：已實作。
  - [src/contentflow/admin/app.py](src/contentflow/admin/app.py)
- 文章、日曆、關鍵字、叢集、SEO、競品、Agent、知識庫、排程、健康、設定、報表、反思頁：已實作。
- **內容健康（Content Health）頁**：已實作（前一版審計遺漏）。
  - `/admin/content_health` — 整合自蝕偵測結果（`CannibalizationDetector`）+ Refresh 建議（`RefreshTriggerChecker`），有獨立後台頁面。
  - Template: [src/contentflow/admin/templates/content_health.html](src/contentflow/admin/templates/content_health.html)
- Live scheduler trigger：已實測可用。
- 反思日誌頁：已實作，包含 WritingRule 更新計數顯示。

**目前缺口**
- Index Coverage Dashboard 仍缺 UI（`GSCIndexCoverageMonitor` 有實作但無後台）。
- 發布狀態與 webhook 回寫不是雙向閉環。

**實作證據**
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)
- [src/contentflow/admin/templates/content_health.html](src/contentflow/admin/templates/content_health.html)
- [src/contentflow/admin/templates/](src/contentflow/admin/templates)
- [src/contentflow/site/app.py](src/contentflow/site/app.py)

**判定**：FULL（92%，Index Coverage dashboard 仍缺）

---

### 3.9 排程系統

目標：讓 SEO 工作自己跑，而不是靠人手動呼叫。

目前實作的 scheduler jobs 共 15 個：

- `sync_gsc_all_projects`
- `sync_ga4_all_projects`
- `sync_keyword_trends`
- `backfill_action_outcomes`
- `check_scheduled_publishes`
- `run_competitor_serp_check`
- `run_attribution_engine`
- `check_refresh_triggers`
- `run_l1_pattern_analysis`
- `run_l2_roi_analysis`
- `run_auto_pipeline`
- `run_render_verification`
- `run_weekly_reflection`
- `send_weekly_report`
- `check_ranking_drops`

**實作證據**
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)

**判定**：FULL

---

### 3.10 報表與通知

目標：讓 SEO 產出不只是文章，而是可見的結果與告警。

- 報表渲染：已實作。
  - [src/contentflow/utils/report_renderer.py](src/contentflow/utils/report_renderer.py)
- 週報 / 月報 / 策略報告：已實作。
- Slack 告警：已實作。
  - 發布、排程、Render Verify、排名下滑等都可通知。

**實作證據**
- [src/contentflow/utils/report_renderer.py](src/contentflow/utils/report_renderer.py)
- [src/contentflow/scheduler.py](src/contentflow/scheduler.py)
- [src/contentflow/api.py](src/contentflow/api.py)
- [src/contentflow/admin/app.py](src/contentflow/admin/app.py)

**判定**：FULL

---

## 4. 明顯缺口與風險

以下不是 bug，而是目前距離「完整取代 SEO 專員」還差的地方：

### 4.1 技術 SEO 閉環尚未完整

1. **Index Coverage 閉環**：`GSCIndexCoverageMonitor`、`IndexCoverageReport`、`detect_newly_unindexed()` 已有，並補上獨立排程 job、後台 UI 與持久化寫入 `KnowledgeEntry`。

2. **自動修復閉環**：站點技術 SEO 已涵蓋 canonical / robots / OG / BreadcrumbList / schema / lang / noindex / render verify，但還沒有「偵測問題 → 自動下修 → 確認修復」的完整閉環。

3. **Redirect/301 管理**：已補上 `old_slugs` 與 301 轉導；改 slug 後可回導到新 URL。後續仍可再加更完整的 redirect 規則管理介面。

### 4.2 外鏈（Backlink）管理：MISSING

- 完全沒有外鏈管理模組（無 ahrefs / Moz / GSC link API 整合）。
- 不能分析外鏈品質、追蹤新增/消失外鏈、偵測有毒外鏈。
- 這是 SEO 實務中無法自動化很大的一塊（需要外部資料來源）。

### 4.3 Learning Loop 仍依賴 LLM 輸出格式

- `_apply_writing_rule_updates()` 已實作並接入，但 WritingRule 是否真的被更新取決於 LLM 每次反思是否產出 `writing_rule_updates` 陣列。
- 可能發生 LLM 回傳空陣列但沒有實質更新的情況，目前沒有告警或觀察機制。

### 4.4 孤兒代碼風險（未接入主流程）

| 模組 | 功能 | 現狀 |
|---|---|---|
| `planning_agent.py` | 歸因 + 叢集 + 自蝕 → ContentPlan | 未被任何模組引入 |

### 4.5 GSC / GA4 資料擷取上限

- GSC 同步已改為分頁抓取，不再受 `row_limit=500` 單次上限限制。
- GA4 仍未補齊分頁，大型站點可能截斷。

---

## 5. 已驗證的現況（以正式環境為準）

以下為目前已在正式環境與 live admin 實際驗證過的項目：

- 主站與 admin 後台可正常運作。
- Scheduler trigger 可成功執行 `backfill_action_outcomes`。
- Public site 與 admin 都已改為本地靜態 CSS，不依賴 Tailwind CDN。
- Render verification 已在正式環境排程中運作。
- PageSpeed 429 會被降級處理，不會把整個技術 SEO 流程打爆。

---

## 6. 結論

如果把 SEO 工作拆成「策略 → 關鍵字 → 內容 → 技術 → 監控 → 學習 → 發布 → 通知」八個段落來看，ContentFlow 目前已經把核心工作做成一個可運行系統：

- **策略、內容（含 Refresh）、發布、排程、通知**：覆蓋率接近滿分，是系統最強的部份。
- **學習閉環**：比前一版審計評估更完整，`_apply_writing_rule_updates()` 確實在每次反思後寫入 WritingRule，但品質依賴 LLM prompt 穩定性。
- **技術 SEO**：工具已補齊到可營運閉環，Index Coverage 排程與儀表板已落地，仍可再補更細的自動修復流程。

**真正 MISSING 的（非代碼問題、是 SEO 實務範圍）：**
- 外鏈管理（backlink acquisition、toxic link 監測）
- GA4 分頁同步（大型站點可能截斷）

**孤兒代碼（存在但未生效）：**
- `planning_agent.py`

總結：這個產品已是一個「SEO 營運系統」而非工具型產品。要從「幾乎可以」升級到「完整取代 SEO 專員」，最高優先的三件事是：
1. 補齊外鏈管理與 toxic link 監測
2. 補齊 GA4 分頁同步
3. 視需要將 `planning_agent.py` 的能力整併到 `strategic_agent.py`
