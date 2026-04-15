# SEO 全站診斷與自動修復閉環

版本：v1.6（收斂版——唯一執行清單）  
日期：2026-04-15  
背景：本文件記錄 2026-04-14～15 討論中產生的架構思路，作為後續開發的設計參考。  
v1.1 修訂：以資深 SEO 專家角度重新審查全文，修正 6 處 SEO 判斷與可行性問題。  
v1.2 修訂：將文件主體從單站觀察重構為「通用 SEO 健康標準與產品能力規格」，避免診斷邏輯被單一網站綁定。  
v1.3 修訂：以 SEO 專員身分直接讀取全部原始碼，修正 7 處代碼與文件不符的偏差，更新 P0~P2 開發任務，修正第 10 節三項功能的實作範圍描述。  
v1.4 修訂：補充「開發後 SEO 實務覆蓋率是否足夠」與「如何保持通用化、不被單一網站綁定」的正式結論，將建議納入文件主體。  
v1.5 修訂：重新讀取全部 18 個 agent/tool 模組、23 張 DB 表、12 個 scheduler jobs，發現 6 個 v1.4 未涵蓋的結構性問題，並將排程架構從零散 job 清單升級為五層 DAG。  
v1.6 修訂：整體評估 v1.1～v1.5 的視野擴張已渴入過度設計，將四份競爭的待辦清單收斂為一份。移除無下游消費的模組規劃，簡化過度抽象的架構設計。新增 ⨁ 第 14 節為本文件唤一權威執行清單，兩週可完成。

---

## 1. 討論背景與核心問題

### 1.1 現況認知

ContentFlow 的核心定位是「內容生產 + SEO 監控」系統，**不是 CMS 或網站後台**。對目標網站的操作能力邊界如下：

| 能力 | 說明 |
|------|------|
| ✅ 讀取診斷 | 呼叫 PSI、GSC、GA4 API 取得外部指標 |
| ✅ 內容發布 | 透過 WordPress REST API 或 ForgeBase API 寫入文章 |
| ✅ SEO meta 寫入 | 自動填入 Yoast / RankMath / AIOSEO meta 欄位 |
| ✅ Schema 產出 | 生成 Article / FAQ / HowTo JSON-LD（存入 DB） |
| ❌ 伺服器層設定 | 無法改動 sitemap、robots.txt、htaccess、CDN |
| ❌ 自動修正 CWV | Core Web Vitals 問題屬主題/伺服器層，ContentFlow 無權限 |

### 1.2 部署架構示例（非產品標準）

以下部署描述是**目前環境示例**，僅用於說明系統與目標網站的耦合方式；**不應成為診斷邏輯或產品規格的一部分**。

目前示例環境中，前台網站與 ContentFlow Admin **共用同一台 Linode 伺服器、同一個 Docker 容器、同一個 FastAPI 應用**：

```
使用者 → Nginx (443) → 127.0.0.1:8000 → FastAPI (前台 + /admin/*)
                                        → PostgreSQL (DB)
```

**影響評估：**
- PSI / GSC / GA4 等外部量測：不受影響，完全準確
- 全站爬蟲（loopback 爬自己）：回應時間偏快但結構問題偵測準確
- 資源競爭：AI Pipeline 跑批次時可能壓縮前台回應速度，進而影響 CWV 量測值
- **建議**：AI 排程任務維持離峰（目前已設凌晨 03:00–08:00），暫不需分離伺服器

### 1.4 本文件定位：產品標準，不是單站健檢報告

本文件的主要目的，不是回答「某一個網站現在有什麼問題」，而是定義：

1. ContentFlow 的**通用 SEO 健康感知模型**應該包含哪些標準檢查項
2. 各檢查項如何標準化輸出為統一問題清單
3. 哪些問題可自動修、哪些只能建議、哪些必須人工確認
4. 系統如何在不同產業、不同 CMS、不同站型下仍可複用同一套機制

因此，**通用規則優先，單站觀察只能作為驗證案例或附錄示例**。

### 1.3 現有自動閉環

排程器（`scheduler.py`）目前執行的完整週期：

```
每天 03:00  GSC 資料同步（sync_gsc_all_projects）
每天 03:30  GA4 資料同步（sync_ga4_all_projects）
每天 04:00  因果回填（backfill_action_outcomes）
每天 08:00  Strategic Agent → 決定當日工作 → execute_strategic_plan
             ↓ generate → run_orchestrator（研究+撰寫+SEO檢查）
             ↓ refresh  → RefreshAgent（內容更新）
             ↓ alert    → Slack 通知
每週一      競品 SERP 掃描、歸因引擎
每週二      Content Refresh 觸發條件檢查
每週三      排名驟降告警
每月 1 日   L1/L2 學習分析
每週日      反思日誌 + 週報
```

---

## 2. 通用產品斷點：目前閉環缺的不是個案修補，而是標準能力

這一節討論的不是某站現在缺什麼，而是 ContentFlow 若要成為通用 SEO 自治系統，現階段缺少哪些**平台級能力**。

### 斷點 1：缺少「風險分級發布政策」，導致內容閉環停在審核前

**現象：**  
`_execute_generate` 寫完文章後，`article.status = "reviewing"`，等待人工審核才能 published。  
目前系統沒有一套可配置的**發布風險政策**，去判定哪些內容可自動發布、哪些內容只能提醒人工審查。

**代價：**  
Strategic Agent 每天在規劃、Pipeline 每天在產出，但實際網站不一定有新內容上線。對產品而言，這代表「生成能力」與「發布能力」之間沒有標準化橋接。

**解法方向：**  
~~設定自動發布門檻——若 `seo_score >= 80` 直接 published。~~

**通用解法方向：建立 Publish Policy Layer**
- 以**站點風險等級**而非特定網站名稱決定發布規則，例如：`low_risk`、`brand`、`commerce`、`ymyl`
- 不同風險等級對應不同門檻：`AUTO_PUBLISH_ENABLED`、`AUTO_PUBLISH_MIN_SCORE`、`REQUIRES_HUMAN_REVIEW`
- 低風險站點可啟用自動發布；高風險站點改為超時通知、雙人審核或僅人工發布
- 讓發布規則成為**專案設定**的一部分，而不是寫死在單一站點判斷中

---

### 斷點 2：缺少「渲染驗證層」，系統只知道有資料，不知道是否真的出現在 HTML

**現象：**  
系統會在 DB 中產生 meta、schema、canonical 等 SEO 資料，但目前缺少一層標準化驗證，去確認這些資料是否真的被前台 template、CMS、主題或 API renderer 正確輸出到 HTML。

**代價：**  
若只檢查 DB，不檢查最終 HTML，系統會產生「資料存在 = SEO 已完成」的錯覺。實務上 Google 只看最終 HTML 與可抓取回應，不看資料庫。

**通用解法方向：建立 Render Verification Layer**
- 對所有站點統一檢查：title、meta description、canonical、robots、Open Graph、JSON-LD、h1
- 輸出結果應是「資料存在」「前台已渲染」「Googlebot 可讀」三層狀態
- 將 schema 診斷從單一 article/faq/howto 類型，擴充為通用 renderer 驗證器

---

### 斷點 3：缺少「標準化行動映射」，系統能發現異常卻無法一致地轉成修復工單

**現象：**  
`analytics_agent._compute_action()` 會輸出 `recommended_action: "rewrite"`，但 `execute_strategic_plan` 只處理三種 action type（`generate / refresh / alert`），沒有 `optimize_meta` 這種針對 title/description CTR 優化的 action。

**代價：**  
系統雖能發現 CTR 低、排名掉、內容老化等訊號，但若沒有標準 action taxonomy，就只能停留在告警或人工解讀，無法形成穩定的產品能力。

**解法方向：**  
新增 `optimize_meta` action type，由 AI 依 `主要關鍵字 + 當前 title + GSC 數據` 重新生成點擊誘因更強的 meta title / description，回寫 DB 並觸發前台更新。

---

## 3. 全站健康感知的產品設計原則

### 3.1 核心概念

> 系統定期自我診斷 → 輸出問題清單（依嚴重程度排序）→ 依風險等級自動執行或排程修復 → 修復後追蹤 GSC 驗收 → 學習哪類修復有效

這是業界「自動化 SEO 稽核 + 修復閉環」的目標形態。Semrush Site Audit、Ahrefs 做診斷（前半段），Alli AI、BrightEdge 嘗試做自動修復（後半段）。

但對 ContentFlow 而言，**真正的產品門檻不是多會看單一網站，而是能否定義一套跨網站、跨 CMS、跨產業仍成立的標準診斷體系。**

### 3.2 設計原則：先定義標準，再診斷網站

診斷層必須遵循以下原則：

1. **標準先於個案**：先定義 SEO 健康標準，再拿網站去套標準，而不是看完網站後臨時整理問題
2. **輸出必須可比較**：不同網站掃描結果要能放進同一張問題表，否則無法形成平台能力
3. **分層而非堆點**：區分抓取、索引、渲染、內鏈、結構化資料、內容品質、效能，而不是平面羅列問題
4. **問題要能映射到行動**：每個 issue type 都要有明確的 `fix_action` 或 `manual_review_reason`
5. **保留站點政策差異**：標準檢查項通用，但門檻、風險政策、可自動修的範圍由 project profile 決定


### 3.3 問題清單格式（SiteIssue）

建議新增的資料結構（對應新 DB 表 `site_issues`）：

```python
@dataclass
class SiteIssue:
    issue_type: str        # 問題類型（見 3.3）
    severity: str          # "critical" / "high" / "medium" / "low"
    auto_fixable: bool     # 是否可全自動修復
    url: str               # 受影響的頁面 URL
    article_id: int | None # 若對應到文章，記錄 article_id
    detail: str            # 問題說明
    fix_action: str        # 修復動作代碼
    detected_at: datetime
    fixed_at: datetime | None
    fix_result: str | None # "success" / "failed" / "no_change"
```

---

### 3.4 通用 SEO 健康標準（診斷層標準模型）

診斷層不應直接從單站現象出發，而應固定檢查以下七大面向：

