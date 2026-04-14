# ContentFlow × AgentOps 整合評估報告

> 建立日期：2026-04-14  
> 最後更新：2026-04-14（外部資訊驗證後修正）  
> 目的：全面比較 ContentFlow 自建 Agent 可觀測系統與 AgentOps SDK，評估整合可行性與價值

---

## 一、ContentFlow 現有 Agent 可觀測系統

### 1.1 Agent 架構總覽

ContentFlow 採用 **LangGraph StateGraph** 驅動，共有 **18 個 Agent**，分為 4 層：

| 層級 | Agent | 職責 |
|------|-------|------|
| **執行層** | Research Agent | SERP + PubMed 研究 |
| | Strategy Agent | 根據 SERP 決定文章格式、字數、結構 |
| | Writing Agent | 三階段撰文（大綱 → 初稿 → 優化） |
| | SEO Check Agent | 規則檢查：關鍵字密度、標題、H2、FAQ |
| | SEO QA Agent | LLM 修正 SEO 檢查失敗項（最多 3 輪） |
| | FactCheck Agent | PubMed 文獻事實查核 |
| **守衛層** | Budget Guard | LLM 呼叫 ≤ 15、成本 ≤ $2.00/篇 |
| **決策層** | Strategic Agent | 日/週決策：產哪些新文、Refresh 哪些舊文 |
| | Planning Agent | 內容規劃 |
| | Refresh Agent | 舊文更新執行 |
| **學習層** | Reflective Agent | Pipeline 反思 → 更新知識庫 + 撰寫規則 |
| | Learning Agent | L1 成功模式分析、L2 ROI 優化 |
| **輔助層** | Cluster Agent | Topic Cluster 主題叢集 |
| | Analytics Agent | 文章表現歸因、cannibalization 偵測 |
| | Image Agent | 文章配圖生成 |

### 1.2 Pipeline 流程

```
research → strategy → write → seo_check
                                    ↓ seo_gate
                    "pass"(≥85) → factcheck
                    "retry"(<85,<3次) → seo_qa → seo_check
                    "force_output"(≥3次) → force_output_marker → factcheck
                                    ↓
                              factcheck → budget_guard → END
```

### 1.3 資料庫觀測模型

#### AgentDecisionLog（Agent 決策日誌）
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| project_id | FK → projects | 所屬專案 |
| article_id | FK → articles | 所屬文章 |
| run_id | String (UUID) | 執行唯一識別碼 |
| step | String | research / strategy / writing / seo_check / ... |
| decision | Text | 決策描述（例：「SEO 評分 87/100」） |
| reason | Text | 推理過程 |
| confidence | String | data / heuristic / rule / verified |
| metadata_json | Text | 額外結構化數據 |
| created_at | DateTime UTC | 記錄時間戳 |

#### PipelineRun（Pipeline 執行記錄）
| 欄位 | 類型 | 說明 |
|------|------|------|
| id | Integer PK | |
| run_id | String (UUID) | 唯一識別碼 |
| project_id | FK → projects | 所屬專案 |
| article_id | FK → articles | 所屬文章 |
| calendar_id | FK → content_calendar | 來源 |
| trigger | String | manual / scheduler / strategic_agent |
| current_step | String | pending → research → ... → completed / failed |
| status | String | running / completed / failed |
| state_json | Text | Checkpoint 可序列化狀態 |
| error_message | Text | 失敗錯誤訊息 |
| total_llm_calls | Integer | 累計 LLM 呼叫次數 |
| total_cost | Float | 累計成本（USD） |
| seo_score | Integer | 最終 SEO 分數 |
| started_at / finished_at | DateTime | 起止時間 |

#### ReflectionLog（反思記錄）
| 欄位 | 類型 | 說明 |
|------|------|------|
| run_id | String | 對應 PipelineRun |
| reflection_type | String | post_pipeline / weekly_review / human_edit |
| insights_json | Text | LLM 萃取的洞察 |
| knowledge_updates | Integer | 本次更新 KnowledgeEntry 數 |
| writing_rule_updates | Integer | 本次更新 WritingRule 數 |
| session_summary | Text | 壓縮摘要 |

#### KnowledgeEntry（知識庫條目）
| 欄位 | 類型 | 說明 |
|------|------|------|
| category | String | format_pattern / seo_score_impact / keyword_roi / ... |
| pattern | Text | 學到的模式描述 |
| evidence_count | Integer | 支持數據筆數 |
| confidence_level | String | unverified → verified (≥5) → universal (≥10+跨專案) |
| is_active | Boolean | 可人工停用 |

