# ContentFlow 產品設計與技術可行性分析

> 基於 `SEO_完整作業流程與閉環設計.md` 22 個章節，逐一對照現有程式碼，
> 評估每個需求的技術可行性、缺口大小、以及建議的實作策略。

---

## 一、真實能力盤點（程式碼層，不算 UI）

SEO 文件結語說「ContentFlow 只做了約 30%」。
深讀完全部程式碼後，修正這個數字：

```
後端邏輯覆蓋率：≈ 55-60%
Admin UI 覆蓋率：≈ 35%
整合完成度（後端 × UI × 排程全通）：≈ 25%
```

**差距不在「能不能」，而在「通不通」。**
很多 Agent 和 Tool 已經寫好，但沒有 UI 觸發、沒有接上排程、或資料沒有回寫 DB。

---

## 二、逐章對照：現況 × 缺口 × 可行性

### Phase 0 — 專案初始化

| 需求 | 現況 | 缺口 |
|------|------|------|
| 品牌背景輸入 | ✅ `Project` 模型有 brand_name, brand_url, brand_description, industry, writing_principles | 欄位在，但沒有引導式填寫流程 |
| 目標受眾 | ⚠️ 塞在 brand_description 一個文字欄位 | 缺獨立欄位：persona_name, age_range, pain_points, search_behavior |
| 商業目標 | ❌ 無 | 需新增 business_goals 欄位（例：提高品牌知名度 / 導購 / 收集名單） |
| 競品清單 | ✅ `Competitor` 模型有 brand_name, website, features, content_analysis | 完整 |
| 撰寫規範 | ✅ `WritingRule` 模型 + `ContentStrategy` 模型 | 完整 |
| Excel 批量匯入 | ✅ `excel_importer.py` 支援 11 種試算表 | 完整且穩定 |

**技術可行性：✅ 完全可行**
- 新增 2-3 個 Project 欄位（business_goals, target_audience_json）
- Admin Settings 頁已有 5 個 Tab，加一個「專案初始化精靈」Tab 即可
- 工作量：小（1-2 天）

---

### Phase 1 — 策略定義

| 需求 | 現況 | 缺口 |
|------|------|------|
| 搜尋意圖分析 | ✅ `strategy_agent.py` 自動分類 informational/commercial/transactional/navigational | 已實作 |
| Topic Cluster 規劃 | ✅ `cluster_agent.py` 用 GPT 語義分群，寫入 `TopicCluster` + `ClusterMember` | 已實作 |
| 競品 SERP 比對 | ⚠️ scheduler 有 `competitor_serp` 排程（每週一 04:00），但函式是 placeholder | 需要接上 `serp.py` 實際查競品關鍵字 |
| 叢集覆蓋率計算 | ✅ `cluster_agent.py` 計算 coverage_rate = covered/total | 已實作 |
| Gap 識別 | ✅ `cluster_agent.py` + `planning_agent.py` 回報 keyword gaps | 已實作 |
| Knowledge Base 注入 | ✅ `knowledge_base.py` ChromaDB + OpenAI embedding → strategy prompt | 完整 |

**技術可行性：✅ 完全可行**
- `competitor_serp` job 的核心邏輯需要補 10-20 行：遍歷 Competitor.website 的主要關鍵字做 SERP 查詢
- Admin `clusters.html` 已存在顯示 pillar + satellite + coverage
- 工作量：小（0.5-1 天接通排程）

---

### Phase 2 — 關鍵字地圖

| 需求 | 現況 | 缺口 |
|------|------|------|
| 關鍵字基礎欄位 | ✅ keyword, search_volume, cpc, seo_difficulty, paid_difficulty, priority | 完整 |
| 搜尋意圖標記 | ❌ Keyword 模型沒有 intent 欄位 | 需要加 `intent` (informational/commercial/transactional) |
| 漏斗階段標記 | ❌ 無 | 需要加 `funnel_stage` (awareness/consideration/decision) |
| 關鍵字 ↔ 叢集 關聯 | ✅ `ClusterMember.keyword` + `ClusterMember.cluster_id` | 已有 |
| 關鍵字 ↔ 文章 關聯 | ✅ `Article.primary_keyword` + `ClusterMember.article_id` | 已有 |
| 優先順序排序 | ⚠️ priority 欄位存在但是文字（"X", "green_x", ""），不是數值化的評分 | 需轉為數值化優先分數或保留原始 + 加算分邏輯 |
| 競品關鍵字差距 | ⚠️ `planning_agent.py` 有 gap detection 邏輯 | 需要 UI 展示 |

