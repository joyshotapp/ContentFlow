# ContentFlow AI — 系統全面審查文件

> 版本：0.1.0 | 審查日期：2026-04-12

---

## 目錄

1. [系統概述](#1-系統概述)
2. [技術架構](#2-技術架構)
3. [目錄結構](#3-目錄結構)
4. [資料模型（ORM）](#4-資料模型orm)
5. [Agent 流水線](#5-agent-流水線)
6. [工具模組（Tools）](#6-工具模組tools)
7. [前端介面（Streamlit）](#7-前端介面streamlit)
8. [設定與環境變數](#8-設定與環境變數)
9. [CLI 入口](#9-cli-入口)
10. [測試覆蓋](#10-測試覆蓋)
11. [資料流圖](#11-資料流圖)
12. [已知限制與技術債](#12-已知限制與技術債)

---

## 1. 系統概述

**ContentFlow AI** 是一套 **SEO 文章全自動化 Agent 系統**，目標是取代傳統人工的「選題→研究→撰文→審核」流程。

### 核心價值主張

| 階段 | 傳統做法 | ContentFlow |
|------|---------|-------------|
| 關鍵字研究 | 人工查詢 Ahrefs / Google Trends | Excel 匯入 → SQLite 資料庫 |
| 學術佐證 | 手動搜尋 PubMed | Research Agent 自動抓取 |
| 競品分析 | 人工看 SERP 前 10 | SERP Tool 自動解析 |
| 文章撰寫 | 文案工程師 | Writing Agent (GPT-4o-mini) |
| SEO 審查 | 人工逐條對照 | SEO Check Agent（規則引擎）|
| 事實查核 | 主編人工把關 | FactCheck Agent + 法規詞庫 |

### 設計原則

- **多租戶（Multi-project）**：每筆資料都綁定 `project_id`，在同一資料庫支援多個品牌/客戶。
- **低成本首選**：主力使用 `gpt-4o-mini`（約 $0.02–0.05/篇），僅特定場景升級使用 `claude-sonnet-4-5`。
- **可審核**：所有 AI 輸出先存資料庫，人工可在 Streamlit UI 查看、修改後才發布。
- **可擴展**：Agent 以純函式設計，可獨立呼叫，也可透過 Orchestrator 串接。

---

## 2. 技術架構

```
┌─────────────────────────────────────────────────────┐
│                     前端介面                         │
│             Streamlit (app/)                        │
│   Home | 文章管理 | 關鍵字 | 日曆 | 規範 | AI研究中心  │
└─────────────────────┬───────────────────────────────┘
                      │ SQLAlchemy ORM
┌─────────────────────▼───────────────────────────────┐
│                  核心套件 (src/contentflow/)          │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │              Agent Pipeline                  │  │
│  │  Research → Strategy → Writing → SEO QA      │  │
│  │  → SEO Check → FactCheck → Image             │  │
│  │          ↑ Orchestrator 統一排程              │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │   Tools         │  │   Models / DB            │  │
│  │  - PubMed API   │  │  - SQLAlchemy ORM        │  │
│  │  - SERP API     │  │  - Pydantic Schemas      │  │
│  │  - Excel Import │  │  - SQLite (預設)          │  │
│  │  - Keyword      │  └──────────────────────────┘  │
│  └─────────────────┘                               │
└─────────────────────────────────────────────────────┘

外部服務：OpenAI / Anthropic / SerpAPI / Serper.dev / PubMed E-utilities
```

### 核心依賴版本

| 套件 | 版本 | 用途 |
|------|------|------|
| `streamlit` | ≥1.38 | Web UI |
| `langchain` / `langgraph` | ≥0.3 / ≥0.2 | Agent 框架（目前 Pipeline 未大量使用 Graph） |
| `openai` | ≥1.50 | GPT-4o-mini 推理 |
| `anthropic` | ≥0.34 | Claude 寫作（可配置） |
| `sqlalchemy` | ≥2.0 | ORM |
| `pydantic` | ≥2.8 | 資料驗證 |
| `httpx` / `aiohttp` | ≥0.27 / ≥3.10 | 非同步 HTTP |
| `openpyxl` | ≥3.1 | Excel 匯入 |

---

## 3. 目錄結構

```
ContentFlow/
├── pyproject.toml             # 套件設定、依賴、工具鏈
├── app/                       # Streamlit 前端
│   ├── Home.py                # 首頁儀表板（KPI + 文章狀態 + 關鍵字Top10）
│   ├── project_selector.py    # 全域 Sidebar 專案切換元件
│   └── pages/
│       ├── 1_📝_文章管理.py    # 文章列表、篩選、狀態追蹤
│       ├── 2_🔑_關鍵字.py     # 關鍵字資料庫查詢
│       ├── 3_📅_內容日曆.py   # 月/週度內容排程
│       ├── 4_📜_撰寫規範.py   # 品牌寫作規範管理
│       ├── 5_🏢_競品分析.py   # 競業市場研究
│       ├── 6_📦_產品資訊.py   # 產品系列資料
│       ├── 7_⚖️_法規合規.py  # 食品廣告用詞法規
│       ├── 8_🔬_AI研究.py    # AI 產文中心（主要操作入口）
│       └── 9_⚙️_設定.py      # Excel 匯入、API 狀態
├── src/contentflow/           # 核心套件
│   ├── __init__.py
│   ├── cli.py                 # CLI 工具（contentflow research）
│   ├── config.py              # 全域設定（pydantic-settings）
│   ├── db.py                  # 資料庫引擎與 Session 管理
│   ├── project_context.py     # 專案上下文載入器（注入 Agent Prompt）
│   ├── agents/
│   │   ├── orchestrator.py    # 端到端 Pipeline 統一協調
│   │   ├── research_agent.py  # SERP + PubMed 研究報告
│   │   ├── strategy_agent.py  # SEO 選題策略分析
│   │   ├── writing_agent.py   # SEO 文章撰寫
│   │   ├── seo_qa_agent.py    # SEO 微調優化
│   │   ├── seo_check_agent.py # SEO 規則檢核評分
│   │   ├── factcheck_agent.py # 事實查核 + 禁用詞
│   │   └── image_agent.py     # 配圖 Prompt 生成 + DALL-E
│   ├── models/
│   │   ├── database.py        # SQLAlchemy ORM 模型（15 張資料表）
│   │   └── schemas.py         # Pydantic 資料模型（Agent I/O）
│   ├── tools/
│   │   ├── serp.py            # Google SERP 搜尋
│   │   ├── pubmed.py          # PubMed E-utilities
│   │   ├── keyword.py         # 關鍵字工具
│   │   └── excel_importer.py  # Excel → SQLite 匯入
│   └── utils/
│       └── report_renderer.py # 研究報告 → Markdown 渲染
├── scripts/
│   ├── run_article_pipeline.py  # 完整 Pipeline CLI 腳本
│   ├── migrate_add_projects.py  # 資料庫遷移
│   └── verify_db.py            # DB 健康檢查
├── data/
│   └── templates/
│       └── research_report_template.md
└── tests/                     # pytest 測試套件
```

---

## 4. 資料模型（ORM）

資料庫採 **SQLite（預設）**，透過 `DATABASE_URL` 可切換至 PostgreSQL。
所有資料表均支援 `project_id` 外鍵，實現多租戶隔離。

### 資料表清單（15 張）

| 資料表 | 模型類別 | 說明 |
|--------|---------|------|
| `projects` | `Project` | 多租戶根節點，儲存品牌資訊、寫作原則、SERP 地區設定 |
| `keywords` | `Keyword` | 關鍵字庫（搜尋量、CPC、SEO 難度、優先順序） |
| `categories` | `Category` | 部落格分類 / Tag，含 meta SEO 欄位 |
| `content_calendar` | `ContentCalendar` | 月/週度內容排程，記錄文章類型、搜尋意圖、寫作架構 |
| `articles` | `Article` | 文章規劃主表，含完整生命週期欄位（草稿、SEO meta、JSON-LD） |
| `writing_rules` | `WritingRule` | 品牌撰寫規範（architecture / principle / tone） |
| `content_strategy` | `ContentStrategy` | 部落格內容定位與策略 |
| `competitors` | `Competitor` | 競品市場研究資料 |
| `products` | `Product` | 產品系列描述與目標症狀 |
| `legal_terms` | `LegalTerm` | 食品廣告法規用詞（allowed / forbidden / caution） |
| `seo_rankings` | `SEORanking` | SEO 關鍵字排名追蹤 |
| `category_seo` | `CategorySEO` | 分類頁 SEO 規劃（二/三級分類、meta 改寫） |
| `changelog` | `Changelog` | Shopify 主題版本變更紀錄 |

### Article 生命週期狀態

```
planned → researching → writing → reviewing → published
                                            └→ failed
```

### 動態 Schema 補丁機制

`db.py` 的 `_ensure_sqlite_columns()` 會在每次啟動時自動偵測舊版資料庫缺少的欄位並補齊（使用 `ALTER TABLE`），確保向下相容。

---

## 5. Agent 流水線

### 5.1 Orchestrator（`orchestrator.py`）

端到端 5 步驟全自動流程：

```
Step 1  Research Agent     — SERP + PubMed 學術文獻
Step 2  Strategy Agent     — 搜尋意圖 + 讀者痛點 + 架構建議
Step 3  Writing Agent      — 大綱 → 段落 → 完整 Markdown
Step 4  SEO QA Agent       — 初檢(SEO Check) → 針對性修正 → 重新評分
Step 5  FactCheck Agent    — 事實查核 + 禁用詞比對
```

函式簽名：
```python
async def run_orchestrator(
    task: ArticleTask,
    project_id: int | None = None,
    project_slug: str | None = None,
    article_type: str = "educational",   # "educational" | "product"
    strategy_context: dict | None = None,
    use_pubmed: bool | None = None,
) -> ArticleTask
```

### 5.2 Research Agent（`research_agent.py`）

**輸入**：文章標題、關鍵字清單、SERP 地區設定  
**輸出**：`ResearchReport`（PubMed 文獻 + SERP 分析 + 建議關鍵字）

重點邏輯：
- 若關鍵字含中文（CJK），先呼叫 GPT-4o-mini 翻譯為英文 MeSH 詞彙再查 PubMed
- 同時並行執行 PubMed 搜尋（多組 query）與 SERP 搜尋
- `use_pubmed` 可由 `project_uses_pubmed()` 依專案產業自動判斷

### 5.3 Strategy Agent（`strategy_agent.py`）

**輸入**：主/副關鍵字、SERP 分析、PAA 問題  
**輸出**：`StrategyReport`（搜尋意圖、讀者輪廓、架構建議、FAQ、競品缺口）

- 全程使用 GPT-4o-mini，約 $0.005–0.01/次
- 輸出 `to_strategy_context()` 供 Writing Agent 消費

### 5.4 Writing Agent（`writing_agent.py`）

**輸入**：`ResearchReport` + `strategy_context` + `ProjectContext`  
**輸出**：`ArticleDraft`（Markdown 全文 + meta title/description + slug + FAQ JSON-LD）

寫作流程（三階段）：
1. `_generate_outline()` — 產出 JSON 大綱（title、meta、H2 sections）
2. `_write_sections()` — 逐段展開成 Markdown
3. `_finalize_draft()` — 組合完整文章 + 清理 GPT artifacts

品牌知識透過 `ProjectContext.build_brand_prompt()` 注入系統 Prompt。

### 5.5 SEO Check Agent（`seo_check_agent.py`）

純規則引擎，無 LLM 呼叫（零成本）：

| 檢查項目 | 規則 |
|---------|------|
| 主關鍵字在標題 | 必含 |
| 主關鍵字在首段 | 必含 |
| 主關鍵字在 H2 | 至少 1 個 |
| Meta Description | 含主關鍵字，50–160 字元 |
| 關鍵字密度 | 0.5%–4% |
| FAQ section | 建議含 `## FAQ` / `## 常見問題` |
| 內部連結建議 | `suggest_internal_links()` 比對現有文章 |

輸出：`{"score": int, "checks": [...]}` 0–100 分

### 5.6 SEO QA Agent（`seo_qa_agent.py`）

**輸入**：SEO Check 失敗項目清單 + 原始草稿  
**輸出**：修正後的 `ArticleDraft`

針對性修正策略（低風險，溫度 0.2）：
- 首段重寫（確保主關鍵字在首段）
- Meta Title / Description 規範化
- 僅修改必要欄位，不大幅改寫全文

### 5.7 FactCheck Agent（`factcheck_agent.py`）

結合 **LLM 事實核對** + **正則禁用詞比對**：

- 禁用詞分級：
  - `product` 模式（嚴格）：全部違規詞標 `error`
  - `educational` 模式（寬鬆）：白名單通用動詞（改善/舒緩/調節等）降為 `warning`
- LLM 核對：文章宣稱 vs. PubMed 文獻證據
- 輸出：`FactCheckItem[]`，需人工審核的項目標記 `needs_review=True`

### 5.8 Image Agent（`image_agent.py`）

- 解析文章 H2 段落，為每段生成 DALL-E 3 英文 Prompt
- `generate_images=True` 時實際呼叫 DALL-E API，否則僅輸出 Prompt 清單
- 輸出圖片存至 `output_dir`

---

## 6. 工具模組（Tools）

### 6.1 SERP Tool（`tools/serp.py`）

雙 API 支援，自動 fallback：
1. **Serper.dev**（`SERPER_API_KEY`，優先）
2. **SerpAPI**（`SERPAPI_KEY`，備用）

抓取：有機搜尋結果前 10 名、PAA 問題、相關搜尋。
每筆結果額外抓取頁面 H2/H3 標題供競品結構分析。

### 6.2 PubMed Tool（`tools/pubmed.py`）

使用 NCBI E-utilities（ESearch → EFetch XML → ESummary）：
- 支援 NCBI API Key（有 key 時 10 req/s，否則 3 req/s）
- 回傳：PMID、標題、摘要、作者、期刊、發表年份、研究類型
- 預設過濾 2015 年後文獻

### 6.3 Excel Importer（`tools/excel_importer.py`）

讀取 SEO 專案管理表 Excel（`openpyxl`），支援所有 13 種工作表自動對應至資料庫模型。

支援的工作表：
- 關鍵字庫、文章規劃、內容日曆、撰寫規範、內容策略
- 競品分析、產品資訊、法規合規、SEO 排名、分類 SEO
- 部落格分類、Changelog

選項：`clear_existing=True` 先清空再匯入（適合完整更新）。

---

## 7. 前端介面（Streamlit）

啟動指令：
```bash
streamlit run app/Home.py
```

### 頁面功能匯整

| 頁面 | 功能 |
|------|------|
| **Home** | KPI 儀表板（關鍵字數、文章數、發布數）、文章狀態分佈圖、月度計劃圖、Top 10 關鍵字 |
| **📝 文章管理** | 列表篩選（狀態/關鍵字/排序）、文章詳情展開、啟動 AI Pipeline 按鈕 |
| **🔑 關鍵字** | 搜尋/篩選（優先度/搜尋量/難度）、排序、匯出功能 |
| **📅 內容日曆** | 月/週度排程瀏覽，文章狀態追蹤 |
| **📜 撰寫規範** | 品牌寫作規範瀏覽與管理 |
| **🏢 競品分析** | 競品品牌資料查看 |
| **📦 產品資訊** | 產品系列資料管理 |
| **⚖️ 法規合規** | 食品廣告禁用詞查看（allowed/forbidden/caution 分類） |
| **🔬 AI 研究中心** | **主要操作入口**：五步驟進度顯示、一鍵執行完整 Pipeline、結果 Markdown 預覽 |
| **⚙️ 設定** | Excel 上傳匯入、本機路徑匯入（開發模式）、API 狀態、DB 資料統計 |

### 專案切換機制

`project_selector.py` 的 `get_current_project_id()` 在每個頁面的 Sidebar 顯示專案下拉選單，透過 `st.session_state._project_id` 跨頁面保持選擇狀態。

---

## 8. 設定與環境變數

設定檔：`.env`（根目錄）

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `OPENAI_API_KEY` | — | OpenAI API 金鑰（必填） |
| `ANTHROPIC_API_KEY` | — | Anthropic API 金鑰（可選） |
| `LLM_WRITING_MODEL` | `claude-sonnet-4-5` | 寫作模型 |
| `LLM_LITE_MODEL` | `gpt-4o-mini` | 輕量推理模型（大多數 Agent 使用） |
| `NCBI_API_KEY` | — | PubMed API Key（建議填寫） |
| `NCBI_EMAIL` | — | PubMed 請求 email（必填） |
| `SERPER_API_KEY` | — | Serper.dev SERP API（優先） |
| `SERPAPI_KEY` | — | SerpAPI（備用） |
| `DATABASE_URL` | `sqlite:///./data/contentflow.db` | 資料庫連線字串 |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `credentials/google-service-account.json` | Google Sheets 整合 |
| `GOOGLE_SHEETS_SCHEDULE_ID` | — | Google Sheets 排程表 ID |
| `WORDPRESS_SITE_URL` | — | WordPress 發布整合 |
| `WORDPRESS_USERNAME` | — | WordPress 帳號 |
| `WORDPRESS_APP_PASSWORD` | — | WordPress 應用程式密碼 |
| `OUTPUT_DIR` | `./outputs` | 輸出目錄 |
| `MAX_ARTICLES_PER_RUN` | `5` | 每次批次最多文章數 |
| `LOG_LEVEL` | `INFO` | 日誌等級 |

---

## 9. CLI 入口

### 安裝
```bash
pip install -e ".[dev]"
```

### contentflow research（研究報告）
```bash
contentflow research "骨盆前傾改善方法" \
  --ingredients "Acanthopanax" \
  --conditions "pelvic tilt" \
  --output outputs/report.md
```

### 完整 Pipeline 腳本
```bash
python scripts/run_article_pipeline.py --seqno 4
```
依 DB 中的文章序號執行完整五步驟，輸出 Markdown 至 `output/` 目錄。

---

## 10. 測試覆蓋

```bash
pytest tests/ -v --cov=src/contentflow
```

| 測試檔案 | 覆蓋範圍 |
|---------|---------|
| `test_db_and_importer.py` | DB 初始化、Excel 匯入 |
| `test_schemas.py` | Pydantic schema 驗證 |
| `test_project_context.py` | 專案上下文載入 |
| `test_research_agent.py` | Research Agent（mock API）|
| `test_pubmed.py` | PubMed XML 解析 |
| `test_orchestrator.py` | Orchestrator 完整流程（mock）|
| `test_writing_seo_features.py` | 寫作 SEO 功能 |
| `test_seo_check_agent.py` | SEO Check 規則 |
| `test_seo_check_new_rules.py` | 新增 SEO 規則 |
| `test_factcheck_severity.py` | FactCheck 嚴重度分級 |
| `test_image_agent.py` | Image Agent prompt 生成 |
| `test_pipeline_utils.py` | Pipeline 工具函式 |

pytest 設定：`asyncio_mode = "auto"`（所有 async 測試自動支援）

---

## 11. 資料流圖

```
用戶操作（UI 或 CLI）
        │
        ▼
  [ArticleTask]
  title, keywords, project_id
        │
        ▼
  ┌─────────────────────────────────┐
  │    Research Agent               │
  │  PubMed API ──► 學術文獻        │
  │  SERP API   ──► 競品結構        │
  │  GPT-4o-mini ─► 關鍵字建議     │
  └────────────┬────────────────────┘
               │ ResearchReport
               ▼
  ┌─────────────────────────────────┐
  │    Strategy Agent               │
  │  GPT-4o-mini 分析:              │
  │  搜尋意圖 / 痛點 / 架構 / FAQ   │
  └────────────┬────────────────────┘
               │ StrategyReport
               ▼
  ┌─────────────────────────────────┐
  │    Writing Agent                │
  │  大綱生成 → 段落撰寫 → 組合     │
  │  品牌 Prompt 注入               │
  └────────────┬────────────────────┘
               │ ArticleDraft (Markdown)
               ▼
  ┌─────────────────────────────────┐
  │    SEO Check + SEO QA           │
  │  規則引擎評分 → LLM 針對性修正  │
  │  → 重新評分確認                 │
  └────────────┬────────────────────┘
               │ Revised ArticleDraft
               ▼
  ┌─────────────────────────────────┐
  │    FactCheck Agent              │
  │  禁用詞比對 + LLM 事實核對      │
  └────────────┬────────────────────┘
               │ FactCheckItem[]
               ▼
         儲存至 SQLite
    (research_report_json + draft_content
     + seo_score + factcheck flags)
               │
               ▼
        Streamlit UI 審閱
        人工修改 → 發布
```

---

## 12. 已知限制與技術債

### 本次已清理
1. **SEO QA token 限制**：已改為可配置的 `LLM_SEO_QA_MAX_COMPLETION_TOKENS`，預設提升為 4096，降低長文章微調被截斷的機率。

2. **`project_uses_pubmed()` 判斷過窄**：已從單純檢查 `industry` 擴充為綜合判斷品牌描述、寫作原則、策略與法規文字。

3. **SQLAlchemy 2.x 舊 API**：UI 與 `project_context.py` 中的 `Query.get()` 已全部替換為 `Session.get()`。

4. **Windows 不相容暫存路徑**：設定頁 Excel 上傳流程已由硬編碼 `/tmp` 改為 `tempfile.NamedTemporaryFile()`。

5. **首頁 dead code**：`Home.py` 中的 placeholder 程式碼已移除。

6. **2 字中文關鍵字邊界誤判**：`seo_check_agent.py` 已修正，避免把「骨盆」誤配到「髖骨盆腔」這類更長詞組內部片段。

### 目前仍存在的技術債
1. **LangGraph 未充分使用**：依賴清單引入了 `langgraph`，但目前 Pipeline 是以順序呼叫純函式實作，並非 Graph 節點。若需要增加條件分支、回退重試邏輯，應重構為 LangGraph StateGraph。

2. **同步 `get_db()` 與 async agent 並存**：目前仍是同步 SQLAlchemy Session。若未來併發量提升，建議遷移至 `AsyncSession`。

3. **WordPress / Google Sheets 整合尚未實作**：`config.py` 已定義相關設定，但對應功能尚未完善。

4. **API 金鑰仍依賴 `.env`**：正式部署時應改用 secrets manager（如 AWS Secrets Manager / GitHub Secrets）。

5. **SQLite 適合單機開發，不適合多人協作**：若要進入共享部署，應改用 PostgreSQL 並補上備份策略。

6. **Image Agent 預設只生成 prompt**：實際 DALL-E 呼叫仍需手動啟用，尚未納入預設流水線。

7. **沒有文章版本控制**：`draft_content` 目前只保留最新版本，仍無法查看歷史修改。