#### SchedulerLog（排程日誌）
- job_id / job_name / status / retry_count / error_message / duration_seconds

### 1.4 成本追蹤機制

```python
# 固定估算值
_LLM_CALL_COST_EST = 0.08  # 每次 LLM 呼叫 $0.08（gpt-4o-mini）

# 各節點累積
research_node:   +1 call = +$0.08
strategy_node:   +1 call = +$0.08
writing_node:    +3 calls = +$0.24（三階段）
seo_qa_node:     +1 call = +$0.08
factcheck_node:  +1 call = +$0.08

# 每篇文章上限
max_llm_calls_per_article = 15
max_cost_per_article = $2.00
```

**限制**：成本是估算值（$0.08/call），不是從 API response 讀取的實際 token 費用。

### 1.5 Admin Dashboard 觀測頁面（共 20 頁）

| 頁面 | 觀測內容 |
|------|---------|
| **儀表板 `/`** | 文章 KPI、最近 8 次 pipeline run、排程監控、累計 AI 成本 |
| **Agent 執行中心 `/agents`** | 決策時間軸瀑布圖、步驟頻率、成功率、預算超限、成本指標 |
| **反思日誌 `/reflections`** | Post-pipeline / 週報 / 人工編輯反思、知識庫更新追蹤 |
| **知識庫 `/knowledge`** | L1 學習模式、信心等級、人工審核軌跡 |
| **Pipeline Runs `/pipeline-runs`** | 歷史執行、狀態篩選、SEO 分數、成本匯總 |
| **Health `/health`** | 服務狀態（OpenAI/Google/Serper）、月成本、每篇平均成本 |
| **SEO `/seo`** | GSC 趨勢、排名分級、cannibalization 警報 |
| **排程 `/scheduler`** | Job 狀態、7 日成功/失敗長條圖 |

### 1.6 現有視覺化

- **垂直時間軸瀑布圖**：決策步驟 + 信心等級色點（agents.html）
- **圓餅圖**：文章狀態分布
- **折線圖**：GSC 30 日趨勢
- **長條圖**：排名分級、步驟頻率、關鍵字量分布
- **表格**：決策序列、Top 20 關鍵字、Pipeline Run 列表

---

## 二、AgentOps SDK 完整介紹

### 2.1 基本資訊

