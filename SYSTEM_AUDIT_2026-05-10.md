# ContentFlow 系統深度診斷報告

**診斷日期：** 2026-05-10  
**診斷方式：** 完整原始碼靜態分析（agents/、tools/、models/、scheduler.py）  
**系統狀態：** 生產中（Linode 172.235.216.10），23 篇已發布，315 tests passed

---

## 摘要

本系統在設計概念上是完整的，但因長期迭代修補，積累了若干**邏輯衝突**、**死程式碼**與**數據準確性問題**。  
以下依嚴重性分級列出 12 個問題，其中 3 個屬於**立即影響生產品質的高優先問題（P0/P1）**。

## 2026-05-10 修復狀態

- P0-1 已修正：`ArticleTask.target_word_count` 改為 1200，Strategic generate 明確傳入 1200。
- P0-2 已修正：`strategy_agent` 不再自行推導 `target_word_count`，字數來源統一。
- P1-1 已修正：AttributionEngine 不再對 28 天聚合 GSC 列做加總。
- P1-2 已修正：SEO Check 改用中文字數判斷，不再吃 Markdown 符號膨脹。
- P1-3 已修正：Strategic rank 分群改為 publish_url path / slug 精準匹配。
- P2-1 已修正：`planning_agent.generate_content_plan()` 已接回 daily strategic 主流程。
- P2-2 已緩解：新增 `run_article_strategy_agent` / `run_daily_strategy_agent` alias，降低命名混淆；未做破壞性 rename。
- P2-3 已修正：Strategic refresh action 會執行完整 `run_refresh_pipeline(generate_content=True, publish=True)`。
- P2-4 已修正：自動補日曆時會優先趨勢上升與高熱度關鍵字。
- P2-5 已修正：daily strategic 前會先跑 planning/cluster 更新，不再讀取陳舊 cluster gap。
- P3-1 已修正：GBP sync 新增 `GBP_SYNC_ENABLED` feature flag；Backlinks 既有 flag 保持可選。
- P3-2 已修正：新增 Admin chat API 測試，補上登入保護與成功路徑驗證。

---

## 高優先問題（P0 — 立即影響產出品質）

### P0-1：字數控制三路衝突，修改效果只有一半

**問題描述：**  
本次 session 修改了 `writing_agent.py` 的預設值為 `target_word_count: int = 1200`，但此修改對 **生產主流程無效**。

**數據流追蹤：**

```
strategic_agent.py line 949:
    task = ArticleTask(task_id=run_id, title=art_title, keywords=[art_kw])
    # ← 未傳 target_word_count，使用 schemas.py 預設值

schemas.py line 135:
    target_word_count: int = 3000      ← 預設 3000！

orchestrator.py line 229:
    target_word_count=task.target_word_count   ← 把 3000 傳給 writing_agent

writing_agent.py line 755:
    target_word_count: int = 1200      ← 這個 1200 被 3000 覆蓋
```

**影響：**  
透過 Scheduler 自動產出的文章（`run_auto_pipeline` → `strategic_agent`），實際收到的 `target_word_count=3000`，加上 `max_chinese = 3000 + 300 = 3300`，硬截斷閾值變成 3,300 字，與目標 1,200 字相差甚遠。手動呼叫 API 也一樣。

**三處需要一致的值：**

| 位置 | 目前值 | 應改為 |
|------|--------|--------|
| `schemas.py` `ArticleTask.target_word_count` | 3000 | 1200 |
| `strategic_agent.py` `ArticleTask(...)` | 未傳（用預設 3000） | 明確傳入 1200 |
| `writing_agent.py` 預設 | 1200 ✅ | 已正確 |

**修復方案（2 行）：**
```python
# schemas.py
target_word_count: int = 1200   # 從 3000 改為 1200

# strategic_agent.py line 949
task = ArticleTask(task_id=run_id, title=art_title, keywords=[art_kw],
                   target_word_count=1200)
```

---

### P0-2：strategy_agent 字數決策邏輯會再度覆蓋為 2,500

**問題描述：**  
`strategy_agent.py` 的 `to_strategy_context()` 方法從 `writing_architecture` 字串匹配數字來決定 `target_word_count`，預設為 2,500。此值被放入 `strategy_context` dict，但 **orchestrator 未使用這個值**，它使用的是 `task.target_word_count`（如上所述為 3000）。

所以系統有兩個都不一致且都沒有被真正採用的字數設定：