**技術可行性：✅ 完全可行**
- Keyword 加 2 個欄位 (intent, funnel_stage) → Alembic migration
- `strategy_agent.py` 已能判斷 intent → 回寫到 Keyword 即可
- Admin keywords.html 已存在，加欄位顯示即可
- 工作量：中（2-3 天，含 migration + agent 回寫 + UI）

---

### Phase 3 — 內容日曆與排程

| 需求 | 現況 | 缺口 |
|------|------|------|
| 基本排程欄位 | ✅ `ContentCalendar` 有 month, week, title, keywords, status, article_id | 完整 |
| 搜尋意圖對應 | ✅ search_intent 欄位已有 | 完整 |
| 文章類型 | ✅ article_type (知識/情境/節慶) | 完整 |
| 寫作架構 | ✅ writing_architecture (倒三角/金字塔/思維流程/敘事型) | 完整 |
| FAQ 規劃 | ✅ faq_questions 欄位 | 完整 |
| 自動排程建議 | ❌ 無 AI 推薦排程邏輯 | planning_agent 可擴展，根據 keyword priority + seasonal trend 推薦 |
| 日曆視覺化 | ⚠️ calendar.html 存在但是表格形式 | 改成真正的月曆/甘特圖視覺化 |

**技術可行性：✅ 完全可行**
- DB 模型完備，不需新增欄位
- AI 排程推薦可以用 `planning_agent.py` 擴展
- 日曆 UI 改版用 FullCalendar.js 或自己畫 CSS Grid
- 工作量：中（3-4 天，主要在 UI 體驗提升）

---

### Phase 4 — 內容生產（AI Pipeline）

| 需求 | 現況 | 缺口 |
|------|------|------|
| 研究階段 | ✅ `research_agent.py` — PubMed + SERP + 關鍵字萃取 + PAA | 完整 |
| 策略分析 | ✅ `strategy_agent.py` — 意圖分析 + 架構推薦 + 競品差距 + KB 注入 | 完整 |
| 內容撰寫 | ✅ `writing_agent.py` — 大綱 → 逐段寫 → Meta → Slug → JSON-LD | 完整 |
| SEO 檢查 | ✅ `seo_check_agent.py` — 12 項加權規則，85 分門檻 | 完整 |
| SEO 修正迴圈 | ✅ `seo_qa_agent.py` — 低風險微調 meta + 開頭段，最多 3 次重試 | 完整 |
| 事實查核 | ✅ `factcheck_agent.py` — PubMed 佐證 + 法規禁詞 + 嚴重分級 | 完整 |
| 預算控制 | ✅ `budget_guard.py` — ≤15 calls, ≤$2.00 per article | 完整 |
| 圖片生成 | ✅ `image_agent.py` — Prompt 生成 + 可選 DALL-E 3 | 完整 |
| 決策日誌 | ✅ `AgentDecisionLog` 模型，orchestrator 每步寫入 | 完整 |
| 端到端編排 | ✅ LangGraph StateGraph 有條件路由 + fallback legacy | 完整 |

**這是 ContentFlow 最成熟的部分，幾乎不需要改動。**

唯一缺口：
- Pipeline 目前只能從 API (`POST /api/v1/articles/generate`) 或 Admin trigger 啟動
- 沒有「批量排程觸發」（例：每天自動處理排程到期的文章）

**工作量：極小（在 scheduler.py 加一個 daily job 檢查 ContentCalendar → trigger pipeline）**

---

### Phase 5 — 人工審閱與發布