| 健康面向 | 核心問題 | 代表性檢查項 |
|---------|---------|-------------|
| Crawlability（可抓取性） | 爬蟲能不能拿到頁面 | robots、status code、redirect chain、blocked resources |
| Indexability（可索引性） | 拿到後能不能進索引 | canonical、meta robots、index coverage、soft 404 |
| Renderability（可渲染性） | HTML 是否真的輸出 SEO 訊號 | title、meta、OG、JSON-LD、主要內容區塊 |
| Discoverability（可發現性） | 網站能否把重要頁面暴露給 Google | sitemap、首頁/列表頁連結、內部連結深度、孤頁 |
| Information Architecture（資訊架構） | 主題關係是否清楚 | category、topic cluster、breadcrumb、站內連結網 |
| Content Quality Signals（內容品質信號） | 頁面是否值得排名 | freshness、thin content、CTR、內容覆蓋度、E-E-A-T 輔助欄位 |
| Performance & UX（效能與體驗） | 速度與互動是否拖累排名 | CWV、cache headers、圖片大小、layout shift |

這七大面向才是產品應內建的標準健康模型。任何新站點接入時，都應套用同一模型，再依站點屬性調整門檻。

---

### 3.5 問題類型與風險分級

SEO 實務上，自動修復的安全性分三層：

#### ✅ 可以全自動（低風險）

| 問題類型 | issue_type | fix_action | 判斷理由 |
|---------|-----------|------------|---------|
| 文章缺 meta description | `missing_meta_description` | `generate_meta` | 改錯最多 CTR 差一點，不影響索引 |
| Schema JSON-LD 未注入頁面 | `schema_not_rendered` | `inject_schema` | 只加不改，最壞是 Google 不採用 |
| approved 文章未上線 | `approved_not_published` | `auto_publish` | 人已審核，延遲上線是浪費 |
| 缺少內部連結 | `missing_internal_links` | `inject_internal_links` | 有助排名，幾乎無負面風險 |
| 缺少 alt 屬性的圖片 | `missing_image_alt` | `generate_alt` | 無排名風險，有 accessibility 加分 |
| 重要入口頁缺少內容發現連結 | `entrypoint_missing_discovery_links` | `inject_discovery_links` | 重要頁面無法把權重與爬取路徑傳遞到內容頁 |
| 缺少 HTTP cache headers | `missing_cache_headers` | `add_cache_headers` | 節省 crawl budget、改善 TTFB |

#### ⚠️ 需設信心門檻（中風險）

| 問題類型 | issue_type | 風險點 | 條件門檻建議 |
|---------|-----------|--------|------------|
| CTR 低 → 改寫 title/description | `low_ctr` | 改差了需 2–4 週才知道 | 漸進式門檻：小站 impressions >= 10 / 中型站 >= 30 / 大站 >= 50，連續 14 天 CTR < 預期值（見 3.6） |
| 排名衰退 → Content Refresh | `ranking_decay` | 若原文 E-E-A-T 強，改寫可能弄壞既有排名 | position 惡化 > 5 名，持續 21 天 |
| 薄內容補字數 | `thin_content` | 加錯東西可能引入不相關信號 | 字數 < 800 且 impressions < 10 |

#### ❌ 絕對不能自動（高風險）

| 問題類型 | 原因 |
|---------|------|
| URL slug 變更 | 舊 URL 的 backlink 全失效，除非補 301 |
| Canonical / noindex 設定 | 一個 bug 可以讓整站消失於 Google |
| 大規模刪文 | 無法預測哪篇有隱性排名貢獻 |
| redirect 規則修改 | 屬伺服器層，ContentFlow 無法安全操作 |

---

### 3.6 CTR 門檻的漸進式設計

CTR 門檻不能綁死單一站點，而應按站點規模分層。若門檻只適用成熟站，小站永遠不會被觸發；若門檻只適用小站，大站會產生過多噪音。

```
漸進式門檻：
  階段 1（小站 / < 50 篇內容）: impressions >= 10 且 position <= 10 → 觸發 CTR 分析
  階段 2（中站 / 50-200 篇） : impressions >= 30 且 position <= 10 → 觸發 CTR 分析  
  階段 3（大站 / > 200 篇）  : impressions >= 50 且 position <= 10 → 觸發 CTR 分析

預期 CTR 參考值（依排名位置，來源：Advanced Web Ranking 2024）：
  Position 1:  ~31%
  Position 2:  ~16%
  Position 3:  ~11%
  Position 4-5: ~7%
  Position 6-10: ~3%

觸發條件：實際 CTR < 預期 CTR × 0.5（即低於預期值的一半）
```

---

### 3.7 診斷來源對照

| 診斷維度 | 資料來源 | 現有模組 |
|---------|---------|---------|
| 文章 SEO 完整度（meta、schema、slug） | DB 直查 | `Article` model |
| Core Web Vitals | Google PSI API | `tools/tech_seo.py` `CoreWebVitalsMonitor` |
| GSC 索引覆蓋率 | GSC API | `tools/tech_seo.py` `GSCIndexCoverageMonitor` |
| 排名表現 / CTR 分析 | DB `seo_rankings` | `agents/analytics_agent.py` `AttributionEngine` |
| 全站斷鏈 / 孤頁 / redirect chain | httpx 爬蟲 | `tools/tech_seo.py` `SiteAuditor` |
| 內容健康度（字數、更新頻率） | DB `articles` | `admin/app.py` content_health 路由 |
| 關鍵字覆蓋缺口 | DB `keywords` vs `articles` | 現無，需新增 |

---

### 3.8 完整閉環流程設計

**⚠️ v1.1 修訂：診斷頻率依重量級分層，避免集中跑導致資源競爭。**

```
【每日 04:30】輕量快速檢查（新增排程）
  ├── DB 查詢（missing meta、schema、slug、未發布文章、超時未審核）
  ├── GSC ranking/CTR 異常偵測（基於已同步的 03:00 資料）
  └── 關鍵字覆蓋缺口分析

【每週日 02:00】全站爬蟲掃描（重量級）
  ├── 爬蟲掃描（斷鏈、孤頁、redirect chain）
  ├── HTTP header 檢查（cache、content-type）
  └── 內部連結拓撲分析

【每月 1 日 or 手動觸發】CWV 量測
  └── PSI API（有 rate limit，且指標變動慢，無需高頻）
        ↓
  生成 SiteIssue 清單，依 severity 排序，存入 site_issues 表

【即時觸發】修復 dispatcher
  ├── severity=critical + auto_fixable=True → 立即執行
  ├── severity=high + auto_fixable=True     → 排入次日 auto_pipeline
  ├── severity=medium                        → 累積，週計畫批次處理
  └── severity=low                           → 記錄，不處理
        ↓
  fix_action 執行對應修復
  更新 site_issues.fixed_at + fix_result

【執行後 28 天】GSC 驗收
  backfill_action_outcomes 回查對應 URL 的排名 / CTR / 曝光變化
  寫入 action_outcomes 表
        ↓
【每月 1 日】L1 學習分析
  哪類 fix_action 平均 GSC 改善最大？
  → 上調有效 action 的自動執行信心門檻
  → 寫入 knowledge_entries 作為系統記憶
```

---

## 4. 與現有架構的整合點

ContentFlow 目前已具備約 **70% 的元件**，缺的是把它們串起來的膠水層：

| 需要新增 | 對應到現有哪裡 |
|---------|-------------|
| `site_issues` DB 表 + migration | 新增 Alembic migration |
| 全站診斷 orchestrator（整合各診斷來源） | 新增 `agents/site_audit_agent.py` |
| fix dispatcher（issue → fix_action 路由） | 新增 `agents/site_fix_agent.py` |
| 排程：每週日 02:00 跑全站掃描 | 新增進 `scheduler.schedule_all_jobs()` |
| Render verification layer | 新增最終 HTML 驗證器，檢查 meta/schema/canonical 是否真的輸出 |
| Admin UI：問題清單頁面 | 新增 `/admin/site-issues` 頁面 |

**不需要動的現有元件：**
- `tools/tech_seo.py` — 直接呼叫，不需修改
- `agents/analytics_agent.py` — 直接呼叫，不需修改  
- `scheduler.py` 的 backfill_action_outcomes — 完全複用，只需新增 site_issues 的回寫邏輯
- `action_outcomes` 表 — 完全復用現有學習閉環

---

## 5. 開發優先順序（先建通用能力，再套用到單站）

依據「最小開發量 × 最大 SEO 效益」排序：

### P0 — 產品底座（先讓診斷層變成標準能力）

1. **⭐ 建立標準健康分類法**：先實作七大健康面向與標準 `issue_type taxonomy`  
  - 目標：任何網站掃完都能輸出同一種問題格式  
  - 產出：`SiteIssue` schema + issue taxonomy + severity mapping

2. **建立 render verification layer**：驗證 DB / CMS 中的 SEO 欄位是否真的出現在 HTML  
  - 目標：避免「資料存在但前台沒輸出」的假完成狀態  
  - 產出：title/meta/canonical/robots/schema/h1 verifier

3. **建立 project policy layer**：把風險、站型、產業屬性與自動化範圍做成專案設定  
  - 目標：讓同一套診斷引擎可用於 YMYL、品牌站、內容站、商業站  
  - 產出：`site_profile`、`risk_profile`、`auto_fix_policy`

4. **建立 entrypoint / internal discovery 檢查器**：找出重要入口頁未把權重傳遞到內容頁的情況  
  - 目標：不限定首頁、部落格首頁或分類頁，統一看「入口頁是否有內容發現能力」

### P1 — 啟動閉環（診斷輸出開始可行動）

1. **全站診斷 orchestrator**：整合 crawlability、indexability、renderability、discoverability、IA、content、performance  
  - 預期效益：系統開始有「全站健康視角」而非零散工具

2. **標準 action taxonomy**：新增 `optimize_meta`、`inject_schema`、`inject_discovery_links`、`notify_review_stale` 等 action  
  - 預期效益：issue 能穩定映射到修復工單

3. **審核與發布政策執行器**：不同風險等級的站點套不同發布規則  
  - 預期效益：把自動化邊界收進產品，而不是靠人工口頭約束

### P2 — 本月

1. **site_issues DB 表 + Admin UI**：讓診斷結果可視化、可追蹤  
2. **fix dispatcher**：把問題清單和修復動作連起來  
3. **排程整合**：每週掃描 + 修復結果 28 天回查  
4. **跨站 benchmarking**：不同 project 的健康分數可橫向比較，驗證通用標準是否穩定

---

## 6. 設計原則（Bounded Autonomy）

系統的自主修復範圍必須有明確邊界，否則一個判斷錯誤可能讓整站排名崩潰：