```python
# strategy_agent.py to_strategy_context()
wc = 2500                              # 預設
if "2000" in arch: wc = 2000          # 文字匹配，不可靠
elif "3000" in arch: wc = 3000
elif "4000" in arch or "長" in arch: wc = 4000
elif "1500" in arch: wc = 1500
```

這個邏輯**完全不會用到 SERP 分析結果**，只是在猜 LLM 輸出的文字裡有沒有出現特定數字。而且 `orchestrator.py` 記錄 log 用到了它（line 203），但寫文章時根本沒傳這個值給 writing_agent。

**修復方案：** 刪除 `to_strategy_context()` 中的 wc 推導邏輯，統一由 `ArticleTask.target_word_count` 控制，`strategy_context` 不再有 `target_word_count` 欄位。

---

## 中優先問題（P1 — 數據準確性）

### P1-1：SEORanking 數據膨脹 28 倍（已知問題）

**問題描述：**  
`gsc.py` 的 `sync_to_db()` 每次拉取 **28 天聚合數據**（GSC API 的 startDate = 28 天前），並將 `tracked_date=today` 寫入資料庫。每天執行一次，所以第 28 天後，同一關鍵字有 28 筆 row，每筆的 `impressions` 都是「過去 28 天的聚合值」。

`analytics_agent.py` 計算 `impressions_28d` 時：
```python
impressions_28d = sum(r.impressions or 0 for r in recent_rows)
# recent_rows = 過去 28 天的所有 row（28 筆）
# 每筆的 impressions 本身就是 28 天的聚合 → 實際膨脹 28 倍
```

**影響：** `AttributionEngine.get_article_performance()` 回傳的 impressions_28d 和 clicks_28d 嚴重失真，`_compute_grade()` 中的 `impressions < 10` 判斷幾乎永遠不會觸發。Learning Agent 的 ROI 分析也受波及。

**修復方案：**  
選一：改存**每日差量**（拉 start=yesterday, end=yesterday）  
選二：`sync_to_db` 繼續存 28 天聚合，但 analytics_agent 改為只取**最新一筆**（`latest = recent_rows[0]`），不做 SUM。

---

### P1-2：SEO Check Agent 的 word_count 判斷基準不一致

**問題描述：**  
`seo_check_agent.py` 的通過條件：
```python
add_check("word_count_ok", draft.word_count >= 1200, ...)
```

`draft.word_count` 的計算：
```python
# writing_agent.py
word_count = len(full_content)     # 字符數，含 Markdown 標記
```

`len("## 標題\n\n**骨刺**的成因...")` 包含 `##`、`**`、`\n` 等標記符號，一篇實際 900 中文字的文章，`len()` 可能回傳 1,200 以上，**輕易通過 1,200 字的門檻但實際內容不足**。

`_count_chinese_chars()` 函式（本次新增）才是正確的計算方式，但 seo_check_agent 沒有使用它。

---

### P1-3：strategic_agent 的排名比對用 slug 模糊匹配，可靠性低

**問題描述：**  
`_collect_project_context()` 中文章分群邏輯：
```python
latest_rank = session.query(SEORanking).filter(
    SEORanking.landing_page.contains(art.slug) if art.slug else False,
).order_by(SEORanking.tracked_date.desc()).first()
```

問題：
1. 若 `art.slug` 為空字串（未填寫），條件變 `False`，文章永遠落入 F 群
2. `.contains(art.slug)` 是 SQL LIKE `%slug%`，可能匹配到不相關的 URL（例如 slug="骨刺" 會匹配任何含「骨刺」的 URL）
3. N+1 查詢問題：每篇文章一次 DB 查詢，23 篇 = 23 次額外查詢（日後文章增多會更顯著）

---

## 中優先問題（P2 — 架構合理性）

### P2-1：planning_agent.py 是完整但從未被呼叫的死程式碼

**問題描述：**  
`planning_agent.py` 有 130 行的 `generate_content_plan()` 函式，規劃了完整的 7 優先序推薦邏輯（cannibalization → refresh → 關鍵字缺口 → P11-P20 → CTR 低 → 6 個月 + P30 → 表現差）。

但系統內**沒有任何地方 import 或呼叫這個函式**。  
Scheduler 沒有它的 job，strategic_agent 沒有用它，admin UI 也沒有觸發它的按鈕。

這些推薦邏輯比 strategic_agent 的 LLM prompt 更可靠（規則引擎 vs 語言模型），但一直沒有被啟用。

