# ContentFlow 產品缺口完整診斷（技術面 + SEO 實務面）

- 診斷日期：2026-05-23
- 診斷範圍：文章生成主流程、策略排程、自動發布、SEO 數據回饋、內容品質把關
- 診斷方法：程式碼靜態審查（agents/tools/scheduler/admin/models）+ 現行文件比對

## 稽核覆蓋聲明（rev2）

- 本文件初版以主流程關鍵模組為主，非逐行讀完整 repo。
- 2026-05-23 第二輪補稽核已新增全域搜尋與交叉驗證，覆蓋：
  - 生成入口：`api.py`、`admin/app.py`、`agents/strategic_agent.py`
  - 發布入口：`scheduler.py`、`publishers/*`
  - 風險欄位：`factcheck_flags_json` 相關讀取點
  - 測試證據：`test_phase_gate_c.py`、`test_strategic_agent.py` 等
- 補稽核後修正一個關鍵判讀：
  - `review_required` 在本系統不是「絕對不可發布」狀態；存在「低風險、近門檻補救後升級並發布」的設計路徑。
  - 因此本文件將該議題定義為「產品策略風險與 gate 定義不夠嚴格」，而非單純程式 bug。

---

## 一頁結論

ContentFlow 已具備「可運作的自動內容管線」，但距離「可穩定商業化擴張」仍有幾個關鍵缺口：

1. 內容真實性把關存在，但在自動發布鏈路上有繞過風險（高風險）。
2. SEO 分數機制偏重格式與規則，對「搜尋意圖命中」與「內容可信度」的實際表現仍偏弱。
3. 數據回饋鏈路可用，但資料模型仍以窗口聚合為主，限制了精細歸因與實驗能力。
4. 系統預設語系/市場偏台灣繁中，跨語系與跨市場可複製性不足。

---

## 診斷評分（0-5）

- 技術穩定度：3.8/5
- 內容可信度控制：2.9/5
- SEO 實戰成熟度：3.2/5
- 可規模化產品化：3.0/5
- 可觀測與可驗證性：3.4/5

---

## A. 技術面缺口（Architecture / Reliability / Data / Risk）

## A1. 自動發布可能繞過 FactCheck 結果（P0）

- 問題：`run_factcheck_agent` 會把有風險文章設為 `review_required`，但目前發布策略允許「review_required 文章在特定條件下補救升級後發布」，且 strategic 自動發布條件仍以 `auto_publish_enabled + seo_score` 為核心。
- 影響：若產品策略目標是「任何 factcheck 風險都必須人工審核」，現行邏輯會與此目標衝突。
- 證據：
  - `src/contentflow/agents/factcheck_agent.py`：`draft.status = REVIEW_REQUIRED if needs_review else APPROVED`
  - `src/contentflow/agents/strategic_agent.py`：`auto_pub = project.auto_publish_enabled and seo_score >= min_score`
  - `src/contentflow/scheduler.py`：存在 review_required 補救流程（近門檻 + 無 factcheck 風險可升級）
  - `tests/test_phase_gate_c.py`：測試明確驗證 review_required 補救升級到 approved
- 建議：
-  - 若定位為高信任內容平台：自動發布 gate 增加硬條件 `status == approved` 且 `factcheck_flags_json == []`。
  - 若要保留補救策略：需在產品文件明確定義「可自動補救」與「必須人工審核」的界線，並提供可追溯審計欄位。
  - 發布前加一個最終 `publish_safety_gate()`（不可被跳過）。

## A2. FactCheck 風險旗標落庫鏈路不清晰（P0）

- 問題：有 `factcheck_flags_json` 欄位，也有 scheduler 以此判斷風險，但主流程中未見明確、穩定的寫回路徑。
- 影響：若旗標未寫回，排程補救與發布保護會失效或不準。
- 證據：
  - `src/contentflow/models/database.py`：`factcheck_flags_json` 欄位存在。
  - `src/contentflow/scheduler.py`：`_article_has_factcheck_risk()` 依賴此欄位。