```
自動執行:     只改「只加不減」的事（加 schema、加 meta、加內部連結）
需要門檻:     改現有內容需要量化信號支持（指定 impressions、持續天數等條件）
人工確認:     任何影響 URL 結構、索引規則、redirect 的操作
永遠不做:     slug 變更、canonical 修改、大規模刪除
```

每次自動執行都寫入 `action_outcomes`，讓系統能在未來學習自己的判斷準確率。當某類 action 的平均 GSC 改善持續 < 0，系統應自動降低該 action 的執行信心門檻，甚至停止執行。

---

## 7. 個案觀察應降級為附錄，而不是主體設計依據

產品設計應以通用標準為主，單站觀察只能扮演兩種角色：

1. **驗證案例**：拿來驗證標準模型是否能抓到真問題
2. **優先級示例**：用來說明某類 issue 在實際站點會長什麼樣子

因此，像「首頁無文章連結」「HowTo Schema 未渲染」「某關鍵字 CTR 很低」這類內容，應被視為：
- 某次掃描的輸出示例
- 某個 site issue 的實際樣本
- 某個修復 action 的驗證案例

而不應直接決定產品的主體架構。

---

## 8. v1.1 SEO 專家審查紀錄（作為案例附錄）

### 審查方法
以資深 SEO 專家角度，對已發布文章頁面進行實際 HTTP 請求檢查，驗證：
- HTML 中的 meta description、canonical、OG tags、h1/h2 結構
- Schema JSON-LD 實際渲染狀況
- sitemap.xml、robots.txt
- 首頁到文章的連結拓撲
- HTTP response headers（cache、content-type）
- Googlebot-Mobile 的一致性

### 主要修正
| # | 原文件記述 | 修正 | 原因 |
|---|----------|------|------|
| 1 | 斷點 2「Schema 未注入」 | 已注入 Article/FAQ/Breadcrumb Schema | 實測 3 段 JSON-LD 皆正確，僅 HowTo 未渲染 |
| 2 | auto_publish seo_score >= 80 | YMYL 文章不應自動發布 | 醫療健康領域需人工審核，Google QRG 明確要求 |
| 3 | CTR 門檻 impressions >= 50 | 改為漸進式門檻（初期 >= 10） | 新站曝光量低，固定高門檻會導致機制永不觸發 |
| 4 | 遺漏：首頁無文章連結 | 新增為 P0 最高優先 | 首頁 → 文章 0 連結，PageRank 無法傳遞，比三個斷點都嚴重 |
| 5 | 診斷全部週日 02:00 跑 | 分層：每日/每週/每月 | 避免集中跑導致資源競爭，依量級分頻率 |
| 6 | 遺漏：HTTP cache | 新增診斷項 | 文章頁無 Cache-Control，浪費 crawl budget |

---

## 9. 下一步行動（v1.2 更新）

- [ ] **P0-1**：定義七大健康面向與標準 issue taxonomy
- [ ] **P0-2**：建立 render verification layer，驗證最終 HTML SEO 訊號
- [ ] **P0-3**：建立 project policy layer（site profile / risk profile / auto-fix policy）
- [ ] **P0-4**：建立 entrypoint / discovery links 檢查器
- [ ] **P1-1**：設計標準 action taxonomy 與 issue → action 映射
- [ ] **P1-2**：設計 `SiteIssue` 資料結構與 `site_audit_agent.py` 架構
- [ ] **P2-1**：`site_issues` DB migration + Admin UI 頁面
- [ ] **P2-2**：fix dispatcher + 28 天 GSC 驗收邏輯
- [ ] **P2-3**：將單站發現（如首頁缺連結、HowTo 未渲染）改為 site issue 實例，不再寫死於產品主體

---

## 10. 擴充功能規劃（P1 補充）

> 此節在第 11 節全面代碼審查後有部分修正，詳見 11.4。

以下三項功能可直接接上現有架構，開發成本低，但對 SEO 效益貢獻顯著，建議在 P0~P2 基礎建設完成後優先納入。

---

### 10.1 Internal Link Equity Flow（內鏈權重流向分析）

#### 背景

`cluster_agent.py` 已有 `InternalLinkSuggestion` dataclass，可輸出跨文章的內部連結建議，但目前只停留在「建議」層，沒有執行路徑，也沒有拓撲分析能力。`tools/tech_seo.py` 的 `SiteAuditor` 已有爬蟲基礎。

#### 能力目標

透過爬取現有文章的 `<a>` 連結，建構站內有向連結圖，量化 PageRank 從「入口頁 → 文章頁」的流向是否通暢。

#### 診斷邏輯

```
SiteAuditor.crawl() → 抽取每頁所有 <a href>
  → 建構有向圖（nodes=URL, edges=連結關係）
  → 計算每個節點的 in-degree（被連結次數）

孤頁（orphan page）: in-degree = 0
漏斗頁（hub page）:  in-degree 高但 out-degree = 0（流入但不流出）

與 TopicCluster 疊加：
  → 同 cluster 內，in-degree 低的文章 = 需要被連入
  → seo_rankings 排名好的文章，是否有指向同 cluster 其他文章
```

#### 新增 issue_type

| issue_type | severity | fix_action | 條件 |
|-----------|----------|-----------|------|
| `orphan_page` | high | `inject_internal_links` | in-degree = 0 且已發布 |
| `cluster_link_gap` | medium | `inject_cluster_links` | cluster 內文章互連率 < 50% |
| `hub_page_no_outlinks` | medium | `inject_discovery_links` | 入口頁 out-degree = 0 到 cluster 文章 |

#### 與現有架構的整合點

- 診斷來源：`SiteAuditor`（已有）+ `TopicCluster / ClusterMember` ORM（已有）
- 修復執行：接入 P1-1 的 fix dispatcher，`fix_action = inject_internal_links`
- 排程時機：併入每週日 02:00 的全站爬蟲掃描
- 驗收：28 天後透過 `backfill_action_outcomes` 觀察受影響文章的排名與 CTR 變化

---

### 10.2 Keyword Trend & Seasonality（關鍵字趨勢感知）

#### 背景

現有 `Keyword` 表的 `search_volume` 是靜態快照（匯入 Excel 時的數值），不隨時間更新。`ContentCalendar` 已有 `month/week` 欄位，有設計意圖支援發布時機排程，但缺少動態趨勢資料支撐決策。

#### 能力目標

對追蹤中的高優先關鍵字定期感知搜尋量趨勢與季節性規律，讓 Strategic Agent 的選題與排程有時機因素的依據。

#### 實作設計

**資料來源**：Google Trends（Pytrends 非官方 Python 套件，或 SerpAPI 的 trends endpoint）

**新增 DB 欄位（在 `keywords` 表）**：

```python
trend_direction: str | None    # "rising" / "stable" / "declining"
trend_updated_at: date | None
peak_months: str | None        # JSON list，例如 "[10, 11, 12]" 代表秋冬高峰
seasonality_index: float | None  # 1.0 = 無季節性；1.5 = 旺季量比均值高 50%
```

**排程**：每月 1 日，對 `search_volume > 500` 的關鍵字批次查詢趨勢，更新上述欄位。

**Strategic Agent 整合**：在 `_collect_project_context()` 中加入趨勢資料，讓 LLM 規劃時可得知：
- 哪些關鍵字正在爬升（優先寫）
- 哪些關鍵字進入季節性高峰（優先排程）
- 哪些關鍵字正在衰退（降低投入優先級）

**ContentCalendar 聯動**：趨勢峰值月份在未來 4 週內時，自動將對應日曆項目的 `week` 提前，並加上 `priority_boost` 旗標。

#### 注意事項

- Pytrends 有頻率限制，每次查詢需間隔至少 1 秒，批次查詢建議不超過 20 個關鍵字/次
- 趨勢數據為相對指數（0–100），不是絕對搜尋量，應以「方向」和「季節性」為主，不做精確預測

---

### 10.3 GSC Link Report — 最低成本 Backlink 情報

#### 背景

目前系統對外部連結（backlinks）完全沒有感知。整合第三方 backlink 工具（Ahrefs / Moz）成本高，但 Google Search Console API 本身提供免費的連結資料端點，可作為零成本起點。

#### GSC Links API 可取得的資料

```
GET /webmasters/v3/sites/{siteUrl}/sampleLinks
回傳：
  - 外部連結域名清單（linking domain，非完整 URL）
  - 各連結域名指向本站的頁面數量
  - 內部連結樣本（確認 SiteAuditor 爬蟲結果是否一致）

GET /webmasters/v3/sites/{siteUrl}/linkedPages  （限 WMT-only 端點）
回傳：
  - 每個頁面被外部指向的連結數量（aggregate）
```

#### 新增 DB 表：`gsc_link_stats`

```python
class GSCLinkStat(Base):
    __tablename__ = "gsc_link_stats"

    id: int
    project_id: int
    page_url: str              # 被連結的頁面
    linking_domain: str        # 外部連結的域名（非完整 URL）
    link_count: int            # 該域名指向此頁的連結數
    link_type: str             # "external" / "internal"
    tracked_date: date
```

#### 診斷能力

| 診斷項目 | 邏輯 |
|---------|------|
| 新增外鏈域名 | 本月 `linking_domain` 集合 vs 上月差集 → 新增域名通知 |
| 外鏈集中頁面 | 哪幾篇文章累積外鏈最多 → 應成為 internal link hub，優先把 PageRank 往其他文章傳 |
| 外鏈空白文章 | 已發布但外鏈為 0 的文章 → 標記為「需要主動推廣或內容整合」 |
| 外鏈 vs 排名相關 | 外鏈多的文章排名是否較好 → 給 L1 學習提供 authority 維度 |

#### 限制與定位

- GSC 只回傳**域名**，不含完整外部連結 URL，因此無法做 anchor text 分析或毒性連結偵測
- 資料更新頻率：GSC Links API 約每週更新一次，建議排程設為每週一，配合現有競品 SERP 掃描一起跑
- 這是 **「有感知」而非「完整 backlink audit」** 的定位——讓系統知道自己獲得了新外鏈、哪篇文章最受外部引用，而不是替代 Ahrefs

#### 整合點

- 在現有 `GSCClient` 新增 `get_link_stats(site_url)` 方法
- 排程：每週一已有 `run_competitor_serp_check()`，新增 `sync_gsc_link_stats()` 同步執行
- 與 `cluster_agent.py` 的內鏈分析疊加：外鏈強的文章 = natural hub，應被 fix dispatcher 優先設為其他文章的連結目標

---

## 11. SEO 專員全面代碼審查（v1.3）