| 項目 | 說明 |
|------|------|
| GitHub | [AgentOps-AI/agentops](https://github.com/AgentOps-AI/agentops) |
| License | **SDK**：MIT開源；**app 平台（Dashboard + API）**：Elastic License 2.0（自用可以，不可作為第三方託管服務） |
| Stars | ~5,462 |
| 最新版本 | v0.4.21 |
| 定價 | Free: 5,000 events/月 · Pro: $40/月起 · Enterprise: 自訂 |
| SOC-2/HIPAA | 僅 Enterprise 方案提供（Free/Pro 未明確提及） |
| SDK 安裝 | `pip install agentops` |
| Dashboard | `https://app.agentops.ai` |
| LangGraph 整合 | README 宣稱支援，但專屬文件頁返回 404（實際整合深度待驗證） |
| 隱私政策 | 未找到公開 DPA 或資料使用政策文件 |

### 2.2 核心概念

#### Session（會話）
一次 pipeline 執行 = 一個 Session。Session 擁有：
- ID / Project ID（由 API Key 決定）/ 起止時間 / 結束狀態（Success / Failure / Indeterminate）
- 可選：Tags、Host Environment、End State Reason

#### Span（追蹤單元）
v0.4 後統一用「Span」取代舊版 Event：

| Span 類型 | 說明 | 自動記錄 |
|-----------|------|---------|
| **Session Span** | 根節點，包裹整個 workflow | 起止時間 |
| **Agent Span** | 追蹤某個 Agent 的所有操作 | Agent name, ID |
| **Operation/Task Span** | 追蹤具體函式 | 輸入參數、返回值、例外 |
| **Workflow Span** | 含多個 Operation 的流程 | 起止時間 |
| **LLM Span** | 自動攔截 LLM 呼叫 | model, prompt, completion, tokens, cost |

每個 Span 的共通屬性：
- `span_id` / `trace_id` / `parent_id`（支援巢狀）
- `name` / `kind` / `start_time` / `end_time`
- `attributes`（自訂屬性）
- 自動捕捉：輸入參數 → 返回值 → 例外

#### LLM Span 特殊屬性
- **Model**：使用的模型
- **Prompt Messages**：完整 prompt
- **Completion Messages**：完整回應
- **Prompt Tokens / Completion Tokens**：精確 token 數
- **Cost**：精確費用（支援 400+ LLM 模型定價）
- **Thread ID**：執行緒追蹤

### 2.3 Decorator 系統

```python
from agentops.sdk.decorators import session, agent, operation, workflow

@session(name="article-pipeline")   # 根節點
def my_pipeline():
    ...

@agent(name="research-agent")       # Agent 層
class MyAgent:
    @operation                       # 操作層
    def perform_task(self, data):
        return result

@workflow                            # 工作流層
def multi_step_process(data):
    ...
```

**階層關係**：Session → Agent → Operation/Task → Nested Operations

**支援函式類型**：同步、async/await、Generator、Async Generator

### 2.4 Auto-Instrumentation（自動偵測）

```python
import agentops
agentops.init("API_KEY")
# 之後所有 openai / anthropic / cohere 呼叫自動被追蹤
# 不需要修改任何 LLM 呼叫程式碼
```

呼叫 `agentops.init()` 後，SDK 自動偵測已安裝的 LLM Provider 並攔截呼叫。

### 2.5 Concurrent Traces（並發追蹤）

```python
agentops.init(auto_start_session=False)
trace_1 = agentops.start_trace("user_query_1")
trace_2 = agentops.start_trace("user_query_2")
# 各自獨立追蹤
agentops.end_trace(trace_1, "Success")
agentops.end_trace(trace_2, "Success")
```

### 2.6 Data Export API

```python
# 取得 Session 統計
GET /v2/sessions/<session_id>/stats
# → event counts, duration, costs, token usage

# 匯出完整 Session 資料
GET /v2/sessions/<session_id>/export
# → metadata + statistics + all events (LLM calls, tool usage, errors)
```

### 2.7 LangChain/LangGraph 整合方式

```python
from agentops.integration.callbacks.langchain import LangchainCallbackHandler

handler = LangchainCallbackHandler(
    api_key="AGENTOPS_API_KEY", 
    tags=["ContentFlow", "article-pipeline"]
)

llm = ChatOpenAI(
    callbacks=[handler],
    model="gpt-4o-mini"
)
```

不需要 `agentops.init()`，CallbackHandler 會自動初始化 AgentOps Client。

### 2.8 Dashboard 功能

| 功能 | 說明 |
|------|------|
| **Session Waterfall** | 時間軸瀑布圖：每個 Agent / LLM Call / Tool Call 的開始、結束、耗時 |
| **Session Replay** | 完整重播一次 pipeline 的所有步驟 |
| **Cost Tracking** | 精確到每個 LLM 呼叫的 token 費用，支援 400+ 模型 |
| **Error Tracking** | Stack trace + 錯誤前後的 Span 上下文 |
| **Trend Analytics** | 跨 Session 的延遲、成本、成功率趨勢 |
| **Time Travel Debugging** | 回溯任意時間點的 Agent 狀態 |

---

## 三、功能對照比較

### 3.1 可觀測能力矩陣

| 能力 | ContentFlow 自建 | AgentOps | 差距 |
|------|-----------------|----------|------|
| **Pipeline 執行記錄** | ✅ PipelineRun 表 | ✅ Session | 同等 |
| **步驟決策記錄** | ✅ AgentDecisionLog | ✅ Span + Agent | ContentFlow 記錄 decision/reason；AgentOps 記錄 input/output |
| **決策信心等級** | ✅ data/heuristic/rule/verified | ❌ | ContentFlow 獨有 |
| **LLM 完整 Prompt** | ❌ 不記錄 | ✅ 自動攔截完整 prompt + completion | **AgentOps 大幅領先** |
| **精確 Token 計數** | ❌ 只有呼叫次數 | ✅ prompt_tokens + completion_tokens | **AgentOps 大幅領先** |
| **精確費用** | ❌ 固定估算 $0.08/call | ✅ 400+ 模型定價自動計算 | **AgentOps 大幅領先** |
| **步驟延遲** | ❌ 只有 Pipeline 總時間 | ✅ 每個 Span 有 start/end time | **AgentOps 大幅領先** |
| **時間軸瀑布圖** | ✅ 自建（信心色點） | ✅ 更精細（含 LLM Call） | AgentOps 較佳 |
| **錯誤追蹤** | ⚠️ 只有 error_message 文字 | ✅ Stack trace + Span 上下文 | AgentOps 較佳 |
| **跨 Session 趨勢** | ⚠️ 需自己組 SQL | ✅ Dashboard 自動生成 | AgentOps 較佳 |
| **即時執行狀態** | ⚠️ In-memory（重啟消失） | ✅ 即時串流 | AgentOps 較佳 |
| **反思學習迴圈** | ✅ ReflectionLog + KnowledgeEntry | ❌ | **ContentFlow 獨有** |
| **知識庫演化** | ✅ 自動信心升級 | ❌ | **ContentFlow 獨有** |
| **撰寫規則學習** | ✅ WritingRule 自動更新 | ❌ | **ContentFlow 獨有** |
| **預算守衛** | ✅ Budget Guard Node | ❌ | **ContentFlow 獨有** |
| **SEO 品質閘門** | ✅ SEO Gate (≥85 pass) | ❌ | **ContentFlow 獨有** |
| **GSC/GA4 整合** | ✅ 排名追蹤、點擊、曝光 | ❌ | **ContentFlow 獨有** |
| **事實查核** | ✅ PubMed 文獻比對 | ❌ | **ContentFlow 獨有** |
| **Prompt Injection 偵測** | ❌ | ✅ PromptArmor 整合 | AgentOps 獨有 |
| **Session 錄影** | ❌ | ✅ 可選 | AgentOps 獨有 |

### 3.2 綜合評估

**ContentFlow 的優勢（AgentOps 無法替代）：**
- 領域特化的 SEO 品質閘門 + 預算守衛
- 自動學習迴圈（Reflective Agent → Knowledge Entry → Writing Rule）
- 完整的 GSC/GA4 數據整合
- 決策信心等級分類（data/heuristic/rule/verified）

**AgentOps 的優勢（ContentFlow 自建困難）：**
- LLM 完整 prompt/completion 記錄（自建需大量改動每個 agent）
- 精確 token 計數與費用（自建需解析每個 API response）
- 每步驟延遲追蹤（自建需在每個 node 加計時器）
- Stack trace 級別的錯誤追蹤
- 跨 Session 趨勢自動視覺化

---

## 四、整合方案

### 4.1 建議策略：互補式整合

**不是取代，是補充。** ContentFlow 自建系統保留（領域邏輯無可替代），AgentOps 補足 LLM 觀測盲區。

### 4.2 實作方式

#### 方案 A：最小整合（2 行改動）

```python
# src/contentflow/agents/orchestrator.py 頂部加入
import agentops
import os
if os.getenv("AGENTOPS_API_KEY"):
    agentops.init(os.getenv("AGENTOPS_API_KEY"))
```

**效果**：自動攔截所有 OpenAI 呼叫，記錄 prompt/completion/token/cost。Dashboard 可查看。

**不需要改動**：任何 agent 程式碼。AgentOps auto-instrumenting 自動偵測 `openai` SDK。

> ⚠️ **LangGraph 扁平化問題**：Auto-instrumentation 只攔截 OpenAI SDK 層，不感知 LangGraph 的 node routing。Session Waterfall 會呈現為 8-12 個無命名的 LLM call 平鋪排列，**缺少 Agent 階層結構**——無法分辨哪個 call 屬於 Research Agent、哪個屬於 Writing Agent。方案 A 的可視化效果可能不如預期，主要價值在於取得精確 token/cost 數據，而非瀑布圖。要獲得有意義的 Agent 歸屬，需升級至方案 B。

#### 方案 B：深度整合（約 30 行改動）

```python
# orchestrator.py
import agentops
import os

if os.getenv("AGENTOPS_API_KEY"):
    agentops.init(
        os.getenv("AGENTOPS_API_KEY"),
        auto_start_session=False,  # 手動控制 session 生命週期
    )

# run_article_pipeline() 內
async def run_article_pipeline(task, ...):
    trace = agentops.start_trace(
        name=f"article:{task.title}",
        tags=["contentflow", f"project:{project_id}"]
    )
    try:
        result = await _get_agent().ainvoke(initial_state)
        agentops.end_trace(trace, "Success")
    except Exception as e:
        agentops.end_trace(trace, "Failure", end_state_reason=str(e))
        raise
```

**增強**：每個 agent 加 `@agentops.agent` 裝飾器

```python
# research_agent.py
from agentops.sdk.decorators import agent, operation

@agent(name="research-agent")
class ResearchAgentWrapper:
    @operation
    async def run(self, title, keywords, ...):
        return await run_research_agent(title, keywords, ...)
```

#### 方案 C：LangChain Callback 整合

```python
from agentops.integration.callbacks.langchain import LangchainCallbackHandler

handler = LangchainCallbackHandler(
    api_key=os.getenv("AGENTOPS_API_KEY"),
    tags=["contentflow"]
)
# 注入到所有 ChatOpenAI 實例的 callbacks
```

### 4.3 環境設定

```bash
# .env.prod
AGENTOPS_API_KEY=<從 https://app.agentops.ai/settings/projects 取得>
```

```dockerfile
# Dockerfile
pip install agentops
```

### 4.4 方案選擇建議

| 方案 | 改動量 | 獲得能力 | 限制 | 建議 |
|------|--------|---------|------|------|
| A 最小 | 2 行 | LLM prompt/token/cost 自動追蹤 | Waterfall 是扁平 LLM call，無 Agent 歸屬 | **先用這個取得精確費用數據** |
| B 深度 | ~30 行 | + 每篇文章獨立 Session + Agent 標記 | 需包裝每個 agent | 方案 A 驗證有效後升級 |
| C Callback | ~10 行 | + LangChain 原生整合 | 不適用於 LangGraph | 暫不考慮 |

---

## 五、成本影響分析

### 5.1 AgentOps 費用

| 方案 | 免費額度 | ContentFlow 預估用量 |
|------|---------|-------------------|
| Free | 5,000 events/月 | 每篇 ~8-12 events → 可支撐 ~400-600 篇/月 |
| Pro ($40/mo) | 無上限 | 無限制 |

目前 ContentFlow 月產量遠低於 400 篇，**免費方案完全足夠**。

### 5.2 LLM 費用可視性提升

導入前：每篇估算 $0.48-$1.20（固定 $0.08 × 6-15 calls）
導入後：精確知道每篇實際花費（取決於使用的模型，見下方定價）

> ⚠️ **模型定價變動說明**：OpenAI 已於 2026 年更新產品線，原 gpt-4o-mini 已下架。當前可用替代方案：
> | 模型 | Input | Output | 備註 |
> |------|-------|--------|------|
> | GPT-5.4 nano | $0.20/1M tokens | $1.25/1M tokens | 最便宜，適合簡單任務 |
> | GPT-5.4 mini | $0.75/1M tokens | $4.50/1M tokens | 適合 ContentFlow 的主要工作 |
> | GPT-5.4 | $2.50/1M tokens | $15.00/1M tokens | 旗艦模型 |

---

## 六、風險評估

| 風險 | 等級 | 緩解 |
|------|------|------|
| **資料外洩（prompt 送到外部）** | **高** | 見下方詳細分析 |
| AgentOps SaaS 停機 | 低 | SDK 設計為 non-blocking，失敗不影響 pipeline |
| SDK 版本不相容 | 低 | 鎖定版本 `agentops==0.4.21` |
| 免費額度用完 | 低 | 停止傳送不影響業務；或升級 Pro |
| 方案 A 可視化不如預期 | 中 | 接受扁平 LLM call 或直接用方案 B |

### 6.1 資料隱私風險深度分析（高風險）

ContentFlow 的 prompt 包含以下敏感資訊，一旦送至 AgentOps SaaS 即脫離控制：

| 敏感資料類型 | 包含位置 | 洩漏影響 |
|-------------|---------|----------|
| PubMed 文獻摘要 | Research Agent prompt | 低（公開資料） |
| 客戶關鍵字策略 | Strategy Agent prompt | **高**（競爭優勢） |
| 撰寫規則與格式模式 | Writing Agent system prompt | **高**（核心 know-how） |
| KnowledgeEntry 學習成果 | Writing Agent context | **高**（累積智慧資產） |
| 客戶品牌名稱 / 網址 | 所有 prompt | 中（可被關聯） |

**SOC2 合規 ≠ 資料安全**。SOC2 只代表他們有安全流程，不代表：
- prompt 內容不會用於模型訓練
- 內部員工無法存取你的 session 資料
- 公司被收購後資料政策不會改變

**整合前必須完成的前置作業**：
1. 確認 AgentOps 的 **Data Processing Agreement (DPA)** 和 opt-out 政策
2. 確認 prompt 資料是否可被用於模型訓練或內部分析
3. 評估 **Self-Hosting 版本**（Enterprise 方案）的可行性與成本
4. 若無法取得滿意的隱私保證，改為自建精確計費（見第八章替代方案）

---

## 七、結論與建議

### 現狀評價
ContentFlow 自建的 Agent 可觀測系統**在領域層面是完整的**：決策日誌、品質閘門、預算守衛、反思學習迴圈——這些是 AgentOps 不提供的。

### AgentOps 的價值
補足**基礎設施層**的盲區：LLM prompt 記錄、精確 token/cost、步驟延遲、錯誤 stack trace。

### 修正後建議行動

1. **前置（必做）**：確認 AgentOps 資料隱私政策，取得 DPA 或評估 Self-Hosting
2. **短期**：用方案 A 導入，主要目的是**取得精確 token/cost 基準數據**（不要期待漂亮的瀑布圖）
3. **短期同步**：用取得的精確成本數據**重新校準 Budget Guard 閾值**（見第八章）
4. **中期**：確認方案 A 有用後升級至方案 B，獲得 Agent 歸屬瀑布圖
5. **長期**：在每個 agent node 自建 OpenAI `usage` 解析，實現不依賴第三方的精確計費。AgentOps 降級為**驗證工具**而非唯一來源
6. **不做**：不需要拆除 ContentFlow 自建系統——兩者互補，不衝突

### 一句話總結
> **ContentFlow 自建系統管「業務可觀測」（SEO 品質、決策推理、知識演化），AgentOps 管「基礎設施可觀測」（LLM 延遲、token 費用、prompt 除錯）。兩者互補，不是替代關係。但資料隱私和 Budget Guard 校準是導入前必須解決的前置議題。**

---

## 八、審閱回饋與修正紀錄

> 本章記錄報告初版經審閱後的重要修正，確保評估的嚴謹性。

### 8.1 資料外洩風險重新評級（中 → 高）

**原始評估**：風險「中」，緩解措施為「確認 SOC2 合規」。

**修正後**：風險「高」。ContentFlow 的 prompt 包含客戶關鍵字策略、撰寫規則、知識庫學習成果——這些是核心商業邏輯，不是一般性文本。完整 prompt 送至第三方 SaaS 後完全脫離控制。SOC2 合規只代表有安全流程，不保證資料不被二次利用。

**行動項**：整合前必須取得 DPA、確認 opt-out 政策，或評估 Self-Hosting。

### 8.2 Budget Guard 閾值校準問題

**報告遺漏的重大隱患**：

現行 Budget Guard 基於 `_LLM_CALL_COST_EST = $0.08/call` 估算成本，上限 $2.00/篇。但實際 LLM 成本取決於模型和 token 數，可能與估算值有顯著差異（需實測確認）。

**這代表**：
- Budget Guard 的成本閘門（$2.00）實際對應的真實上限可能是 $0.08-$0.40
- 成本閘門從上線至今**可能從未被觸發過**
- 真正發揮作用的只有「LLM 呼叫次數 ≤ 15」這條規則

**修正方案**：
```python
# 現行（估算）
_LLM_CALL_COST_EST = 0.08  # 不準確
max_cost_per_article = 2.0  # 形同虛設

# 應該改為：從 OpenAI response.usage 讀取精確值
def _extract_real_cost(response) -> float:
    usage = response.usage
    prompt_cost = usage.prompt_tokens * MODEL_PRICING[model]["input"]
    completion_cost = usage.completion_tokens * MODEL_PRICING[model]["output"]
    return prompt_cost + completion_cost

# 然後用真實數據重新設定合理閾值
max_cost_per_article = 0.50  # 基於實測校準
```

用 AgentOps 取得精確成本後的第一件事，不是「記錄更準」，而是**重新校準 Budget Guard 的閾值**。

### 8.3 方案 A 的 LangGraph 扁平化問題

**原始評估**：「2 行改動即可獲得 Session Waterfall」。

**修正後**：Auto-instrumentation 只攔截 OpenAI SDK 層，不感知 LangGraph 的 StateGraph node routing。方案 A 產生的 Waterfall 是 8-12 個扁平排列的無名 LLM call——無法分辨 Research Agent vs Writing Agent。

**結論**：方案 A 的真正價值是「取得精確 token/cost」，不是「漂亮的瀑布圖」。瀑布圖要有意義，必須用方案 B 加 `@agent` 裝飾器。

### 8.4 長期策略方向修正

**原始建議**：「長期將 AgentOps 精確 cost 回寫到 PipelineRun.total_cost」。

**修正後**：方向應該反過來——在 ContentFlow 的每個 agent node 直接解析 OpenAI API response 的 `usage` 欄位，自建精確計費。理由：

1. **不依賴第三方服務**：AgentOps 停機/收費不影響計費功能
2. **無額外 API 呼叫**：`usage` 已在 response 中，零成本取得
3. **無隱私風險**：資料留在本地
4. **LLM 定價有公開文件**（但模型更新快，需定期校對）

**AgentOps 的正確定位**：作為驗證工具，確認自建計費沒有偏差——而非唯一來源。

```python
# 自建精確計費範例（基於 2026-04 OpenAI 定價）
MODEL_PRICING = {
    "gpt-5.4-nano":  {"input": 0.20 / 1_000_000, "output": 1.25 / 1_000_000},
    "gpt-5.4-mini":  {"input": 0.75 / 1_000_000, "output": 4.50 / 1_000_000},
    "gpt-5.4":       {"input": 2.50 / 1_000_000, "output": 15.0 / 1_000_000},
    # 舊模型（若仍在使用）
    "gpt-4o-mini":   {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gpt-4o":        {"input": 2.50 / 1_000_000, "output": 10.0 / 1_000_000},
}

def calculate_real_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["gpt-5.4-nano"])
    return prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]
```

---

## 附錄：外部資訊驗證紀錄

> 驗證日期：2026-04-14。以下為報告中引用的外部資訊之查證結果。

| 宣稱 | 來源 | 查證結果 | 狀態 |
|------|------|---------|------|
| AgentOps Free: 5,000 events/月 | agentops.ai 官網 Pricing 區 | 確認：`Free up to 5,000 events` | ✅ |
| AgentOps Pro: $40/月 | agentops.ai 官網 Pricing 區 | 確認：`starts at $40 per month` | ✅ |
| AgentOps Enterprise 含 Self-Hosting | agentops.ai 官網 + GitHub `app/` 目錄 | 確認：官網列出 `Self-hosting (AWS, GCP, Azure)`；GitHub 有完整 Docker Compose 架設文件 | ✅ |
| AgentOps SDK License: MIT | GitHub README badges | 確認：SDK 部分為 MIT | ✅ |
| AgentOps app 平台 License: MIT | GitHub `app/LICENSE` | **錯誤**：app 目錄使用 **Elastic License 2.0**（不可作為第三方託管服務） | ❌ 已修正 |
| AgentOps SOC-2 合規 | agentops.ai 官網 | **部分正確**：SOC-2, HIPAA, NIST AI RMF 僅列於 Enterprise 方案；Free/Pro 未明確提及 | ⚠️ 已修正 |
| AgentOps Stars 5,500+ | GitHub repo 頁面 | 實際為 ~5,462 | ⚠️ 已修正 |
| AgentOps LangGraph 原生支援 | GitHub README、docs | README 列出整合；但 `docs.agentops.ai/v1/integrations/langgraph` 返回 404 | ⚠️ 已標註 |
| AgentOps 隱私政策 / DPA | docs.agentops.ai | `docs.agentops.ai/v1/concepts/privacy` 返回 404；**未找到公開 DPA 或資料使用政策** | ❌ 已標註 |
| gpt-4o-mini 定價 $0.15/$0.60 | openai.com/api/pricing | **過時**：OpenAI 定價頁已無 gpt-4o-mini。當前最低為 GPT-5.4 nano（$0.20/$1.25）；GPT-5.4 mini（$0.75/$4.50） | ❌ 已修正 |
| ContentFlow 使用 gpt-4o-mini | orchestrator.py 註解 | 程式碼註解仍寫 `gpt-4o-mini`，需確認實際部署使用的模型版本 | ⚠️ 待確認 |

**最關鍵的發現**：
1. **AgentOps 沒有公開隱私政策**——這讓§6.1 的資料外洩風險進一步升高，因為連評估的基礎都不存在
2. **Self-Hosting 平台是 ELv2 而非 MIT**——可以自用，但不能轉賣為服務
3. **LLM 定價已大幅變動**——Budget Guard 的校準需要基於當前實際使用的模型重新計算