- 建議：
  - 在 orchestrator 完成後固定 serialize `fact_check_items -> factcheck_flags_json`。
  - 新增一致性測試：`draft.fact_check_items` 與 DB 欄位內容一致。
  - 在 strategic generate / scheduler publish 前新增 assert 或監控事件，若 `factcheck_flags_json` 缺失或格式錯誤直接阻擋發布。

## A3. 無 project_id 時 PubMed 預設開啟（P1）

- 問題：research agent 在 `use_pubmed is None` 且沒有 `project_id` 時預設 `True`。
- 影響：非醫療主題會增加噪音查詢與成本，且不一定提升品質。
- 證據：`src/contentflow/agents/research_agent.py`（`elif use_pubmed is None: use_pubmed = True`）
- 建議：
  - 預設改成 `False`，或改為 `policy_required_only`。
  - 若未提供 project context，採用 `domain=general` 的低風險模式。

## A4. GSC 資料模型偏「窗口快照」，不利精細歸因（P1）

- 問題：GSC 同步預設抓 28 天窗口，`tracked_date=today` 落庫；analytics 目前取最新一筆已避免重複加總，但仍是重疊窗口資料。
- 影響：
  - 不利做日級趨勢與因果分析。
  - A/B 測試和更新效果回溯粒度不足。
- 證據：
  - `src/contentflow/tools/gsc.py`：`start=today-28d, end=yesterday`，寫入 `tracked_date=today`。
  - `src/contentflow/agents/analytics_agent.py`：以最新列代表 28d 表現。
- 建議：
  - 增加「daily incremental」資料表或欄位（至少 clicks/impressions 日級）。
  - 保留窗口快照作 dashboard，但歸因改用日級明細。

## A5. 多語系與多市場支援仍不足（P1）

- 問題：策略與寫作 prompt 強烈綁定繁中台灣語境。
- 影響：跨國客戶導入時，語氣、SERP 解讀與內容樣式失真。
- 證據：
  - `strategy_agent.py`：system prompt 明確「專精繁體中文市場」。
  - `project_context.py`：預設 `locale=zh-tw`, `serp_gl=tw`, `serp_hl=zh-tw`。
- 建議：
  - 將語系策略模組化：`language_pack + market_pack`。
  - Prompt 改為依 project locale 動態載入。

## A6. 發布與品質 gate 職責耦合過深（P2）

- 問題：strategic_agent 同時負責生成、狀態決策、對外發布，責任過重。
- 影響：調整任一 gate 會連動多處邏輯，回歸風險高。
- 建議：
  - 拆為：`content_pipeline`、`quality_gate`、`publisher_orchestrator` 三層。
  - 發布前一律走統一 `ready_to_publish` 狀態機。

---

## B. SEO 實務面缺口（Strategy / Content / SERP Performance）

## B1. SEO 評分偏規則合規，對「真實搜尋表現」關聯仍弱（P1）

- 問題：目前 SEO Check 以結構規則為主（關鍵字、meta、格式），對 intent match、信息增量、競品差異深度的評估較弱。
- 影響：容易出現「分數高但 CTR/停留不佳」的內容。
- 證據：`src/contentflow/agents/seo_check_agent.py`（規則引擎導向）
- 建議：
  - 增加結果導向特徵：標題可點擊性、snippet entropy、query coverage。
  - 將 GSC 低 CTR query 回灌到 rewrite prompt 作硬約束。

## B2. 幻覺防線有，但仍屬「事後審核型」而非「生成即對齊證據」（P1）

- 問題：目前是 research 注入 + factcheck 檢查；缺少 claim-level 引用綁定（段落內聲明對應來源）。
- 影響：即使被標 review_required，也增加人工修稿成本與延遲。
- 證據：
  - `writing_agent.py`：使用研究摘要，但未建立 claim->citation 結構。
  - `factcheck_agent.py`：AI 後驗檢查為主。
- 建議：
  - 生成階段採 `claim registry`：每個關鍵聲明需附來源 ID。
  - 無來源聲明在 publish gate 直接 fail。

## B3. 非醫療領域 evidence connector 不足（P1）