**審查日期**：2026-04-15  
**審查方式**：直接讀取 `agents/`、`tools/`、`scheduler.py`、`models/database.py` 原始碼核查，確認本文件的規劃是否與實際系統符合，並從 SEO 實務角度找出流程問題。

---

### 11.1 現有系統完整流程確認

#### 文章生產閉環（完整，流程正確）

```
ContentCalendar(planned)
  → Strategic Agent 08:00 選出日曆項目
  → Orchestrator(LangGraph StateGraph)
       ├─ research_node   (SERP + PAA + PubMed)
       ├─ strategy_node   (search intent / writing arch / content angle)
       ├─ write_node      (brand context + author/reviewer metadata)
       ├─ seo_check_node  (加權評分 ≥85 才過 gate)
       │      ↑ 最多重試 3 次，透過 seo_qa_agent 微調
       ├─ factcheck_node  (禁用詞 + AI 事實查核 + PubMed 比對)
       └─ budget_guard    (≤15 LLM 呼叫，≤$2.00)
  → article.status = "reviewing"  ← 流程停在此
```

**SEO 實務評估：流程設計正確。** research → strategy → write → check → factcheck 的順序符合業界最佳實踐。特別是 strategy_node 在 SERP 分析後才決定搜尋意圖與寫作架構，這讓生產出的文章在創作前就已以 SERP 為基準，而非憑空臆測。

---

### 11.2 代碼核查發現的偏差與問題

#### 問題 1：`eeat_score` 欄位語意被覆蓋（高風險）

**位置**：`scheduler.py` → `run_attribution_engine()`

```python
# 現有代碼（不正確）
grade_map = {"A": 95, "B": 80, "C": 60, "D": 40, "F": 20}
article.eeat_score = grade_map.get(perf.performance_grade, 50)
```

`eeat_score` 欄位語意上應代表「E-E-A-T 信號強度」（作者資質、引用品質、信任訊號），但 attribution engine 將其改寫為 GSC **排名表現等級**（A~F 轉成數字）。這是欄位語意混用：

- 若 `learning_agent.py` 的 L1 模式分析用 `eeat_score` 做相關性分析，它分析的是「排名績效」而非「E-E-A-T 品質」，結論不具意義
- 若人工在 Admin 看 `eeat_score = 20`，應理解為「E-E-A-T 弱」，但真正意思是「GSC 排名 F 等」

**修正方向**：新增 `performance_grade` 欄位存排名績效（"A"/"B"/"C"/"D"/"F"），保留 `eeat_score` 專門給 E-E-A-T 品質計算（作者有 credentials + reviewer 已設定 + 有 PubMed 引用 + schema 完整 = 高分）。

---

#### 問題 2：SEO gate 檢查的是 Markdown draft，不是渲染後 HTML（中風險）

**位置**：`orchestrator.py` → `seo_check_node` → `run_seo_check_agent(draft)`

Orchestrator 的 `SEO_PASS_THRESHOLD = 85` 只針對生產階段 Markdown 草稿執行。代碼直接對：
- `draft.meta_title`、`draft.meta_description`（DB 欄位）
- `draft.content_markdown`（文字內容）

進行規則比對。這些值存入 DB，但**是否真的由 CMS 渲染到 HTML `<title>` 和 `<meta>`，目前沒有任何機制去確認**。文件第 2 節斷點 2 的診斷是正確的，渲染驗證層缺失確認。

---

#### 問題 3：`suggested_internal_links` 已建立但永遠停在建議狀態（中風險）

**位置**：`seo_check_agent.py` → `suggest_internal_links()` + `Article.suggested_internal_links`（DB 欄位）

系統在 SEO Check 階段已計算內部連結建議並存入 DB，但：
- 沒有任何模組讀取這個欄位並將連結注入已發布的文章
- `refresh_agent.py` 的局部增補模式（CF-06-03）補的是內容段落和 FAQ，不處理 `suggested_internal_links`
- 建議會隨時間過時（文章新增後舊文章的建議不會重新計算）

**修正方向**：在 fix dispatcher（P1）中新增 `inject_internal_links` 執行路徑，讀取 `suggested_internal_links` 並透過 publisher 更新文章。這個 action type 文件第 3.5 節已列出，屬低風險可自動修復。

---

#### 問題 4：`FeaturedSnippetDetector` 和 `CompetitorThreatDetector` 只在 Refresh 觸發後才跑（低→中風險）

**位置**：`refresh_agent.py` → CF-06-05（CompetitorThreatDetector）、CF-06-06（FeaturedSnippetDetector）

這兩個分析器已實作，但架構上只在 `execute_strategic_plan → _execute_refresh()` 被呼叫時才執行。這意味著：
- 若某篇文章排名穩定、不被選為 refresh 對象，即使其 Featured Snippet 被競品搶走也不會被偵測
- CompetitorThreatDetector 偵測「競品排名超越」的功能也只在已進入 refresh 流程的文章才會跑

**修正方向**：將 `FeaturedSnippetDetector` 和 `CompetitorThreatDetector` 的邏輯從 refresh 流程解耦，改為獨立診斷工具，納入每週日的全站掃描排程（與 P2 site_audit_agent 合併觸發）。

---

#### 問題 5：Keyword Cannibalization 資料未被 Strategic Agent 消費

**位置**：`scheduler.py` → `check_refresh_triggers()` 寫入 `KnowledgeEntry(category="cannibalization")`  
**位置**：`strategic_agent.py` → `_collect_project_context()` 讀取 `category="refresh_priority"` 但沒有讀取 `category="cannibalization"`

系統能偵測自蝕（CannibalizationDetector），結果存入 KnowledgeEntry，但 Strategic Agent 每天做規劃時拿不到這份資料。結果可能是：系統繼續對互相競爭的關鍵字安排新文章，加劇自蝕，而不是規劃合併或差異化。

**修正方向**：在 `_collect_project_context()` 中加入 `category="cannibalization"` 的查詢，輸入 Strategic Agent 的 context_snapshot。同時在 `STRATEGIC_SYSTEM_PROMPT` 中加入「若有 cannibalization 問題，不應再 generate 同關鍵字文章」的決策規則。

---

#### 問題 6：`scheduled_publish_at` 欄位無執行機制

**位置**：`models/database.py` → `Article.scheduled_publish_at`（已存在）

Article 表有 `scheduled_publish_at` 欄位，但排程器中沒有任何 job 定期掃描「`scheduled_publish_at <= now()` 且 `status = "approved"`」的文章並自動發布。這個欄位目前是死欄位。

**修正方向**：在 Publish Policy Layer（P0 斷點 1 解法）實作時，同步實作 `scheduled_publish_at` 執行邏輯。建議加入每日 04:30 的輕量診斷 job 中，掃描到期的排程發布文章。

---

#### 問題 7：CTR 優化斷點確認

**位置**：`analytics_agent.py` → `_compute_action()` 可輸出 `recommended_action = "rewrite"`  
**位置**：`strategic_agent.py` → `STRATEGIC_SYSTEM_PROMPT` 只定義 `generate / refresh / alert` 三種 action

Strategic Agent 規劃的 action 不包含 `optimize_meta`，即使 analytics engine 偵測到 CTR 低，系統也無法將其轉換為「改寫 title/description」的執行工單。這是文件第 2 節斷點 3 的確認。

---

### 11.3 待開發任務修正（P0~P2）

基於代碼核查，原 P0~P2 清單調整如下：

| 任務 | 原描述 | 修正 |
|------|--------|------|
| P0-1 | 建立 issue taxonomy | **新增前置**：先修正 `eeat_score` 欄位語意，避免 L1 學習污染 |
| P0-2 | Render Verification Layer | 確認：`seo_check` 跑 markdown；HTML 驗證目前真的缺失，本任務 **必要** |
| P0-3 | Project Policy Layer | 現有 `Project` 有 `industry`/`brand_url` 但無 `risk_profile`/`auto_fix_policy`，需新增 |
| P0-4 | Entrypoint checker | `SiteAuditor` 已有 `orphan_page` 偵測，但無 cluster topology 疊加，需補 |
| P1-1 | Action taxonomy | 確認缺 `optimize_meta`；同時需補 `inject_internal_links`（`suggested_internal_links` 已有資料但無執行路徑） |
| P1-2 | SiteIssue dataclass | 注意：`tools/tech_seo.py` 已有 `SiteAuditIssue`，新的 `SiteIssue` 應繼承或整合，避免兩套結構並存 |
| P1-3（新增） | Cannibalization → Strategic Agent | 讓 `_collect_project_context()` 讀取 cannibalization 資料，並更新 STRATEGIC_SYSTEM_PROMPT |
| P1-4（新增） | `scheduled_publish_at` 執行器 | 在 Publish Policy Layer 中同步實作；搭配 04:30 輕量 job |
| P2-2 | Fix Dispatcher | `inject_internal_links` 應為首批低風險 action，因為 `Article.suggested_internal_links` 資料已存在 |
| P2-4（新增） | FeaturedSnippetDetector 解耦 | 將 CF-06-06 從 refresh 流程獨立，納入每週日全站診斷排程 |

---

### 11.4 第 10 節三項功能的代碼核查修正

#### 10.1 Internal Link Equity Flow — 部分已有基礎

**代碼現況**：
- `seo_check_agent.py` 的 `suggest_internal_links()` 已在文章生產時計算pairwise 連結建議
- `Article.suggested_internal_links` DB 欄位已存在，儲存建議清單
- 但此函式是**逐篇配對**邏輯（比對關鍵字是否出現在內文），並非有向圖拓撲分析

**需要補充**：
- 爬取已發布文章的 `<a>` link，建構有向圖，計算 in-degree / out-degree
- 與關鍵字搜尋量和排名疊加，確認 PageRank 是否流向高潛力文章
- 上述是「10.1 節全部」要做的事，現有的 `suggest_internal_links` 只是**點對點建議**，不是拓撲分析

**修正後開發範圍**：`suggest_internal_links()` 輸出的建議已有，開發重點在：(1) 爬蟲 + 有向圖計算、(2) 將 `Article.suggested_internal_links` 建議接上 fix dispatcher 執行路徑。

---

#### 10.2 Keyword Trend & Seasonality — DB 欄位已存在，只差 Sync Job

**代碼現況**：`models/database.py` → `Keyword` 表已有以下欄位：
```python
trends_score = Column(Integer, default=None)     # 0-100，SerpAPI Google Trends 年均值
trend_direction = Column(String, default=None)   # "up" / "down" / "stable"
```
這兩個欄位標注「Phase 3」，代表已被設計但尚未實作 sync 邏輯。

