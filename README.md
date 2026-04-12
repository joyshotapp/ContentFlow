# ContentFlow AI

> SEO 文章全自動化 Agent 系統

ContentFlow AI 將「選題 → 學術研究 → 撰文 → SEO 審查 → 事實查核」整合為一條全自動 Pipeline，讓內容團隊從重複性產製工作中解放出來，專注於品牌策略與人工審閱。

---

## 目錄

- [系統需求](#系統需求)
- [本地開發環境建置](#本地開發環境建置)
- [環境變數說明](#環境變數說明)
- [啟動應用程式](#啟動應用程式)
- [執行測試](#執行測試)
- [CLI 工具](#cli-工具)
- [目錄結構](#目錄結構)
- [Agent Pipeline 說明](#agent-pipeline-說明)
- [資料庫設計](#資料庫設計)
- [已知架構技術債](#已知架構技術債)
- [常見問題 FAQ](#常見問題-faq)

---

## 系統需求

| 項目 | 最低版本 | 備註 |
|------|---------|------|
| Python | 3.11 | 建議使用 3.12+ |
| 作業系統 | Windows 10 / macOS 12 / Ubuntu 20.04 | |
| OpenAI API Key | — | GPT-4o-mini，主力推理用 |
| Anthropic API Key | — | Claude Sonnet，文章撰寫用（可選） |
| SerpAPI 或 Serper.dev Key | — | SERP 競品分析用（擇一） |

---

## 本地開發環境建置

### 1. 複製專案

```bash
git clone <repo-url>
cd ContentFlow
```

### 2. 建立虛擬環境並安裝依賴

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 安裝套件（含開發工具）
pip install -e ".[dev]"
```

### 3. 設定環境變數

複製範例設定檔並填入 API 金鑰：

```bash
cp .env.example .env
# 用任意編輯器開啟 .env 並填入金鑰
```

詳細說明見 [環境變數說明](#環境變數說明)。

### 4. 初始化資料庫

```bash
python scripts/verify_db.py
```

執行後會在 `data/contentflow.db` 建立 SQLite 資料庫並確認所有資料表存在。

### 5. （可選）匯入初始資料

將關鍵字、寫作規範、產品資料等整理為 Excel 後，透過 Streamlit UI 的「設定」頁面匯入，或執行：

```bash
# 驗證 DB 健康狀態
python scripts/verify_db.py
```

---

## 環境變數說明

在專案根目錄建立 `.env` 檔案（參考以下範本）：

```dotenv
# ── LLM 金鑰 ──────────────────────────────────────────
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# ── 搜尋 API（擇一填入）──────────────────────────────
SERPAPI_KEY=...          # https://serpapi.com
SERPER_API_KEY=...       # https://serper.dev（較便宜）

# ── 資料庫 ─────────────────────────────────────────────
# 預設使用 SQLite，不需更改；切換 PostgreSQL 時填入完整 URL
DATABASE_URL=sqlite:///data/contentflow.db

# ── LLM 模型選擇（可選，有預設值）──────────────────────
LLM_LITE_MODEL=gpt-4o-mini          # 研究/策略/SEO QA 使用
LLM_WRITING_MODEL=claude-sonnet-4-5 # 文章撰寫使用

# ── Token 上限（可選，有預設值）─────────────────────────
LLM_SEO_QA_MAX_COMPLETION_TOKENS=4096

# ── WordPress（尚未實作，留空即可）─────────────────────
WORDPRESS_SITE_URL=
WORDPRESS_USERNAME=
WORDPRESS_APP_PASSWORD=

# ── Google Sheets（尚未實作，留空即可）──────────────────
GOOGLE_SHEETS_SCHEDULE_ID=
```

> **注意**：`.env` 檔案不應提交至 git。請確認 `.gitignore` 已包含 `.env`。

---

## 啟動應用程式

```bash
# 確認已啟動 venv
streamlit run app/Home.py
```

瀏覽器會自動開啟 `http://localhost:8501`。

**頁面說明：**

| 頁面 | 功能 |
|------|------|
| 🏠 Home | KPI 儀表板、文章狀態圓餅圖、內容日曆甘特圖、關鍵字 Top 10 |
| 📝 文章管理 | 文章列表、狀態篩選、草稿內容查看與手動編輯 |
| 🔑 關鍵字 | 關鍵字資料庫、搜尋量、CPC、優先度 |
| 📅 內容日曆 | 月/週度內容排程規劃 |
| 📜 撰寫規範 | 品牌寫作原則、禁止用語、語氣設定 |
| 🏢 競品分析 | 競業市場研究與分析紀錄 |
| 📦 產品資訊 | 產品系列、成分、適用症狀 |
| ⚖️ 法規合規 | 食品廣告法規用詞（允許/禁止/注意）|
| 🔬 AI 研究 | **主要操作入口** — 啟動 Pipeline、查看研究報告、SEO 評分、事實查核 |
| ⚙️ 設定 | Excel 匯入、API 連線狀態、DB 統計 |

---

## 執行測試

```bash
# 執行完整測試套件
pytest

# 顯示詳細輸出
pytest -v

# 含測試覆蓋率報告
pytest --cov=src/contentflow

# 僅跑特定測試檔
pytest tests/test_seo_check_agent.py -v
```

**測試套件結構：**

| 測試檔案 | 覆蓋範圍 |
|---------|---------|
| `test_db_and_importer.py` | DB 初始化、Excel 匯入 |
| `test_schemas.py` | Pydantic Schema 驗證 |
| `test_project_context.py` | 專案上下文載入 |
| `test_research_agent.py` | Research Agent（mock API）|
| `test_pubmed.py` | PubMed XML 解析 |
| `test_orchestrator.py` | 完整 Pipeline 流程（mock）|
| `test_writing_seo_features.py` | 寫作 SEO 功能 |
| `test_seo_check_agent.py` | SEO Check 規則引擎 |
| `test_seo_check_new_rules.py` | 進階 SEO 規則 |
| `test_factcheck_severity.py` | FactCheck 嚴重度分級 |
| `test_image_agent.py` | Image Agent Prompt 生成 |
| `test_pipeline_utils.py` | Pipeline 工具函式 |

> 目前 126 個測試全數通過（`asyncio_mode = "auto"`）。

---

## CLI 工具

除了 Streamlit UI 之外，也可透過命令列直接操作：

```bash
# 執行單一關鍵字的研究階段
contentflow research \
  --keyword "骨盆前傾" \
  --project-id 1 \
  --ingredients "Acanthopanax" \
  --conditions "pelvic tilt" \
  --output outputs/report.md

# 對指定文章執行完整五步驟 Pipeline
python scripts/run_article_pipeline.py --seqno 4

# 資料庫健康檢查
python scripts/verify_db.py
```

---

## 目錄結構

```
ContentFlow/
├── .env                         # 本地環境變數（不提交 git）
├── .env.example                 # 環境變數範本
├── pyproject.toml               # 套件設定、依賴宣告、工具設定
├── SYSTEM_OVERVIEW.md           # 進階系統技術文件
│
├── app/                         # Streamlit 前端
│   ├── Home.py                  # 首頁儀表板
│   ├── project_selector.py      # 全域 Sidebar 專案切換元件
│   └── pages/                   # Streamlit 多頁面（依此順序顯示）
│       ├── 1_📝_文章管理.py
│       ├── 2_🔑_關鍵字.py
│       ├── 3_📅_內容日曆.py
│       ├── 4_📜_撰寫規範.py
│       ├── 5_🏢_競品分析.py
│       ├── 6_📦_產品資訊.py
│       ├── 7_⚖️_法規合規.py
│       ├── 8_🔬_AI研究.py       # 主操作入口
│       └── 9_⚙️_設定.py
│
├── src/contentflow/             # 核心套件
│   ├── config.py                # 全域設定（pydantic-settings，讀取 .env）
│   ├── db.py                    # DB 引擎、Session、自動 schema 補丁
│   ├── project_context.py       # 載入品牌資訊並注入 Agent prompt
│   ├── cli.py                   # CLI 入口（contentflow 指令）
│   │
│   ├── agents/                  # 各 Agent 模組
│   │   ├── orchestrator.py      # Pipeline 統一協調（呼叫以下各 agent）
│   │   ├── research_agent.py    # SERP + PubMed → ResearchReport
│   │   ├── strategy_agent.py    # SEO 策略分析 → StrategyReport
│   │   ├── writing_agent.py     # 三階段撰文（大綱→段落→完整稿）
│   │   ├── seo_qa_agent.py      # SEO LLM 微調（meta / 開頭段落）
│   │   ├── seo_check_agent.py   # SEO 規則引擎評分（零 LLM 成本）
│   │   ├── factcheck_agent.py   # 事實查核 + 禁用詞比對
│   │   └── image_agent.py       # 配圖 Prompt + DALL-E（預設關閉）
│   │
│   ├── models/
│   │   ├── database.py          # SQLAlchemy ORM（15 張資料表）
│   │   └── schemas.py           # Pydantic Schema（Agent I/O 驗證）
│   │
│   ├── tools/
│   │   ├── serp.py              # Google SERP 搜尋工具
│   │   ├── pubmed.py            # PubMed E-utilities 工具
│   │   ├── keyword.py           # 關鍵字工具
│   │   └── excel_importer.py    # Excel → SQLite 匯入
│   │
│   └── utils/
│       └── report_renderer.py   # 研究報告 → Markdown 渲染
│
├── scripts/
│   ├── run_article_pipeline.py  # 完整 Pipeline CLI 腳本
│   ├── migrate_add_projects.py  # 資料庫遷移腳本
│   └── verify_db.py             # DB 健康檢查
│
├── data/
│   ├── contentflow.db           # SQLite 資料庫（自動建立，不提交 git）
│   └── templates/
│       └── research_report_template.md
│
└── tests/                       # pytest 測試套件
```

---

## Agent Pipeline 說明

一篇文章從無到成稿，經過以下五個步驟：

```
用戶觸發（UI 或 CLI）
       │
       ▼
 [Step 1] Research Agent
   ├── SERP API → 競品前 10 篇文章結構
   ├── PubMed API → 學術文獻（依產業自動判斷是否啟用）
   └── GPT-4o-mini → 彙整 ResearchReport
       │
       ▼
 [Step 2] Strategy Agent
   └── GPT-4o-mini → 搜尋意圖 / 讀者痛點 / 文章架構建議 / FAQ
       │
       ▼
 [Step 3] Writing Agent
   └── Claude Sonnet（可設定）→ 大綱 → 段落 → 完整 Markdown
       │
       ▼
 [Step 4] SEO Check + SEO QA Agent
   ├── SEO Check（純規則引擎，零 LLM 成本）→ 評分 + 缺失清單
   └── SEO QA（LLM）→ 針對缺失微調 → 重新評分確認
       │
       ▼
 [Step 5] FactCheck Agent
   └── GPT-4o-mini → 禁用詞比對 + 事實核對 → FactCheckItem[]
       │
       ▼
   存入 SQLite（draft_content + seo_score + factcheck_flags）
       │
       ▼
   Streamlit UI 人工審閱 → 發布
```

**專案上下文注入**：每個 Agent 在呼叫 LLM 前，都會透過 `project_context.py` 載入該專案的品牌名稱、撰寫原則、法規詞庫等，確保輸出符合品牌調性。

**SEO Check 評分項目（11 項規則引擎）**：

| 規則 | 說明 |
|------|------|
| 標題含主關鍵字 | `<h1>` 必須包含主關鍵字 |
| Meta 描述長度 | 70–160 字元 |
| 關鍵字密度 | 0.5%–3.0% |
| 內文長度 | ≥800 字 |
| 小標結構 | H2/H3 層次使用 |
| FAQ 區塊 | 是否包含 FAQ |
| 站內連結 | 內部連結數量 |
| 圖片 Alt 文字 | 圖片 alt 屬性 |
| 段落可讀性 | 段落平均長度 |
| 開頭關鍵字 | 前 100 字是否含關鍵字 |
| 結構化資料 | JSON-LD schema 是否存在 |

---

## 資料庫設計

- 預設使用 **SQLite**，資料庫存放於 `data/contentflow.db`
- 所有資料表均有 `project_id` 欄位，支援多個品牌/客戶共用同一資料庫
- **自動 schema 補丁**：`db.py` 在每次啟動時自動偵測缺少的欄位並執行 `ALTER TABLE`，確保向下相容

### 主要資料表

| 資料表 | 說明 |
|--------|------|
| `projects` | 多租戶根節點，品牌資訊與寫作原則 |
| `articles` | 文章主表，含完整生命週期（planned → published） |
| `keywords` | 關鍵字庫（搜尋量、CPC、SEO 難度） |
| `content_calendar` | 月/週度內容排程 |
| `writing_rules` | 品牌撰寫規範 |
| `legal_terms` | 食品廣告法規用詞 |
| `competitors` | 競品研究資料 |
| `products` | 產品系列資料 |

切換至 PostgreSQL 只需更改 `.env`：

```dotenv
DATABASE_URL=postgresql://user:password@localhost:5432/contentflow
```

---

## 已知架構技術債

> 以下為系統目前存在的架構層級技術債項目。這些並非 bug，現有功能運作正常，但在擴展規模或正式部署前需要刻意決策與處理。新接手的工程師應在動手修改前完整理解這些脈絡。

---

### ⚠️ TD-01：LangGraph 引入但未實際使用

**現況：** `pyproject.toml` 依賴清單中已引入 `langgraph`，但 `orchestrator.py` 的 Pipeline 仍是純順序函式呼叫，與 LangGraph 的 Graph 節點架構無關。

**風險：** 若需要加入條件分支（例如：研究失敗時跳過撰文）或回退重試邏輯，目前架構無法優雅支援。

**建議做法：** 將 `orchestrator.py` 重構為 `StateGraph`，每個 Agent 為一個節點，失敗條件觸發特定邊（edge）。參考：[LangGraph 官方文件](https://langchain-ai.github.io/langgraph/)

**影響評估：** 中高。需完整重寫 `orchestrator.py` 並同步更新相關測試 `test_orchestrator.py`。

---

### ⚠️ TD-02：同步 SQLAlchemy Session 與非同步 Agent 並存

**現況：** `db.py` 中的 `get_db()` 回傳同步 `Session`，而所有 Agent 函式均為 `async def`。Streamlit 頁面透過同步方式存取 DB，Agent 呼叫時以 `asyncio.run()` 或 await 驅動。

**風險：** 高並發情境下同步 Session 會阻塞事件迴圈，導致效能瓶頸。目前單機低並發下無明顯問題。

**建議做法：** 遷移至 `AsyncSession` + `aiosqlite`（SQLite）或 `asyncpg`（PostgreSQL）。`db.py` 需改為 `async_sessionmaker`。

**影響評估：** 高。需改動 `db.py`、所有使用 `get_db()` 的頁面，以及 Agent 內部的 DB 操作。

---

### ⚠️ TD-03：WordPress / Google Sheets 整合未實作

**現況：** `config.py` 中已定義 `WORDPRESS_SITE_URL`、`WORDPRESS_USERNAME`、`WORDPRESS_APP_PASSWORD`、`GOOGLE_SHEETS_SCHEDULE_ID` 等設定欄位，且 `pyproject.toml` 已引入 Google API 相關套件，但沒有任何程式碼實作對應功能。

**風險：** 設定欄位存在但無對應功能，容易讓接手工程師誤以為功能已完成。

**建議做法：**
- WordPress：透過 [WordPress REST API](https://developer.wordpress.org/rest-api/) 實作 `POST /wp/v2/posts`，在文章審閱通過後自動發布。
- Google Sheets：透過 `google-api-python-client` 讀寫 `GOOGLE_SHEETS_SCHEDULE_ID` 指定的試算表，作為內容日曆的資料來源。

**影響評估：** 中。屬於新增功能，不影響現有 Pipeline。需新增 `tools/wordpress.py`、`tools/google_sheets.py` 並整合至 UI。

---

### ⚠️ TD-04：API 金鑰儲存於 `.env` 檔案

**現況：** OpenAI、Anthropic、SerpAPI 等金鑰透過 `.env` 檔案載入。

**風險：** 開發環境可接受。但正式部署至雲端或 CI/CD 環境時，`.env` 檔案存在洩漏風險（例如不小心提交、容器映像層暴露等）。

**建議做法（依部署平台選擇）：**
- AWS：使用 [AWS Secrets Manager](https://aws.amazon.com/secrets-manager/) 並透過 IAM Role 授權
- GCP：使用 [Secret Manager](https://cloud.google.com/secret-manager)
- Vercel / Railway：使用平台內建的環境變數加密機制
- Docker 部署：透過 Docker Secrets 或 Kubernetes Secrets

**近期最小改善：** 至少確保 `.env` 已加入 `.gitignore`，且不存在於任何 Docker image 層中。

---

### ⚠️ TD-05：SQLite 不適合多用戶正式部署

**現況：** 預設資料庫為 `data/contentflow.db`（SQLite），適合單機開發與小型內部使用。

**風險：** SQLite 在多個 writer 同時寫入時會發生 locked 錯誤。若多名編輯同時使用 Streamlit UI，可能出現競態條件。此外 SQLite 不支援完整的備份/還原策略。

**建議做法：** 正式部署改用 PostgreSQL。切換方式：

```dotenv
# .env
DATABASE_URL=postgresql://user:password@host:5432/contentflow
```

同時需安裝 `psycopg2-binary` 或 `asyncpg`（若同步推進 TD-02）。

**影響評估：** 低到中。切換 URL 即可運作（SQLAlchemy 負責抽象層），但需注意 SQLite 特有的 schema 補丁邏輯（`_ensure_sqlite_columns()`）在 PostgreSQL 需改為正式 migration 工具（如 [Alembic](https://alembic.sqlalchemy.org/)）。

---

### ⚠️ TD-06：Image Agent DALL-E 生成預設關閉，且無法透過設定啟用

**現況：** `image_agent.py` 中 `generate_images` 參數預設為 `False`，且沒有對應的 config 欄位或 UI 開關。若要啟用 DALL-E 圖片生成，需直接修改程式碼。

**風險：** 非技術人員無法自行啟用；且目前只有 Prompt 生成邏輯，尚未完整實作圖片儲存與 URL 回寫至 `articles.image_url`。

**建議做法：**
1. 在 `config.py` 新增 `ENABLE_IMAGE_GENERATION=false` 欄位
2. `image_agent.py` 改為讀取此設定
3. 補齊圖片下載並存至 `data/images/`，將路徑寫回 DB

**影響評估：** 低。範圍侷限於 `image_agent.py` 與 `config.py`。

---

### ⚠️ TD-07：無文章版本歷史，草稿永遠被覆蓋

**現況：** `Article` 模型只有一個 `draft_content` 欄位。每次 Pipeline 產生新稿或人工修改，都會直接覆蓋舊內容，無法還原。

**風險：** 若 LLM 或人工修改後內容變差，無法回滾至前一個版本。

**建議做法：** 新增 `article_versions` 資料表：

```python
class ArticleVersion(Base):
    __tablename__ = "article_versions"
    id: int (PK)
    article_id: int (FK → articles.id)
    version: int          # 自動遞增版本號
    content: str          # 當時的 draft_content 快照
    source: str           # "pipeline" / "manual" / "seo_qa"
    created_at: datetime
```

每次儲存前先 insert 一筆版本紀錄，UI 提供版本對照與選擇性還原。

**影響評估：** 中。需新增資料表、修改 `orchestrator.py` 儲存邏輯，以及 UI 版本歷史介面。

---

## 常見問題 FAQ

**Q: 我沒有 Anthropic API Key，可以只用 OpenAI 嗎？**

可以。在 `.env` 中設定：
```dotenv
LLM_WRITING_MODEL=gpt-4o-mini
```
`writing_agent.py` 會依據模型名稱自動選擇 OpenAI 或 Anthropic client。

---

**Q: 執行 `streamlit run app/Home.py` 後頁面空白或報錯？**

1. 確認 `.env` 已建立且 `OPENAI_API_KEY` 已填入
2. 確認已執行 `python scripts/verify_db.py` 完成 DB 初始化
3. 確認虛擬環境已啟動（`pip install -e ".[dev]"` 已執行）

---

**Q: `pytest` 顯示 `ModuleNotFoundError`？**

確認安裝方式使用 `pip install -e ".[dev]"` 而非僅 `pip install -r requirements.txt`（本專案無 `requirements.txt`，依賴宣告在 `pyproject.toml`）。

---

**Q: 如何新增一個品牌/客戶（Project）？**

在 Streamlit UI 的 Home 頁面，點擊 Sidebar 的「新增專案」按鈕，填入品牌名稱與產業後儲存。所有後續資料（關鍵字、文章、規範）都會自動綁定該專案。

---

**Q: Pipeline 費用大概多少？**

以 GPT-4o-mini 為主力，一篇約 1,500 字的文章（含研究、策略、SEO QA）約 **$0.02–0.05 USD**。若 Writing Agent 設定為 Claude Sonnet，寫作階段額外約 **$0.05–0.15 USD**。

---

*詳細技術架構請參閱 [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)。*