- 問題：醫療可用 PubMed，其它領域多為 none/manual reference。
- 影響：法律/財務/科技內容的可信度與可驗證性不一致。
- 建議：
  - 法律：法規/判決資料源。
  - 財務：公開財報與監理資料源。
  - 科技：官方文件與 release notes source pack。

## B4. 內容刷新（Refresh）策略與執行閉環仍可再強化（P2）

- 問題：有 refresh pipeline 與排程補救機制，但「何時刷新、刷新後如何驗證 uplift」仍偏規則化，實驗設計不足。
- 影響：投入在 refresh 的 ROI 可能不穩定。
- 建議：
  - 建立 refresh 實驗框架：前後 14/28 天 uplift、對照組、停損條件。
  - 對 P11-P20 與 high-impression low-CTR 做不同策略模板。

## B5. 內部連結建議有產出，但自動注入與效果驗證不足（P2）

- 問題：已生成 internal link suggestions，但是否被採納與帶來何種排名效益未形成閉環。
- 影響：Topic authority 建設速度慢。
- 建議：
  - 導入「建議採納率」與「採納後排名變化」追蹤。
  - 對高關聯 anchor 提供半自動套用機制。

## B6. 站點層 Technical SEO 已有檢查，但「內容層 entity/semantic SEO」仍薄（P2）

- 問題：目前重點在 sitemap/indexing/health；內容語意層（entity coverage、同義詞意圖網、SERP feature 對位）仍不夠強。
- 影響：在競爭詞上較難突破。
- 建議：
  - 建立 entity graph（每篇文章的核心實體、關聯實體、缺口實體）。
  - 擴充 SERP feature 策略：FAQ、HowTo、比較表、定義卡片等。

---

## C. 產品化缺口（對外商業化）

## C1. 品質 SLA 未產品化（P1）

- 問題：雖有流程與分數，但缺少對外可承諾的品質 SLA（例如 factual risk rate、publish pass rate、revision turnaround）。
- 影響：B2B 客戶難以信任與續約評估。
- 建議：
  - 導出月報 SLA 指標並上 dashboard：
    - factual flags / 1k words
    - auto-publish safe rate
    - 28d CTR uplift median

## C2. 缺乏「失敗可解釋」與「人工接手 UX」設計（P2）

- 問題：review_required 後的處理仍偏工程資料視角。
- 影響：非技術審稿者修稿效率低。
- 建議：
  - 將 factcheck issues 轉成可操作清單（問題句、建議改法、可替代來源）。
  - 一鍵 re-run 指定段落而非整篇重跑。

---

## D. 優先修復清單（建議 30/60/90 天）

## D+30（先補風險）

1. 自動發布 gate 納入 factcheck 硬條件。
2. 補齊 `factcheck_flags_json` 穩定落庫與一致性測試。
3. `use_pubmed` 預設改為 context-aware 安全值。
4. 增加 publish 前最終 `quality_gate` 統一入口。

## D+60（補數據與 SEO 成效）

1. GSC 新增日級資料，保留窗口快照雙軌。
2. SEO Check 引入結果導向特徵（CTR/query coverage）。
3. 建立 refresh uplift 觀測與停損機制。
4. 內部連結採納率與效果追蹤落地。

## D+90（補可規模化能力）

1. 多語系/多市場 prompt pack。
2. 非醫療 evidence connector 擴充。
3. claim-level citation 機制（生成即綁證據）。
4. 對外 SLA 指標與客戶可視報表。

---

## E. 總結

這套產品的核心能力已經足夠「持續生產內容」，但要成為高信任、可大規模商業化的 SEO AI 平台，下一階段重點不在「再多生幾篇」，而在：

1. 把品質 gate 從「流程存在」提升為「不可繞過」。
2. 把 SEO 評分從「格式合規」提升為「對實際排名與 CTR 負責」。
3. 把資料層從「可看 dashboard」提升為「可做可靠因果分析」。

只要先補齊 P0/P1 缺口，這套系統就能從「可運作」進一步走到「可放心對外承諾成效」。