**修正後開發範圍**：不需修改 DB schema；只需實作 `sync_keyword_trends()` scheduler job（每月 1 日），呼叫 Trends API 或 SerpAPI trends endpoint 更新這兩欄，並修改 `_collect_project_context()` 讓 Strategic Agent 讀到趨勢方向。`peak_months` 和 `seasonality_index` 若需要則再新增欄位。

---

#### 10.3 GSC Link Report — 真正缺失，描述準確無需修正

代碼中無任何 GSC link 相關呼叫。本節規劃正確，可直接進入開發。

---

### 11.5 SEO 實務流程總評

以下是以 SEO 專員角度對整個系統流程的最終評估：

| 流程段 | 評估 | 說明 |
|-------|------|------|
| 關鍵字選題 | ✅ 正確 | 有搜尋量、意圖分類、漏斗階段、競品分析 |
| 搜尋意圖判斷 | ✅ 正確 | strategy_agent 從 SERP 前 10 判斷意圖，文章格式與意圖一致 |
| 內容生產品質 | ✅ 正確 | PubMed 佐證 + 事實查核 + 法規禁用詞 + 加權 SEO gate |
| E-E-A-T 基礎 | ✅ 有基礎 | Author/Reviewer DB + writing_agent 注入到文章；但 `eeat_score` 欄位被覆蓋需修 |
| 文章發布閉環 | ❌ 斷點 | `status="reviewing"` 後無自動發布，`scheduled_publish_at` 未被執行 |
| SEO 完整性驗證 | ❌ 斷點 | gate 驗 markdown，發布後 HTML 渲染無驗證 |
| CTR 優化閉環 | ❌ 斷點 | 偵測到低 CTR 但 `optimize_meta` 無執行路徑 |
| Content Refresh | ✅ 正確 | RefreshDiffAnalyzer + FeaturedSnippetDetector + CompetitorThreatDetector 完整 |
| 自蝕防護 | ⚠️ 有偵測無防護 | CannibalizationDetector 有，但結果未饋入 Strategic Agent 決策 |
| 全站技術診斷 | ⚠️ 工具有、閉環沒 | SiteAuditor 有，但無標準化輸出、無 fix dispatcher、未排程 |
| 學習與記憶 | ✅ 正確 | L1/L2/3 層信心升級 + action_outcomes 28 天回查 + reflective loop |
| 內鏈管理 | ⚠️ 建議有、執行缺 | `suggested_internal_links` 有資料但無注入路徑 |
| 外部連結感知 | ❌ 缺失 | GSC Link Report 未實作 |
| Featured Snippet | ⚠️ 有偵測無主動追蹤 | CF-06-06 有，但只在 refresh 流程內觸發 |

**結論**：系統的內容生產品質管控非常扎實，是整個架構最成熟的部分。主要的 SEO 閉環缺口集中在「生產後」：發布、驗證、CTR 優化、副作用防護（自蝕）這幾條路徑尚未打通。P0~P2 的開發順序和方向正確，只需根據 11.3 的修正表調整細節。

---

## 12. v1.4 補充結論：覆蓋率、優先級與通用化原則

本節回答兩個產品層問題：

1. 這份開發計畫完成後，ContentFlow 對 SEO 實務工作的覆蓋率是否明顯提升？
2. 要如何確保這套能力是通用平台能力，而不是只對單一網站或單一產業有效？

---

### 12.1 結論先行：建議將本節正式納入開發文件

**建議：是，應正式納入。**

原因不是為了再擴大 scope，而是為了把「哪些能力一定要做，否則閉環仍然不成立」寫清楚，避免後續開發只完成工具堆疊，卻沒有完成 SEO 實務上的最後一公里。

v1.3 已確認 P0~P2 方向正確；v1.4 補充的是：

- 哪些項目屬於**必修正的架構錯位**
- 哪些項目會直接提高 SEO 實務覆蓋率
- 哪些原則必須寫進規格，才能維持**跨網站、跨 CMS、跨產業**的通用性

---

### 12.2 開發後的 SEO 實務覆蓋率評估

以目前系統能力來看，ContentFlow 已經不是單純的 AI 寫稿工具，而是具備以下強項：

- 關鍵字研究、SERP 解析、搜尋意圖判斷
- 內容生產、SEO 檢查、法規與事實查核
- GSC / GA4 / 競品位次 / 學習閉環
- 基礎 Topic Cluster 與內鏈建議

目前缺口主要在「文章生成之後」：

- 是否能安全發布
- 是否真的渲染到 HTML
- 是否能把問題轉成修復動作
- 是否能針對排名 / CTR / 自蝕 / 技術問題形成正式閉環

#### 覆蓋率判斷

| 狀態 | 覆蓋率評估 | 說明 |
|------|-----------|------|
| 現況 | 約 60%–70% | 強在內容 SEO、生產流程、學習回饋；弱在發布後治理、技術 SEO 閉環、off-page 感知 |
| 完成 v1.4 前述 P0~P2 後 | 約 80%–85% | 可補齊 on-page、內容更新、發布驗證、基礎 technical SEO、低風險自動修復 |
| 仍未完整覆蓋 | 約 15%–20% | 外鏈經營 / 數位 PR / hreflang / 本地 SEO / 伺服器 log 分析 / 重 JS render 診斷 |

#### 實務上的定位

完成本文件後，系統定位應從：

> 內容導向 SEO 自動化系統

升級為：

> 內容 SEO + on-page SEO + 基礎 technical SEO + 成效學習 的自治平台

這個定位對大多數內容站、品牌站、醫療資訊站、商業內容站而言，已足以覆蓋日常 SEO 營運的核心工作。

---

### 12.3 必須納入文件的三類補充

#### A. 必修正的架構錯位

這些不修，系統會看起來很完整，但實際 SEO 閉環仍不成立：

1. **拆開 `eeat_score` 與排名績效欄位**  
  現況把 A-F 排名表現寫進 `eeat_score`，會污染學習系統與管理視圖。應新增 `performance_grade` 或 `performance_score`，保留 `eeat_score` 專門表示 E-E-A-T 品質信號。

2. **將發布後 HTML 驗證列為 P0 必做，不可降級**  
  目前 SEO gate 驗的是 markdown/draft，不是最終 HTML。若沒有 render verification layer，就無法聲稱系統真的完成 SEO meta / schema / canonical 輸出。

3. **讓 `scheduled_publish_at` 真正被執行**  
  欄位已存在但沒有執行器。Publish Policy Layer 應同步補上定時發布 job。

4. **把 Cannibalization 結果正式餵回 Strategic Agent**  
  目前能偵測自蝕，但每日規劃拿不到這個訊號，會導致 generate 決策與 SEO 實務相衝突。

5. **把 `optimize_meta` 納入 action taxonomy**  
  否則 CTR 問題永遠只能被偵測，不能被執行修復。

#### B. 會直接提高 SEO 覆蓋率的功能

這些功能不是裝飾，而是讓系統從「能分析」變成「能營運」的關鍵：

1. **Render Verification Layer**  
  驗證 title / meta description / canonical / robots / JSON-LD / h1 是否真的出現在 HTML。

2. **Fix Dispatcher**  
  讓 `generate_meta`、`inject_internal_links`、`inject_schema`、`notify_review_stale`、`optimize_meta` 有統一執行入口。

3. **Internal Link Equity Flow**  
  將現有的內鏈建議從「點對點建議」提升為「站內權重流向管理」。

4. **Keyword Trend Sync**  
  讓 Strategic Agent 的選題與排程有趨勢依據，而不是只看靜態搜尋量。

5. **GSC Link Report 感知層**  
  雖然不是完整 backlink audit，但足以讓平台開始具備最基本的 off-page awareness。

#### C. 通用化必須明文化的原則

這些原則若不寫進文件，實作時很容易又退化成某個網站的客製方案：

1. **所有規則建在站點屬性，不建在網站名稱**  
  應使用 `risk_profile`、`site_profile`、`publisher_capabilities`、`content_type_policy`，而不是用網站名或產業名寫死條件。

2. **所有診斷輸出必須回到統一 taxonomy**  
  不論是 WordPress、ForgeBase、自建站，最終都要輸出同一種 `SiteIssue` 結構；平台差異只影響 `fix_action` 是否可執行。

3. **locale / geo / SERP 設定必須由 project context 驅動**  
  `gl`、`hl`、語系、發布語言、法規詞庫、SERP region 都應從專案設定決定，不應默認台灣繁中邏輯。

4. **Publisher 能力要抽象成 capability matrix**  
  例如：
  - `can_write_meta`
  - `can_write_schema`
  - `can_update_existing_post`
  - `can_schedule_publish`
  - `can_edit_internal_links`

  讓 fix dispatcher 決定「能不能做」，而不是在業務邏輯中寫死 WordPress / ForgeBase 特判。

5. **風險政策應由 project policy layer 決定，不由內容類型散落判斷**  
  `ymyl`、`commerce`、`brand`、`low_risk` 都應是 project-level policy，而不是各 agent 自己判。

---

### 12.4 建議加入文件的優先矩陣

以下為建議補入的開發優先順序，避免「功能很多但閉環沒打通」：

| 優先級 | 類型 | 項目 |
|-------|------|------|
| P0 | 架構修正 | `eeat_score` 語意拆分、render verification、publish policy、`scheduled_publish_at` 執行器 |
| P1 | 閉環打通 | `optimize_meta`、`inject_internal_links`、cannibalization → strategic context、site_issues + dispatcher |
| P2 | 覆蓋率提升 | Internal Link Equity Flow、Keyword Trend Sync、GSC Link Report |
| P3 | 高階擴充 | 完整 backlink intelligence、AI Overview visibility、international SEO、server log analysis |

這個排序的原則是：

- **先修閉環斷點，再加功能寬度**
- **先做通用能力，再做高成本進階情報**
- **先讓平台能穩定執行，再追求更多分析面向**

---

### 12.5 最終結論

若依照本文件 v1.4 的方向完成開發，ContentFlow 將不再只是「幫網站產內容」的系統，而會成為：

> 一個可跨網站、跨 CMS、跨產業複用的 SEO 自治平台底座。

它仍然不會涵蓋 SEO 的全部世界，但已可覆蓋大部分內容型 SEO 團隊每天最常見、最耗時、最需要流程化的工作：