**影響：** 含 Cannibalization 偵測、P11-P20 Refresh 建議都在這裡有完整邏輯，strategic_agent 的 LLM 需要自己「猜」這些應該優先建議什麼。

---

### P2-2：兩個名稱相似的 Agent 職責完全不同，但沒有任何區分文件

**問題描述：**  

| 檔案 | 職責 | 呼叫時機 |
|------|------|----------|
| `strategy_agent.py` | SERP 分析 → 個別文章的寫作策略報告（intent、角度、FAQ） | 每次 pipeline 的 strategy_node |
| `strategic_agent.py` | 每日整體決策引擎（選題、Refresh、Alert） | 每日 08:00 排程 |

差一個字，功能天壤之別。新開發者或 AI 助手極易混淆，維護風險高。

---

### P2-3：Content Refresh 是 P1-P20 最重要的 ROI 動作，但沒有自動執行機制

**問題描述：**  
`check_refresh_triggers`（每週二）只負責**找出候選**並記錄到 KnowledgeEntry，不會啟動實際的 Refresh Pipeline。`strategic_agent` 的 `refresh` action 雖然會在每日自動流程中執行，但目前只做到 `RefreshDiffAnalyzer.analyze()`、更新 `last_refresh_date` 與記錄 `ActionOutcome`；它**不會**呼叫 `run_refresh_pipeline()` 去產生補丁內容、重跑 SEO 檢查或發布更新。完整 Refresh Pipeline 目前仍只有 Admin UI 的手動 refresh 路徑會執行。

實際上，P11-P20 的文章只要小幅 Refresh 就可能進首頁，是投入產出比最高的動作，但系統的「自動」在此斷裂了。

---

### P2-4：GSC 機會詞 → 文章生成的鏈路在關鍵一步有缺口

**問題描述：**  
Strategic Agent 確實有讀取 `keyword_trends`（熱度上升的關鍵字）和 `seasonal_opportunities`（季節高峰詞），並在 prompt 中要求 LLM 將這些納入 generate 計畫。

但問題是：generate action 需要 `calendar_id`，而季節性機會詞可能根本不在 ContentCalendar 中。

`_collect_project_context()` 有自動補充日曆的邏輯（`MIN_CALENDAR_BUFFER=5`），但這個補充只根據 `Keyword.search_volume` 排序，**不使用 `trend_direction` 或 `seasonal_opportunities`**，使得季節性偵測的設計意圖在執行端沒有確實落地。

---

### P2-5：cluster_agent 無排程，strategic_agent 讀到的 cluster_gaps 永遠是舊的

**問題描述：**  
Strategic Agent 讀取：
```python
cluster_gaps_raw = session.query(ClusterMember, TopicCluster)
    .filter(ClusterMember.article_id == None)  # 找出缺口
```

但 `TopicCluster` 和 `ClusterMember` 的資料來自 `cluster_agent.py` 的分析，而 `cluster_agent` 沒有自動排程——它需要從 Admin UI 手動觸發或從 Topic Map 頁面運行。新發布的文章不會自動更新 cluster 成員關係。

---

## 低優先問題（P3 — 資源配置與維護性）

### P3-1：GBP、反向連結、L1/L2 在現階段投入產出比偏低

**GBP（Google Business Profile）：** `sync_gbp_metrics` 目前是**每天 03:50 執行**，資料會存入 DB，但在目前程式碼中看不到後續決策邏輯或後台頁面對這批資料的消費。對以內容 SEO 為主的站台（goodbone.com.tw）而言，現階段投入產出比偏低。

**反向連結（DataForSEO）：** `sync_backlink_metrics` 每週二執行，需要付費 API。23 篇文章的新站台，反向連結數量極少，監控意義幾乎為零。適合等站台到達 100 篇後再啟用。

**L1/L2 學習分析：** `run_l1_pattern_analysis` 和 `run_l2_roi_analysis` 每月一次，需要足夠的樣本才能產出統計意義的洞察。23 篇文章的樣本，平均 `evidence_count` 遠低於 `_VERIFIED_THRESHOLD=5`，大多數知識條目會停在 `unverified` 等級。

---

### P3-2：chat_agent.py 已接入 Admin，但測試與運維成熟度不足

