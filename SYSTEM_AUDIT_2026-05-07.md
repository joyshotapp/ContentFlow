# ContentFlow 系統深度盤點

更新日期：2026-05-08

## 範圍與方法

本文件已從「原始審計紀錄」更新為「審計後修復結果」。

本次最終確認包含四個面向：

- 本機工作區程式碼與文件
- 本機完整測試結果（`python -m pytest -q`）
- 生產伺服器 `172.235.216.10` 實際運行狀態
- 生產資料庫中與本次修復直接相關的欄位與佇列資料

## 結論

本輪審計中可由程式、部署流程與資料修補直接處理的問題，已全部完成並驗證。

最新已驗證狀態：

- 本機測試：`315 passed`
- production：`site` / `scheduler` / `db` healthy，`/health` 與 `/version` 正常回傳最新 build metadata（`build_time=2026-05-08T01:41:59Z`），對外首頁 / admin / robots / sitemap 正常
- production 資料：`published_missing=0`、`invalid_planned=0`
- production 排程：已改為獨立 `scheduler` service；`/health` 以共享 heartbeat 驗證 scheduler 活性，不再只看 PID；`run_weekly_reflection` 已於 production 手動實測成功，LLM 失敗時 fallback 仍可完成產出
- deploy 腳本：已支援 `docker compose` / `docker-compose`、`.env.prod` BOM/CRLF 清洗、以及沒有 `rsync` 時的 `tar + scp` fallback

## 修復結果總表

### 已修復

1. 生產版本缺乏可追蹤性
狀態：已修復
結果：新增 build metadata，`/health` 與 `/version` 會回傳 `build_commit`、`build_time`、`build_source`；部署腳本也會在 dirty working tree 時標記 `-dirty`。

2. `send_weekly_report` 舊 bug 已在線上發生過
狀態：已修復
結果：production 已重新部署到包含修正版 scheduler 的版本，健康檢查正常。

3. Admin 弱預設密鑰 fallback
狀態：已修復
結果：未設定 `API_SECRET_KEY` 時會拒絕登入並回傳 503，不再 fallback 到弱密碼；session secret 也不再固定使用 `dev-secret-change-me`。

4. README 測試與架構描述失真
狀態：已修復
結果：README 已更新為目前架構、部署與測試現況，測試數已同步為 315。

5. 本機測試環境可重現性不足
狀態：已修復
結果：`agentops` 改為 optional dependency，不再阻塞 pytest 收集；`tests/conftest.py` 也補上條件式 `pytest_asyncio` 載入與主執行緒 event loop 自動重建，已消除 Python 3.13 / Windows 下的 plugin 與 loop 問題；本機完整測試已通過。

6. `published_at` 缺漏
狀態：已修復
結果：production 歷史缺漏資料已回填，目前 `published_missing=0`；後續發布路徑也已統一寫入 `published_at`。

7. `planned` 佇列低品質題目
狀態：已修復
結果：production 既有異常資料已清理，且 admin/strategic 流程已加入 topic hygiene 驗證，避免再次進入佇列。

8. weekly reflection 長期零更新
狀態：已修復
結果：`reflect_weekly()` 現在在 LLM 失敗或輸出空更新時，會走更具體的 `_fallback_weekly_reflection()`，加入去重、平均 SEO、`review_required` backlog 與篇幅不足等規則；production 已於 2026-05-07 08:44 手動實測，Gemini 輸出解析失敗時仍成功寫入 fallback summary（`ReflectionLog#53`，summary 含平均 SEO 與 backlog 資訊）。

9. `review_required` 稿件沒有保守補救路徑
狀態：已修復
結果：`check_scheduled_publishes()` 現在會先掃描接近門檻、且無 factcheck 風險的 `review_required` 文章，必要時補跑一次低風險 SEO QA 後再重新評分；同時修正 production 驗證時發現的 `import re` 漏引入問題，避免 secondary keyword 字串解析在 production 失敗。production 已於 2026-05-07 08:47 手動跑完整 rescue 流程，4 篇接近門檻文章皆成功完成重新檢查與 SEO QA，但分數仍未達 85，因此保留 `review_required`，未發生誤升級發布。

10. Chroma 持久化設定不夠顯性
狀態：已修復
結果：`Settings` 已明確提供 `CHROMA_PERSIST_DIR`，compose / env example 已帶入，KB 程式也改為直接讀顯式設定欄位。

11. repo 內未納管的一次性腳本
狀態：已修復
結果：本次調查留下的 one-off debug / cleanup 腳本已移除，避免隱性操作知識殘留在工作樹。

12. pytest warning 殘留
狀態：已修復
結果：測試中 `Query.get()` legacy 用法已改掉，第三方 `pkg_resources` 類 warning 已在 pytest 設定中過濾；`pytest_asyncio` plugin double registration 與 `There is no current event loop` 也已一併修正；目前完整測試輸出為乾淨全綠。