- 選題與搜尋意圖判斷
- 內容生產與品質控管
- 發布後驗證
- CTR / refresh / 內鏈 / 自蝕修復
- 基礎技術 SEO 巡檢
- 成效回填與策略學習

因此，**建議將本節保留在文件中，作為後續開發是否真正補足 SEO 實務覆蓋率，以及是否維持平台通用性的判準。**

---

## 13. v1.5 補強：6 個結構性問題與排程 DAG 重構

**審查日期**：2026-04-15  
**審查方式**：重新讀取全部 18 個 agent/tool 模組原始碼、23 張 DB 表欄位定義、12 個 scheduler jobs 與 6 個 FastAPI 路由，以 SEO 全流程視角比對 v1.4 文件，找出被遺漏的結構性問題。

v1.4 已正確識別「生產後」的主要斷點（發布/驗證/CTR/自蝕），以下 6 個問題是 v1.4 未涵蓋但同樣會阻斷 SEO 閉環的結構性缺口。

---

### 13.1 問題 1：Topic Cluster 完全孤立——已建好工具但未排程、未消費

#### 代碼現況

- `cluster_agent.py` 有三個核心函式：`build_topic_clusters()`、`detect_cluster_gaps()`、`suggest_internal_links()`
- DB 有 `topic_clusters` + `cluster_members` 兩張表
- Streamlit 第 11 頁 Topic Map 有完整 UI

#### 問題

1. **scheduler.py 沒有任何 job 呼叫 cluster_agent**——叢集資料完全依賴人工在 UI 手動觸發
2. `strategic_agent._collect_project_context()` 不含任何叢集缺口資訊——**Strategic Agent 選題時完全不知道 Topic Cluster 有哪些缺口**
3. `planning_agent.generate_content_plan()` 有呼叫 `detect_cluster_gaps()`，但 `planning_agent` 本身在 scheduler 中未被使用（`run_auto_pipeline()` 直接跑 `run_strategic_agent()`，不經過 `planning_agent`）

#### SEO 實務影響

Topic Cluster 是 Google 2024 以來最重視的內容架構信號之一。系統已建好工具但不用，等於核心 SEO 能力被閒置。Strategic Agent 在不知道叢集缺口的情況下做選題，無法形成有組織的內容拓撲。

#### 修正方向

1. 新增排程 job：每月 1 日（在 L1 之前）呼叫 `build_topic_clusters()` + `detect_cluster_gaps()`
2. `_collect_project_context()` 加入 cluster gap 查詢，讓 Strategic Agent 做 `generate` 決策時優先填補叢集缺口
3. v1.4 的 Internal Link Equity Flow 應與 cluster topology 結合——同叢集內的互連率應是修復優先指標

---

### 13.2 問題 2：Tech SEO 診斷工具存在但從未被自動排程

#### 代碼現況

`tools/tech_seo.py` 有 5 個已完成的診斷元件：

| 元件 | 功能 | 開發狀態 |
|------|------|----------|
| `CoreWebVitalsMonitor` | PSI API → LCP/INP/CLS 量測 | ✅ 完成 |
| `GSCIndexCoverageMonitor` | 索引覆蓋率 + 新增失索引偵測 | ✅ 完成 |
| `SiteCrawler` | broken_link / orphan_page / redirect_chain / missing_title | ✅ 完成 |
| `TechSEOHealthDashboard` | 加權分數（40% CWV + 30% 索引 + 30% 爬蟲） | ✅ 完成 |
| `GSCMobileUsabilityMonitor` | Mobile Usability 問題偵測 | ✅ 完成 |

#### 問題

scheduler.py **完全沒有呼叫 tech_seo.py 的任何元件**。v1.4 Section 3.8 描述了理想排程（每週日全站爬蟲、每月 CWV），Section 4 也建議「新增進 `scheduler.schedule_all_jobs()`」，但 **P0-P2 開發任務清單中沒有對應的明確任務項目**，導致這些工具可能無限期閒置。

#### 修正方向

加入 3 個 scheduler jobs：

| Job | 頻率 | 呼叫 | 輸出 |
|-----|------|------|------|
| `run_site_crawl()` | 每週日 02:00 | `SiteCrawler.crawl()` + `GSCIndexCoverageMonitor` | 寫入 `site_issues` 表 |
| `run_cwv_check()` | 每月 1 日 05:00 | `CoreWebVitalsMonitor.fetch()` | 寫入 `site_issues` 表 |
| `run_mobile_usability_check()` | 每月 1 日 05:30 | `GSCMobileUsabilityMonitor.get_issues()` | 寫入 `site_issues` 表 |

這些 job 的輸出應統一寫入 v1.4 規劃的 `site_issues` 表，接上 fix dispatcher。

---

### 13.3 問題 3：Article 狀態機不完整，無法支撐新流程

#### 代碼現況

目前 Article 狀態僅有：

```
planned → researching → writing → reviewing → published / failed
```

#### 問題

v1.4 新增的多條流程需要更多中間狀態：

| 新流程 | 需要的狀態 | 目前狀態 |
|--------|-----------|----------|
| 人工審核通過但未發布 | `approved` | 不存在，直接從 reviewing 跳 published |
| 排程發布等待中 | `scheduled` | `scheduled_publish_at` 欄位有但無對應狀態 |
| 發布後渲染驗證中 | `verifying` | 不存在 |
| Content Refresh 進行中 | `refreshing` | 不存在 |

#### 修正方向

擴充狀態機為：

```
planned → researching → writing → reviewing
  → approved → scheduled → published → verifying → live
  → refreshing → published（update）
  → failed（any stage）
```

關鍵設計：
- `approved`：人工或 Publish Policy 確認可發布
- `scheduled`：`scheduled_publish_at` 有值且未到期
- `verifying`：已推送到 CMS，等待 Render Verification
- `live`：渲染驗證通過，確認 SEO 信號完整
- `refreshing`：Content Refresh Pipeline 進行中

---

### 13.4 問題 4：Publish → Verify 完整閉環流程未設計

v1.4 正確指出需要 Render Verification Layer，但只定義了「驗什麼」（title/meta/canonical/robots/JSON-LD/h1），沒有設計「何時驗、驗完做什麼」的完整流程。

#### 建議的完整流程

```
文章 approved + publish_policy allows auto-publish
  → Publisher 推送到 WordPress / ForgeBase
  → Article.status = "verifying"
  → 等待 5-10 分鐘（讓 CDN / cache 清除）
  → Render Verification 爬該 URL 的 HTML
     ├─ 檢查項目：
     │   title ∈ <title>、meta description ∈ <meta>、
     │   canonical ∈ <link rel="canonical">、robots ∈ <meta name="robots">、
     │   JSON-LD 存在且 @type 正確、h1 含主關鍵字、OG tags 完整
     ├─ 全部通過 → Article.status = "live"
     └─ 任一失敗 → 產生 SiteIssue（severity=high）+ Slack 告警
            → Article.status 保持 "verifying"，等待人工或自動修復後重驗
```

#### 排程設計

每日 10:00 `run_render_verification()` 掃描條件：
- `Article.status = "verifying"` 且 `published_at` 已超過 10 分鐘
- 或 `Article.status = "published"` 且 `published_at` 在過去 24 小時內（涵蓋手動發布）

---

### 13.5 問題 5：`planning_agent` 在自動流程中完全未被使用

#### 代碼現況

- `planning_agent.generate_content_plan()` 整合了 `AttributionEngine` + `CannibalizationDetector` + `detect_cluster_gaps()`——**恰好是 Strategic Agent 缺少的三項資訊**
- 但 `run_auto_pipeline()` 直接呼叫 `run_strategic_agent()`，**完全跳過 planning_agent**

#### 問題

系統有兩個重疊的規劃引擎（`planning_agent` 和 `strategic_agent`），但自動流程只用 strategic_agent，而 planning_agent 獨有的 cluster gap + cannibalization 整合能力被浪費。

#### 修正方向（二擇一）

**方案 A（推薦）**：將 `planning_agent` 的分析邏輯整合進 `strategic_agent._collect_project_context()`

```python
# 在 _collect_project_context() 中新增：
from ..agents.analytics_agent import CannibalizationDetector
from ..agents.cluster_agent import detect_cluster_gaps

# 1. Cannibalization 資料（v1.4 已建議但可進一步明確來源）
cannibal_pairs = CannibalizationDetector(session).detect(project_id)
context["cannibalization"] = [{"kw": p.keyword, "articles": p.article_ids} for p in cannibal_pairs[:5]]

# 2. Cluster 缺口（v1.5 新增）
gaps = detect_cluster_gaps(project_id, session)
context["cluster_gaps"] = [{"cluster": g.cluster_name, "missing": g.missing_keywords} for g in gaps[:5]]
```

**方案 B**：在 `run_auto_pipeline()` 中先跑 `generate_content_plan()`，將產出作為 Strategic Agent 的額外 context 輸入。

方案 A 更直接——避免兩個 agent 職責重疊，將 planning 能力收歸 strategic agent。

---

### 13.6 問題 6：排程架構應從「零散 job 清單」升級為「分層 DAG」

#### 現況

scheduler.py 目前有 12 個 job，各自獨立 cron 表達式，job 之間無顯式依賴。v1.4 預計再加 ~6-8 個 job（site crawl、CWV、mobile、trend sync、GSC link、render verify、cluster rebuild、scheduled publish executor）。

#### 問題

~20 個獨立 cron job 會造成：
- **時序衝突**：site crawl 還沒跑完，strategic agent 就開始讀 site_issues
- **資源競爭**：多個重量級 job 同時跑（crawl + CWV + attribution）
- **新增困難**：每次加 job 不知道插在哪裡、會不會跟其他 job 衝突

#### 修正方向：五層排程架構（Tiered Schedule DAG）