**問題描述：**  
`chat_agent.py` 並非死碼，已接入 Admin UI：`/admin/chat` 會渲染聊天頁面，`/admin/api/chat` 會呼叫 `chat_agent.chat()` 執行對話。  
目前真正的問題不是「是否整合」，而是**測試與運維成熟度不足**：這個介面已有登入保護，但在測試目錄中看不到對應的路由或 agent 整合測試，也缺少失敗率、操作審計與權限邊界的額外驗證。

---

## 彙總優先序

| 優先級 | 問題 | 可修復難度 | 影響 |
|--------|------|-----------|------|
| **P0-1** | 字數控制三路衝突（schemas + strategic_agent + writing_agent） | 低（改 2 行） | 所有自動產出文章字數失控 |
| **P0-2** | strategy_agent 字數推導邏輯不可靠 | 低（刪除 wc 推導） | 字數設定混亂 |
| **P1-1** | SEORanking 數據膨脹 28 倍 | 中（改 analytics_agent 取法） | 歸因分析、ROI 計算嚴重失真 |
| **P1-2** | word_count 用字符數而非中文字數 | 低（改用 _count_chinese_chars） | SEO 評分的字數關卡失效 |
| **P1-3** | 排名比對用 slug 模糊匹配 | 中（改精確查詢） | 文章排名分群結果不可信 |
| **P2-1** | planning_agent.py 死程式碼 | 低（接入 scheduler） | 浪費已有的推薦邏輯 |
| **P2-2** | 兩個 Agent 名稱混淆 | 低（rename 其中一個） | 維護風險 |
| **P2-3** | Refresh 自動流程只做到分析，不是完整 Pipeline | 中（補齊 strategic refresh 執行鏈） | 最高 ROI 動作尚未自動完成補文與發布 |
| **P2-4** | GSC 機會詞補充日曆不用 trend 排序 | 低（改排序邏輯） | 季節性佈局邏輯未落地 |
| **P2-5** | cluster_gaps 無自動更新 | 中（加排程） | 叢集缺口數據過時 |
| **P3-1** | GBP/反向連結/L1-L2 資源錯配 | 低（暫停 job） | API 成本浪費 |
| **P3-2** | chat_agent.py 缺少測試與運維護欄 | 中（補測試與審計） | 對話操作風險難評估 |

---

## 立即可執行的修復（不超過 30 分鐘）

**修復 P0-1**（最重要）：

```python
# 1. schemas.py — 改 ArticleTask 預設值
target_word_count: int = 1200   # 原為 3000

# 2. strategic_agent.py line 949 — 明確傳入
task = ArticleTask(
    task_id=run_id,
    title=art_title,
    keywords=[art_kw],
    target_word_count=1200,   # 新增這行
)
```

**修復 P1-2**（5 分鐘）：

```python
# seo_check_agent.py — 改用中文字數
from .writing_agent import _count_chinese_chars
chinese_count = _count_chinese_chars(draft.content_markdown)
add_check("word_count_ok", chinese_count >= 800,
          f"文章中文字數 {chinese_count} 字，建議至少 800 字", weight=1.0)
```

**修復 P2-4**（5 分鐘）：

```python
# strategic_agent.py _collect_project_context() 的關鍵字補充排序
candidate_keywords = (
    session.query(Keyword)
    .filter(Keyword.project_id == project_id, Keyword.search_volume > 0)
    .order_by(
        (Keyword.trend_direction == "up").desc(),   # 趨勢上升優先
        Keyword.trends_score.desc(),                # 熱度分數次之
        Keyword.search_volume.desc(),               # 搜尋量再次
    )
    .limit(50)
    .all()
)
```

---

## 系統設計的根本限制（非 bug，是架構取捨）

1. **技術 SEO 的監控與修復分離：** 系統能偵測 CWV/索引覆蓋率，但無法自動修復（需要前端控制權），這是正確的邊界。

2. **長尾關鍵字依賴人工匯入：** 系統沒有主動挖掘長尾詞的機制（如 Google Autocomplete API 或 PAA 批量挖掘），新選題仍需人工研究後匯入 Excel。

3. **LLM 決策的不確定性：** Strategic Agent 的 generate/refresh 決策透過 LLM（gpt-4o-mini），prompt 中的規則有時會被忽略或解讀錯誤，`_normalize_plan_result()` 是目前唯一的防線（限制 generate 配額）。規則引擎（planning_agent.py）被閒置就是最大的反諷。

4. **多租戶架構的維護成本：** 目前只有 1 個 project，但 DB schema 和程式碼都有 project_id 篩選，維護成本為單站台 2 倍，ROI 要等第 2 個客戶才能體現。
