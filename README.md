# ContentFlow AI

> SEO 自主優化閉環系統（Autonomous SEO Optimization Loop）

ContentFlow AI 是一套**全自動 SEO 閉環系統**，整合 AI 策略決策、內容生產、自動發布、數據回饋與持續學習，形成完整的自我優化迴路，每日自動選題、研究、撰寫、審查、發布，並持續從排名回饋中學習優化。

**核心閉環流程：**
```
資料分析（GSC/GA4）→ 策略規劃 → 研究 → 寫作 → SEO 審查 → 事實查核 → 自動發布
       ↑                                                                    │
       └────────── 學習反思（排名回饋 → 知識庫 → 下一輪優化）─────────────────┘
```

---

## 系統定位與人機角色

### 這套系統是什麼

ContentFlow AI 不是通用 AI 寫作工具，而是**針對特定網站打造的 SEO 內容自主運轉機器**。它的設計假設是：一個人可以操作，但不需要每天手動介入。

| 面向 | 說明 |
|------|------|
| **設計對象** | 需要持續產出 SEO 內容的單一網站擁有者或小型團隊 |
| **產能定位** | 每日自動生產 1 篇 SEO 文章，產能等同一個小型內容團隊 |
| **部署現況** | 已在 Linode 生產環境服務 goodbone.com.tw（繁體中文骨科保健） |
| **多租戶支援** | 程式碼層面支援多個 Project，共用同一資料庫 |

### 人的角色：監督者，不是操作者

系統設計的目標是讓「人」從「每天操作」退到「例外處理」：

```
自動（每日）                        人工（例外時）
────────────────────────────────    ──────────────────────────────────
• Strategic Agent 決定今天寫什麼    • 審閱 SEO 分數未達門檻的稿件
• Research + Writing Agent 生產稿件 • 處理 FactCheck 標記的高風險聲明
• SEO 評分 → 達標自動發布           • 確認 GSC 偵測到的新機會詞方向
• 排名回饋 → 知識庫自動更新         • 調整品牌撰寫規範或關鍵字策略
• 22 個排程任務靜默監控全站健康     • 在 Admin 後台查看週報摘要
```

### 與一般 AI 寫作工具的差異

| 比較維度 | 一般工具（Jasper / Copy.ai） | ContentFlow AI |
|---------|--------------------------|----------------|
| 觸發方式 | 人給指令 → 輸出文字 | 系統自己看數據 → 自己決定寫什麼 |
| 選題來源 | 人工輸入關鍵字 | GSC 排名數據 + 日曆策略自動選題 |
| 品質把關 | 人工審閱 | SEO 規則引擎（11 項）+ LLM QA 最多 3 輪 |
| 發布 | 人工複製貼上 | 自動發布 WordPress / ForgeBase + Google Indexing API |
| 學習機制 | 無 | 每週反思 → 知識庫 → 下次寫得更好 |
| 監控 | 無 | 22 個排程任務持續監控排名、索引、反向連結 |

---

## 目錄