```
═══ Tier 1：資料採集（03:00-04:00）═══════════════════════════════
  03:00  sync_gsc_all_projects           每日     ← 現有
  03:15  sync_gsc_link_stats             每週一   ← 新增（§10.3）
  03:30  sync_ga4_all_projects           每日     ← 現有
  03:45  sync_keyword_trends             每月1日  ← 新增（§10.2）

═══ Tier 2：診斷掃描（04:00-05:30）═══════════════════════════════
  04:00  backfill_action_outcomes         每日     ← 現有
  04:00  check_scheduled_publishes        每日     ← 新增（§13.3）
  04:30  run_competitor_serp_check        每週一   ← 現有
  04:30  run_site_crawl                   每週日   ← 新增（§13.2）
  05:00  run_cwv_check                    每月1日  ← 新增（§13.2）
  05:00  run_attribution_engine           每週一   ← 現有
  05:30  check_refresh_triggers           每週一   ← 移動（原每週二→與 attribution 同日）
  05:30  run_mobile_usability_check       每月1日  ← 新增（§13.2）

═══ Tier 3：分析與規劃（06:00-07:00）═══════════════════════════════
  06:00  run_cluster_rebuild              每月1日  ← 新增（§13.1）
  06:00  run_l1_pattern_analysis          每月1日  ← 現有
  07:00  run_l2_roi_analysis              每月1日  ← 現有

═══ Tier 4：執行（08:00-10:00）═══════════════════════════════════
  08:00  run_auto_pipeline                每日     ← 現有
         → Strategic Agent 決策（含 cluster gaps + cannibalization）
         → generate / refresh / alert / optimize_meta / inject_links

═══ Tier 5：後驗證與反思（10:00-22:00）═══════════════════════════
  10:00  run_render_verification           每日     ← 新增（§13.4）
  22:00  check_ranking_drops               每日     ← 現有
  Sun 08:00 run_weekly_reflection           每週日   ← 現有
  Sun 09:00 send_weekly_report              每週日   ← 現有
```

#### 分層原則

| 層級 | 名稱 | 時段 | 職責 | 依賴 |
|------|------|------|------|------|
| Tier 1 | COLLECT | 03:00-04:00 | 拉取外部資料（GSC/GA4/Trends/Links）| 無 |
| Tier 2 | DIAGNOSE | 04:00-05:30 | 分析數據產生問題清單 | Tier 1 完成 |
| Tier 3 | ANALYZE | 06:00-07:00 | 模式學習、叢集重建 | Tier 2 完成 |
| Tier 4 | EXECUTE | 08:00-10:00 | Strategic Agent 決策 + Pipeline 執行 | Tier 2+3 結果可用 |
| Tier 5 | VERIFY | 10:00-22:00 | 發布後驗證、排名監控、反思學習 | Tier 4 有產出 |

#### 關鍵調整

- `check_refresh_triggers` 從**週二移到週一**（與 attribution 同天），讓 Strategic Agent 在次日即有最新 refresh 建議
- Tech SEO jobs 放在 Tier 2（04:30-05:30），確保在 Strategic Agent 08:00 決策前完成
- `check_scheduled_publishes` 每日 04:00 掃描到期的排程文章並觸發發布
- 新增 Tier 5 的 render verification，確保發布後 SEO 信號真正生效

---

### 13.7 改進後的完整 SEO 閉環圖

```
┌──────────────────────────────────────────────────────────────────────┐
│                    ContentFlow SEO 自治平台（v1.5）                  │
└──────────────────────────────────────────────────────────────────────┘

 Tier 1: COLLECT ─────────────────────────────────────────────────────
 │  GSC Rankings │ GA4 Metrics │ GSC Links  │ Keyword Trends │
 │  (daily)      │ (daily)     │ (weekly)   │ (monthly)      │
 └───────────────────────┬───────────────────────────────────────────

 Tier 2: DIAGNOSE ───────┴───────────────────────────────────────────
 │ Attribution  │ Refresh     │ SiteCrawl  │ CWV     │ Scheduled  │
 │ Engine       │ Triggers    │ (weekly)   │ (mth)   │ Publishes  │
 │ (weekly)     │ (weekly)    │            │         │ (daily)    │
 │──────────────────────────┬───────────────────────────────────────
 │                          ▼
 │              site_issues 統一問題表
 └───────────────────────────┬───────────────────────────────────────

 Tier 3: ANALYZE ────────────┴───────────────────────────────────────
 │ Cluster Rebuild │ L1 Pattern │ L2 ROI │ KB Sync │
 │ (monthly)       │ (monthly)  │ (mth)  │ (auto)  │
 └───────────────────────────┬───────────────────────────────────────

 Tier 4: EXECUTE ────────────┴───────────────────────────────────────
 │ Strategic Agent（_collect_project_context 整合）                   │
 │  ├─ Cluster Gaps（哪些主題缺文章？）                               │
 │  ├─ Cannibalization（哪些關鍵字自蝕？）                            │
 │  ├─ Keyword Trends（哪些正在上升？）                               │
 │  ├─ KB Query（過去成功模式？）                                     │
 │  ├─ Action Outcomes（什麼 action 有效？）                          │
 │  └→ StrategicPlan:                                               │
 │     generate / refresh / optimize_meta / inject_links / alert     │
 │                                                                   │
 │  generate    → Orchestrator Pipeline                              │
 │    (research→strategy→write→seo_check→factcheck→budget)           │
 │  refresh     → RefreshAgent Pipeline                              │
 │    (fetch→diff→patch→publish)                                     │
 │  optimize_meta → AI rewrite title/desc → publish update           │
 │  inject_links  → read suggested_links → publish update            │
 │  auto_publish  → publish_policy check → publisher                 │
 └───────────────────────────┬───────────────────────────────────────

 Tier 5: VERIFY & LEARN ─────┴───────────────────────────────────────
 │ Render Verify (daily 10:00)                                       │
 │  → title/meta/canonical/robots/JSON-LD/h1/OG                      │
 │  → 通過 → status = live                                           │
 │  → 失敗 → SiteIssue + 告警                                        │
 │                                                                   │
 │ Post-Pipeline Reflection (per article)                            │
 │ Weekly Reflection (Sun)                                           │
 │ L1/L2 Pattern Analysis (monthly)                                  │
 │ Action Outcome Backfill (daily → 7d/14d/28d check)                │
 │ ──→ KnowledgeEntry ──→ 回饋至 Tier 4 Strategic Agent              │
 └───────────────────────────────────────────────────────────────────
```

---

### 13.8 覆蓋率評估修正

| 狀態 | 覆蓋率 | 說明 |
|------|--------|------|
| 現況（v1.4 前）| ~60-70% | 強在內容生產 + 學習；弱在發布後治理 + 技術 SEO 閉環 |
| 完成 v1.4 所列 P0-P2 | ~80-85% | 補齊發布政策、渲染驗證、CTR 修復、自蝕防護 |
| **加上 v1.5 的 6 項補強** | **~88-90%** | 加入叢集規劃排程、tech SEO 排程、狀態機、publish→verify 流程、planning 整合、分層 DAG |
| 仍未覆蓋 | ~10-12% | 外鏈經營/數位 PR、hreflang/多語 SEO、Server Log 分析、AI Overview 優化、Local SEO |

#### 未覆蓋項目的定位說明

| 項目 | 為何不在 v1.5 範圍 |
|------|-------------------|
| 外鏈經營 / 數位 PR | 需要人際溝通與外部協商，非平台可自動化 |
| hreflang / 多語 SEO | 依賴 CMS 層 + 翻譯流程，非 ContentFlow 職責 |
| Server Log 分析 | 需要存取伺服器 log（access.log），多數客戶環境無法提供 |
| AI Overview 優化 | Google AI Overview 排名機制尚不穩定，觀察中 |
| Local SEO | 需要 Google Business Profile API，屬獨立產品線 |

---

### 13.9 補充 P0-P2 任務清單

以下任務應補入開發計畫，與 v1.4 的 P0-P2 合併執行：

#### P0（架構必修）

| 任務 ID | 任務 | 對應問題 | 前置依賴 |
|---------|------|----------|----------|
| P0-5 | Article 狀態機擴充（approved/scheduled/verifying/live/refreshing） | §13.3 | 無 |
| P0-6 | Cluster Agent 排程 + Strategic Agent context 整合 | §13.1 | 無 |

#### P1（閉環打通）

| 任務 ID | 任務 | 對應問題 | 前置依賴 |
|---------|------|----------|----------|
| P1-5 | Tech SEO 診斷排程（site crawl + CWV + mobile → site_issues） | §13.2 | P2-1（site_issues 表）|
| P1-6 | Publish → Render Verify 完整流程 | §13.4 | P0-2（render layer）+ P0-5（狀態機）|
| P1-7 | `planning_agent` 邏輯整合進 `strategic_agent._collect_project_context()` | §13.5 | P0-6 |

#### P2（架構優化）

| 任務 ID | 任務 | 對應問題 | 前置依賴 |
|---------|------|----------|----------|
| P2-5 | 排程五層 DAG 重構（含 check_refresh_triggers 移至週一） | §13.6 | 所有新 job 已實作 |

---

### 13.10 v1.4 + v1.5 合併後的完整優先矩陣

| 優先級 | 類型 | 項目 |
|--------|------|------|
| **P0** | 架構修正 | `eeat_score` 語意拆分（v1.4）、Render Verification Layer（v1.4）、Publish Policy Layer（v1.4）、`scheduled_publish_at` 執行器（v1.4）、**Article 狀態機擴充（v1.5）**、**Cluster → Strategic Agent 整合（v1.5）** |
| **P1** | 閉環打通 | `optimize_meta` action（v1.4）、`inject_internal_links` 執行路徑（v1.4）、Cannibalization → Strategic context（v1.4）、site_issues + fix dispatcher（v1.4）、**Tech SEO 排程（v1.5）**、**Publish → Verify 流程（v1.5）**、**planning_agent 整合（v1.5）** |
| **P2** | 覆蓋率 + 基建 | Internal Link Equity Flow（v1.4）、Keyword Trend Sync（v1.4）、GSC Link Report（v1.4）、跨站 benchmarking（v1.4）、**排程 DAG 重構（v1.5）** |
| **P3** | 高階擴充 | 完整 backlink intelligence、AI Overview visibility、international SEO、server log analysis |

---

### 13.11 結論

v1.4 的診斷方向完全正確——「生產後」的斷點確實是系統最大弱項。v1.5 的補強集中在三個 v1.4 忽略的維度：

1. **已建好卻沒用的能力**：Topic Cluster Agent、Tech SEO 工具、planning_agent——這些不是新功能，是把既有投資變現
2. **流程中缺失的中間狀態**：Article 狀態機只有 5 個狀態，撐不住 v1.4 規劃的 8 條新流程路徑
3. **排程從堆疊到分層**：20 個獨立 cron job 需要明確的 DAG 結構，否則 job 之間的時序依賴無法保證

完成 v1.4 + v1.5 全部開發後，系統的 SEO 實務覆蓋率可達 ~88-90%，剩餘 ~10-12% 屬於需要人際協商或外部平台 API 的領域，不在 ContentFlow 的產品邊界內。

---