| 需求 | 現況 | 缺口 |
|------|------|------|
| 草稿瀏覽 | ✅ article_detail.html 顯示完整 Markdown + 元資料 + 決策日誌 | 完整 |
| 人工編輯 | ❌ | Admin 沒有 Markdown 編輯器，只能看不能改 |
| Diff 追蹤 | ⚠️ API 有 `POST /articles/{id}/review-feedback` 接收 diff → KnowledgeEntry | 後端有，UI 沒接 |
| 審核通過 | ❌ | 沒有「核准」按鈕改 status → approved |
| 發布到 WordPress | ✅ `publishers/wordpress.py` — REST API 推文 | 完整 |
| 發布到 ForgeBase | ✅ `publishers/forgebase.py` — API 推文 + 更新 | 完整 |
| 發布後更新舊文連結 | ⚠️ orchestrator.py 給出 internal_link_suggestions | 只是建議，沒有實際回去改舊文 |
| 提交 Google Indexing | ❌ | 需要 Google Indexing API client |

**技術可行性：✅ 完全可行**
- Markdown 編輯器：前端用 EasyMDE / Milkdown / 直接 `<textarea>` + preview
- 審核按鈕：一個 POST endpoint 改 status
- Indexing API：Google 有現成 REST API，寫個 `tools/indexing.py` 即可
- **自動回改舊文連結**：這比較複雜，需要：
  1. 查 DB 找相關文章
  2. 在舊文的 Markdown 中找到適當位置插入連結
  3. 推回 WordPress/ForgeBase
  → 可行但需要 LLM 輔助找插入點
- 工作量：中-大（4-6 天）

---

### Phase 6 — 發布後觀測

| 需求 | 現況 | 缺口 |
|------|------|------|
| GSC 數據同步 | ✅ `gsc.py` — get_page_performance, get_keyword_rankings, sync_to_db | 完整 |
| GA4 數據同步 | ✅ `ga4.py` — get_page_metrics (users, sessions, engagement, bounce, conversions) | 完整 |
| 自動排程同步 | ✅ scheduler.py: gsc_sync 每日 03:00, ga4_sync 每日 03:30 | 完整 |
| 排名分群 (A-F) | ✅ `analytics_agent.py` AttributionEngine — 5 等級 A-F 含行動建議 | 完整 |
| 收錄偵測 | ✅ `tech_seo.py` GSCIndexCoverageMonitor — total_indexed, newly_unindexed | 完整 |
| 排名掉落警報 | ✅ `analytics_agent.py` RefreshTriggerChecker — rank decline >5 = high priority | 完整 |
| Slack 通知 | ✅ scheduler.py `_send_failure_alert()` + config.slack_webhook_url | 完整 |
| Dashboard UI | ⚠️ seo.html 存在但僅顯示基本 GSC 數據 | 需要增強：排名趨勢圖、分群分布、異動警報列表 |

**技術可行性：✅ 完全可行**
- 後端 100% 就緒，只需要 UI 增強
- 用 Chart.js（已引入）畫排名趨勢折線圖
- 加一個「異動警報」區塊從 RefreshTriggerChecker 拉資料
- 工作量：中（3-4 天主要是 UI）

---

### Phase 7 — 優化迭代閉環

| 需求 | 現況 | 缺口 |
|------|------|------|
| L1 規則學習 | ✅ `learning_agent.py` — 分析已發布文章 vs 排名 → 寫入 KnowledgeEntry | 完整 |
| L2 策略學習 | ✅ `learning_agent.py` — ROI 計算 + refresh priority | 完整 |
| Refresh Pipeline | ✅ `refresh_agent.py` — fetch → diff → patch → republish | 完整 |
| 知識库人工審閱 | ✅ `KnowledgeAuditLog` 模型 + knowledge.html UI | 完整 |
| 自動觸發 Refresh | ⚠️ scheduler 有 refresh_check (每週二 04:00) | 函式存在但需確認是否實際串接 |
| 學習自動回寫規則 | ❌ | L1 patterns 寫入 KnowledgeEntry，但不自動更新 WritingRule |

**技術可行性：✅ 完全可行**
- 自動回寫 WritingRule 需要人工確認步驟（避免壞規則污染全局）
- 可以做成：L1 發現 pattern → 建議新 WritingRule → Admin 一鍵採納
- 工作量：小-中（2-3 天）

