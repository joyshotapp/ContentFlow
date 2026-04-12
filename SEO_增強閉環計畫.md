# SEO 增強閉環計畫

> ContentFlow × ForgeBase — 會自己學習的 SEO 內容 Agent，每一輪比上一輪更準
>
> 版本：v1.3 | 建立日期：2026-04-12 | 更新：2026-04-12
>
> 執行追蹤清單：另見 `SEO_增強閉環_開發任務清單.md`

---

## 目錄

1. [願景與核心概念](#1-願景與核心概念)
2. [閉環七階段總覽](#2-閉環七階段總覽)
3. [現有能力盤點](#3-現有能力盤點)
4. [缺漏與開發項目](#4-缺漏與開發項目)
5. [階段一：LISTEN — 採集信號](#5-階段一listen--採集信號)
6. [階段二：ANALYSE — 歸因分析](#6-階段二analyse--歸因分析)
7. [階段三：PLAN — AI 選題決策](#7-階段三plan--ai-選題決策)
8. [階段四：CREATE — AI Agent 自主產文](#8-階段四create--ai-agent-自主產文)
9. [階段五：REVIEW — 人工審閱關卡](#9-階段五review--人工審閱關卡)
10. [階段六：PUBLISH — 雙平台發布](#10-階段六publish--雙平台發布)
11. [階段七：LEARN — 三層學習與自動進化](#11-階段七learn--三層學習與自動進化)
12. [Off-Page SEO — 反向連結監控與策略](#12-off-page-seo--反向連結監控與策略)
13. [Topic Cluster — 主題叢集架構](#13-topic-cluster--主題叢集架構)
14. [技術 SEO 健康監控](#14-技術-seo-健康監控)
15. [系統職責分工：ContentFlow vs ForgeBase](#15-系統職責分工contentflow-vs-forgebase)
16. [AI Agent 架構升級：從 Pipeline 到有限自主 Agent](#16-ai-agent-架構升級從-pipeline-到有限自主-agent)
17. [安全防護：Bounded Autonomy 設計](#17-安全防護bounded-autonomy-設計)
18. [排程與背景任務系統](#18-排程與背景任務系統)
19. [部署架構與資料庫規劃](#19-部署架構與資料庫規劃)
20. [WordPress 串接方案](#20-wordpress-串接方案)
21. [閉環數據流全圖](#21-閉環數據流全圖)
22. [開發優先順序與里程碑](#22-開發優先順序與里程碑)
23. [預期成效](#23-預期成效)

---

## 1. 願景與核心概念

### 什麼是 SEO 增強閉環？

**傳統 SEO 是單程作業**：人工研究 → 寫文 → 發布 → 等結果 → 手動調整（如果有的話）

**增強閉環是自動循環**：系統發布內容後，持續觀測 Google 回饋的真實排名與流量數據，AI 自動分析什麼有效、什麼沒效，並決定下一步動作（修正舊文、補新文、改連結），每一輪的命中率都比上一輪更高。

```
                    ┌──────────────────────────────────┐
                    │                                  │
                    ▼                                  │
    ① LISTEN ──→ ② ANALYSE ──→ ③ PLAN               │
    採集信號      歸因分析       AI 選題決策            │
                                    │                  │
                                    ▼                  │
                ④ CREATE ──→ ⑤ REVIEW ──→ ⑥ PUBLISH  │
                AI Agent產文  人工審閱      雙平台發布    │
                                                │      │
                                                ▼      │
                                          ⑦ LEARN ─────┘
                                          三層學習
                                          自動進化
```

### 核心原則

- **Agent 自主執行，人在關鍵點把關**：AI Agent 自主決策文章策略、結構、修正方式；人工只在 REVIEW 關卡決定是否發布
- **有限自主（Bounded Autonomy）**：Agent 有明確的預算上限、重試上限、禁止操作清單，不會失控
- **數據驅動**：所有決策基於 GSC / GA4 真實數據，不靠直覺
- **雙平台支援**：支援 ForgeBase（深度整合）與 WordPress（全球主流），不做其他平台
- **越做越準**：三層學習機制（模式記憶 → 策略優化 → 競品適應），新客戶啟動即享受歷史學習成果

---

## 2. 閉環七階段總覽

| 階段 | 負責系統 | 自動化程度 | 人工介入 |
|------|---------|-----------|---------|
| ① LISTEN 採集信號 | ContentFlow + GSC/GA4 API | 全自動 | ✗ |
| ② ANALYSE 歸因分析 | ContentFlow | 全自動 | ✗ |
| ③ PLAN 選題決策 | ContentFlow | AI 推薦 | 可選（確認/略過） |
| ④ CREATE AI Agent 產文 | ContentFlow AI Agent | Agent 自主決策 | ✗ |
| ⑤ REVIEW 人工審閱 | Streamlit UI / ForgeBase Admin | — | **必要** |
| ⑥ PUBLISH 雙平台發布 | ContentFlow API → ForgeBase / WordPress | 全自動 | ✗ |
| ⑦ LEARN 三層學習 | ContentFlow | 全自動 | 可選（覆核學習結論） |

---

## 3. 現有能力盤點

### 3.1 ContentFlow — 已完成 ✅

| 能力 | 模組 | 狀態 |
|------|------|------|
| 關鍵字庫管理（搜尋量、CPC、KD、優先度） | `models/database.py` — `Keyword` | ✅ 完成 |
| SERP 競品分析（前 10 名結構、PAA） | `tools/serp.py`（Serper + SerpAPI 雙備援） | ✅ 完成 |
| PubMed 學術文獻搜尋 | `tools/pubmed.py` | ✅ 完成 |
| 中文關鍵字 → 英文 MeSH 翻譯 | `agents/research_agent.py` | ✅ 完成 |
| SEO 策略分析（搜尋意圖、讀者輪廓、架構建議） | `agents/strategy_agent.py` | ✅ 完成 |
| 三階段撰文（大綱 → 段落 → 完整稿） | `agents/writing_agent.py` | ✅ 完成 |
| SEO 規則引擎評分（零 LLM 成本） | `agents/seo_check_agent.py` | ✅ 完成 |
| SEO QA 自動修正（針對性修正） | `agents/seo_qa_agent.py` | ✅ 完成 |
| 事實查核 + 禁用詞比對 | `agents/factcheck_agent.py` | ✅ 完成 |
| FAQ JSON-LD 生成 | `agents/writing_agent.py` | ✅ 完成 |
| 配圖 Prompt 生成 | `agents/image_agent.py` | ✅ 完成 |
| Orchestrator 五步驟 Pipeline | `agents/orchestrator.py` | ✅ 完成 |
| 多專案（Multi-project）支援 | `project_context.py` + 全資料表 `project_id` | ✅ 完成 |
| 品牌知識注入 Agent Prompt | `project_context.py` → `build_brand_prompt()` | ✅ 完成 |
| 內容日曆排程 | `models/database.py` — `ContentCalendar` | ✅ 完成 |
| Excel 匯入（13 種工作表） | `tools/excel_importer.py` | ✅ 完成 |
| Streamlit UI（10 頁） | `app/` | ✅ 完成 |
| CLI 工具 | `cli.py` + `scripts/` | ✅ 完成 |
| 126 個 pytest 測試 | `tests/` | ✅ 全數通過 |

### 3.2 ContentFlow — 已定義但未實作 ⚠️

| 能力 | 現況 | 說明 |
|------|------|------|
| WordPress 發布 | `config.py` 已定義 3 個 WP 環境變數 | 無實作程式碼 |
| Google Sheets 整合 | `config.py` 已定義設定 | 無實作程式碼 |
| SEO 排名資料表 | `models/database.py` — `SEORanking` | 資料表存在，但無寫入來源 |

### 3.3 ForgeBase — 已完成 ✅

| 能力 | 模組/檔案 | 狀態 |
|------|----------|------|
| SEO 基礎欄位（seo_title / meta_desc / canonical / noindex） | `Page`、`Product`、`Application` 模型 | ✅ 完成 |
| OG Image + Alt Text | 所有內容模型 + migration 0023 | ✅ 完成 |
| JSON-LD Schema（Product / FAQ / Breadcrumb / Organization） | `web/src/components/seo/StructuredData.tsx` | 4 種 ✅ 完成 |
| Canonical URL 自動生成 | `web/src/lib/seo.ts` — `buildCanonicalUrl()` | ✅ 完成 |
| hreflang 多語系（6 語言） | `buildLocaleAlternates()` + 多語儀表板 | ✅ 完成 |
| 動態 Sitemap（7 種內容類型） | `web/src/app/sitemap.ts` | ✅ 完成 |
| robots.txt | `web/src/app/robots.ts` | ✅ 完成 |
| Next.js generateMetadata（42 個頁面） | 所有 `page.tsx` | ✅ 完成 |
| OG / Twitter Card | `buildDefaultMetadata()` + `buildTwitterMeta()` | ✅ 完成 |
| 301/302 SEO 重定向管理 | `api/endpoints/redirects.py` + Admin UI | ✅ 完成 |
| AI SEO 優化建議 | `api/endpoints/seo_optimize.py` | ✅ 完成 |
| AI 內容優化器（關鍵字密度、可讀性） | `api/endpoints/ai_intelligence.py` | ✅ 完成 |
| on-page SEO 稽核 | `seo_optimize.py` — `_audit_issues()` | ✅ 完成 |
| PageBrief AI 內容生成工作流 | `api/endpoints/ai_generate.py` + `PageBrief` 模型 | ✅ 完成 |
| 訪客行為追蹤（15 種事件） | `TrackingEvent` 模型 + 前端追蹤 | ✅ 完成 |
| 意圖評分 + ML 意圖預測 | `Visitor` 模型 + `ml_scoring.py` | ✅ 完成 |
| GA4 事件整合 | `web/src/lib/analytics.ts` | ✅ 完成 |
| UTM 參數追蹤 | `TrackingEvent.campaign_id` | ✅ 完成 |
| 頁面/產品流量分析 | `api/endpoints/analytics.py` | ✅ 完成 |
| 內容效能分析 Admin UI | `admin/dashboard/content-performance/` | ✅ 完成 |
| 重定向管理 Admin UI | `admin/dashboard/redirects/` | ✅ 完成 |
| 內容優化器 Admin UI | `admin/dashboard/content-optimizer/` | ✅ 完成 |
| 多語管理 Admin UI | `admin/dashboard/multilingual/` | ✅ 完成 |
| RFQ 詢價表單 + Chat → RFQ handoff | RFQ 系統 + AI Product Advisor | ✅ 完成 |
| Dynamic CTA | 依訪客意圖階段切換 | ✅ 完成 |

### 3.4 ForgeBase — 已定義但不完整 ⚠️

| 能力 | 現況 | 說明 |
|------|------|------|
| GSC 數據消費 | `seo_optimize.py` 接受 GSC 參數 | 僅支援手動輸入，無自動拉取 |
| 分析儀表板 | `admin/dashboard/analytics/` 目錄存在 | 頁面遺失 |

---

## 4. 缺漏與開發項目

### 缺漏總表（依閉環階段分類）

| 閉環階段 | 缺漏項目 | 優先級 | 預估工作量 |
|---------|---------|--------|-----------|
| ① LISTEN | GSC API 自動串接 | 🔴 高 | 1 週 |
| ① LISTEN | GA4 Data API 串接 | 🟡 中 | 1 週 |
| ① LISTEN | 競品排名定期追蹤 | 🟡 中 | 3 天 |
| ② ANALYSE | 文章 → 排名 → 轉換歸因引擎 | 🔴 高 | 1 週 |
| ② ANALYSE | Cannibalization 偵測 | 🟡 中 | 3 天 |
| ③ PLAN | AI 選題推薦引擎（基於數據缺口） | 🔴 高 | 1 週 |
| ③ PLAN | Content Refresh 自動觸發規則 | 🔴 高 | 3 天 |
| ④ CREATE | Pipeline 已完成，Agent 升級見下方「Agent 架構」 | — | — |
| ⑤ REVIEW | 已完成（Streamlit UI + ForgeBase Admin） | — | — |
| ⑥ PUBLISH | ContentFlow FastAPI 路由層 | 🔴 高 | 1 週 |
| ⑥ PUBLISH | ForgeBase 推送 Adapter | 🔴 高 | 3 天 |
| ⑥ PUBLISH | WordPress 推送 Adapter | 🔴 高 | 1 週 |
| ⑦ LEARN | 成功模式分析器 | 🟡 中 | 1 週 |
| ⑦ LEARN | 自動 Content Refresh Pipeline | 🟡 中 | 3 天 |
| 跨階段 | 內部連結自動化 | 🟡 中 | 3 天 |
| 跨階段 | LSI / 語意關鍵字分析 | 🟢 低 | 3 天 |
| 跨階段 | Image Alt Text 自動生成 | 🟢 低 | 1 天 |
| **Agent 架構** | LangGraph StateGraph 重構（orchestrator.py） | 🔴 高 | 1 週 |
| **Agent 架構** | 品質閘門迴圈（SEO ≥ 85 才放行） | 🔴 高 | 3 天 |
| **Agent 架構** | 預算守衛（$2.00/篇硬上限 + 15 call 上限） | 🔴 高 | 2 天 |
| **Agent 架構** | 決策透明日誌（每步 reason + confidence） | 🟡 中 | 2 天 |
| **學習機制** | L1 模式記憶（文章屬性 vs 排名統計） | 🟡 中 | 1 週 |
| **學習機制** | 知識庫信心等級（待驗證/已驗證/通用規則） | 🟡 中 | 3 天 |
| **學習機制** | L1 學習成果注入 Agent（KB RAG 查詢） | 🟡 中 | 1 週 |
| **學習機制** | L2 策略優化（keyword ROI 分析） | 🟡 中 | 1 週 |
| **學習機制** | L3 競品適應（威脅偵測 + 自動防禦建議） | 🟡 中 | 1 週 |
| **學習機制** | Streamlit 知識庫管理 UI | 🟡 中 | 3 天 |
| **Off-Page** | 反向連結 Profile 監控（Ahrefs/Moz API） | 🟡 中 | 1 週 |
| **Off-Page** | 競品反向連結來源分析 | 🟡 中 | 3 天 |
| **Off-Page** | Unlinked Mention 偵測 | 🟢 低 | 3 天 |
| **Off-Page** | 斷鏈回收機會識別 | 🟢 低 | 3 天 |
| **Off-Page** | Outreach Email 範本生成（AI） | 🟢 低 | 2 天 |
| **Topic Cluster** | 關鍵字自動分群（Pillar/Cluster） | 🔴 高 | 1 週 |
| **Topic Cluster** | Topic Map 視覺化 + 缺口偵測 | 🟡 中 | 1 週 |
| **Topic Cluster** | 撰文時自動標記 Cluster 歸屬 + Pillar 回連 | 🟡 中 | 3 天 |
| **Topic Cluster** | Pillar Page 模板（ForgeBase） | 🟡 中 | 1 週 |
| **技術 SEO** | Core Web Vitals 監控（ForgeBase） | 🟡 中 | 1 週 |
| **技術 SEO** | 全站爬蟲掃描（斷鏈/孤頁/redirect chain）（ForgeBase） | 🟡 中 | 1.5 週 |
| **技術 SEO** | GSC 索引覆蓋率監控（ForgeBase） | 🟡 中 | 3 天 |
| **技術 SEO** | Mobile Usability 檢測（ForgeBase） | 🟢 低 | 3 天 |
| **技術 SEO** | 技術 SEO 健康儀表板（ForgeBase Admin） | 🟡 中 | 1 週 |
| **基礎設施** | SQLite → PostgreSQL 遷移 | 🔴 高 | 3 天 |
| **基礎設施** | 排程與背景任務系統（APScheduler） | 🔴 高 | 3 天 |
| **基礎設施** | FastAPI 認證機制（API Key） | 🔴 高 | 1 天 |
| **基礎設施** | ForgeBase Service Account 認證串接 | 🔴 高 | 1 天 |
| **基礎設施** | DB schema 擴充（SEORanking 擴欄 + 3 張新表） | 🔴 高 | 2 天 |
| **學習機制** | RAG 技術選型（向量庫 + Embedding + KB schema） | 🔴 高 | 1 週 |

---

## 5. 階段一：LISTEN — 採集信號

### 目的

從 Google 回收「發布後的真實結果」，作為所有後續決策的數據基礎。

### 5.1 Google Search Console API 串接

**現況**：

| 系統 | 狀態 |
|------|------|
| ContentFlow | ❌ 完全未實作（`SEORanking` 資料表存在但無寫入來源） |
| ForgeBase | ⚠️ `seo_optimize.py` 接受 GSC 參數但需手動輸入 |

**開發內容**：

```python
# 新增檔案：src/contentflow/tools/gsc.py

class GSCClient:
    """Google Search Console API 串接"""

    async def get_page_performance(
        self,
        site_url: str,
        start_date: str,
        end_date: str,
    ) -> list[PagePerformance]:
        """
        回傳每個頁面的：
        - 關鍵字（query）
        - 曝光次數（impressions）
        - 點擊次數（clicks）
        - 平均排名（position）
        - CTR
        """

    async def get_keyword_rankings(
        self,
        site_url: str,
        keywords: list[str],
    ) -> list[KeywordRanking]:
        """指定關鍵字的排名追蹤"""

    async def sync_to_db(self, project_id: int):
        """定期同步 GSC 數據到 ContentFlow SEORanking 資料表"""
```

**資料寫入目標**：ContentFlow `SEORanking` 資料表（已存在，欄位需確認/擴充）

**排程**：每日自動執行一次（cron 或後端排程器）

### 5.2 GA4 Data API 串接

**現況**：

| 系統 | 狀態 |
|------|------|
| ContentFlow | ❌ 未實作 |
| ForgeBase | ✅ 前端 GA4 事件已埋設；✅ 自有行為追蹤已完成 |

**開發內容**：

```python
# 新增檔案：src/contentflow/tools/ga4.py

class GA4Client:
    """GA4 Data API 串接"""

    async def get_page_metrics(
        self,
        property_id: str,
        start_date: str,
        end_date: str,
    ) -> list[PageMetrics]:
        """
        回傳每個頁面的：
        - 活躍用戶數
        - 平均參與時間
        - 跳出率
        - 轉換事件（表單提交 / RFQ）
        """
```

**備註**：ForgeBase 客戶可用自有追蹤替代 GA4；WordPress 客戶必須用 GA4。

### 5.3 競品排名監控

**現況**：ContentFlow 的 `tools/serp.py` 可查即時 SERP，但無定期追蹤。

**開發內容**：

- 新增 `CompetitorRanking` 資料表
- 每週自動對目標關鍵字跑一次 SERP，記錄競品排名變化
- 偵測「競品新進前 10 名」→ 觸發閉環 ③ PLAN 推薦應對

---

## 6. 階段二：ANALYSE — 歸因分析

### 目的

將採集到的信號（排名、流量、轉換）歸因到每篇文章，回答「這篇文章帶來了什麼結果」。

### 6.1 文章表現歸因引擎

**現況**：

| 系統 | 狀態 |
|------|------|
| ContentFlow | ❌ 無歸因機制 |
| ForgeBase | ✅ 訪客行為追蹤 → 意圖評分 → RFQ 完整鏈路（僅限 ForgeBase 網站） |

**開發內容**：

```python
# 新增檔案：src/contentflow/agents/analytics_agent.py

class ArticlePerformance:
    """單篇文章的表現歸因"""
    article_id: int
    url: str
    published_date: date

    # GSC 數據
    target_keyword: str
    current_rank: float
    rank_change_7d: float       # 7 天排名變化
    impressions_28d: int
    clicks_28d: int
    ctr: float

    # GA4 / ForgeBase 數據
    pageviews_28d: int
    avg_engagement_time: float
    bounce_rate: float

    # 轉換數據（ForgeBase 精確 / WordPress 模糊）
    conversions_28d: int        # RFQ / 表單提交
    conversion_value: float     # 預估價值

    # AI 分析
    performance_grade: str      # A / B / C / D / F
    recommended_action: str     # "maintain" / "refresh" / "rewrite" / "merge" / "deprioritize"
    action_reason: str          # 為什麼建議這個動作
```

### 6.2 Cannibalization 偵測

**現況**：兩個系統皆未實作

**開發內容**：

```
偵測規則：
同一個 project 下，如果有 2+ 篇文章
在同一個關鍵字上都有 impressions 但排名都在 P10+
→ 標記為 Cannibalization
→ 建議合併或重新分工
```

### 6.3 ForgeBase vs WordPress 歸因差異

| 歸因維度 | ForgeBase | WordPress |
|---------|-----------|-----------|
| 某篇文章帶來幾筆 RFQ | ✅ 精確（訪客行為鏈路） | ⚠️ GA4 conversion 事件歸因 |
| 訪客看了哪些頁面後轉換 | ✅ 完整路徑 | ⚠️ GA4 路徑分析（有取樣） |
| 詢價預估金額 | ✅ RFQ 表單含數量/金額 | ❌ 無（需自接 CRM） |
| 對閉環的影響 | 完整數據 → AI 決策更精準 | 核心數據（排名/CTR）仍足夠 |

---

## 7. 階段三：PLAN — AI 選題決策

### 目的

基於 ② 分析結果，AI 自動推薦下一步動作：寫新文、改舊文、補連結。

### 7.1 AI 選題推薦引擎

**現況**：ContentFlow 有關鍵字庫和內容日曆，但選題完全靠人工。

**開發內容**：

```python
# 新增到：src/contentflow/agents/planning_agent.py

async def generate_content_plan(project_id: int) -> ContentPlan:
    """
    基於數據自動推薦內容計劃

    推薦邏輯：
    1. 關鍵字缺口：有搜尋量但我們沒有對應文章的關鍵字
    2. 排名近首頁：P11-P20 的文章，Content Refresh 可推進前 10
    3. 競品弱點：競品排名但內容深度不足的主題
    4. 搜尋趨勢上升：GSC impressions 上升中的關鍵字
    5. 轉換高但流量低：已證明能帶來 RFQ，但曝光不夠

    輸出：
    - 優先排序的選題清單
    - 每個選題的預期影響與執行方式
    - 自動排入內容日曆
    """
```

### 7.2 Content Refresh 自動觸發規則

**現況**：兩個系統皆無

**開發內容**：

```
觸發條件（任一成立即推薦 Refresh）：
├── 排名下滑 > 5 個位置（連續 2 週）
├── 發布超過 6 個月且排名 P10–P30
├── 競品在同一關鍵字新進前 10
├── 文章 CTR 低於該位置應有的平均值
└── 被偵測到 Cannibalization
```

---

## 8. 階段四：CREATE — AI Agent 自主產文

### 目的

根據 ③ 的選題計劃，**AI Agent 自主決策文章策略並執行生產**——不再是固定順序 Pipeline，而是目標導向的智慧 Agent。

### 現況：✅ Pipeline 已完成（待升級為 Agent）

| 流程 | Agent | 狀態 |
|------|-------|------|
| SERP + PubMed 研究 | Research Agent | ✅ |
| 搜尋意圖 + 策略分析 | Strategy Agent | ✅ |
| 三階段撰文 | Writing Agent | ✅ |
| SEO 規則評分 | SEO Check Agent | ✅ |
| SEO 微調修正 | SEO QA Agent | ✅ |
| 事實查核 | FactCheck Agent | ✅ |
| 配圖 Prompt | Image Agent | ✅ |
| 端到端 Pipeline | Orchestrator | ✅ 固定順序 → ❌ 待升級為 LangGraph Agent |

### 現狀問題（Pipeline 思維 vs Agent 思維）

```
現在（Pipeline）                        未來（Agent）
──────────────                         ──────────
固定 5 步，每次都一樣                    目標導向：「讓這篇排進前 10」
每步呼叫 LLM 一次                       StateGraph 條件迴圈：根據狀態動態分支
無工具選擇                              動態選用工具：SERP/PubMed/GSC/知識庫
SEO 只修一次                            SEO ≥ 85 才放行，否則自動重修（最多 3 輪）
零記憶                                  查詢知識庫：上次同類 keyword 什麼策略有效
寫完就結束                              發布後追蹤 → 觸發 Content Refresh
```

### Agent 自主決策範例

```
輸入：keyword = "膝蓋長骨刺怎麼辦"

Agent 思考過程：
├── 查 KB：同類「骨科 + 症狀」keyword，How-to 格式平均排名 #4 > Listicle #8
│   → 決定用 How-to 格式
├── 查 SERP：前 3 名平均 3200 字，都有影片
│   → 決定目標 3800 字 + 配圖 Prompt
├── 查 PubMed：找到 12 篇相關文獻，3 篇高品質 RCT
│   → 決定引用 3 篇 RCT + 1 篇 Meta-analysis
├── 撰文 → SEO Check = 72 分（H2 缺主關鍵字）
│   → 自動觸發 SEO QA 修正
├── 修正後 SEO Check = 81 分（缺 FAQ schema）
│   → Agent 判斷 SERP 有 Featured Snippet → 加 FAQ
├── 最終 SEO Check = 89 分 ✅ 通過
│   → 輸出草稿 + 決策日誌
└── 控制層：總共 11 次 LLM 呼叫，成本 $1.34（< $2.00 預算）✅
```

### 閉環升級需求

| 升級項目 | 說明 | 狀態 |
|---------|------|------|
| **LangGraph StateGraph 重構** | orchestrator.py 改為 Graph 節點 + 條件邊 | ❌ 待開發 |
| **StateGraph 條件迴圈** | 狀態驅動分支，工具按需選用 | ❌ 待開發 |
| **品質閘門迴圈** | SEO ≥ 85 才放行，最多 3 輪重修 | ❌ 待開發 |
| 注入歷史學習成果 | ⑦ LEARN 的成功模式自動注入 Agent 決策 | ❌ 待開發 |
| Content Refresh 模式 | 不從零撰寫，而是基於現有文章 + 缺漏分析進行增補 | ❌ 待開發 |
| 內部連結自動建議 | 撰文時自動推薦連結到站內其他相關文章 | ⚠️ `suggest_internal_links()` 存在但未串接 |

---

## 9. 階段五：REVIEW — 人工審閱關卡

### 目的

確保 AI 產出符合品牌標準、技術正確性、法規合規。

### 現況：✅ 已完成

| 審閱介面 | 系統 | 狀態 |
|---------|------|------|
| Streamlit AI 研究中心 | ContentFlow | ✅ 完整（五步驟進度 + Markdown 預覽 + SEO 評分 + 事實查核結果） |
| ForgeBase Admin 內容管理 | ForgeBase | ✅ 完整（Page 編輯 + SEO 欄位 + AI 優化建議） |

### 閉環升級需求

| 升級項目 | 說明 | 狀態 |
|---------|------|------|
| 審閱通知推送（Email / Slack） | 草稿就緒時自動通知審閱人 | ❌ 待開發 |
| 審閱回饋回收 | 人工修改的內容回饋給 ⑦ LEARN（「人改了什麼 → AI 以後就不犯」） | ❌ 待開發 |

---

## 10. 階段六：PUBLISH — 雙平台發布

### 目的

審閱通過的內容自動推送到目標網站平台。

### 10.1 ContentFlow FastAPI 路由層

**現況**：❌ ContentFlow 目前只有 CLI + Streamlit，無 API 供外部呼叫。

**開發內容**：

```python
# 新增檔案：src/contentflow/api.py（FastAPI 路由層）

# ── 主動觸發 ──
POST   /api/v1/articles/generate
       →  觸發完整 Pipeline（keyword + project_id）
       →  回傳 task_id

GET    /api/v1/articles/{id}/status
       →  Pipeline 執行進度

# ── 草稿取回 ──
GET    /api/v1/articles/{id}/draft
       →  ArticleDraft（Markdown + meta + SEO score + factcheck）

# ── 發布推送 ──
POST   /api/v1/articles/{id}/publish
       →  推送到指定平台（forgebase / wordpress）
       →  回傳發布 URL

# ── 數據回寫 ──
POST   /api/v1/articles/{id}/performance
       →  接收 GSC / GA4 數據（供 ⑦ LEARN 使用）
```

### 10.1.1 認證與授權設計

ContentFlow API 所有端點均需認證，Phase 1 採用 API Key 方案：

```python
# src/contentflow/api.py — 認證中介層
from fastapi import Security, Depends, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(api_key_header)):
    if api_key != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# 所有寫入端點加上依賴
@app.post("/api/v1/articles/generate", dependencies=[Depends(verify_api_key)])
```

| 端點 | 認證需求 | 說明 |
|------|---------|------|
| `GET /status` | API Key | 讀取也需驗證（含敏感進度資訊） |
| `POST /generate` | API Key | 會觸發 LLM 呼叫，必須保護 |
| `POST /publish` | API Key + project_id 校驗 | 需確認呼叫者有權操作該專案 |
| `POST /performance` | API Key | 數據寫入需驗證 |

### 10.2 ForgeBase 推送 Adapter

**現況**：❌ 未實作

**目標 API**：ForgeBase REST API（需 `require_content_editor` 權限）

**認證方式**：ContentFlow 以 Service Account 身分呼叫 ForgeBase API。需在 ForgeBase 建立專用 service user（角色 = `content_editor`），取得 JWT token 或長期 API Key。

**三步驟推送流程**：

```
Step 1: 建立 PageBrief
POST /api/v1/content/briefs
{
  "target_page_type": "blog_post",
  "target_slug": draft.slug,
  "title_draft": draft.title,
  "primary_keyword": primary_keyword,
  "secondary_keywords": secondary_keywords,  // JSON array
  "word_count_target": draft.word_count,
  "locale": project_context.locale
}
→ 回傳 brief_id

Step 2: 建立 Page（草稿狀態）
POST /api/v1/content/pages
{
  "page_type": "blog_post",        ← 所有 SEO 文章統一為 blog_post
  "slug": draft.slug,
  "title": draft.title,
  "body": convert_body(draft.content_markdown),  ← 見下方格式說明
  "seo_title": draft.meta_title,
  "seo_description": draft.meta_description,
  "structured_data": draft.faq_schema_json,
  "locale": project_context.locale,
  "status": "draft",               ← 預設草稿，人工確認後才發布
  "brief_id": brief_id             ← 關聯 Step 1 的 brief
}
→ 回傳 page_id

Step 3: 人工審閱通過後發布
POST /api/v1/content/pages/{page_id}/publish
→ status 自動改為 "published"，寫入 published_at
```

**body 格式轉換**：

ForgeBase Page 的 `body` 欄位接受 richtext 或 blocks JSON。需確認 ForgeBase 前端渲染機制後決定：

| ForgeBase 前端渲染 | 轉換方式 | 複雜度 |
|-------------------|---------|--------|
| 直接渲染 HTML | Markdown → HTML（`markdown` 套件） | 低 |
| Block-based JSON（類 Notion） | Markdown → AST → Block JSON | 中高 |
| 直接支援 Markdown | 無需轉換 | 零 |

**欄位映射**（修正版）：

| ContentFlow 欄位 | ForgeBase 欄位 | 說明 |
|-----------------|---------------|------|
| `meta_title` | `seo_title` | |
| `meta_description` | `seo_description` | |
| `slug` | `slug` | |
| `content_markdown` | `body`（需轉換格式） | 見上方格式轉換 |
| `faq_schema_json` | `structured_data` | JSON-LD 字串 |
| 固定值 `"blog_post"` | `page_type` | ⚠️ 不是 `article_type` 直接映射 |
| `primary_keyword` | `PageBrief.primary_keyword` | 透過 brief_id 關聯 |

### 10.3 WordPress 推送 Adapter

**現況**：`config.py` 有 WP 設定欄位，❌ 無實作程式碼

**開發內容**：

```python
# 新增檔案：src/contentflow/publishers/wordpress.py

class WordPressPublisher:
    """WordPress REST API v2 串接"""

    async def publish_draft(self, draft: ArticleDraft) -> PublishResult:
        """
        POST /wp-json/wp/v2/posts
        - Markdown → HTML（markdown 套件）
        - status: "draft"（人工確認後改 publish）
        - Yoast / RankMath meta 欄位寫入
        - 分類 / Tag 自動對應
        - Featured Image 上傳（如有）
        """

    async def update_post(self, post_id: int, draft: ArticleDraft):
        """Content Refresh 時更新既有文章"""

    async def get_post_url(self, post_id: int) -> str:
        """取得發布 URL 供 ① LISTEN 追蹤"""
```

**支援的 SEO 外掛**：

| 外掛 | meta key 格式 | 支援 |
|------|--------------|------|
| Yoast SEO | `_yoast_wpseo_title`、`_yoast_wpseo_metadesc` | 計劃支援 |
| RankMath | `rank_math_title`、`rank_math_description` | 計劃支援 |
| All in One SEO | `_aioseo_title`、`_aioseo_description` | 計劃支援 |

### 10.4 發布端抽象層

```python
# 新增檔案：src/contentflow/publishers/base.py

class BasePublisher(ABC):
    """所有發布平台的抽象基底"""

    @abstractmethod
    async def publish_draft(self, draft: ArticleDraft) -> PublishResult: ...

    @abstractmethod
    async def update_post(self, post_id, draft: ArticleDraft) -> PublishResult: ...

    @abstractmethod
    async def get_post_url(self, post_id) -> str: ...

# 實作：
# ├── ForgeBasePublisher(BasePublisher) — 深度整合（精確歸因 + 意圖評分 + Dynamic CTA）
# └── WordPressPublisher(BasePublisher) — 主流市場（Yoast/RankMath + GA4 歸因）
```

---

## 11. 階段七：LEARN — 三層學習與自動進化

### 目的

這是閉環的靈魂，也是系統從「工具」變成「Agent」的核心——系統不只是從歷史數據中找模式，而是建立**三層遞進的學習機制**，讓每一輪產出的內容都比上一輪更精準。

### 11.0 三層學習架構總覽

```
                    ┌──────────────────────┐
                    │   知識庫（KB）         │
                    │                      │
                    │ L1: 模式記憶          │◄─── GSC 每日同步
                    │   • 排名數據           │◄─── 文章屬性 vs 表現統計
                    │   • 格式/字數/FAQ 勝率  │
                    │                      │
                    │ L2: 策略優化          │◄─── ROI 分析
                    │   • keyword 投入產出   │◄─── Content Refresh 效果
                    │   • 最佳發布時機       │
                    │                      │
                    │ L3: 競品適應          │◄─── 定期 SERP 監控
                    │   • 競品新內容偵測     │◄─── 排名變化 → 防禦策略
                    │   • 市場趨勢變化       │
                    └──────────┬───────────┘
                               │ 每次產文時 RAG 查詢
                               ▼
                  ┌──────────────────────────────┐
                  │  Strategy Agent（升級版）       │
                  │                              │
                  │ 「根據 KB：                     │
                  │   同類 keyword How-to 排名 #4   │
                  │   Listicle 排名 #8              │
                  │   → 這次用 How-to」             │
                  └──────────────────────────────┘
```

| 層級 | 學什麼 | 怎麼學 | 效果 | 階段 |
|------|--------|--------|------|------|
| **L1: 模式記憶** | 哪種文章結構/字數/格式排名好 | 統計 GSC 數據 vs 文章屬性 | 第 10 篇比第 1 篇好 30%+ | Phase 3 |
| **L2: 策略優化** | 哪個 keyword 值得投入、何時 refresh | 分析 ROI（排名提升 / token 成本） | 自動砍掉低 ROI keyword | Phase 3 |
| **L3: 競品適應** | 競品新內容出現時如何回應 | 定期 SERP 監控 + 差異分析 | 排名掉了自動觸發防禦 | Phase 4 |

### 11.1 L1 — 模式記憶（Pattern Memory）

**現況**：兩個系統皆無

**開發內容**：

```python
# 新增檔案：src/contentflow/agents/learning_agent.py

async def analyze_success_patterns(project_id: int) -> LearningReport:
    """
    L1 模式記憶：分析所有已發布文章的表現數據，找出成功因子

    分析維度：
    ├── 文章長度 vs 排名（最佳字數區間）
    ├── 文章格式（How-to / Listicle / 比較文）vs 排名
    ├── FAQ 數量 vs CTR
    ├── PubMed 引用數量 vs 排名
    ├── Title 格式（含數字？含品牌？含年份？）vs CTR
    ├── H2 數量 vs 排名
    ├── 搜尋意圖分類準確度 vs 排名
    ├── 內部連結數量 vs 排名
    └── 發布後多久達到穩定排名

    輸出：
    - 成功文章的共同特徵（知識庫條目，標記「待驗證」）
    - 失敗文章的共同問題
    - 下一輪 Agent 決策的建議參數
    """
```

**知識庫信心等級機制**：

```
Agent 從 GSC 數據學到：「How-to 格式比 Listicle 排名好」
     ↓
寫入知識庫 → 標記為「待驗證」（< 5 篇數據支持）
     ↓
累積 5+ 篇同類數據支持 → 自動升級為「已驗證」
     ↓
累積 10+ 篇 + 跨專案一致 → 升級為「通用規則」
     ↓
人可以隨時在 Streamlit 看到 Agent 學了什麼、手動推翻
```

### 11.2 L2 — 策略優化（Strategy Optimization）

```python
async def optimize_content_strategy(project_id: int) -> StrategyUpdate:
    """
    L2 策略優化：分析投入產出比，最佳化資源配置

    分析維度：
    ├── keyword ROI = (排名提升 × 搜尋量) / token 成本
    ├── Content Refresh 效果 = 修改前後排名差 / 修改成本
    ├── 最佳發布時機（星期幾/幾月效果最好）
    ├── keyword 飽和度（已有文章 vs 潛在 keyword）
    └── Topic Cluster 投資回報（整個 cluster vs 單篇）

    輸出：
    - 高 ROI keyword 加碼建議
    - 低 ROI keyword 停止建議
    - Content Refresh 優先排序
    - 資源配置建議（新文 vs 更新舊文的比例）
    """
```

### 11.3 L3 — 競品適應（Competitor Adaptation）

```python
async def detect_competitor_threats(project_id: int) -> ThreatReport:
    """
    L3 競品適應：偵測競品動態，自動觸發防禦策略

    偵測機制：
    ├── 每週 SERP 監控：我們排前 10 的 keyword，競品排名變化
    ├── 新進入者偵測：之前不在 SERP 的域名出現在前 10
    ├── 內容升級偵測：競品文章字數/結構/更新日期變化
    └── Featured Snippet 搶奪偵測

    自動回應：
    ├── 排名被超越 → 自動排入 Content Refresh 佇列
    ├── 新競品出現 → 差異分析 + 補強建議
    ├── Featured Snippet 被搶 → FAQ/Table 格式調整建議
    └── 所有回應僅為「建議」，需人在 REVIEW 確認
    """
```

### 11.4 學習成果自動注入 Agent

```
LearningReport + StrategyUpdate → 自動寫入 Project 知識庫 → Agent 每次產文時 RAG 查詢

範例注入結果：
「本專案過去 30 篇文章分析結果（L1 模式記憶）：
  - 排名前 5 的文章平均含 4.2 個 FAQ → 信心：已驗證（8 篇支持）
  - 含 PubMed 引用的文章平均排名比不含的高 8.3 位 → 信心：已驗證（12 篇支持）
  - Title 含具體數字的 CTR 高 23% → 信心：待驗證（3 篇支持）
  - How-to 格式排名優於 Listicle 平均 4 位 → 信心：通用規則（跨 3 專案一致）
  
  策略建議（L2 策略優化）：
  - 「膝蓋」cluster 已有 8 篇，ROI 遞減 → 建議轉向「腰椎」cluster
  - Content Refresh 優先：3 篇排名 #11-15 的文章（最低成本進前 10）」
```

### 11.5 自動 Content Refresh Pipeline

**現況**：ContentFlow 有完整 CREATE Pipeline，但只支援「從零撰寫」。

**開發內容**：

```
Refresh 模式：
1. 讀取既有文章（從 ForgeBase / WordPress 拉回）
2. 比對新 SERP 結果（競品有什麼新內容？）
3. AI 分析缺漏（缺 FAQ？缺規格比較？內部連結不足？）
4. 局部增補（不全部重寫，只補缺的段落）
5. 重新跑 SEO Check（Agent 品質閘門）
6. 推送更新版本
```

### 11.6 RAG 技術選型與知識庫架構

L1/L2 學習成果要「注入 Agent」，核心技術是 RAG（Retrieval-Augmented Generation）。目前 codebase 中**零** RAG 相關程式碼，需從頭建置。

**向量資料庫選型**：

| 方案 | 優點 | 缺點 | 建議 |
|------|------|------|------|
| **ChromaDB**（本地） | 零基礎設施、Python 原生、輕量 | 不支援多 process 併發寫入 | ✅ Phase 3 MVP 首選 |
| **PostgreSQL + pgvector** | 與主 DB 共用、支援併發、可 JOIN 關聯查詢 | 需安裝 pgvector 擴充 | ✅ Phase 3+ 遷移目標 |
| Pinecone / Weaviate（雲端） | 全託管、高效能 | 月費、資料出境、供應商鎖定 | ❌ 不建議（過度依賴外部服務） |

**Embedding Model 選型**：

| 方案 | 維度 | 成本 | 建議 |
|------|------|------|------|
| `text-embedding-3-small`（OpenAI） | 1536 | $0.02/1M tokens | ✅ 首選（已有 OpenAI key） |
| `text-embedding-3-large`（OpenAI） | 3072 | $0.13/1M tokens | 備選（精度需求高時） |
| `sentence-transformers/all-MiniLM-L6-v2`（本地） | 384 | 免費 | 備選（離線 / 成本敏感） |

**知識庫 Document Schema**：

```python
# 每一條「知識」的結構
class KnowledgeDocument:
    id: str                         # UUID
    project_id: int | None          # null = 跨專案通用規則
    category: str                   # "format_pattern" / "keyword_strategy" / "timing" / "content_structure"
    pattern_text: str               # 人可讀的模式描述（用於 RAG 檢索）
    evidence_summary: str           # 統計摘要（如「8 篇支持，平均排名差 +4.2 位」）
    confidence_level: str           # "unverified" / "verified" / "universal"
    evidence_count: int             # 支持數據筆數
    metadata: dict                  # 原始統計數據（JSON）
    embedding: list[float]          # 向量（ChromaDB 儲存）
    created_at: datetime
    updated_at: datetime
```

**RAG 查詢策略**：

```
Agent 撰文前 → 組合查詢：
  query = f"{keyword} {article_type} {industry}"
  
  → ChromaDB similarity_search(query, k=5, filter={"project_id": project_id})
  → 再查 universal rules: similarity_search(query, k=3, filter={"confidence_level": "universal"})
  → 合併去重 → 注入 Strategy Agent prompt

查詢限制：
  • 每篇文章最多查 8 條知識（避免 prompt 過長）
  • "unverified" 知識以「僅供參考」語氣注入
  • "verified" / "universal" 以「建議遵循」語氣注入
```

**跨專案知識隔離**：

```
Project A 的知識 → 只有 Project A 查得到
通用規則（project_id = null）→ 所有專案都查得到
升級路徑：verified（單專案）→ universal（跨專案）需滿足：
  • 3+ 個不同專案有一致結論
  • 人工覆核確認（Streamlit 知識庫 UI）
```

---

## 12. Off-Page SEO — 反向連結監控與策略

### 目的

反向連結仍是 Google 排名前三大因素。雖然「拿到連結」需要人工，但「發現機會」和「監控現狀」可以完全自動化。

### 系統歸屬：ContentFlow

ContentFlow 已有 SERP 分析能力，反向連結監控是其自然延伸。

### 12.1 可自動化的部分（系統執行）

| 功能 | 做法 | 自動化程度 | 額外 API |
|------|------|-----------|---------|
| 反向連結 Profile 追蹤 | 串 Ahrefs API / Moz API，每週拉取自站連結數據 | ✅ 全自動 | 💰 Ahrefs $99+/月 或 Moz $99+/月 |
| 競品反向連結來源分析 | 同上 API，比對「競品有、我們沒有」的連結來源 | ✅ 全自動 | 同上 |
| Unlinked Mention 偵測 | 串 Google Alerts API 或 Brand24 API | ✅ 全自動 | Brand24 $79+/月 或 Google Alerts 免費 |
| 斷鏈回收機會識別 | 掃描外部網站指向我們但回 404 的連結 | ✅ 全自動 | 同 Ahrefs/Moz |
| Outreach Email 範本 | AI 產出聯繫信範本（品牌提及 → 請求加連結） | ✅ 全自動 | LLM API（現有） |

**開發內容**：

```python
# 新增檔案：src/contentflow/tools/backlink.py

class BacklinkClient:
    """反向連結監控（Ahrefs API / Moz API）"""

    async def get_backlink_profile(self, domain: str) -> BacklinkProfile:
        """
        回傳：
        - 總反向連結數 / referring domains 數
        - DA（Domain Authority）
        - 新增 / 失去的連結（最近 30 天）
        """

    async def get_competitor_backlinks(
        self, my_domain: str, competitor_domains: list[str]
    ) -> list[BacklinkGap]:
        """
        找出「競品有但我們沒有」的連結來源
        → 推薦 outreach 目標
        """

    async def find_unlinked_mentions(self, brand_name: str) -> list[UnlinkedMention]:
        """
        偵測品牌名被提及但無超連結的頁面
        → 推薦聯繫要連結
        """

    async def find_broken_backlinks(self, domain: str) -> list[BrokenBacklink]:
        """
        找出外部連結指向我們 404 的情況
        → 建議設定 301 重定向或修復
        """
```

### 12.2 無法自動化的部分（人工執行）

| 工作 | 說明 | 系統輔助 |
|------|------|---------|
| Guest Post 合作談判 | 聯繫目標站長、協商內容 | AI 產出 outreach email 範本 |
| 媒體 PR / HARO | 回應記者需求、提供專家意見 | 系統推薦可回應的 HARO 查詢 |
| 業界資源交換 | 策略合作、互相連結 | 系統識別潛在合作對象 |

### 12.3 反向連結數據進入閉環

```
BacklinkClient 每週掃描
        ↓
② ANALYSE：文章 A 有 3 個反向連結 → 排名 P5
           文章 B 有 0 個反向連結 → 排名 P18
        ↓
⑦ LEARN：「有反向連結的文章平均排名高 12 位」
        ↓
③ PLAN：推薦優先為排名 P11-P20 的文章執行 link building
```

### 12.4 務實建議

> Off-Page SEO 監控需要昂貴的第三方 API（$99+/月），且發現機會後仍需人工執行。
> **建議列為進階 / Premium 功能**，不納入基礎方案。

---

## 13. Topic Cluster — 主題叢集架構

### 目的

將零散的文章組織成有結構的主題叢集（Pillar + Cluster），強化站內語意關聯和內部連結，讓 Google 視你為該主題的權威來源。

### 系統歸屬：ContentFlow（規劃層）+ ForgeBase（實作層）

### 13.1 什麼是 Topic Cluster

```
                    ┌─────────────────────┐
                    │   Pillar Page        │
                    │ 「不鏽鋼螺栓完整指南」│
                    │  （長篇、高權重）     │
                    └──────────┬──────────┘
                               │
          ┌────────────────────┼────────────────────┐
          │                    │                    │
   ┌──────▼──────┐    ┌───────▼──────┐    ┌───────▼──────┐
   │ Cluster 文章 │    │ Cluster 文章 │    │ Cluster 文章 │
   │ 「DIN 931 vs │    │ 「316 不鏽鋼 │    │ 「螺栓扭矩   │
   │  DIN 933」   │    │  耐腐蝕測試」│    │  規範對照表」 │
   └──────────────┘    └──────────────┘    └──────────────┘
   
   ↕ 所有 Cluster 文章都雙向連回 Pillar
   ↕ Cluster 之間也互相連結
```

### 13.2 ContentFlow 負責的部分（100% 可自動化）

| 功能 | 做法 | 自動化 | 額外成本 |
|------|------|--------|---------|
| **關鍵字自動分群** | 分析關鍵字庫 → AI 依語意相似度分群 → 最大搜尋量的母題為 Pillar | ✅ 全自動 | LLM（現有）|
| **Topic Map 生成** | 從分群結果自動產出 Topic Map（Pillar → Cluster 關係） | ✅ 全自動 | 零成本 |
| **缺口偵測** | 「這個 Cluster 下有 SERP 機會但你還沒有對應文章」 | ✅ 全自動 | 零成本 |
| **Pillar/Cluster 標記** | 撰文時自動判定文章屬於哪個 Cluster，加入連回 Pillar 的連結 | ✅ 全自動 | 零成本 |
| **內部連結建議** | 比對同 Cluster 現有文章，推薦互相連結的配對 | ✅ 全自動 | 零成本 |
| **覆蓋率報表** | 每個 Topic Cluster 的完成度（幾篇寫了 / 幾篇未寫） | ✅ 全自動 | 零成本 |

**開發內容**：

```python
# 新增檔案：src/contentflow/agents/cluster_agent.py

class TopicCluster:
    """單一主題叢集"""
    pillar_keyword: str             # 支柱關鍵字
    pillar_title: str               # 支柱頁標題
    cluster_keywords: list[str]     # 衛星關鍵字
    cluster_articles: list[int]     # 已發布的衛星文章 IDs
    coverage_rate: float            # 覆蓋率（0.0–1.0）
    gaps: list[str]                 # 尚未覆蓋的衛星主題

async def build_topic_clusters(project_id: int) -> list[TopicCluster]:
    """
    從關鍵字庫自動建立 Topic Cluster 架構

    流程：
    1. 讀取所有關鍵字 → AI 語意分群
    2. 每群中搜尋量最高者 → Pillar
    3. 其餘 → Cluster keywords
    4. 比對現有文章 → 計算覆蓋率
    5. 找出缺口 → 排入 ③ PLAN
    """

async def suggest_internal_links(
    article_id: int,
    project_id: int,
) -> list[InternalLinkSuggestion]:
    """
    針對一篇文章，推薦該連結到哪些同 Cluster 文章
    以及該被哪些文章連過來
    """

async def detect_cluster_gaps(project_id: int) -> list[ClusterGap]:
    """
    偵測每個 Topic Cluster 的缺口
    → 推薦新文章選題
    → 排入 ③ PLAN 的推薦清單
    """
```

**資料模型擴充**：

```python
# 新增至 models/database.py

class TopicCluster(Base):
    """主題叢集"""
    id: int
    project_id: int
    pillar_keyword: str         # 支柱關鍵字
    pillar_title: str           # 支柱頁標題
    pillar_article_id: int      # 支柱頁對應的文章 ID（可為 null）
    status: str                 # "planned" / "building" / "complete"
    created_at: datetime

class ClusterMember(Base):
    """叢集成員（衛星文章）"""
    id: int
    cluster_id: int             # FK → TopicCluster
    keyword: str                # 衛星關鍵字
    article_id: int | None      # 對應文章（null = 尚未撰寫）
    link_to_pillar: bool        # 是否已含連回 Pillar 的連結
```

### 13.3 ForgeBase 負責的部分

| 功能 | 說明 | 狀態 |
|------|------|------|
| Pillar Page 模板 | 不同於一般文章的長頁面結構（TOC + 各段摘要 + 連結到 Cluster 文章） | ❌ 待開發 |
| Topic Cluster 導覽 UI | 前台：讀者可從 Pillar 探索所有相關 Cluster 文章 | ❌ 待開發 |
| Cluster 內部連結渲染 | 在文章頁面底部自動顯示「相關文章」區塊 | ❌ 待開發 |

### 13.4 Topic Cluster 進入閉環

```
③ PLAN：AI 選題推薦引擎
    ↓
    「Cluster A 覆蓋率只有 40%（3/8 篇），建議本月補 2 篇」
    「Cluster B 的 Pillar 排名 P15，但衛星文平均排名 P8
     → Pillar 需要 Content Refresh + 更多 Cluster 回連」
    ↓
④ CREATE：撰文時自動標記 Cluster 歸屬 + 加入 Pillar 回連
    ↓
⑦ LEARN：「Cluster 覆蓋率 > 70% 的主題，Pillar 排名平均高 5 位」
```

---

## 14. 技術 SEO 健康監控

### 目的

確保網站本身的技術基礎不拖垮內容 SEO 效果。一篇好文章如果在一個速度慢、斷鏈多、行動版破版的網站上，排名也上不去。

### 系統歸屬：ForgeBase（WordPress 客戶需自行處理）

技術 SEO 是**網站平台的健康問題**，不是內容問題，因此由 ForgeBase 負責。

### 14.1 Core Web Vitals 監控

**現況**：ForgeBase ❌ 未實作

**開發內容**：

```
資料來源：
├── CrUX API（Chrome User Experience Report）— 真實用戶數據
├── PageSpeed Insights API — 實驗室數據
└── 可選：web-vitals.js 前端即時上報

監控指標：
├── LCP（Largest Contentful Paint）→ 目標 < 2.5s
├── INP（Interaction to Next Paint）→ 目標 < 200ms
├── CLS（Cumulative Layout Shift）→ 目標 < 0.1

排程：
├── 每週自動檢測全站 Top 50 頁面
├── 指標惡化時 → 通知 Admin
└── 數據存入 DB → 趨勢圖表
```

### 14.2 全站爬蟲掃描

**現況**：ForgeBase ❌ 未實作

**開發內容**：

```
自建輕量爬蟲（或串 Screaming Frog API / Sitebulb API）：
├── 斷鏈偵測（內部 404 / 外部 404）
├── Redirect Chain 偵測（超過 2 跳的重定向鏈）
├── Orphan Pages 偵測（沒有內部連結指向的頁面）
├── 重複內容偵測（相似度 > 85% 的頁面配對）
├── 缺少 Alt Text 的圖片
├── H1 缺失或重複
└── 過深頁面（點擊深度 > 4 層）

排程：每週或每月自動掃描
輸出：健康報告 + 修復建議清單
```

### 14.3 GSC 索引覆蓋率監控

**現況**：ForgeBase ⚠️ GSC 參數可手動輸入，無自動化

**開發內容**：

```
GSC URL Inspection API / Index Coverage Report：
├── 已索引頁面數
├── 排除的頁面數（noindex / canonical 指向其他 / 404）
├── 爬取異常（伺服器錯誤 / 超時 / DNS 錯誤）
├── 新提交 URL 的索引狀態追蹤

觸發動作：
├── 索引數下降 > 10% → 警示
├── 新文章發布 3 天後未被索引 → 主動提交 + 警示
└── 大量 404 增加 → 與重定向管理聯動
```

### 14.4 Mobile Usability 檢測

**現況**：ForgeBase ❌ 未實作

**開發內容**：

```
GSC Mobile Usability API：
├── 文字太小無法閱讀
├── 可點擊元素間距太近
├── 內容寬度超出螢幕
├── 使用不相容外掛

觸發動作：問題偵測 → Admin 通知 + 修復建議
```

### 14.5 技術 SEO 健康儀表板（ForgeBase Admin）

```
┌─────────────────────────────────────────────────┐
│  🏥 技術 SEO 健康報告    最後掃描：2026-04-12    │
├─────────────────────────────────────────────────┤
│                                                  │
│  Core Web Vitals                                 │
│  ├── LCP: 1.8s  ✅ Good                         │
│  ├── INP: 156ms ✅ Good                         │
│  └── CLS: 0.08  ✅ Good                         │
│                                                  │
│  索引覆蓋率                                      │
│  ├── 已索引：187 頁（↑12 vs 上週）              │
│  ├── 排除：23 頁（正常 noindex）                 │
│  └── 錯誤：2 頁 ⚠️（伺服器 500 → 查看詳情）    │
│                                                  │
│  爬蟲健康                                        │
│  ├── 斷鏈：4 個 🔴（→ 建議修復清單）            │
│  ├── Redirect Chain：1 個 🟡                     │
│  ├── Orphan Pages：7 個 🟡                       │
│  ├── 重複內容：0 ✅                              │
│  └── 缺少 Alt Text：12 張圖 🟡                  │
│                                                  │
│  Mobile Usability                                │
│  └── 所有頁面通過 ✅                             │
│                                                  │
│  綜合健康分數：87/100 🟢                         │
│  上週：82/100（↑5）                              │
└─────────────────────────────────────────────────┘
```

### 14.6 WordPress 客戶的替代方案

技術 SEO 監控僅內建於 ForgeBase。WordPress 客戶的替代方案：

| 功能 | ForgeBase | WordPress 替代 |
|------|-----------|---------------|
| Core Web Vitals | ✅ 內建 | Google PageSpeed Insights（手動）|
| 全站爬蟲掃描 | ✅ 內建 | Screaming Frog / Ahrefs Audit |
| 索引覆蓋率 | ✅ 內建 | GSC 介面（手動檢查）|
| Mobile Usability | ✅ 內建 | GSC 介面（手動檢查）|

> **這是 ForgeBase 相對 WordPress 的差異化賣點之一**。

---

## 15. 系統職責分工：ContentFlow vs ForgeBase

### 分工原則

> **ContentFlow 管「內容層面的 SEO 決策」，ForgeBase 管「網站層面的 SEO 健康」。**

### 完整職責分工表

| SEO 面向 | 子項目 | 歸屬 | 說明 |
|---------|--------|------|------|
| **關鍵字研究** | 關鍵字發掘、分群 | ContentFlow | 內容決策 |
| | 搜尋意圖分類 | ContentFlow | 內容決策 |
| **競品分析** | SERP 競品結構 | ContentFlow | 內容分析 |
| | 競品反向連結分析 | ContentFlow | 內容分析延伸 |
| **On-Page SEO** | Title / Meta / 關鍵字密度 | ContentFlow（生成）+ ForgeBase（儲存/渲染） | 雙方協作 |
| | JSON-LD Schema | ContentFlow（FAQ 生成）+ ForgeBase（Product/Breadcrumb/Organization） | 雙方各做各的 Schema |
| | 圖片 Alt Text | ContentFlow（AI 生成）+ ForgeBase（儲存/渲染） | 雙方協作 |
| **內容生產** | 全自動產文 Pipeline | ContentFlow | 核心功能 |
| | 事實查核 / 法規合規 | ContentFlow | 核心功能 |
| **Topic Cluster** | 關鍵字分群 / Topic Map / 缺口偵測 | ContentFlow | 內容規劃 |
| | Pillar Page 模板 / Cluster 導覽 UI | ForgeBase | 網站結構 |
| **Off-Page SEO** | 反向連結監控 / 競品分析 / Unlinked Mention | ContentFlow | 內容策略延伸 |
| | Outreach（人工執行） | 人工 | AI 產出範本輔助 |
| **技術 SEO** | Canonical / Sitemap / robots / hreflang | ForgeBase | 網站基礎設施 |
| | 301/302 重定向管理 | ForgeBase | 網站基礎設施 |
| | Core Web Vitals 監控 | ForgeBase | 網站健康 |
| | 全站爬蟲掃描 | ForgeBase | 網站健康 |
| | 索引覆蓋率 / Mobile Usability | ForgeBase | 網站健康 |
| **排名追蹤** | GSC 串接 | ContentFlow（同步數據）+ ForgeBase（接收 GSC 參數） | 雙方協作 |
| **歸因分析** | 文章 → 排名 → 流量 | ContentFlow | 內容分析 |
| | 文章 → RFQ 轉換 | ForgeBase（精確歸因）| 平台獨有 |
| **持續優化** | Content Refresh / 模式學習 | ContentFlow | 閉環核心 |
| | Google 演算法更新因應 | 人工決策 | AI 提供數據分析輔助 |

### 職責分界線

```
ContentFlow 的邊界                  ForgeBase 的邊界
─────────────────                  ──────────────────
產「哪些內容」的決策               「網站本身」的技術健康
「文章品質」的保證                 「頁面載入」的速度保證
「排名數據」的分析                 「訪客行為」的精確追蹤
「下一步做什麼」的 AI 建議         「網站結構」的正確呈現
```

---

## 16. AI Agent 架構升級：從 Pipeline 到有限自主 Agent

### 為什麼要升級？

| 面向 | 現在 Pipeline | Agent 架構 |
|------|--------------|------------|
| 執行方式 | 固定 5 步，每次都一樣 | 目標導向，根據情境決策 |
| 品質上限 | 永遠同一水準 | 隨學習累積，品質持續提升 |
| 工具選擇 | 硬編碼（永遠用相同工具） | StateGraph 條件分支，動態選用最佳工具 |
| 錯誤處理 | 一步失敗就停止 | 自動重試 + 替代方案 |
| 學習能力 | 零（每次從零開始） | 查詢知識庫，運用歷史經驗 |
| 品質保證 | SEO 不及格照樣交出 | 品質閘門：不達標就自動修正 |
| 成本控制 | 固定 6 次 LLM 呼叫 | 動態 6-15 次，但有預算硬上限 |
| 技術依賴 | 純 async 函式呼叫 | LangGraph StateGraph（已在 pyproject.toml） |

### 16.1 技術實作方案：LangGraph StateGraph

**現況**：`pyproject.toml` 已引入 `langgraph>=0.2.0`，但 `orchestrator.py` 完全沒有使用。

**重構計劃**：

```python
# 重構檔案：src/contentflow/agents/orchestrator.py

from langgraph.graph import StateGraph, END

class ArticleState(TypedDict):
    """Agent 工作狀態"""
    task: ArticleTask
    project_context: ProjectContext
    research_report: ResearchReport | None
    strategy_context: dict | None
    draft: ArticleDraft | None
    seo_score: int
    seo_retry_count: int
    agent_decisions: list[dict]     # 決策日誌
    total_cost: float               # 累計成本
    total_llm_calls: int            # 累計 LLM 呼叫次數

# ── 建構 Graph ──────────────────────────────────
graph = StateGraph(ArticleState)

# 節點（每個現有 Agent 函式包裝為節點）
graph.add_node("research", research_node)
graph.add_node("strategy", strategy_node)
graph.add_node("write", writing_node)
graph.add_node("seo_check", seo_check_node)
graph.add_node("seo_qa", seo_qa_node)
graph.add_node("factcheck", factcheck_node)
graph.add_node("budget_guard", budget_guard_node)

# 邊（條件分支）
graph.add_edge("research", "strategy")
graph.add_edge("strategy", "write")
graph.add_edge("write", "seo_check")

# 條件邊：SEO 不及格 → 重修 or 放棄
graph.add_conditional_edges("seo_check", seo_gate, {
    "pass": "factcheck",           # ≥ 85 分 → 進入 FactCheck
    "retry": "seo_qa",             # < 85 分且重試 < 3 → 修正
    "force_output": "factcheck",   # < 85 分但已重試 3 次 → 強制輸出 + 標記
})

graph.add_edge("seo_qa", "seo_check")  # 修正後重新檢查
graph.add_edge("factcheck", "budget_guard")

# 預算守衛
graph.add_conditional_edges("budget_guard", budget_gate, {
    "ok": END,
    "over_budget": END,  # 超預算也結束，但標記警示
})

agent = graph.compile()
```

### 16.2 現有 Agent 函式的改動

**關鍵：6 個 Agent 函式完全不需要改。** 只改 `orchestrator.py` 一個檔案。

| 檔案 | 改動 |
|------|------|
| `orchestrator.py` | 🔴 全部重構（順序呼叫 → StateGraph） |
| `research_agent.py` | ✅ 不動（包裝為 `research_node`） |
| `strategy_agent.py` | ✅ 不動（包裝為 `strategy_node`） |
| `writing_agent.py` | ✅ 不動（包裝為 `writing_node`） |
| `seo_check_agent.py` | ✅ 不動（包裝為 `seo_check_node`） |
| `seo_qa_agent.py` | ✅ 不動（包裝為 `seo_qa_node`） |
| `factcheck_agent.py` | ✅ 不動（包裝為 `factcheck_node`） |
| **新增** `budget_guard.py` | 🆕 預算守衛節點 |
| **新增** `knowledge_base.py` | 🆕 學習知識庫查詢 |

### 16.3 決策透明日誌

每篇文章產出時，Agent 自動記錄所有決策過程：

```json
{
  "article_id": "art_001",
  "keyword": "膝蓋長骨刺怎麼辦",
  "agent_decisions": [
    {"step": "strategy", "decision": "選 How-to 格式", "reason": "KB: 同類 keyword How-to 排名 #4 > Listicle #8", "confidence": "verified"},
    {"step": "strategy", "decision": "目標 3800 字", "reason": "SERP 前 3 名平均 3200 字,+18% 策略", "confidence": "heuristic"},
    {"step": "writing", "decision": "引用 3 篇 RCT", "reason": "PubMed 找到 12 篇,篩選 Impact Factor > 3", "confidence": "data"},
    {"step": "seo_qa", "decision": "重寫 H2 結構", "reason": "SEO 72→81,H2 缺主關鍵字", "confidence": "rule"},
    {"step": "seo_qa_retry", "decision": "加 FAQ schema", "reason": "SERP 有 Featured Snippet", "confidence": "data"},
    {"step": "factcheck", "decision": "移除第3段統計", "reason": "PubMed 原文 p=0.08 不顯著", "confidence": "data"}
  ],
  "quality_gate": {"initial_score": 72, "final_score": 89, "retries": 2},
  "budget": {"llm_calls": 11, "cost_usd": 1.34, "budget_usd": 2.00},
  "kb_queries": 3,
  "timestamp": "2026-04-12T10:30:00Z"
}
```

**用途**：
- 人工可在 Streamlit 審查 Agent 的每一步決策理由
- 累積決策日誌 → 供 L2 策略優化分析
- 異常偵測：Agent 連續做出反常決策 → 警示

---

## 17. 安全防護：Bounded Autonomy 設計

### 設計原則

> **不是「完全自主」vs「完全固定」的二選一，而是「放多少繩子」的設計。**

### 17.1 三層權限架構

```
┌─────────────────────────────────────────────────────┐
│                  控制層（不可繞過的硬規則）              │
│                                                     │
│  • 最大重試次數：3 次/步驟（硬上限）                    │
│  • 單篇 token 預算：$2.00（超過就停止）                │
│  • 最大 LLM 呼叫數：15 次/篇（硬上限）                │
│  • 發布前必須人工確認（絕不自動 publish）               │
│  • FactCheck 紅燈 = 強制攔截，不交稿                   │
│  • 所有決策留 log（可審計，不可關閉）                   │
│                                                     │
├─────────────────────────────────────────────────────┤
│                  自主層（Agent 可自行決策）              │
│                                                     │
│  • 文章結構選擇（How-to / Listicle / 比較文）          │
│  • 字數決策（根據競品 SERP 分析結果）                   │
│  • SEO 不及格 → 自己修正（最多 3 輪）                  │
│  • 選用哪些工具（PubMed / SERP / GSC 知識庫）          │
│  • 根據知識庫歷史數據調整策略                           │
│  • FAQ 數量 / Title 格式 / 引用數量                    │
│                                                     │
├─────────────────────────────────────────────────────┤
│                  禁止層（Agent 絕不可做）               │
│                                                     │
│  • 自動發布到正式環境                                  │
│  • 修改已發布文章（需人工確認）                         │
│  • 刪除任何內容                                       │
│  • 超出預設 keyword 範圍自行選題                       │
│  • 呼叫付費外部 API 超過預算上限                       │
│  • 修改系統設定或用戶資料                              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### 17.2 預算守衛（Budget Guard）

```python
# 新增檔案：src/contentflow/agents/budget_guard.py

class AgentBudget:
    """每篇文章的資源預算"""
    max_llm_calls_per_article: int = 15      # 現在 Pipeline 是 6 次
    max_cost_per_article: float = 2.0        # 美元
    max_retry_per_step: int = 3              # 每個步驟最多重試次數
    max_total_retries: int = 6               # 整篇文章最多重試總次數

def budget_guard_node(state: ArticleState) -> ArticleState:
    """
    預算守衛節點 — 在 Graph 的每個關鍵點檢查

    超過任何一項上限 → 
    1. 強制停止
    2. 輸出目前最佳結果
    3. 標記 "needs_human_review: budget_exceeded"
    4. 記錄到決策日誌
    """
```

### 17.3 品質閘門（Quality Gate）

```
撰文完成 → SEO Check = 72 分
                ↓
        SEO QA 修正（第 1 輪）
                ↓
        SEO Check = 81 分（< 85）
                ↓
        SEO QA 修正（第 2 輪）
                ↓
        SEO Check = 89 分 ✅ 通過（≥ 85 → 進入 FactCheck）
                ↓
        FactCheck 通過 → 輸出草稿

如果第 3 輪還沒過（< 85）→ 
        強制輸出 + 標記「needs_human_review: seo_below_threshold」
        人在 Streamlit 看到 ⚠️ 標記後決定是否手動處理
```

### 17.4 學習層人工覆核

```
知識庫自動學習的結論：

「待驗證」（< 5 篇數據支持）
  → Agent 參考但不強制套用
  → Streamlit 知識庫頁面顯示黃色標記

「已驗證」（5+ 篇數據支持）
  → Agent 作為重要參考
  → Streamlit 知識庫頁面顯示綠色標記

「通用規則」（10+ 篇 + 跨專案一致）
  → Agent 作為預設行為
  → Streamlit 知識庫頁面顯示藍色標記

任何等級 → 人都可以在 Streamlit 手動推翻或修正
           推翻紀錄也會被記入知識庫
```

### 17.5 風險評估 vs 現有 Pipeline

| 風險類型 | Pipeline（現在） | Bounded Agent | 防護措施 |
|---------|-----------------|--------------|---------|
| **成本失控** | 固定 6 call = $0.50 | 動態 6-15 call | 預算硬上限 $2.00/篇 |
| **品質失控** | 可能交出 72 分文章 | 最多 3 輪修正 | 品質閘門 ≥ 85 |
| **幻覺/錯誤** | FactCheck 一次 | FactCheck 不變 | FactCheck 紅燈 = 攔截 |
| **自動發布** | 不可能 | 不可能 | 禁止層硬規則 |
| **決策黑箱** | 無日誌 | 完整決策日誌 | 每步驟記錄 reason |
| **學習偏差** | 不學習 | 可能學錯 | 信心等級 + 人工覆核 |

**結論**：Bounded Agent 在所有風險維度都 ≤ 現有 Pipeline，但品質上限和效率顯著提升。

---

## 18. 排程與背景任務系統

### 為什麼需要排程系統？

閉環的核心是「自動、定期、持續」。以下任務全部依賴背景排程，沒有排程 = 閉環斷裂：

| 任務 | 頻率 | 依賴階段 |
|------|------|---------|
| GSC 數據同步 | 每日 | ① LISTEN |
| GA4 數據同步 | 每日 | ① LISTEN |
| 競品 SERP 監控 | 每週 | ① LISTEN / L3 |
| 文章表現歸因 | 每週 | ② ANALYSE |
| Content Refresh 觸發檢查 | 每週 | ③ PLAN |
| Topic Cluster 覆蓋率更新 | 每週 | ③ PLAN |
| L1 模式分析 | 每月 | ⑦ LEARN |
| L2 ROI 分析 | 每月 | ⑦ LEARN |
| 反向連結 Profile 更新 | 每週 | Off-Page |

### 18.1 技術選型

| 階段 | 方案 | 理由 |
|------|------|------|
| Phase 1–2 | **APScheduler** 內嵌 FastAPI | 零額外基礎設施，`AsyncIOScheduler` 與 FastAPI 同 process 啟動，cron trigger 定義任務 |
| Phase 3+ | 視需求評估 **Celery + Redis** | 若任務量或併發需求超過 APScheduler 能力再遷移；SQLite → PostgreSQL 完成後 Celery 才有意義 |

### 18.2 APScheduler 架構

```python
# 新增檔案：src/contentflow/scheduler.py

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = AsyncIOScheduler()

# ── 每日任務 ──
scheduler.add_job(sync_gsc_all_projects,  CronTrigger(hour=3, minute=0),  id="gsc_sync")
scheduler.add_job(sync_ga4_all_projects,  CronTrigger(hour=3, minute=30), id="ga4_sync")

# ── 每週任務（週一凌晨）──
scheduler.add_job(run_competitor_serp_check, CronTrigger(day_of_week="mon", hour=4), id="competitor_serp")
scheduler.add_job(run_attribution_engine,   CronTrigger(day_of_week="mon", hour=5), id="attribution")
scheduler.add_job(check_refresh_triggers,   CronTrigger(day_of_week="tue", hour=4), id="refresh_check")

# ── 每月任務（每月 1 號）──
scheduler.add_job(run_l1_pattern_analysis, CronTrigger(day=1, hour=6), id="l1_learn")
scheduler.add_job(run_l2_roi_analysis,     CronTrigger(day=1, hour=7), id="l2_learn")

# ── 與 FastAPI 生命週期綁定 ──
@app.on_event("startup")
async def start_scheduler():
    scheduler.start()

@app.on_event("shutdown")
async def stop_scheduler():
    scheduler.shutdown()
```

### 18.3 失敗重試策略

```
任務失敗 →
├── 記錄錯誤到 DB（SchedulerLog 表）
├── 自動重試（最多 3 次，間隔指數退避：5min → 15min → 45min）
├── 3 次都失敗 → 標記為 FAILED + Email/Slack 通知管理員
└── 不阻擋其他任務（獨立失敗隔離）
```

### 18.4 任務監控

```
Streamlit 排程管理頁面：
├── 所有排程任務列表（下次執行時間 / 上次執行結果）
├── 手動觸發按鈕（不用等排程，立即執行某項任務）
├── 執行歷史記錄（SchedulerLog 查詢）
└── 失敗任務告警（紅色標記 + 重試狀態）
```

---

## 19. 部署架構與資料庫規劃

### 19.1 Process Topology

Phase 1 的最小部署採用 **兩個應用服務 + 一個資料庫服務**。排程器不獨立拆成第三個 process，而是內嵌在 FastAPI 服務內。

```
┌───────────────────────────────────────────────────┐
│                  VPS / Docker Host                  │
│                                                     │
│  ┌────────────────────────┐  ┌────────────────────┐  │
│  │  FastAPI (Uvicorn)     │  │  Streamlit         │  │
│  │  Port 8000             │  │  Port 8501         │  │
│  │                        │  │                    │  │
│  │  • API 端點             │  │  • 人工審閱         │  │
│  │  • 發布推送             │  │  • 知識庫管理       │  │
│  │  • APScheduler 排程器   │  │  • 報表            │  │
│  │  • GSC/GA4 同步任務     │  │                    │  │
│  │  • 歸因 / 學習任務      │  │                    │  │
│  └───────────┬────────────┘  └──────────┬─────────┘  │
│              │                           │            │
│              └──────────────┬────────────┘            │
│                             │                         │
│                    ┌────────▼────────┐                │
│                    │   PostgreSQL    │                │
│                    │    (共用 DB)    │                │
│                    └─────────────────┘                │
└───────────────────────────────────────────────────┘
```

| 服務 | 說明 | 啟動方式 |
|------|------|---------|
| **FastAPI** | API 路由層 + 排程器（APScheduler 嵌入） | `uvicorn contentflow.api:app --port 8000` |
| **Streamlit** | 人工審閱 UI、知識庫管理、報表 | `streamlit run app/Home.py --server.port 8501` |
| **PostgreSQL** | 共用資料庫（替代 SQLite） | Docker container 或系統服務 |

**Phase 1 最小部署**：Docker Compose 定義兩個應用服務 + 一個 PostgreSQL container。

### 19.1.1 Phase 1 必要依賴與設定變數

**需新增到 `pyproject.toml` 的套件**：

| 階段 | 套件 | 用途 |
|------|------|------|
| Phase 1 | `fastapi` | API 路由層 |
| Phase 1 | `uvicorn` | FastAPI 啟動 |
| Phase 1 | `apscheduler` | 背景排程 |
| Phase 1 | `asyncpg` | PostgreSQL async driver |
| Phase 1 | `psycopg2-binary` | migration / sync 工具相容 |
| Phase 1 | `alembic` | schema migration |
| Phase 1 | `markdown` | WordPress / ForgeBase body 轉換 |
| Phase 3 | `chromadb` | RAG MVP 向量庫 |

**需新增到 `src/contentflow/config.py` 的設定欄位**：

| Settings 欄位 | Env 名稱 | 用途 |
|---------------|----------|------|
| `api_secret_key` | `API_SECRET_KEY` | ContentFlow API Key 認證 |
| `forgebase_api_base_url` | `FORGEBASE_API_BASE_URL` | ForgeBase API 入口 |
| `forgebase_api_token` | `FORGEBASE_API_TOKEN` | ForgeBase Service Account token |
| `scheduler_enabled` | `SCHEDULER_ENABLED` | 本地開發可關閉排程 |
| `scheduler_timezone` | `SCHEDULER_TIMEZONE` | 排程時區，預設 `Asia/Taipei` |

> `DATABASE_URL` 仍為主資料庫設定，不額外拆 `DB_PASSWORD` 到 `Settings`；部署時由 Docker Compose 或 secret manager 注入完整連線字串。

### 19.2 SQLite → PostgreSQL 遷移

**為什麼必須遷移？**

| 問題 | SQLite | PostgreSQL |
|------|--------|-----------|
| 多 writer 併發 | ❌ `database is locked` | ✅ MVCC |
| FastAPI + Streamlit + Scheduler 同時寫入 | ❌ 互相鎖死 | ✅ 無問題 |
| 連線池 | ❌ 不支援 | ✅ `asyncpg` + SQLAlchemy pool |
| 全文搜尋 | ⚠️ FTS5 可用但功能有限 | ✅ GIN index + `tsvector` |
| JSON 查詢 | ⚠️ `json_extract` | ✅ `jsonb` 原生支援 |

**遷移策略**：

```
Phase 1 第 1 週：
1. pyproject.toml 加入 asyncpg、psycopg2-binary
2. config.py 的 database_url 預設改為 PostgreSQL
   DATABASE_URL=postgresql+asyncpg://contentflow:pass@localhost:5432/contentflow
3. SQLAlchemy ORM 不需改（已經是宣告式，DB-agnostic）
4. 寫 Alembic migration init（從現有 Base.metadata 產生）
5. 提供 scripts/migrate_sqlite_to_pg.py（讀 SQLite → 寫 PostgreSQL）
```

**實際 migration 指令流程**：

```bash
alembic init migrations
alembic revision --autogenerate -m "phase1_infra"
alembic upgrade head
python scripts/migrate_sqlite_to_pg.py
```

**資料搬移注意事項**：

| 欄位變更 | 搬移策略 |
|---------|---------|
| `seo_rankings.tracked_date` | 字串轉 `Date`，無法解析者寫入 null 並記錄 migration log |
| `seo_rankings.rank` → `position` | 舊 `rank` 直接轉 float 到新欄位 `position` |
| 新增 `impressions/clicks/ctr` | 舊資料以 null 起始，不補假資料 |

### 19.3 資料表擴充與新增

**① SEORanking 表擴充**（現有欄位不足以支撐閉環）：

| 現有欄位 | 問題 | 修正 |
|---------|------|------|
| `tracked_date: String` | 字串無法排序/日期比較 | → `tracked_date: Date` |
| 缺少 impressions | 閉環需要曝光量 | + `impressions: Integer` |
| 缺少 clicks | 閉環需要點擊量 | + `clicks: Integer` |
| 缺少 CTR | 閉環需要點擊率 | + `ctr: Float` |
| `rank: Integer` | GSC 回傳的是浮點數 | → `position: Float`（取代 rank） |

**② 新增 AgentDecisionLog 表**：

```python
class AgentDecisionLog(Base):
    __tablename__ = "agent_decision_logs"
    id: int                     # PK
    project_id: int             # FK → projects
    article_id: int | None      # FK → articles（可 null，排程任務無文章）
    run_id: str                 # 單次執行的 UUID
    step: str                   # "research" / "strategy" / "seo_check" / ...
    decision: str               # 決策描述
    reason: str                 # 理由
    confidence: str             # "data" / "heuristic" / "rule" / "verified"
    metadata_json: str          # 任意額外資訊（JSON）
    created_at: datetime
```

**③ 新增 KnowledgeEntry 表**（配合 §11.6 RAG 架構的關聯式索引）：

```python
class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"
    id: int                     # PK
    project_id: int | None      # FK → projects（null = 跨專案通用規則）
    category: str               # "format_pattern" / "keyword_strategy" / ...
    pattern: str                # 學到的模式描述
    evidence_count: int         # 支持數據筆數
    confidence_level: str       # "unverified" / "verified" / "universal"
    metadata_json: str          # 統計數據（JSON）
    is_active: bool             # 人工可停用（default True）
    created_at: datetime
    updated_at: datetime
```

**④ 新增 SchedulerLog 表**：

```python
class SchedulerLog(Base):
    __tablename__ = "scheduler_logs"
    id: int                     # PK
    job_id: str                 # APScheduler job ID
    job_name: str               # 任務名稱
    status: str                 # "success" / "failed" / "retrying"
    retry_count: int            # 已重試次數
    error_message: str | None   # 錯誤訊息
    duration_seconds: float     # 執行時長
    started_at: datetime
    finished_at: datetime | None
```

### 19.4 Docker Compose 範例

```yaml
# docker-compose.yml
version: "3.9"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: contentflow
      POSTGRES_USER: contentflow
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  api:
    build: .
    command: uvicorn contentflow.api:app --host 0.0.0.0 --port 8000
    environment:
      DATABASE_URL: postgresql+asyncpg://contentflow:${DB_PASSWORD}@db:5432/contentflow
    depends_on:
      - db
    ports:
      - "8000:8000"

  ui:
    build: .
    command: streamlit run app/Home.py --server.port 8501 --server.address 0.0.0.0
    environment:
      DATABASE_URL: postgresql+asyncpg://contentflow:${DB_PASSWORD}@db:5432/contentflow
    depends_on:
      - db
    ports:
      - "8501:8501"

volumes:
  pgdata:
```

---

## 20. WordPress 串接方案

### 完整串接架構

```
WordPress 網站（客戶官網）
        │
        ├── Yoast/RankMath SEO 外掛
        │     └── ContentFlow 寫入 meta 欄位
        │
        ├── WP REST API v2
        │     ├── ContentFlow 推送草稿 / 更新文章
        │     └── ContentFlow 拉回既有文章（Refresh 用）
        │
        └── Google Search Console
              └── ContentFlow 讀取排名數據（Site Property）

ContentFlow 作為中央引擎在背景運行：
        │
        ├── 每日同步 GSC 數據
        ├── 每週分析表現 + 推薦動作
        ├── 按計劃執行產文 / Refresh
        └── 推送到 WordPress（草稿狀態）
```

### WordPress 客戶 vs ForgeBase 客戶的功能差異

| 功能 | ForgeBase 客戶 | WordPress 客戶 |
|------|---------------|---------------|
| SEO 全自動產文 | ✅ | ✅ |
| SEO 規則評分 | ✅ | ✅ |
| 事實查核 | ✅ | ✅ |
| GSC 排名追蹤 | ✅ | ✅ |
| Content Refresh 自動觸發 | ✅ | ✅ |
| 成功模式學習 | ✅ | ✅ |
| 訪客行為鏈路（精確歸因） | ✅ 完整 | ⚠️ GA4 歸因 |
| 意圖評分 → 詢價追蹤 | ✅ 完整 | ⚠️ 需客戶自建 |
| SEO ROI 報表（每篇文章 → RFQ 金額） | ✅ 精確 | ⚠️ 近似值 |
| Dynamic CTA | ✅ | ❌ |
| AI Product Advisor | ✅ | ❌ |

---

## 21. 閉環數據流全圖

```
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  ① LISTEN                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │  GSC API     │  │  GA4 API     │  │  SERP Tool   │  │ Backlink   │  │
│  │  排名/CTR/   │  │  流量/停留/  │  │  競品排名/   │  │ API        │  │
│  │  曝光/點擊   │  │  跳出/轉換   │  │  新進前10    │  │ 反向連結   │  │
│  │  索引覆蓋率  │  │              │  │              │  │ 品牌提及   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘  │
│         │                 │                 │                │          │
│         └────────────┬────┴────────────┬────┘                │          │
│                      │                 └─────────────────────┘          │
│                      ▼                                                   │
│  ② ANALYSE                                                               │
│  ┌──────────────────────────────────────────┐                           │
│  │ 歸因引擎                                  │                           │
│  │ 每篇文章 → 排名 + 流量 + 轉換 + 表現評等  │                           │
│  │ Cannibalization 偵測                      │                           │
│  │ 競品缺口識別                               │                           │
│  │ Topic Cluster 覆蓋率分析                   │                           │
│  │ 反向連結缺口分析                           │                           │
│  └──────────────────┬───────────────────────┘                           │
│                      ▼                                                   │
│  ③ PLAN                                                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ AI 選題推薦引擎                            │                           │
│  │ ├── 新選題（關鍵字缺口 + 競品弱點）        │                           │
│  │ ├── Topic Cluster 缺口補齊                │                           │
│  │ ├── Content Refresh 排程                  │                           │
│  │ ├── 內部連結補強計劃                       │                           │
│  │ ├── Link Building 推薦目標                │                           │
│  │ └── 自動排入內容日曆                       │                           │
│  └──────────────────┬───────────────────────┘                           │
│                      ▼                                                   │
│  ④ CREATE                                                                │
│  ┌──────────────────────────────────────────┐                           │
│  │ ContentFlow AI Agent（LangGraph StateGraph）│                          │
│  │ Research → Strategy → Writing              │                           │
│  │ → SEO Check ⇄ SEO QA（品質閘門 ≥ 85）     │                           │
│  │ → FactCheck + 預算守衛（$2.00/篇）         │                           │
│  │ ＋查詢知識庫（L1/L2 學習成果）             │                           │
│  │ ＋自動標記 Topic Cluster 歸屬 + Pillar 回連│                           │
│  └──────────────────┬───────────────────────┘                           │
│                      ▼                                                   │
│  ⑤ REVIEW                                                                │
│  ┌──────────────────────────────────────────┐                           │
│  │ 人工審閱（唯一必要的人工步驟）             │                           │
│  │ Streamlit UI / ForgeBase Admin（已完成 ✅）│                           │
│  │ ＋審閱通知 → Email / Slack                │                           │
│  │ ＋人工修改回饋收集 → 送 ⑦ LEARN           │                           │
│  └──────────────────┬───────────────────────┘                           │
│                      ▼                                                   │
│  ⑥ PUBLISH                                                               │
│  ┌──────────────────────────────────────────┐                           │
│  │ ContentFlow FastAPI → 發布端抽象層         │                           │
│  │ ├── ForgeBasePublisher → Page API         │                           │
│  │ └── WordPressPublisher → WP REST API      │                           │
│  └──────────────────┬───────────────────────┘                           │
│                      │                                                   │
│                      │   發布後等待 Google 收錄（7–30 天）               │
│                      │                                                   │
│  ⑦ LEARN             ▼                                                   │
│  ┌──────────────────────────────────────────┐                           │
│  │ 三層學習引擎                                │                           │
│  │ L1 模式記憶：哪種格式/字數/FAQ 排名好？     │                           │
│  │ L2 策略優化：keyword ROI → 資源配置建議     │                           │
│  │ L3 競品適應：排名被超 → 自動 Refresh 建議   │                           │
│  │ ├── 人工審閱回饋收集（AI 以後避免）         │                           │
│  │ ├── 知識庫信心等級：待驗證/已驗證/通用規則   │                           │
│  │ └── 自動注入 Agent 決策 → 下一輪 ④ CREATE  │                           │
│  └──────────────────┬───────────────────────┘                           │
│                      │                                                   │
│                      └──────────→ 回到 ① LISTEN ────────────────────────┘
│                                                                          │
│  ═══════════════════════════════════════════════════════════════          │
│  ForgeBase 獨立循環（技術 SEO 健康監控）                                  │
│  ┌──────────────────────────────────────────┐                           │
│  │ 每週自動掃描：                              │                           │
│  │ ├── Core Web Vitals（LCP / INP / CLS）    │                           │
│  │ ├── 全站爬蟲（斷鏈 / 孤頁 / redirect chain） │                        │
│  │ ├── GSC 索引覆蓋率                         │                           │
│  │ ├── Mobile Usability                      │                           │
│  │ └── 健康分數 → Admin 儀表板                │                           │
│  └──────────────────────────────────────────┘                           │
│  ═══════════════════════════════════════════════════════════════          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 22. 開發優先順序與里程碑

### Phase 1 — 打通管道（第 1–4 週）

| 項目 | 說明 | 預估 |
|------|------|------|
| SQLite → PostgreSQL 遷移 | Alembic init + 資料搬移腳本 + Docker Compose | 3 天 |
| ContentFlow FastAPI 路由層 | 4 個核心端點 + API Key 認證 | 1 週 |
| 排程系統基礎建設 | APScheduler 嵌入 FastAPI + GSC 每日同步排程 | 2 天 |
| DB schema 擴充 | SEORanking 擴欄 + AgentDecisionLog/KnowledgeEntry/SchedulerLog 新表 | 2 天 |
| ForgeBase 推送 Adapter | 3-step flow（Brief → Page → Publish）+ Service Account 認證 | 3 天 |
| WordPress 推送 Adapter | WP REST API + Yoast/RankMath | 1 週 |
| 發布端抽象層 | BasePublisher（僅 ForgeBase + WordPress） | 1 天 |
| GSC API 串接 + 每日同步 | gsc.py + SEORanking 寫入 | 1 週 |

**里程碑**：ContentFlow 產出的文章可一鍵推送到 ForgeBase 或 WordPress，排名數據每日自動回收，系統運行在 Docker Compose + PostgreSQL 上。

### Phase 2 — 建立閉環 + Topic Cluster + Agent 架構（第 5–10 週）

| 項目 | 說明 | 歸屬 | 預估 |
|------|------|------|------|
| 文章表現歸因引擎 | GSC + GA4 數據 → 每篇文章表現評等 | ContentFlow | 1 週 |
| AI 選題推薦引擎 | 基於數據缺口自動推薦 | ContentFlow | 1 週 |
| **關鍵字自動分群（Topic Cluster）** | AI 語意分群 → Pillar/Cluster 架構 | ContentFlow | 1 週 |
| **Topic Map 視覺化 + 缺口偵測** | 覆蓋率報表 + 缺口推薦 | ContentFlow | 1 週 |
| **LangGraph StateGraph 重構** | orchestrator.py 改為 Graph 節點 + 條件邊 | ContentFlow | 1 週 |
| **品質閘門 + 預算守衛** | SEO ≥ 85 閘門 + $2.00/篇預算硬上限 | ContentFlow | 3 天 |
| **決策透明日誌** | Agent 每步決策記錄 reason + confidence | ContentFlow | 2 天 |
| Content Refresh 觸發規則 | 排名下滑 / 過期 / 競品威脅 | ContentFlow | 3 天 |
| Cannibalization 偵測 | 同關鍵字多文章警示 | ContentFlow | 3 天 |
| 審閱通知（Email） | 草稿就緒自動通知 | ContentFlow | 2 天 |

**里程碑**：閉環成立 + Agent 自主決策上線（Bounded Autonomy）+ Topic Cluster 架構建立。

### Phase 3 — 三層學習 + 技術 SEO（第 11–16 週）

| 項目 | 說明 | 歸屬 | 預估 |
|------|------|------|------|
| **L1 模式記憶：成功模式分析器** | 歷史表現數據 → 勝率因子 + 知識庫 | ContentFlow | 1 週 |
| **知識庫信心等級機制** | 待驗證/已驗證/通用規則 三級信心 | ContentFlow | 3 天 |
| **L1 學習成果自動注入 Agent** | KB RAG 查詢 → Agent 動態決策 | ContentFlow | 1 週 |
| **L2 策略優化：ROI 分析引擎** | keyword ROI + 資源配置建議 | ContentFlow | 1 週 |
| **Streamlit 知識庫管理 UI** | 查看/推翻 Agent 學習結論 | ContentFlow | 3 天 |
| Content Refresh Pipeline（增補模式）| 局部更新而非全部重寫 | ContentFlow | 1 週 |
| **撰文時自動標記 Cluster + Pillar 回連** | 撰文自動加入 Cluster 連結 | ContentFlow | 3 天 |
| 人工審閱回饋收集 | 人改了什麼 → 回饋給 LEARN | ContentFlow | 3 天 |
| 內部連結自動化串接 | 撰文時自動推薦站內連結 | ContentFlow | 3 天 |
| GA4 Data API 串接 | 流量 / 停留時間 / 跳出率 | ContentFlow | 1 週 |
| **Core Web Vitals 監控** | CrUX + PageSpeed Insights API | ForgeBase | 1 週 |
| **GSC 索引覆蓋率監控** | 索引狀態追蹤 + 異常警示 | ForgeBase | 3 天 |
| **Pillar Page 模板** | 長頁面結構 + Cluster 導覽 UI | ForgeBase | 1 週 |

**里程碑**：Agent 開始「越做越聰明」（L1+L2 學習上線）；ForgeBase 具備技術 SEO 健康監控。

### Phase 4 — 競品適應 + 進階優化 + Off-Page SEO（第 17 週+）

| 項目 | 說明 | 歸屬 | 優先級 |
|------|------|------|--------|
| **L3 競品適應：威脅偵測引擎** | 排名被超 → 自動排入 Refresh 佇列 | ContentFlow | 🔴 高 |
| **L3 Featured Snippet 搶奪偵測** | 被搶 → FAQ/Table 格式調整建議 | ContentFlow | 🟡 中 |
| SEO ROI 儀表板 | 每篇文章 → 排名 → 轉換 → 金額 | ContentFlow + ForgeBase | 🟡 中 |
| 競品排名定期追蹤 | 每週追蹤 + 威脅警示 | ContentFlow | 🟡 中 |
| **反向連結 Profile 監控** | 串 Ahrefs/Moz API，追蹤反向連結數據 | ContentFlow | 🟡 中 |
| **競品反向連結來源分析** | 找出「競品有我們沒有」的連結來源 | ContentFlow | 🟡 中 |
| **全站爬蟲掃描** | 斷鏈 / 重複內容 / 孤頁 / redirect chain | ForgeBase | 🟡 中 |
| **技術 SEO 健康儀表板** | 綜合健康分數 + 修復建議 | ForgeBase | 🟡 中 |
| **Mobile Usability 檢測** | GSC Mobile Usability API | ForgeBase | 🟢 低 |
| LSI / 語意關鍵字分析 | NLP 相關詞佈局 | ContentFlow | 🟢 低 |
| Image Alt Text 自動生成 | SEO 圖片優化 | ContentFlow | 🟢 低 |
| **Unlinked Mention 偵測** | 品牌提及但無連結 → 推薦聯繫 | ContentFlow | 🟢 低 |
| **斷鏈回收機會識別** | 外部 404 連結 → 建議修復 | ContentFlow | 🟢 低 |
| **Outreach Email 範本** | AI 生成聯繫信範本 | ContentFlow | 🟢 低 |
| A/B Title 測試 | 同頁面不同 Title 輪換 | ContentFlow | 🟢 低 |
| Google 演算法更新因應機制 | Core Update 偵測 + 影響分析 | ContentFlow + 人工 | 🟢 低 |

---

## 23. 預期成效

### 閉環啟動後的演進曲線

```
月份    關鍵字命中率    前10排名數    每月產文量    SEO詢價佔比
─────  ────────────  ──────────  ──────────  ──────────
M1     25-30%         3-5 個      8-10 篇      5%
M2     35-40%         8-12 個     10-12 篇     10%
M3     45-55%         15-25 個    12-15 篇     20%
M6     60-70%         40-60 個    15-20 篇     35%
M12    70-80%         80-120 個   20-25 篇     50%+
```

> 備註：以上數據基於工業利基關鍵字（月搜尋量 100–3,000），
> 高競爭大眾關鍵字的命中率會較低。

> ⚠️ **學習效果標注**：
> - **M1–M4**：閉環基礎建設期，AI Agent 尚未上線學習機制，產文品質依賴現有 Pipeline + SERP 研究
> - **M5–M7**：Agent 架構上線（§16），品質閘門生效，但 L1 學習尚在收集數據階段（< 5 篇驗證）
> - **M8+**：L1 模式記憶開始有可觀測影響（5+ 篇數據支持的「已驗證」規則積累），命中率提升加速
> - **M12+**：L2 策略優化 + L3 競品適應效果疊加

### 與人工 SEO 團隊的成本比較

| 項目 | 3人 SEO 團隊（年） | 本系統（年） |
|------|-------------------|-------------|
| 人力成本 | NT$ 1,800,000 | NT$ 0 |
| 系統 / API 費用 | NT$ 120,000（工具訂閱） | NT$ 60,000（LLM API + GSC） |
| 月產文量 | 8–12 篇 | 15–25 篇 |
| 人工審閱時數 | — | 10–15 hr/月 |
| **年度總成本** | **NT$ 1,920,000** | **NT$ 60,000 + 審閱時間** |

---

> **本文件為 SEO 增強閉環的完整規劃藍圖。**
> 涵蓋完整 SEO 十大面向：關鍵字研究、競品分析、技術 SEO、內容策略、On-Page SEO、
> 內容創作、Off-Page SEO、Topic Cluster、排名追蹤監控、持續優化。
>
> **架構定位**：
> - 從「固定 Pipeline 工具」升級為「有限自主 AI Agent」（Bounded Autonomy）
> - 三層學習機制：L1 模式記憶 → L2 策略優化 → L3 競品適應
> - 雙平台策略：ForgeBase（深度整合）+ WordPress（主流市場），不做其他平台
>
> **安全防護**：
> - 預算硬上限 $2.00/篇 + 15 次 LLM 呼叫上限
> - 品質閘門 SEO ≥ 85 + FactCheck 紅燈攔截
> - 發布永遠需人工確認，Agent 不可自動 publish
> - 所有 Agent 決策留日誌，人可隨時審查和推翻學習結論
>
> **基礎設施**：
> - PostgreSQL（替代 SQLite）+ APScheduler 排程器 + Docker Compose 部署
> - FastAPI API Key 認證 + ForgeBase Service Account 連接
> - ChromaDB 向量庫（Phase 3 MVP）→ pgvector（長期）支撐 RAG 學習注入
>
> **一句話定位**：從「SEO 文章產生器」變成「會自己學習的 SEO 內容 Agent」——前者是工具，後者是員工。
