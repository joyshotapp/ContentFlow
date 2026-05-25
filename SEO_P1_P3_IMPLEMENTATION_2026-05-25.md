# SEO P1–P3 實作紀錄（2026-05-25）

本文件記錄 [SEO_EXPERT_EVALUATION_2026-05-25.md](SEO_EXPERT_EVALUATION_2026-05-25.md) 第八節建議的 **P1–P3 全項實作**（P0 見 [SEO_P0_IMPLEMENTATION_2026-05-25.md](SEO_P0_IMPLEMENTATION_2026-05-25.md)）。

> **完整總覽（含部署、生產驗證、事故）**：[SEO_P0_P3_DEPLOYMENT_AND_VERIFICATION_2026-05-25.md](SEO_P0_P3_DEPLOYMENT_AND_VERIFICATION_2026-05-25.md)

---

## P1 — 短期（已完成）

### 4. Slug 治理

| 項目 | 實作 |
|------|------|
| 新稿語意化 slug | `writing_agent` 改用 `propose_article_slug(primary_keyword, title)` |
| 弱 slug 偵測 | `utils/slug_governance.py` → `is_weak_slug()` |
| 301 登記 | `register_slug_change()` 寫入 `old_slugs`；前台 `/blog/{slug}` 已有反查 |
| 批次遷移腳本 | `scripts/migrate_weak_slugs.py`（`--dry-run` / `--project-id`） |

### 5. Topic cluster URL 語意化

| 項目 | 實作 |
|------|------|
| DB 欄位 | `topic_clusters.slug`（migration `019`） |
| 路由 | `/topic/{slug}`；數字 ID 自動 **301** 至 slug |
| 叢集建立 | `cluster_agent` 寫入 `slugify_topic_keyword(pillar_keyword)` |
| Sitemap / 模板 | 使用 `topic_cluster_url(cluster)`；首頁連結已更新 |
| 排程補齊 | `backfill_topic_cluster_slugs`（每月 2 號） |

### 6. HEAD 405 修正

- `site_app` 加入 HTTP middleware：HEAD 轉為 GET 處理並回傳空 body（監控工具不再收到 405）

### 7. GSC 日級增量

| 項目 | 實作 |
|------|------|
| 資料表 | `gsc_daily_metrics`（project + keyword + page + metric_date 唯一） |
| 同步 | `GSCClient.sync_daily_incremental()` 同步「昨日」單日資料 |
| 排程 | 併入每日 `sync_gsc_all_projects`（03:00） |

---

## P2 — 中期（已完成）

### 8. 上線後意圖命中評分

- `tools/intent_match.py`：`score_intent_match()`、`evaluate_published_article_intent()`
- 文章欄位：`intent_match_score`、`intent_match_checked_at`
- 排程：`run_intent_match_evaluation`（每週四 05:30，發布後第 14/28 天窗口）
- 低分（<45）寫入 `KnowledgeEntry` category=`intent_match_low` 供策略/人工追蹤

### 9. 自蝕自動執行

- `strategic_context` 輸出 `article_ids`
- Fallback 計畫新增 action：`resolve_cannibalization`
- 執行器 `_execute_resolve_cannibalization`：refresh 較弱文 → 支柱文 inject_internal_links → Slack alert

### 10. Hero 圖片覆蓋率

- 既有 pipeline：`run_hero_image_agent`（orchestrator）
- 排程：`check_missing_hero_images`（每週二 06:30）對已發布且缺 `hero_image_url` 的文章 Slack 警示

### 11. Off-page 最小閉環

- `tools/brand_mentions.py`：Serper 搜尋品牌提及
- 資料表：`brand_mention_snapshots`、`outreach_tasks`
- 排程：`sync_brand_mentions_all_projects`（每週三 05:30）

---

## P3 — 長期（基礎版已完成）

### 12. Market / language pack

- `market_packs.py`：`zh-tw`、`zh-hk`、`en-us`、`ja-jp`
- `ProjectContext.build_brand_prompt()` 注入 `market_prompt_block(locale)`

### 13. 實驗框架

- `experiments.py`：`start_content_experiment()`、`complete_content_experiment()`、`snapshot_gsc_baseline()`
- 資料表：`content_experiments`（variant / holdout / baseline & result JSON）

### 14. PSI / CWV 內建監控

- 設定：`GOOGLE_API_KEY`（`config.py`）
- 排程：`run_cwv_monitoring_all_projects`（每週六 06:00）→ `cwv_snapshots`
- 使用既有 `tools/tech_seo.CoreWebVitalsMonitor`

---

## 資料庫遷移

```bash
alembic upgrade head   # revision 019_seo_p1_p3_enhancements
```

SQLite 本地開發亦已透過 `db.py` `_ensure_sqlite_columns` 補欄位。

---

## 部署後建議操作

1. **遷移弱 slug**（goodbone 等租戶）  
   `PYTHONPATH=src python scripts/migrate_weak_slugs.py --dry-run`  
   確認後去掉 `--dry-run`

2. **補齊 topic slug**  
   等待排程 `backfill_topic_cluster_slugs`，或手動觸發一次

3. **設定環境變數**（可選）  
   - `GOOGLE_API_KEY`：CWV 排程  
   - `SERPER_API_KEY`：品牌提及（已有則啟用）

4. **驗證 HEAD**  
   `curl -sI https://goodbone.com.tw/` 應為 200 而非 405

---

## 測試

```bash
PYTHONPATH=src pytest tests/test_seo_p1_p3.py tests/test_publish_safety.py tests/test_site_app.py -q
```

---

## 與評估報告的對應

| 原建議 | 狀態 |
|--------|------|
| P0 三項 | 已完成（前次提交） |
| P1 四項 | ✅ 本批完成 |
| P2 四項 | ✅ 本批完成 |
| P3 三項 | ✅ 基礎模組 + 排程已就緒；實驗需業務方定義實驗 key 後啟用 |