---

### Section 10 — 內部連結策略

| 需求 | 現況 | 缺口 |
|------|------|------|
| 叢集內連結規則 | ✅ `ClusterMember.link_to_pillar` 追蹤是否連回柱文 | 已有追蹤 |
| 新文章出站連結 | ✅ orchestrator.py 從 DB 查已發布文章給出 suggestions | 已實作 |
| 回改舊文入站連結 | ❌ | 最大技術挑戰之一 |
| 孤兒頁偵測 | ✅ `tech_seo.py` SiteCrawler 偵測 orphan_page | 已實作 |
| 斷裂連結偵測 | ✅ `tech_seo.py` SiteCrawler 偵測 broken_link | 已實作 |

**技術可行性：✅ 可行但「自動回改舊文」複雜度高**
- 偵測面（孤兒、斷裂）完全就緒
- 自動回改需要：LLM 找插入點 + publisher API 推更新
- 建議分兩步：先做「建議清單」（哪篇舊文應該加連結到哪篇新文）→ 再做「一鍵執行」
- 工作量：中（3-4 天做建議清單，5-7 天做自動執行）

---

### Section 11 — Off-Page SEO 與反向連結

| 需求 | 現況 | 缺口 |
|------|------|------|
| 反向連結監控 | ❌ | GSC 可以拿到部分外部連結資料，但精度低 |
| Referring Domains | ❌ | 需要 Ahrefs / Moz / Majestic API（付費） |
| 競品連結差距 | ❌ | 同上 |
| 有害連結偵測 | ❌ | 同上 |

**技術可行性：⚠️ 有限制**
- Google Search Console 的 Links API 可以免費拿到「誰連到你」的資料
- 但精度和即時性遠不如 Ahrefs（月費 $99+）
- **建議的策略：**
  1. 第一步：用 GSC Links API 做基本反向連結監控（免費）
  2. 第二步：如果需要更精確，考慮 Ahrefs API 2.0（按量計費）
  3. Off-page 策略本身（寫外部文章、媒體合作）無法自動化，只能追蹤結果
- **建議不在第一期做。**記錄需求但優先順序放後面。
- 工作量：小（GSC links 方案 1-2 天）/ 大（Ahrefs 整合 5+ 天）

---

### Section 12 — SERP Feature 搶佔

| 需求 | 現況 | 缺口 |
|------|------|------|
| PAA 捕獲 | ✅ `serp.py` 自動捕獲 PAA + related_searches | 完整 |
| FAQ Schema 產出 | ✅ `writing_agent.py` 自動產出 FAQPage JSON-LD | 完整 |
| Featured Snippet 優化 | ⚠️ writing_agent 產出的結構有利於 FS，但沒有專門的檢查規則 | seo_check_agent 加一條規則 |
| PAA 追蹤 | ❌ | PAA 抓了但沒存 DB。需要 PeopleAlsoAsk 持久化 |
| HowTo Schema | ❌ | writing_agent 目前只產 FAQ + Article schema |

**技術可行性：✅ 完全可行**
- Featured Snippet 檢查：在 `seo_check_agent.py` 加一條規則「H2 問句後的第一段是否 40-60 字精準回答」
- PAA 持久化：在 Article 或新 table 存 SERP 的 PAA 快照
- HowTo schema：writing_agent 的 schema 生成步驟加一個分支
- 工作量：小-中（2-3 天）

---

### Section 13 — 內容健康管理

| 需求 | 現況 | 缺口 |
|------|------|------|
| 自蝕偵測 | ✅ `analytics_agent.py` CannibalizationDetector — 多 URL 搶同一 keyword | 完整 |
| 修剪建議 | ⚠️ analytics_agent RefreshTriggerChecker 會標記 grade D/F | 有但沒有「修剪」動作選項 |
| 內容新鮮度 | ✅ refresh_agent.py freshness_score 0-100 | 完整 |
| 全站內容審計 | ❌ | 需要一個「審計報告」功能，把所有文章的排名 + engagement + freshness 匯總 |