13. production nginx 仍代理到舊的 `/site` 子路徑
狀態：已修復
結果：production nginx 已改為直接代理到 app root 路由，`https://goodbone.com.tw/`、`/admin/login`、`/robots.txt`、`/sitemap.xml` 皆實測回 200，`http://goodbone.com.tw/` 會 301 導向 HTTPS。

14. production scheduler 健康檢查存在假陽性，且多 worker 內嵌排程有停滯風險
狀態：已修復
結果：2026-05-08 重新稽核時發現 `site` container 與 `/health` 仍顯示正常，但最近 12 小時 `SchedulerLog` 為 0，代表原本只依賴 `/tmp/contentflow_scheduler.pid` 與 `os.kill(pid, 0)` 的檢查會把「持鎖 worker 還活著」誤判成「scheduler 仍在正常 dispatch job」。現已改為將 scheduler 拆成獨立 `scheduler` service，`site` 不再內嵌排程；同時新增 `scheduler_heartbeat.json` 與每分鐘 heartbeat job，`/health` 改為檢查 heartbeat 新鮮度。production 已於 2026-05-08 01:50 驗證 `site` / `scheduler` / `db` 全部 healthy，`scheduler_reason=tick`、`scheduler_heartbeat_age_seconds=1.7`，確認排程 loop 持續運作。

### 已緩解，但屬架構或營運性議題

1. 生產不是 git repository
狀態：已緩解
說明：目前仍採檔案式部署，不是 git-based release；但 build metadata 與部署腳本已足以追蹤實際上線版本。若要徹底改成 git/tag/release 流程，屬部署架構升級，不是 hotfix。

2. 生產 image 偏重
狀態：已部分改善
說明：已移除 `agentops` 的強制安裝，且 production 現已拆成 `site` 與 `scheduler` 兩個 service，消除了「多 worker web process 內嵌 scheduler」的主要風險。不過兩者仍共用同一個 image 與大部分 pipeline 依賴；若要真正大幅瘦身，仍需進一步拆 image 與執行環境。

3. production 單租戶，無法證明多租戶真實運行
狀態：無法以程式碼單獨消除
說明：程式碼與測試可支援多租戶，但 production 目前只有單一專案資料。這需要真實第二租戶或專門 staging 驗證，不能靠單次 hotfix 自動完成。

4. `review_required` 文章仍有存量
狀態：已部分改善
說明：程式已新增保守補救路徑，且 production 手動驗證已確認該路徑可完整執行；但 production 目前仍有 8 篇 `review_required`，最高分 84，尚未滿足 85 的自動發布門檻。這屬內容門檻與營運策略，不宜用 hotfix 強行發布。

5. weekly reflection 產出品質仍偏保守
狀態：列為營運性待辦
說明：排程本身正常，且 production 已於 2026-05-07 手動驗證 fallback 可在 LLM 解析失敗時產出 summary；但實際新增 KB / writing rule 筆數仍可能因去重而維持 0，這仍屬 prompt 與策略品質議題，不是 job 故障。

6. build metadata 仍帶 `-dirty`
狀態：已知但不影響運作
說明：2026-05-08 這次熱修復已正確部署並驗證，但部署來源仍顯示 `34c77c0-dirty`，代表本輪修正尚未整理為乾淨 commit 後再重新部署。這不影響目前 production 運作，但會降低版本追蹤精確度。

## 驗證結果

- 本機：`python -m pytest -q` → `315 passed`
- production compose：`site` / `scheduler` / `db` 皆為 healthy
- production `/health`：回傳 `status=ok`、`db=ok`、`scheduler=running`，並帶 `scheduler_last_heartbeat`、`scheduler_heartbeat_age_seconds`、`scheduler_reason=tick`，最新 `build_time=2026-05-08T01:41:59Z`
- production `/version`：回傳最新 build metadata
- production 資料審核：`published_missing=0`、`invalid_planned=0`
- production 對外端點：`https://goodbone.com.tw/`、`/admin/login`、`/robots.txt`、`/sitemap.xml` 實測 200；`http://goodbone.com.tw/` 實測 301 → HTTPS
- production 排程稽核：`scheduler.py` 已確認包含 `import re` hotfix；`run_weekly_reflection` 已於 2026-05-07 08:44 手動實測成功，fallback summary 寫入 `ReflectionLog#53`；`check_scheduled_publishes` 已於 2026-05-07 08:47 手動完整跑完，backlog rescue 正常執行且未誤發佈未達標文章；2026-05-08 已完成 `site` / `scheduler` service 拆分、heartbeat 機制與 `/health` 真實活性檢查，確認 scheduler 週期性 heartbeat 持續更新。

## 附註

本文件最早版本是修復前審計紀錄；目前內容已改寫為修復後狀態，作為本輪工作的最終結案記錄。