## 14. v1.6 唯一執行清單——收斂版

> **本節取代 第 5、8、9、11.3、12.4、13.9、13.10 節 的所有待辦清單。**  
> 開發時只畫這一張表。先前各節保留為演變史記錄與設計根據，不作為執行依據。

---

### 14.1 為什麼要收斂

v1.1～v1.5 屠5 次疊加複查对的過程中，出現了三個問題：

1. **四份競爭的待辦清單**：第 5、9、11.3、12.4、13.9、13.10 節
2. **Scope 掛張超過系統定位**：`site_issues` + SiteAuditAgent + SiteFixAgent 將 ContentFlow 拉成 Semrush 小複製
3. **工程成本訠独遙超過實際 SEO 效益**：有向圖 PageRank flow 分析、五層 DAG 框架、趪站 benchmarking

收斂原則：
- **只建與現有 SEO 决策鏈有下游消費關係的能力**
- 診斷資訊若沒有任何 agent 會讀它，就不建
- 簡化版實作優先於抽象架構設計

---

### 14.2 特別註記：移除或凍結的規劃

| 項目 | 啪決 | 原因 |
|------|------|------|
| `site_issues` 表 + SiteAuditAgent + SiteFixAgent | **移除** | `SiteAuditor` 已債測 orphan page / broken link，直接輸出 Slack 已足夠。建一套独立的 issue lifecycle 是在做另一個產品 |
| Internal Link 有向圖拓撲分析 | **移除** | In-degree/out-degree 圖計算工程成本高。系統規模小時价値不足。現有 `suggested_internal_links` 執行路徑（第 6 項）已足夠 |
| 五層 DAG 排程重構 | **移除** | 12～20 個 cron job 用時間限制分層即可。不需要引入 DAG 框架 |
| 跨站 benchmarking | **移除** | 没有任何 agent 消費它，先做完主流閩環再説 |
| GSC Link Report | **凍結** | 待 fix dispatcher 可消費它之後再實作 |
| planning_agent 小節 (§13.5) | **收斂進 Layer 2** | 不需要独立 agent，只需將 `CannibalizationDetector` + `detect_cluster_gaps()` 結果加進 `_collect_project_context()` |
| Article 狀態機完整設計 (§13.3) | **收斂進 Layer 1** | 只需新增 `approved` 一個狀態即可支撐發布流程，不需要全部 10 個狀態 |
| Tech SEO 全套排程 (§13.2) | **收斂進 Layer 2** | site crawl 輸出到 Slack，不需要 site_issues 表 |

---

### 14.3 唯一執行清單

#### Layer 1：代碼漏洞修補（建議週 1 完成）

這 6 項都是對現有代碼的漏洞修補，不需新模組。

| # | 任務 | 對應問題 | 预估工時 |
|---|------|----------|----------|
| **L1-1** | `run_attribution_engine()` 改寫 `Article.performance_grade`（新欄）而不是 `eeat_score` | §11.2 問題 1 | 1 小時 |
| **L1-2** | `_collect_project_context()` 加入 `CannibalizationDetector.detect()` 查詢 + 更新 STRATEGIC_SYSTEM_PROMPT | §11.2 問題 5 | 2 小時 |
| **L1-3** | `_collect_project_context()` 加入 `detect_cluster_gaps()` 查詢，讓選題能填補叢集缺口 | §13.1 | 2 小時 |
| **L1-4** | 加入 `Article.status = "approved"` 狀態 + 對 `_execute_generate()` 的流程更新 | §13.3 | 半天 |
| **L1-5** | 新增 `check_scheduled_publishes()` cron job（每日 04:00）：掃描 `scheduled_publish_at <= now()` 且 `status=approved` 則發布 | §11.2 問題 6 | 半天 |
| **L1-6** | 實作 `sync_keyword_trends()` scheduler job（每月1日）+ 更新 `_collect_project_context()` 讓 Strategic Agent 讀到趨勢方向 | §11.4 10.2 | 1 天 |

#### Layer 2：發布閉環打通——簡化版（建議週 2 完成）

這 4 項是同一主题的完整流程：文章寫完 → 審核 → 發布 → 驗證。

| # | 任務 | 實作訪求 | 預估工時 |
|---|------|----------|----------|
| **L2-1** | Publish Policy：`Project` 表加兩個欄位 `auto_publish_enabled: bool` + `auto_publish_min_score: int`，在 `_execute_generate()` 中依此决定熊 `approved` 還是跳至 `auto_publish` | §2 斷點 1 | 1 天 |
| **L2-2** | `optimize_meta` action：在 `execute_strategic_plan()` + STRATEGIC_SYSTEM_PROMPT 讓 LLM 可輸出此 action type；`_execute_optimize_meta()` 呼叫 SEO QA Agent 重寫 title/description 並透過 publisher 回寫 | §2 斷點 3 | 1.5 天 |
| **L2-3** | `inject_internal_links` 執行路徑：讀取 `Article.suggested_internal_links`，產生 Markdown 寫入片段，透過 publisher 更新文章 | §11.2 問題 3 | 2 天 |
| **L2-4** | Render Verification：實作 `verify_rendered_html(article_url)` 函式（httpx GET → BeautifulSoup 檢查 title/meta/h1/JSON-LD/canonical）+ 每日 10:00 cron job 掃描個小時內新發布文章；對所 如缺失簻發 Slack 告警 | §2 斷點 2 | 1.5 天 |

#### Layer 3：可選擴充（選擇性，待 Layer 1+2 驗收庌再評估）

| # | 項目 | 前置条件 | 嬘開發理由 |
|---|------|----------|----------|
| **L3-1** | Cluster Agent 排程：每月 1 日呼叫 `build_topic_clusters()` + `detect_cluster_gaps()`（L1-3 只加資訊輸入，這項是定期更新數據） | L1-3 已完成 | 叢集資料需定期更新才有意義 |
| **L3-2** | Tech SEO 定期報警：每週日跑 `SiteCrawler.crawl()` ，將 orphan page + broken link 結果寫 Slack，不建新 DB 表 | 無 | 宮d份不要跟不上 |
| **L3-3** | `FeaturedSnippetDetector` + `CompetitorThreatDetector` 解耦：納入每週日完整籄範處理，不僅再 refresh 時才跑 | 無 | 目前僅在 refresh 時觸發 |
| **L3-4** | GSC Link Report：新增 `GSCClient.get_link_stats()` + 每週兩 sync job | L2-2/L2-3 已完成 | 其資訊對現有決策鏈無貢獫，尀開後才有實際用途 |

---

### 14.4 簡化版實作規格

#### L2-1 Publish Policy：只加兩個 DB 欄位

```python
# models/database.py — Project 表新增
auto_publish_enabled = Column(Boolean, default=False)
auto_publish_min_score = Column(Integer, default=85)

# strategic_agent.py — _execute_generate() 內
auto = project.auto_publish_enabled and article.seo_score >= project.auto_publish_min_score
if auto:
    await publisher.publish(article)  # 直接發布
else:
    article.status = "approved"        # 等待人工或排程發布
```

不需要 `risk_profile`、`site_profile`、`publisher_capabilities` 矩陣。不同站點由專案管理元在 Admin UI 設定這兩個欄位即可。

#### L2-4 Render Verification：一個函式 + 一個 cron job

```python
# tools/render_verify.py （新增一個檔案）
async def verify_rendered_html(article_url: str, expected: dict) -> list[str]:
    """httpx GET → BeautifulSoup，回傳缺失清單"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(article_url, timeout=15)
    soup = BeautifulSoup(resp.text, "html.parser")
    issues = []
    if not soup.find("title"): issues.append("missing_title")
    if not soup.find("meta", {"name": "description"}): issues.append("missing_meta_description")
    if not soup.find("h1"): issues.append("missing_h1")
    if not soup.find("script", {"type": "application/ld+json"}): issues.append("missing_schema")
    if not soup.find("link", {"rel": "canonical"}): issues.append("missing_canonical")
    return issues

# scheduler.py — 新增 job
async def run_render_verification():
    """10:00 每日：檢查前 2 小時內發布的文章"""
    cutoff = datetime.utcnow() - timedelta(hours=2)
    articles = session.query(Article).filter(
        Article.published_at >= cutoff,
        Article.publish_url != ""
    ).all()
    for article in articles:
        issues = await verify_rendered_html(article.publish_url, ...)
        if issues:
            notify_slack(f"[Render Verify] {article.title} 缺少: {issues}")
```

不需要 `verifying` 狀態、不需要 `site_issues` 表、不需要 `SiteFixAgent`。Slack 告警配上 Admin UI 父星就能處理。

---

### 14.5 完成後的閉環時序

```
每日 03:00   sync_gsc_all_projects
每日 03:30   sync_ga4_all_projects
每日 04:00   backfill_action_outcomes
              check_scheduled_publishes          ← L1-5 新增
每週一 04:30  run_competitor_serp_check
每週日 04:30  run_site_crawl → Slack 告警  ← L3-2 可選
每週一 05:00  run_attribution_engine
每週一 05:30  check_refresh_triggers
每日 08:00   run_auto_pipeline
              → Strategic Agent（骚有 cannibalization + cluster gaps）
              → generate / refresh / alert / optimize_meta
每日 10:00   run_render_verification         ← L2-4 新增
每日 22:00   check_ranking_drops
每月 1 日  sync_keyword_trends              ← L1-6 新增
每月 1 日  build_topic_clusters             ← L3-1 可選
每月 1 日  run_l1_pattern_analysis
每月 1 日  run_l2_roi_analysis
週天 08:00  run_weekly_reflection
週天 09:00  send_weekly_report
```

---

### 14.6 收斂後的覆蓋率評估

| 狀態 | 覆蓋率 | 說明 |
|------|--------|------|
| 現況 | ~65% | 內容生產成熟，學習機制完整；發布後對預封閉 |
| **Layer 1 完成後** | **~73%** | 自蝕防護、叢集選題、排程發布、趨勢輸入進决策層 |
| **Layer 1+2 完成後** | **~82%** | 發布後驗證、CTR 修復、內鉤執行、發布政策標準化 |
| Layer 1+2+3 全部可選 | ~86% | 定期技術审計、Featured Snippet 追蹤、外鉤識別 |
| 將永遠不在範圍內 | ~14% | 外鉤經營、多語 SEO、Server Log、Local SEO、AI Overview |

**Layer 1 + Layer 2 加起來約 10 個工作日，全部是對現有架構的游絃層修補，不引入任何新系統。**