**技術可行性：✅ 完全可行**
- CannibalizationDetector 已存在，只缺 UI 展示 + 行動按鈕
- 內容審計 = 把 analytics_agent 跑一次全 project，結果彙整成報表
- 修剪 = 在 planning_agent 的 recommendations 加 "prune" action type
- 工作量：中（3-4 天）

---

### Section 14 — 圖片 SEO

| 需求 | 現況 | 缺口 |
|------|------|------|
| AI 圖片生成 | ✅ `image_agent.py` — DALL-E 3 | 完整 |
| Alt text 最佳化 | ❌ | image_agent 產 prompt 但不產 alt text |
| 檔名規範 | ❌ | 圖片存檔用 UUID，不是語義化檔名 |
| WebP 轉換 | ❌ | DALL-E 輸出 PNG |
| 壓縮 | ❌ | 無壓縮邏輯 |

**技術可行性：✅ 完全可行**
- Alt text：image_agent 的 prompt 改一下，同時產 alt_text 欄位
- 檔名：用 slug + section keyword 產檔名
- WebP/壓縮：Python Pillow 一行 `img.save("x.webp", quality=80)`
- 工作量：小（1-2 天）

---

### Section 15 — 轉換優化（SEO × CRO）

| 需求 | 現況 | 缺口 |
|------|------|------|
| CTA 設計指引 | ❌ | 無 |
| CTA 追蹤 | ❌ | GA4 有 conversions 欄位但沒有 event setup |
| 轉換漏斗 | ❌ | 無 |
| Landing Page 優化 | ❌ | 無 |

**技術可行性：⚠️ 部分可行**
- CTA 在寫作階段注入：可以在 `writing_agent.py` 的 system prompt 加 CTA 區塊要求
- CTA 追蹤：需要在前端（WordPress/ForgeBase）埋 GA4 event → 這是前端工作
- 轉換漏斗分析：GA4 已能拿到 conversions，做一個 dashboard 即可
- **核心問題：CRO 高度依賴前端（WordPress 佈局），ContentFlow 作為後端工具能做的是「在內容裡自動插入 CTA」和「追蹤結果」**
- 工作量：中（3-4 天，但效果取決於前端配合）

---

### Section 16 — GA4 行為指標

| 需求 | 現況 | 缺口 |
|------|------|------|
| 頁面指標 | ✅ ga4.py — active_users, sessions, avg_engagement_time, bounce_rate, conversions | 完整 |
| 排程同步 | ✅ scheduler ga4_sync 每日 03:30 | 完整 |
| 聯合診斷 | ❌ | GSC 排名 + GA4 行為 的交叉分析沒有實作 |
| Dashboard | ❌ | seo.html 只有 GSC 數據 |

**技術可行性：✅ 完全可行**
- GA4 數據需要存 DB（目前 ga4.py 只是 client，沒有持久化 table）
- 新增 `PageMetric` 模型或擴展 `SEORanking` 加 GA4 欄位
- 聯合診斷 = JOIN seo_rankings (GSC) + page_metrics (GA4) on landing_page
- 工作量：中（3-4 天含 model + sync + UI）

---

### Section 17 — SEO 報告機制與 KPI

| 需求 | 現況 | 缺口 |
|------|------|------|
| 週報自動生成 | ❌ | 數據在 DB，但沒有報告組裝邏輯 |
| 月報 | ❌ | 同上 |
| 季報 | ❌ | 同上 |
| KPI 追蹤 | ❌ | 沒有 KPI 定義和計算 |

**技術可行性：✅ 完全可行**
- 所有報告需要的數據都已經有來源（GSC, GA4, Article, SEORanking）
- 週報自動化：scheduler 加一個 weekly job → 組裝 markdown/HTML 報告 → Slack/Email
- 月報：同邏輯但加上 Chart.js 圖表（可以用 matplotlib 生成 PNG 或直接在 Admin 頁面渲染）
- 建議做法：
  1. 新增 `ReportGenerator` 模組
  2. 新增 Admin 報告頁面 `/admin/reports`
  3. 每週 /月自動生成，也可以手動觸發