- [產品定位與商業模式](#產品定位與商業模式)
- [系統需求](#系統需求)
- [本地開發環境建置](#本地開發環境建置)
- [環境變數說明](#環境變數說明)
- [啟動應用程式](#啟動應用程式)
- [執行測試](#執行測試)
- [CLI 工具](#cli-工具)
- [SEO 閉環與後台](#seo-閉環與後台)
- [目錄結構](#目錄結構)
- [Agent Pipeline 說明](#agent-pipeline-說明)
- [資料庫設計](#資料庫設計)
- [已知架構技術債](#已知架構技術債)
- [常見問題 FAQ](#常見問題-faq)

---

## 產品定位與商業模式

### 這款產品現在代表什麼？

ContentFlow 已完成「Phase 0–6 產品獨立化」，從「GoodBone 網站的專屬工具」升級為**可對外服務多個客戶的 SEO AI 平台**。

具體完成的邊界包含：
- 每個客戶（Project）有獨立的品牌設定、Connector（WordPress / ForgeBase 帳號）、RBAC 角色、審核流程、使用量紀錄
- 平台層與客戶端站台完全分離（`control-plane` vs `managed-site` 模式）
- GoodBone 從「硬寫在系統裡」變成「第一個掛上去、已驗證的租戶」，而非產品邊界本身
- Connector 金鑰以 Fernet 加密存 DB（`cfsec:v1:` prefix）
- Onboarding checklist、Approval history、Audit trail、Usage metering 基礎全部到位

---

### 端到端文章生命週期

```
1. 管理員輸入關鍵字（或排程自動觸發）
        ↓
2. Research Agent
   → 抓 SERP 前 10 競品結構 + PAA
   → 抓 PubMed 學術佐證（醫療類專案自動啟用）
        ↓
3. Strategy Agent
   → 搜尋意圖分析、文章架構、FAQ 骨架
        ↓
4. Writing Agent（三階段：大綱 → 段落 → 完整稿）
   → 含 JSON-LD Schema（FAQ / HowTo / Article）
        ↓
5. SEO Check（規則引擎，零 LLM 成本）→ 低於 85 分退回 SEO QA 修稿（最多 3 輪）
        ↓
6. FactCheck Agent → 法規詞庫比對 + 學術陳述核實
        ↓
7. Budget Guard → 確認 LLM 呼叫 ≤ 15 次 / 成本 ≤ $2.00
        ↓
8. 草稿進 Admin 後台等人工審閱（或達標自動發布）
        ↓
9. 發布至 WordPress / ForgeBase + Google Indexing API 主動送交收錄
        ↓
10. 排程器每日同步 GSC 排名 + GA4 → 回寫 DB → 驅動下一輪策略
```

---

### 可視為一款對外獨立產品嗎？

**是，但有條件。**

#### 已具備的條件 ✅

| 項目 | 說明 |
|------|------|
| 多租戶架構 | 多個 Project 共用平台，資料完全隔離 |
| RBAC 角色控管 | Admin / Reviewer / Editor，客戶間資料互不可見 |
| Connector 加密 | API 金鑰 Fernet 加密存 DB |
| Onboarding checklist | 新客戶設定引導流程 |
| 成本計量基礎 | 每篇文章 LLM 成本有完整記錄 |
| 審核流程 | Approval history + Audit trail |
| 部署自動化 | `setup_remote.sh` 一鍵部署，含等待迴圈與健康驗證 |
| 正式 HTTPS 上線 | `goodbone.com.tw` 已驗證為第一個租戶 |
| 匿名健康探針 | `GET /health` 無需認證，供 Docker / 外部監控使用 |

#### 目前仍缺少（對外商業化）⚠️

| 缺口 | 影響 |
|------|------|
| 無自助註冊 / 付費頁面 | 每個客戶需手動開通，無法規模化 |
| 無 Stripe / 計費整合 | 成本有記錄，但無法自動開發票或限額控管 |
| 無客戶獨立 subdomain | 所有租戶共用同一網址空間 |
| WordPress connector 需手動設定 | 技術門檻偏高，非技術型客戶難上手 |
| 無公開說明文件 / 官網 | 潛在客戶無法自行了解與評估 |

---

### 適合的商業模式

#### 模式一：代操服務（最快變現，最符合現狀）

```
客戶付月費 → 你幫他跑 ContentFlow → 每月交付 N 篇 SEO 文章 + 成效報告
```

- **定價參考**：NT$5,000–$30,000/月（依篇數與產業）
- **你負責**：開設專案、調整品牌設定、審核草稿、確認發布
- **客戶只看**：排名變化、流量成長、月報
- **優點**：現在就可以做，系統完全夠用，GoodBone 是活生生的 case study
- **適合客戶**：診所、律師事務所、電商品牌、補習班（有 SEO 需求但無技術能力）

#### 模式二：白牌 / 授權給 SEO 代理商

```
SEO 代理商付平台費 → 用 ContentFlow 服務他們自己的多個客戶
```

- **定價參考**：NT$50,000–$150,000/月（平台使用費）
- 代理商自行管理各自的 Project，你只維護平台基礎設施
- **優點**：一個代理商 = 10–30 個最終客戶，收入倍增不等比增加人力
- **需要補強**：白牌品牌設定、多語系支援、代理商專屬管理視圖

#### 模式三：垂直領域 SaaS（中期目標）

針對特定產業深度優化，建立競爭壁壘：

```
醫療診所版 ContentFlow
  → 內建 PubMed 整合 + 台灣醫療法規詞庫（已完成）
  → 內建 GoodBone 驗證過的 SEO 規則（已完成）
  → 月費 NT$8,000/診所
```

- **差異化優勢**：一般 AI 寫文工具沒有台灣醫療法規合規 + 學術佐證 + 骨科/復健 SEO 知識庫
- GoodBone 的真實排名成效就是最強的銷售工具
- 可複製模式到牙科、眼科、中醫等鄰近市場

#### 模式四：B2B API（長期）

開放 `/api/v1/articles/generate` 給其他平台串接，按篇計費（類似 OpenAI API 的計費模型）。

---

### 建議的優先順序

| 階段 | 時間 | 行動 |
|------|------|------|
| **立刻** | 現在 | 用現有系統接第 2 個真實客戶（代操），驗證多租戶流程 |
| **短期** | 1 個月 | 做一頁式官網 + 定價頁，讓潛在客戶能自行了解 |
| **中期** | 3 個月 | 串接 Stripe，讓付款與配額管理自動化 |
| **長期** | 6 個月 | 自助註冊流程，走向真正的 SaaS |

> GoodBone 的實際 SEO 成效（排名、流量、文章品質）是這款產品最有力的市場證明。每一篇已發布的文章都是可展示的 demo。

---

## 系統需求

| 項目 | 最低版本 | 備註 |
|------|---------|------|
| Python | 3.11 | 建議使用 3.12+ |
| 作業系統 | Windows 10 / macOS 12 / Ubuntu 20.04 | |
| Gemini API Key | — | gemini-3-flash-preview，所有 Agent 主力 LLM |
| OpenAI API Key | — | LLM fallback（可選）|
| Anthropic API Key | — | LLM fallback（可選）|
| SerpAPI 或 Serper.dev Key | — | SERP 競品分析用（擇一）|
| Google Service Account | — | GSC 排名同步 + GA4 頁面指標（可選）|
| PostgreSQL | 14+ | 正式環境必備；開發可用 SQLite |

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

# 若需要 AgentOps 可觀測性
pip install -e ".[dev,observability]"
```

### 3. 設定環境變數

複製範例設定檔並填入 API 金鑰：

```bash
cp .env.example .env
# 用任意編輯器開啟 .env 並填入金鑰
```

詳細說明見 [環境變數說明](#環境變數說明)。

### 4. 啟動服務（Docker Compose 推薦）

```bash
docker-compose up -d
```

服務啟動後：
- **Admin 後台**：`http://localhost:8000/admin`（密碼：`API_SECRET_KEY`）
- **Public 站台**：`http://localhost:8000/`

PostgreSQL 資料庫由 Docker Compose 自動建立；`migrate` service 會在 `api` 啟動前自動執行 bootstrap runner。空庫會自動建 schema 並對齊 Alembic revision，既有庫則會升級到最新 head。

### 4b. 本地開發（不使用 Docker）

```bash
source .venv/bin/activate
pip install -e ".[dev]"
# 確保 DATABASE_URL 指向本地 PostgreSQL 或 SQLite
python -m contentflow.db_bootstrap  # 使用 PostgreSQL 時先跑 bootstrap / migration
uvicorn contentflow.api:app --reload --port 8000
```

---

## 環境變數說明

在專案根目錄建立 `.env` 檔案（參考以下範本）：

```dotenv
# ── LLM 金鑰（必填）────────────────────────────────────
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GEMINI_API_KEY=...             # 主要 LLM（gemini-3-flash-preview）+ 圖片生成（gemini-3.1-flash-image-preview）

# ── 搜尋 API（擇一填入）─────────────────────────────────
SERPAPI_KEY=...                # https://serpapi.com
SERPER_API_KEY=...             # https://serper.dev（較便宜）

# ── DataForSEO（排名追蹤 / SERP 補充 / 反向連結監控，可選）──
DATAFORSEO_LOGIN=...
DATAFORSEO_PASSWORD=...
BACKLINK_SYNC_ENABLED=false    # true = 每週同步反向連結摘要

# ── Google Business Profile（本地 SEO 監控，可選）──────────
GBP_LOCATION_IDS=              # GBP location ID，多個以逗號分隔
GBP_LOCATION_PROJECT_MAP=      # location_id:project_id，例：123456789:2,987654321:5
GBP_OAUTH_ACCESS_TOKEN=...     # Business Profile API OAuth access token

# ── 資料庫（正式環境必填）──────────────────────────────
DATABASE_URL=postgresql+psycopg2://user:pass@db:5432/contentflow
# 本地 SQLite 開發：sqlite+aiosqlite:///data/contentflow.db

# ── Google Service Account（GSC + Google Indexing API）──
GOOGLE_SERVICE_ACCOUNT_FILE=/app/creds/google_service_account.json

# ── Google Analytics 4 ─────────────────────────────────
GA4_PROPERTY_ID=properties/XXXXXXXXX
GA4_MEASUREMENT_ID=G-XXXXXXXXXX

# ── Cloudflare R2（Hero Image 上傳）──────────────────────
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT_URL=https://ACCOUNT_ID.r2.cloudflarestorage.com
R2_BUCKET_NAME=contentflow-images
R2_PUBLIC_URL=https://images.yourdomain.com

# ── ForgeBase / Headless CMS（自動發布）──────────────────
FORGEBASE_API_BASE_URL=https://api.forgebase.io
FORGEBASE_API_KEY=...
FORGEBASE_SITE_ID=...

# ── WordPress（自動發布）────────────────────────────────
WORDPRESS_SITE_URL=https://yourdomain.com
WORDPRESS_USERNAME=...
WORDPRESS_APP_PASSWORD=...

# ── PubMed NCBI API（學術文獻查詢）──────────────────────
NCBI_API_KEY=...
NCBI_EMAIL=your@email.com

# ── ChromaDB 知識庫 ─────────────────────────────────────
CHROMA_PERSIST_DIR=/app/data/chroma

# ── LLM 模型選擇（可選，有預設值）──────────────────────
LLM_LITE_MODEL=gemini-3-flash-preview    # 研究/策略/SEO QA 使用
LLM_WRITING_MODEL=gemini-3-flash-preview # 文章撰寫使用（DALL-E 圖片生成改用 Gemini）

# ── 行為控制（可選）────────────────────────────────────
LLM_SEO_QA_MAX_COMPLETION_TOKENS=4096
MAX_ARTICLES_PER_RUN=5
STRATEGIC_DAILY_GENERATE_LIMIT=5
SCHEDULER_ENABLED=true
SCHEDULER_TIMEZONE=Asia/Taipei

# ── 後台 / 對外站點（建議正式環境設定）────────────────────
API_SECRET_KEY=change-me-to-strong-secret
ADMIN_URL=https://yourdomain.com
SITE_URL=https://yourdomain.com

# ── 監控 / 通知（可選）─────────────────────────────────
AGENTOPS_API_KEY=...           # LLM 用量追蹤
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...  # 週報通知
```

> **注意**：`.env` 檔案不應提交至 git。請確認 `.gitignore` 已包含 `.env`。

---

## 啟動應用程式

### 正式環境（Docker Compose — 推薦）

```bash
# 複製設定檔
cp .env.example .env
# 填入 API 金鑰後啟動
docker-compose up -d
```

服務啟動後：
- Admin 後台：`http://localhost:8000/admin`（登入密碼：`API_SECRET_KEY`）
- Public 站台：`http://localhost:8000/`

### 本地開發環境

```bash
source .venv/bin/activate
uvicorn contentflow.api:app --reload --port 8000
```

**Admin 後台頁面說明：**

| 頁面路由 | 功能 |
|---------|------|
| `/admin` | KPI 儀表板、文章統計、快速操作入口 |
| `/admin/articles` | 文章管理、狀態篩選、手動觸發 Pipeline |
| `/admin/agents` | Agent Pipeline 執行紀錄、費用分析 |
| `/admin/keywords` | 關鍵字庫、AI 挖掘、批次匯入 |
| `/admin/calendar` | 月/週度內容排程規劃 |
| `/admin/clusters` | Topic Cluster 主題叢集管理 |
| `/admin/seo` | GSC 排名趨勢、關鍵字等級分布、機會詞 |
| `/admin/content-health` | 關鍵字自蝕偵測、Refresh 待辦 |
| `/admin/tech-seo` | Core Web Vitals、GA4 頁面指標 |
| `/admin/knowledge` | 知識庫管理（AI 學習成果）|
| `/admin/reports` | 週報/月報/季報中心 |
| `/admin/scheduler` | 排程任務監控與手動觸發 |
| `/admin/pipeline-runs` | Pipeline 執行歷史 |
| `/admin/strategic-plans` | Strategic Agent 決策紀錄 |
| `/admin/reflections` | 週反思學習日誌 |
| `/admin/settings` | 專案設定、API 狀態、自動發布規則 |
| `/admin/health` | 系統健康檢查 |

---

## SEO 閉環與後台

系統由 FastAPI 驅動，分為三層：

- **Admin 後台** `/admin`：完整管理介面，含 AI Pipeline 觸發、排程監控、SEO 報表
- **Public Reference Site** `/`：SEO 驗證前端，支援 JSON-LD schema、BreadcrumbList、TOC、FAQ 手風琴、E-E-A-T 信號
- **Scheduler**：獨立 `scheduler` service，APScheduler 驅動 21 個排程任務（含每分鐘 heartbeat），涵蓋 GSC/GA4 同步、反向連結監控、GBP 整合、策略分析、自動發布、索引健康監控、反思學習等。Heartbeat 機制每分鐘寫入 `scheduler_heartbeat.json`，`/health` 端點透過 heartbeat 新鮮度驗證排程器真實活性（非僅 PID 存活）

管理員登入密碼：`API_SECRET_KEY` 環境變數；**未設定時系統回傳 503 拒絕啟動，不提供任何 fallback 密碼**（安全設計）

**自動發布機制**：每個 Project 可獨立設定 `auto_publish_enabled` 與 `auto_publish_min_score`（預設 85 分）。Pipeline 完成後若分數達標，系統自動發布至 WordPress 或 ForgeBase，並呼叫 Google Indexing API 主動請求收錄。

### 目前實際部署現況

- 公網主站：`https://goodbone.com.tw/`（繁體中文骨科保健）
- Admin 後台：`https://goodbone.com.tw/admin`
- 資料庫：PostgreSQL 16（Docker）
- Scheduler：獨立 service，21 個排程任務，heartbeat 機制確保真實活性
- 已發布文章：23 篇（截至 2026-05）
- 自動發布：Project id=2「好骨科診所」已啟用，最低分數 85 分
- 建置驗證：`398 passed`，`/health` 回傳 `status=ok`、`scheduler=running`
- 最新 commit：`bb21fe9`（匿名 /health 探針 + 強固化部署腳本）

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

> 目前 398 個測試通過（`asyncio_mode = "auto"`）。`AgentOps` 已改為可選依賴，不再阻塞測試收集。

---

## CLI 工具

除了 Web Admin 之外，也可透過命令列直接操作：

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
├── docker-compose.yml           # 本地開發容器編排（api + db）
├── Dockerfile                   # 主服務映像
├── SYSTEM_OVERVIEW.md           # 進階系統技術文件
│
├── src/contentflow/             # 核心套件
│   ├── config.py                # 全域設定（pydantic-settings，讀取 .env）
│   ├── db.py                    # DB 引擎、Session、自動 schema 補丁
│   ├── api.py                   # FastAPI 主應用（掛載 site + admin）
    ├── scheduler.py             # APScheduler — 21 個排程任務（含 heartbeat）
│   ├── scheduler_runner.py      # 獨立 Scheduler service 進入點
│   ├── project_context.py       # 載入品牌資訊並注入 Agent prompt
│   ├── llm_client.py            # 多 Provider LLM（OpenAI → Anthropic failover）
│   ├── cli.py                   # CLI 入口（contentflow 指令）
│   │
│   ├── agents/                  # 各 Agent 模組
│   │   ├── orchestrator.py      # LangGraph StateGraph Pipeline 協調
│   │   ├── research_agent.py    # SERP + PubMed → ResearchReport
│   │   ├── strategy_agent.py    # SEO 策略分析 → StrategyReport
│   │   ├── writing_agent.py     # 三階段撰文（大綱→段落→完整稿）
│   │   ├── seo_check_agent.py   # SEO 規則引擎評分（零 LLM 成本）
│   │   ├── seo_qa_agent.py      # SEO LLM 微調（meta / 開頭段落）
│   │   ├── factcheck_agent.py   # 事實查核 + 禁用詞比對
│   │   ├── budget_guard.py      # 預算守門（LLM 呼叫次數 + 金額上限）
│   │   ├── image_agent.py       # 配圖 Prompt + Alt Text + SEO 檔名
│   │   ├── hero_image_agent.py  # Gemini 生成 Hero Banner → 上傳 R2
│   │   ├── strategic_agent.py   # 每日策略決策（動態配額 + 自動觸發 Pipeline）
│   │   ├── refresh_agent.py     # 舊文更新 Pipeline（分析 + 改寫 + 重新發布）
│   │   ├── reflective_agent.py  # 文章完成後反思 → 更新知識庫 + 寫作規範
│   │   ├── learning_agent.py    # L1/L2 週期學習（模式統計 + ROI 分析）
│   │   ├── analytics_agent.py   # 排名歸因分析、關鍵字自蝕偵測、Refresh 觸發判斷
│   │   ├── cluster_agent.py     # Topic Cluster 建置、缺口偵測
│   │   └── planning_agent.py    # 基於數據的內容計畫推薦
│   │
│   ├── models/
│   │   ├── database.py          # SQLAlchemy ORM（25+ 張資料表）
│   │   └── schemas.py           # Pydantic Schema（Agent I/O 驗證）
│   │
│   ├── tools/
│   │   ├── serp.py              # Google SERP（SerpAPI / Serper.dev + Google Trends + DataForSEO）
│   │   ├── pubmed.py            # PubMed E-utilities 學術文獻查詢
│   │   ├── gsc.py               # Google Search Console Data API
│   │   ├── ga4.py               # Google Analytics 4 Data API
│   │   ├── tech_seo.py          # Core Web Vitals + robots/sitemap 檢查
│   │   ├── render_verify.py     # 前台 Render 驗證（检查實際渲染輸出）
│   │   ├── knowledge_base.py    # ChromaDB 向量知識庫（embedding 搜尋）
│   │   ├── keyword.py           # 關鍵字提取工具
│   │   └── excel_importer.py    # Excel → DB 批次匯入
│   │
│   ├── publishers/
│   │   ├── wordpress.py         # WordPress REST API 自動發布
│   │   └── forgebase.py         # ForgeBase API 自動發布
│   │
│   ├── admin/
│   │   └── app.py               # FastAPI Admin 後台（3100+ 行，含全部路由）
│   │
│   └── site/
│       └── app.py               # Public Reference Site（SEO 驗證前端）
│
├── migrations/                  # Alembic 資料庫遷移
├── scripts/
│   ├── run_article_pipeline.py  # 完整 Pipeline CLI 腳本
│   ├── migrate_add_projects.py  # 資料庫遷移腳本
│   ├── migrate_sqlite_to_pg.py  # SQLite → PostgreSQL 遷移
│   └── verify_db.py             # DB 健康檢查
│
└── tests/                       # pytest 測試套件（398 個測試）
```

---

## Agent Pipeline 說明

一篇文章從無到發布，經過以下步驟（由 LangGraph StateGraph 協調）：

```
用戶觸發 / Scheduler 自動觸發
       │
       ▼
 [Step 1] Research Agent
   ├── SERP API → 競品前 10 篇文章結構 + PAA + 相關搜尋
   ├── PubMed API → 學術文獻（健康/醫療類專案自動啟用）
   └── Gemini → 彙整 ResearchReport + 建議關鍵字
       │
       ▼
 [Step 2] Strategy Agent
   └── Gemini + 知識庫（ChromaDB）→ 搜尋意圖 / 讀者痛點 / 架構 / FAQ 建議
       │
       ▼
 [Step 3] Writing Agent
   └── Gemini（或 OpenAI / Anthropic fallback）→ 大綱 → 段落 → 完整 Markdown
       含：FAQ schema / HowTo schema / Article schema JSON-LD
       │
       ▼
 [Step 4] SEO Check + SEO QA（最多 3 次迴圈）
   ├── SEO Check（純規則引擎，零 LLM 成本）→ 評分 + 缺失清單
   └── SEO QA（LLM）→ 針對缺失微調 → 重新評分
       分數 ≥ 85 → PASS；< 85 + 重試 < 3 → RETRY；≥ 3 次 → FORCE_OUTPUT
       │
       ▼
 [Step 5] FactCheck Agent
   └── 禁用詞比對（product 模式嚴格；educational 模式降級處理）
       └── Gemini 對照 PubMed 摘要核實聲明
       │
       ▼
 [Step 6] Budget Guard
   └── 檢查 LLM 呼叫次數（≤15）+ 金額（≤$2.00）
       超限時標記 _budget_exceeded=True，但保留草稿不棄稿
       │
       ▼
 [Step 7] 最佳努力後處理（Pipeline 主流程完成後非同步執行）
   ├── Hero Image Agent → Gemini 生圖 → 上傳 Cloudflare R2
   ├── Image Agent → 各段落配圖 Prompt + Alt Text + WebP 檔名
   └── 站內連結建議（比對同站已發布文章）
       │
       ▼
 [Step 8] 反思學習（fire-and-forget，不阻塞主流程）
   └── Reflective Agent → 分析本次產出 → 更新知識庫 + 寫作規範
       │
       ▼
   存入 DB（draft_content + seo_score + factcheck_flags + schemas）
       │
       ▼
   ┌─ 自動發布（seo_score ≥ auto_publish_min_score）→ WordPress / ForgeBase
   │       └── Google Indexing API 主動送交收錄
   └─ 人工審閱（Admin 後台）→ 手動發布
```

### Scheduler 排程任務（共 21 個）

> Scheduler 以獨立 service 運行（`scheduler_runner.py`），不內嵌於 web workers。每分鐘 heartbeat 寫入 `scheduler_heartbeat.json`，`/health` 端點以 heartbeat 新鮮度驗證排程器真實活性，確保 job dispatch 持續正常運作。

| 任務 | 排程 | 說明 |
|------|------|------|
| `_scheduler_heartbeat_job` | 每分鐘 | 寫入 heartbeat 時間戳，供 `/health` 驗證排程器活性 |
| `sync_gsc_all_projects` | 每日 03:00 | 同步 Google Search Console 排名 |
| `sync_ga4_all_projects` | 每日 03:30 | 同步 GA4 頁面指標（含分頁，上限 500 筆）|
| `sync_keyword_trends` | 每月 1 號 03:45 | 更新關鍵字 Google Trends 熱度分數 |
| `sync_gbp_metrics` | 每日 03:50 | 同步 Google Business Profile 每日曝光 / 點擊指標 |
| `backfill_action_outcomes` | 每日 04:00 | 歸因分析：回填文章行動成效 |
| `check_scheduled_publishes` | 每日 04:05 | 定時發布排程文章；含近門檻文章自動補跑 SEO QA 補救路徑 |
| `check_published_noindex` | 每日 04:10 | 發布後驗證：確認文章 HTML 無 noindex、robots.txt 無誤封鎖 |
| `run_auto_pipeline` | 每日 08:00 | Strategic Agent → 每日自動 AI Pipeline |
| `run_render_verification` | 每日 10:00 | 驗證前台實際渲染輸出（schema/meta/cws） |
| `check_gsc_sitemap_health` | 每週一 04:45 | 稽核 GSC 已提交 Sitemap 狀態，偵測「無法擷取」並告警 |
| `run_competitor_serp_check` | 每週一 04:30 | 追蹤競品 SERP 排名 |
| `run_attribution_engine` | 每週一 05:00 | 計算文章 ROI + 推薦行動 |
| `check_refresh_triggers` | 每週二 04:00 | 偵測需更新的文章（排名下滑/陳舊/低 CTR）|
| `sync_backlink_metrics` | 每週二 05:30 | DataForSEO 反向連結摘要同步，大量失去時告警 |
| `check_ranking_drops` | 每週三 06:00 | 偵測7日內排名下滑 > 5 位的關鍵字，寫知識庫 |
| `run_index_coverage_check` | 每週五 05:00 | Index Coverage 掃描，偵測新失索頁面並寫入知識庫 |
| `run_weekly_reflection` | 每週日 08:00 | 週級反思：彙整學習成果，更新寫作規範 |
| `send_weekly_report` | 每週日 09:00 | 產出 Slack 週報摘要 |
| `run_l1_pattern_analysis` | 每月 1 號 06:00 | L1 學習：統計高分文章格式模式 |
| `run_l2_roi_analysis` | 每月 1 號 07:00 | L2 學習：ROI 分析，更新策略偏好 |

**專案上下文注入**：每個 Agent 均透過 `project_context.py` 載入品牌名稱、撰寫原則、法規詞庫、ChromaDB 知識庫，確保輸出符合品牌調性。

**LLM Provider Failover**：`llm_client.py` 實作三層 failover — Gemini（主，`gemini-3-flash-preview`）→ OpenAI（備）→ Anthropic（備），任一 Provider rate limit 後自動 60 秒 cooldown 並切換。圖片生成使用 `gemini-3.1-flash-image-preview`。

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

- 正式部署使用 **PostgreSQL 16**（Docker Compose 內建服務），`DATABASE_URL` 設定為 `postgresql+psycopg2://`
- 所有資料表均有 `project_id` 欄位，支援多個品牌/客戶共用同一資料庫
- **Schema migrations** 由 Alembic 管理（`migrations/` 目錄）
- 本地開發可使用 SQLite：`sqlite+aiosqlite:///data/contentflow.db`

### 主要資料表（共 25+ 張）

| 資料表 | 說明 |
|--------|------|
| `projects` | 多租戶根節點，品牌資訊、寫作原則、自動發布規則 |
| `articles` | 文章主表，含完整生命週期（planned → draft → published）、seo_score、slug |
| `keywords` | 關鍵字庫（搜尋量、CPC、SEO 難度、Trends 熱度、cluster 分組） |
| `content_calendar` | 月/週度內容排程 |
| `writing_rules` | AI 學習更新的品牌撰寫規範 |
| `legal_terms` | 食品廣告法規用詞（禁用詞 / 替換建議） |
| `competitors` | 競品研究資料 |
| `competitor_snapshots` | 競品 SERP 排名快照（每週追蹤） |
| `products` | 產品系列資料（成分、功效、禁忌） |
| `seo_rankings` | GSC 關鍵字排名歷史（每日同步） |
| `ga_page_metrics` | GA4 頁面指標（點擊率、工作階段、跳出率） |
| `pipeline_runs` | Pipeline 執行紀錄（per-article，含 token 用量與費用） |
| `agent_decision_logs` | 每個 Agent 節點的決策過程日誌（AgentDecisionLog ORM） |
| `knowledge_entries` | ChromaDB 向量知識庫的結構化版本 |
| `knowledge_audit_logs` | 知識庫新增/修改稽核記錄 |
| `reflection_logs` | 週級 / post-pipeline 反思學習日誌 |
| `strategic_plans` | Strategic Agent 每日計畫決策（quota、行動清單） |
| `action_outcomes` | ROI 分析：行動 → 成效歸因 |
| `scheduler_logs` | 排程任務執行記錄（成功/失敗/耗時） |
| `topic_clusters` | Topic Cluster 主題叢集（pillar + cluster） |
| `cluster_members` | 叢集成員（article ↔ cluster 關係） |
| `authors` | 作者 E-E-A-T 資訊（用於 JSON-LD） |
| `category_seos` | 分類頁 SEO 設定（title / description / schema） |
| `changelogs` | 系統重要事件日誌 |

---

## 已知架構技術債

> 以下為系統目前存在的架構層級技術債項目。這些並非 bug，現有功能運作正常，但在擴展規模或正式部署前需要刻意決策與處理。新接手的工程師應在動手修改前完整理解這些脈絡。

---

### ✅ TD-01：LangGraph StateGraph 已實作（已解決）

**解決時間：** 本 session

**現況：** `orchestrator.py` 已完整使用 `StateGraph`，Pipeline 共 7 個節點（research → strategy → write → seo_check → seo_qa → factcheck → budget_guard），SEO QA 條件邊實作 ≤3 次重試邏輯，Budget Guard 在費用超限時保護系統但不棄稿。完整支援條件分支、回退重試與狀態共享。

**此項技術債已解決，無需進一步行動。**

---

### ✅ TD-02：舊 Streamlit 後台已退役（已解決）

**解決時間：** 本 session

**現況：** 舊的 `app/` Streamlit 後台與 `docker-compose.yml` 的 `ui` service 已移除，專案只保留 FastAPI site + admin + scheduler 路徑。`db.py` 仍使用同步 SQLAlchemy Session 與 `psycopg2`，但已無第二套 Web UI 直接連 DB 的結構性分叉。

**影響評估：** 中低。啟動與部署路徑已收斂，後續只需針對 FastAPI 管理介面持續演進。

---

### ✅ TD-03：WordPress 自動發布已實作（已解決）

**解決時間：** 本 session

**現況：** `publishers/wordpress.py` 已完整實作 WordPress REST API 發布（`POST /wp/v2/posts`），含 Retry、Auth Header 設定、slug/categories 支援，並接入 Google Indexing API 主動送交收錄。`orchestrator.py` 在 Pipeline 完成且 `seo_score ≥ auto_publish_min_score` 時自動觸發。

**尚未實作：** Google Sheets 整合（Google Sheets 作為資料來源的需求已於 content_calendar DB 表取代，此需求已降低優先度）。

**此項技術債（WordPress 部分）已解決。Google Sheets 整合已降低優先度，可視情況移除此 TD。**

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

### ✅ TD-05：PostgreSQL 正式部署已完成（已解決）

**解決時間：** 本 session

**現況：** 正式部署已使用 PostgreSQL 16（Docker Compose 內建服務），`DATABASE_URL` 使用 `postgresql+psycopg2://`。Alembic 管理 schema migrations（`migrations/` 目錄）。SQLite 的 `_ensure_sqlite_columns()` 補丁仍保留，以兼容本地舊資料庫。

**此項技術債已解決，無需進一步行動。**

---

### ✅ TD-06：Image Agent 已遷移至 Gemini 圖片生成（已解決）

**解決時間：** 本 session

**現況：** `image_agent.py` 已移除 DALL-E，改用 `gemini-3.1-flash-image-preview`（`response_modalities=["IMAGE"]`，輸出 WebP）。圖片生成使用與其他 Agent 相同的 `GEMINI_API_KEY`，無需額外 OpenAI 費用。

**此項技術債已解決，無需進一步行動。**

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

**Q: 如何啟動服務？**

```bash
cp .env.example .env  # 填入金鑰
docker-compose up -d
```

Admin 後台：`http://localhost:8000/admin`，Password = `API_SECRET_KEY` 環境變數。

---

**Q: `pytest` 顯示 `ModuleNotFoundError`？**

確認安裝方式使用 `pip install -e ".[dev]"` 而非僅 `pip install -r requirements.txt`（本專案無 `requirements.txt`，依賴宣告在 `pyproject.toml`）。

---

**Q: 如何新增一個品牌/客戶（Project）？**

在 Admin 後台 `/admin/settings` 新增專案，填入品牌名稱、產業、寫作原則。所有後續資料（關鍵字、文章、規範）自動綁定該專案。多個專案共用同一 PostgreSQL 資料庫（透過 `project_id` 隔離）。

---

**Q: 自動發布如何設定？**

在 Admin → 設定 → 自動發布規則，設定 `auto_publish_min_score`（建議 85+）與目標 Publisher（WordPress / ForgeBase）。Pipeline 完成且 SEO 分數達標後自動發布並呼叫 Google Indexing API。

---

**Q: Scheduler 排程如何開啟？**

`.env` 設定 `SCHEDULER_ENABLED=true`（Docker Compose 預設已開啟）。Scheduler 以獨立 service 運行，Admin → 排程管理頁可查看所有 21 個任務的執行狀態與 heartbeat 健康，並可手動觸發個別任務。`/health` 端點的 `scheduler_heartbeat_age_seconds` 欄位可確認排程器真實活性。

---

**Q: Pipeline 費用大概多少？**

以 `gemini-3-flash-preview` 為主力，一篇約 1,500 字的文章（含研究、策略、SEO QA）約 **$0.01–0.03 USD**。圖片生成使用 `gemini-3.1-flash-image-preview`，每張約 **$0.001 USD**。Budget Guard 設定上限為每次 Pipeline 15 次 LLM 呼叫 / $2.00，超限時保留草稿不強制棄稿。

---

**Q: 如何查看 AI 的學習成果？**

Admin → 知識庫（`/admin/knowledge`）可查看 Reflective Agent 自動整理的寫作洞見、失敗原因分析、最佳實踐。知識庫同時以 ChromaDB 向量形式儲存，供 Strategy Agent 在規劃時自動引用。

---

*詳細技術架構請參閱 [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md)。*
*產品獨立性評估請參閱 [PRODUCT_INDEPENDENCE_ASSESSMENT_2026-05-11.md](PRODUCT_INDEPENDENCE_ASSESSMENT_2026-05-11.md)。*