- 工作量：中-大（5-7 天，因為報告格式設計需要打磨）

---

### Section 18 — 演算法更新因應

| 需求 | 現況 | 缺口 |
|------|------|------|
| 排名快照 | ⚠️ SEORanking 有 tracked_date，但不是每日完整快照 | 需要「每日排名快照」邏輯 |
| 異動偵測 | ✅ RefreshTriggerChecker 偵測 rank decline >5 | 有但粒度不夠（±5 可能不足以偵測 Core Update） |
| 受損文章分析 | ❌ | 需要共同特徵分析（缺 E-E-A-T？缺引用？） |
| SOP 流程 | ❌ | 這是人工判斷，系統可以提供數據支持 |

**技術可行性：⚠️ 部分可行，部分需人工**
- 排名快照：GSC sync 已是每日，確保存的是每日粒度
- 批量受損分析：可以用 LLM 分析「這些掉排名的文章有什麼共同點」→ 新 agent 或擴展 analytics
- Core Update 本身的偵測：依賴外部消息（Google 公告），可以用 RSS 監控
- 工作量：小-中（2-3 天做數據面，SOP 面是文件不是程式碼）

---

### Section 19 — 競品持續監控

| 需求 | 現況 | 缺口 |
|------|------|------|
| 競品新文章偵測 | ❌ | scheduler 有 weekly `competitor_serp`，但函式 placeholder |
| 競品排名追蹤 | ❌ | 同上 |
| 威脅分級 | ❌ | 需要邏輯 |

**技術可行性：✅ 完全可行**
- `competitor_serp` job 的實作路徑：
  1. 從 DB 讀 Competitor 列表
  2. 對每個 competitor 的主要 URL 做 SERP 查詢
  3. 比對上週快照 → 找出新文章 / 排名變化
  4. 寫入新 model（CompetitorSnapshot 或擴展 Competitor）
  5. 觸發 Slack 警報
- 工作量：中（3-4 天含 model + serp 查詢 + 比對邏輯 + UI）

---

### Section 20 — 技術 SEO

| 需求 | 現況 | 缺口 |
|------|------|------|
| Core Web Vitals | ✅ tech_seo.py CoreWebVitalsMonitor — PageSpeed Insights API | 完整 |
| 索引覆蓋率 | ✅ tech_seo.py GSCIndexCoverageMonitor | 完整 |
| 站點爬蟲 | ✅ tech_seo.py SiteCrawler — broken_link, orphan_page, redirect_chain, missing_title | 完整 |
| 健康儀表板 | ✅ tech_seo.py TechSEOHealthDashboard — 加權評分 (CWV 40% + 索引 30% + 爬蟲 30%) | 完整 |
| Mobile Usability | ✅ tech_seo.py GSCMobileUsabilityMonitor | 完整 |
| Pillar Page 模板 | ✅ tech_seo.py generate_pillar_page_template | 完整 |
| Admin UI | ⚠️ health.html 只顯示基本連線狀態 | 需要接上 tech_seo 工具的完整數據 |

**技術可行性：✅ 工具層 100% 就緒，只缺 UI**
- health.html 擴展或新開 `/admin/tech-seo` 頁面
- 把 CoreWebVitals + IndexCoverage + SiteAudit + HealthScore 全部視覺化
- 工作量：中（3-4 天 UI 開發）

---

### Section 21 — E-E-A-T

| 需求 | 現況 | 缺口 |
|------|------|------|
| 作者資訊 | ❌ 無 Author 模型 | 需要新增 |
| PubMed 引用 | ✅ research_agent 抓 PubMed + factcheck_agent 驗證 | 完整 |
| 醫療免責聲明 | ✅ writing_agent 自動加在文末 | 完整 |
| 發布/更新日期 | ✅ Article.created_at, updated_at + article_schema_json 含 datePublished/dateModified | 完整 |
| E-E-A-T 評分 | ❌ | 可以做但需要定義評分規則 |

**技術可行性：✅ 完全可行**
- 新增 `Author` 模型：name, title, bio, credentials, profile_url, photo_url
- Article 加 author_id FK
- E-E-A-T 評分：在 seo_check_agent 加檢查項（有作者？有引用？有免責？有更新日期？）
- writing_agent 的 Article schema 加 author info
- 工作量：中（3-4 天）

---

### Section 22 — 數據模型

數據模型對照已在 SEO 文件中列出。上面各章節的分析已覆蓋所有缺口。

---

## 三、需要新增的資料模型

根據以上分析，歸納需要新增或修改的模型：

### 新增模型

```python
class Author(Base):
    """E-E-A-T 作者管理"""
    id, project_id, name, title, bio, credentials,
    profile_url, photo_url, created_at

class PageMetric(Base):
    """GA4 頁面指標持久化"""
    id, project_id, page_path, active_users, sessions,
    avg_engagement_time, bounce_rate, conversions,
    tracked_date, created_at

class CompetitorSnapshot(Base):
    """競品排名快照"""
    id, competitor_id, keyword, position, url,
    is_new_content, tracked_date

class SerpFeatureTracking(Base):
    """SERP Feature 追蹤"""
    id, project_id, keyword, feature_type,  # featured_snippet / paa / faq_rich
    our_url, captured_by_us, tracked_date

class SEOReport(Base):
    """報告紀錄"""
    id, project_id, report_type,  # weekly / monthly / quarterly
    content_json, generated_at
```

### 修改現有模型

```python
# Project — 加欄位
+ business_goals = Column(Text, default="")
+ target_audience_json = Column(Text, default="{}")

# Keyword — 加欄位
+ intent = Column(String, default="")       # informational / commercial / transactional
+ funnel_stage = Column(String, default="")  # awareness / consideration / decision

# Article — 加欄位
+ author_id = Column(Integer, ForeignKey("authors.id"), nullable=True)
+ last_refresh_date = Column(DateTime, nullable=True)
+ eeat_score = Column(Integer, nullable=True)
```

---

## 四、架構設計建議

### 4.1 不要動現有核心架構

ContentFlow 目前的分層是合理的：

```
Config → DB → Models
              ↓
Tools (serp, pubmed, gsc, ga4, tech_seo, knowledge_base)
              ↓
Agents (14 個，各司其職)
              ↓
Orchestrator (LangGraph 狀態圖)
              ↓
API (FastAPI) + Scheduler (APScheduler)
              ↓
Admin UI (Jinja2 + Tailwind + Alpine.js)
Site UI (同上)
```

**不需要重寫。只需要：**
1. 補接線（Agent ↔ DB 的回寫、Scheduler ↔ Agent 的串接）
2. 補 UI（Admin 頁面增強 + 新頁面）
3. 補模型（5 個新 table + 3 個 ALTER TABLE）

### 4.2 Admin UI 新頁面規劃

目前 Admin 有 15 個頁面，建議新增 3 個：

| 新頁面 | 路徑 | 用途 |
|--------|------|------|
| 技術 SEO | `/admin/tech-seo` | CWV 分數 + 索引覆蓋 + 爬蟲問題 + 健康分數 |
| 內容健康 | `/admin/content-health` | 自蝕偵測 + 修剪建議 + Refresh 佇列 + 內部連結健康 |
| 報告中心 | `/admin/reports` | 週/月/季報產出 + KPI 追蹤 + 歷史報告瀏覽 |

### 4.3 Scheduler Jobs 補完

| Job | 現況 | 需要做 |
|-----|------|--------|
| gsc_sync | ✅ 完整 | — |
| ga4_sync | ✅ 完整但不存 DB | 加 PageMetric 寫入 |
| competitor_serp | ⚠️ Placeholder | 接上 serp.py 實際查詢 + CompetitorSnapshot |
| attribution | ✅ 完整 | — |
| refresh_check | ⚠️ 需確認 | 確認串接 analytics_agent |
| l1_learn | ✅ 完整 | — |
| l2_learn | ✅ 完整 | — |
| **新增** weekly_report | ❌ | 每週日 → 組裝 + Slack 發送 |
| **新增** auto_pipeline | ❌ | 每日 → 檢查 ContentCalendar 到期項目 → trigger pipeline |
| **新增** content_audit | ❌ | 每季 → 全站內容審計 |

---

## 五、優先級建議

以「對 SEO 產出品質影響最大」排序，分三期：

### 第一期：讓閉環能跑起來（核心打通）

> 目標：一篇文章能走完 計畫 → 生產 → 審閱 → 發布 → 追蹤 的完整閉環。

| # | 任務 | 工作量 | 為何優先 |
|---|------|--------|---------|
| 1 | Article 編輯功能（Markdown editor + 保存） | 2 天 | 沒有人工編輯就無法閉環 |
| 2 | 審核/發布按鈕 + 狀態機 | 1 天 | 閉環的關鍵節點 |
| 3 | WordPress 發布觸發 | 1 天 | publisher 已寫好，接 UI 即可 |
| 4 | auto_pipeline scheduler job | 1 天 | ContentCalendar 到期 → 自動觸發 |
| 5 | GA4 PageMetric 持久化 | 1 天 | 觀測階段的基礎 |
| 6 | SEO Dashboard 增強（排名趨勢 + 分群） | 2 天 | 看見結果才能迭代 |

**預估：8-10 天**

### 第二期：SEO 品質提升

| # | 任務 | 工作量 |
|---|------|--------|
| 7 | Keyword 加 intent + funnel_stage | 1 天 |
| 8 | Author 模型 + E-E-A-T 檢查 | 3 天 |
| 9 | SERP Feature 優化規則 (Featured Snippet check) | 1 天 |
| 10 | 競品持續監控 (CompetitorSnapshot + 排程) | 3 天 |
| 11 | 內部連結建議清單 | 3 天 |
| 12 | 內容健康頁面 (自蝕 + 修剪 + Refresh) | 3 天 |
| 13 | 圖片 SEO (alt text + WebP + 命名) | 2 天 |

**預估：16-18 天**

### 第三期：報告 & 進階自動化

| # | 任務 | 工作量 |
|---|------|--------|
| 14 | Tech SEO Dashboard (CWV + 索引 + 爬蟲) | 4 天 |
| 15 | 報告中心 (週/月/季報) | 5 天 |
| 16 | 自動回改舊文連結 | 5 天 |
| 17 | 演算法更新 SOP (排名快照 + 批量分析) | 3 天 |
| 18 | Off-Page 基礎 (GSC Links API) | 2 天 |
| 19 | CRO 整合 (CTA 注入 + 追蹤) | 3 天 |

**預估：22-25 天**

---

## 六、技術風險評估

| 風險 | 嚴重度 | 因應 |
|------|--------|------|
| Google API 配額限制（GSC/GA4 每日查詢量） | 中 | 已用 Service Account，配額足夠中小站 |
| LLM 成本失控 | 低 | Budget Guard 已有 $2/article 限制 |
| 伺服器記憶體不足（2GB Linode） | 中 | ChromaDB + 多 Agent 同時跑可能吃記憶體。建議升到 4GB 或把 ChromaDB 改用 SQLite 後端 |
| WordPress API 權限 | 低 | 用 Application Password，已支援 |
| SERP API 費用 | 低 | Serper.dev 按量計費，小量使用 < $5/月 |
| 資料庫 migration 風險 | 低 | 已用 Alembic，PostgreSQL 支援 ALTER TABLE 不停機 |

---

## 七、結論

**ContentFlow 的底子比預期的好很多。**

14 個 Agent、9 個 Tool、18+ 個 DB 模型——核心後端幾乎都寫完了。
問題不在「能不能做」，而在：

1. **「通不通」**— 很多 Agent 寫好了但沒接上 scheduler / UI / DB 回寫
2. **「看不看得到」**— 後端能力很強但 Admin UI 只展示了 30%
3. **「走不走得完」**— 閉環有斷點（不能編輯 → 不能審核 → 不能自動觸發）

三期加起來約 **46-53 天**，可以把 SEO 文件中 22 個章節的需求全部覆蓋。
但第一期 **8-10 天就能讓閉環可運行**，這才是實際收到 SEO 回報的起點。
