# SEO P0–P3 完整紀錄：評估、實作、部署與生產驗證（2026-05-25）

本文件為 **P0–P3 SEO 強化專案** 的單一總覽，串接評估報告、分項實作紀錄、生產部署過程、事故處理與驗證結果。  
細節仍以分冊為準，本文件供營運／工程交接使用。

---

## 1. 文件索引

| 文件 | 用途 |
|------|------|
| [SEO_EXPERT_EVALUATION_2026-05-25.md](SEO_EXPERT_EVALUATION_2026-05-25.md) | 資深 SEO 評估、生產站問題、**P0–P3 優先順序（第八節）** |
| [SEO_P0_IMPLEMENTATION_2026-05-25.md](SEO_P0_IMPLEMENTATION_2026-05-25.md) | P0 三項：反堆砌、headline、發布閘（程式與測試） |
| [SEO_P1_P3_IMPLEMENTATION_2026-05-25.md](SEO_P1_P3_IMPLEMENTATION_2026-05-25.md) | P1–P3 十一項：slug、topic、HEAD、GSC、意圖、自蝕等 |
| **本文件** | 部署方式、生產事故、DB 處理、驗證清單與結果 |

---

## 2. 項目總表（評估 → 實作狀態）

| 優先級 | # | 項目 | 狀態 | 主要程式位置 |
|--------|---|------|------|----------------|
| **P0** | 1 | YMYL / 自動發布硬 gate | ✅ 已上線 | `utils/publish_safety.py`、`strategic_agent.py`、`scheduler.py` |
| **P0** | 2 | JSON-LD headline 與 title 一致 | ✅ 已上線 | `utils/article_schema.py`、`writing_agent.py`、`site/app.py` |
| **P0** | 3 | SEO Check 反關鍵字堆砌 | ✅ 已上線 | `agents/seo_check_agent.py` |
| **P1** | 4 | Slug 治理 + 弱 slug 遷移腳本 | ✅ 程式就緒；生產遷移待執行 | `utils/slug_governance.py`、`scripts/migrate_weak_slugs.py` |
| **P1** | 5 | Topic cluster `/topic/{slug}` + 301 | ✅ 已上線；DB 尚無 slug 資料 | `site/app.py`、`cluster_agent.py` |
| **P1** | 6 | HEAD 405 修正 | ✅ 已驗證 200 | `site/app.py` middleware |
| **P1** | 7 | GSC 日級 `gsc_daily_metrics` | ✅ 已上線 | `tools/gsc.py`、`scheduler.py`（併入 `gsc_sync`） |
| **P2** | 8 | 上線後意圖命中評分 | ✅ 已上線 | `tools/intent_match.py`、排程 `intent_match` |
| **P2** | 9 | 自蝕自動執行 | ✅ 已上線 | `strategic_agent.py` → `resolve_cannibalization` |
| **P2** | 10 | Hero 圖覆蓋檢查 | ✅ 已上線 | 排程 `hero_image_check` |
| **P2** | 11 | Off-page 品牌提及 + outreach | ✅ 已上線 | `tools/brand_mentions.py`、排程 `brand_mentions` |
| **P3** | 12 | Market / language pack | ✅ 已上線 | `market_packs.py`、`project_context.py` |
| **P3** | 13 | 內容實驗框架 | ✅ 基礎就緒 | `experiments.py`、`content_experiments` 表 |
| **P3** | 14 | PSI / CWV 監控 | ✅ 排程就緒 | `tools/tech_seo.py`、排程 `cwv_monitor`（需 `GOOGLE_API_KEY`） |

**排程總數**：`SCHEDULER_JOB_SPECS` = **27**（原 22 + P1–P3 共 5 個新 job）。  
測試：`tests/test_publish_safety.py`、`tests/test_seo_p1_p3.py`、`tests/test_seo_check_new_rules.py` 等；全 suite **421 passed**（2026-05-25 本地）。

---

## 3. 生產環境資訊

| 項目 | 值 |
|------|-----|
| 網域 | https://goodbone.com.tw |
| 伺服器 | `root@172.235.216.10`（Linode 2GB，JP Osaka） |
| 專案路徑 | `/root/contentflow` |
| Compose | `docker-compose.prod.yml` |
| 程式掛載 | `./src` → `/app/src`（**改程式不必 rebuild image**） |
| SSH 金鑰 | `~/.ssh/linode_key`（`~/.ssh/config` 已設定） |

---

## 4. 部署方式（建議與禁止）

### 4.1 建議：rsync + restart（本次採用）

```bash
# 本機
cd /path/to/ContentFlow
rsync -e "ssh -o StrictHostKeyChecking=accept-new" -avz \
  --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
  --exclude='.venv' --exclude='outputs/' --exclude='contentflow.db' \
  ./ root@172.235.216.10:/root/contentflow/

ssh root@172.235.216.10 \
  'docker restart contentflow-site-1 contentflow-scheduler-1'
```

適用：僅變更 `src/` 內 Python／模板；容器已掛載 `src` volume。

### 4.2 禁止（除非升級 RAM 或改 CI）

```bash
DOMAIN=goodbone.com.tw ./deploy/setup_remote.sh   # 內含遠端 docker compose build
```

**原因（2026-05-25 事故）**：2GB VPS 上全量 `docker build`（chromadb、langgraph 等）導致：

- CPU ~143%、磁碟 I/O 飆升（Linode 監控約 03:00）
- OOM → SSH `Connection timed out during banner exchange`
- 網站 HTTPS 無回應

**處置**：使用者 Linode **Reboot**；本機中止卡住的 deploy SSH 程序。

### 4.3 若必須 schema 變更

- 優先：`docker exec contentflow-site-1 python -m contentflow.db_bootstrap`  
- 若 Alembic 鏈與生產不一致，見 **第 5 節** 手動 SQL。

### 4.4 可選：更新 build 標籤（不影響程式邏輯）

```bash
ssh root@172.235.216.10 'cat > /root/contentflow/.build-meta.env <<EOF
CONTENTFLOW_BUILD_COMMIT=$(git rev-parse --short HEAD)
CONTENTFLOW_BUILD_TIME=$(date -u +%Y-%m-%dT%H:%M:%SZ)
CONTENTFLOW_BUILD_SOURCE=local-rsync
EOF'
docker restart contentflow-site-1
```

---

## 5. 資料庫：Migration 與生產修復

### 5.1 本地 / 標準路徑

- Revision：`migrations/versions/019_seo_p1_p3_enhancements.py`（`revision = "019"`，`down_revision = "018"`）
- 內容：`topic_clusters.slug`、`articles.intent_match_*`、`gsc_daily_metrics`、`brand_mention_snapshots`、`outreach_tasks`、`content_experiments`、`cwv_snapshots`

```bash
PYTHONPATH=src python -m contentflow.db_bootstrap
# 或
alembic upgrade head
```

### 5.2 生產異常（2026-05-25）

| 現象 | 原因 |
|------|------|
| 前台 HTTP **500** | 程式已 rsync 新 model，DB 缺 `articles.intent_match_score` |
| `db_bootstrap` 失敗 | `alembic_version = 021`，容器內 migration 檔無 `021`（主機有 `019`–`021` 多支，鏈與 image 不一致） |

**處置**：在 PostgreSQL 以 idempotent SQL 補齊 `019_seo` 欄位與表（已執行），然後 `docker restart contentflow-site-1`。

**後續建議**：

1. 統一 repo 與生產主機的 `migrations/versions/`，避免重複 revision id（例如兩個 `019`）。
2. 將 `019_seo_p1_p3_enhancements` 合併進正式 Alembic 鏈，或新增 `022` 僅補 SEO 欄位並在生產 `stamp`。
3. 文件化：生產 `alembic_version` 以 `docker exec contentflow-db-1 psql ... -c "SELECT version_num FROM alembic_version;"` 為準。

---

## 6. 生產驗證（2026-05-25，Reboot + SQL + rsync 後）

### 6.1 連線與健康

| 檢查 | 結果 |
|------|------|
| SSH `root@172.235.216.10` | ✅（Reboot 後） |
| `http://127.0.0.1:8000/health` | ✅ `status: ok`，`db: ok`，`scheduler: running` |
| 對外 `GET /health` | ⚠️ nginx **403**（`robots.txt` Disallow，屬預期） |

### 6.2 前台 SEO 端點

| 檢查 | 結果 |
|------|------|
| `GET https://goodbone.com.tw/` | **200** |
| `GET /blog` | **200** |
| `HEAD /` | **200**（P1，非 405） |
| `/robots.txt` | **200**，含 `Sitemap: https://goodbone.com.tw/sitemap.xml` |
| `/sitemap.xml` | **200** |
| `/sitemap_index.xml` | **301** → `/sitemap.xml` |

### 6.3 程式模組（容器內）

| 檢查 | 結果 |
|------|------|
| `publish_safety` | ✅ `approved` 可發布、`review_required` 阻擋 |
| `SCHEDULER_JOB_SPECS` | **27**；含 `intent_match`、`brand_mentions`、`topic_slug_backfill`、`cwv_monitor` |
| SEO 原始碼 | ✅ `publish_safety.py`、`site/app.py` HEAD、`scheduler.py` 已存在於 `/root/contentflow/src` |

### 6.4 JSON-LD headline 抽樣

- 文章：`/blog/luozhen-jianbu-tongkuai-jie`
- `@type`：`BlogPosting` + `MedicalWebPage`
- `headline`：**落枕怎麼辦？快速緩解頸部疼痛的自救與預防技巧**
- `<title>`：同上 + ` — GoodBone 好骨頭`  
→ **headline 與可見標題一致**（P0 #2）

### 6.5 尚待營運執行

| 項目 | 說明 |
|------|------|
| 弱 slug 遷移 | `PYTHONPATH=src python scripts/migrate_weak_slugs.py --dry-run` → 確認後正式執行 |
| Topic slug 補齊 | DB 目前 0 筆叢集 slug；可等排程 `backfill_topic_cluster_slugs` 或手動觸發 |
| `GOOGLE_API_KEY` | CWV 排程需設定才會寫入 `cwv_snapshots` |
| `SERPER_API_KEY` | 品牌提及排程需設定 |
| 醫療 Project `auto_publish_enabled` | P0 建議營運關閉，非程式預設 |

---

## 7. 事故時間軸（摘要）

| 時間（約） | 事件 |
|------------|------|
| 部署啟動 | `setup_remote.sh` rsync 成功 |
| ~03:00 | 遠端 `docker compose build`，CPU/磁碟飆高 |
| 之後 | SSH banner 逾時、HTTPS 逾時；使用者無法連線 |
| 處置 | 中止本機 deploy 程序；Linode **Reboot** |
| Reboot 後 | SSH 恢復；站台 **500**（缺 DB 欄位） |
| 修復 | 手動 SQL 補 SEO schema；restart site |
| 驗證部署 | rsync + restart site/scheduler；前台 **200** |

---

## 8. 關鍵檔案速查

```
src/contentflow/utils/publish_safety.py      # P0 發布閘
src/contentflow/utils/article_schema.py      # P0 headline 同步
src/contentflow/utils/slug_governance.py     # P1 slug
src/contentflow/agents/seo_check_agent.py      # P0 反堆砌
src/contentflow/site/app.py                    # P0 渲染同步、P1 HEAD/topic/sitemap
src/contentflow/tools/gsc.py                   # P1 日級 GSC
src/contentflow/tools/intent_match.py          # P2
src/contentflow/tools/brand_mentions.py        # P2
src/contentflow/market_packs.py                # P3
src/contentflow/experiments.py                 # P3
src/contentflow/scheduler_job_registry.py      # 27 jobs
migrations/versions/019_seo_p1_p3_enhancements.py
scripts/migrate_weak_slugs.py
deploy/setup_remote.sh                         # ⚠️ 含遠端 build，小 VPS 慎用
```

---

## 9. 測試指令

```bash
# P0 + P1–P3 相關
PYTHONPATH=src pytest \
  tests/test_publish_safety.py \
  tests/test_seo_p1_p3.py \
  tests/test_seo_check_new_rules.py \
  tests/test_site_app.py \
  tests/test_phase_gate_c.py::test_check_scheduled_publishes_rescues_review_required_backlog \
  -q

# 全量（約 10 分鐘）
PYTHONPATH=src pytest tests/ -q
```

---

## 10. 生產快速驗證腳本（營運可複製）

```bash
BASE=https://goodbone.com.tw
curl -sS -o /dev/null -w "GET / => %{http_code}\n" "$BASE/"
curl -sS -o /dev/null -w "HEAD / => %{http_code}\n" -X HEAD "$BASE/"
curl -sS -o /dev/null -w "GET /blog => %{http_code}\n" "$BASE/blog"
curl -sS "$BASE/robots.txt" | head -6
curl -sS -o /dev/null -w "sitemap_index => %{http_code}\n" "$BASE/sitemap_index.xml"

ssh root@172.235.216.10 'curl -sf http://127.0.0.1:8000/health | python3 -m json.tool | head -15'
```

---

## 11. Phase A：Admin Agent 治理儀表（2026-05-25）

| 項目 | 說明 |
|------|------|
| 路徑 | `/admin/agent-governance`（側欄：策略與優化 → **Agent 治理**） |
| 登入 | 未登入會 **303 → `/admin/login`**（密碼 = `.env` 的 `API_SECRET_KEY`），屬正常行為 |
| 程式 | `admin/agent_ops.py`、`admin/templates/agent_governance.html`、`admin/app.py` 路由 |
| 發布閘 | 統計 review_required、FactCheck 高風險、可自動發布數、未通過閘候選與原因（呼叫 `publish_safety`） |
| 意圖→Refresh | 低意圖分（&lt;45）優先佇列、知識庫 `intent_match_low` / `refresh_priority` |
| 測試 | `tests/test_agent_ops.py` |
| Git | `eed6fae` 新增；`2cb2ccb` 修復 HEAD / 時區比較 |

**刻意未做**：LLM 機率化自省（中長期選項）。

### 11.1 曾發生之 500 與修復（`2cb2ccb`）

| 症狀 | 原因 | 修正檔案 |
|------|------|----------|
| 首頁 / `HEAD /` → Internal Server Error | HEAD middleware 保留 GET 的 `Content-Length`，body 為空 | `site/app.py` → `_head_empty_response()` |
| `/admin/agent-governance` 登入後 500 | PostgreSQL `published_at` 為 naive，與 UTC aware 比較失敗 | `admin/agent_ops.py` → `_as_utc()` |

---

## 12. 接手人閱讀順序（建議）

1. [README.md](README.md) — 系統定位、部署方式、Admin 路由表  
2. **本文件** — P0–P3 總表、生產部署、驗證、事故、Phase A  
3. [SEO_P0_IMPLEMENTATION_2026-05-25.md](SEO_P0_IMPLEMENTATION_2026-05-25.md) — 發布閘、反堆砌、headline  
4. [SEO_P1_P3_IMPLEMENTATION_2026-05-25.md](SEO_P1_P3_IMPLEMENTATION_2026-05-25.md) — 其餘 SEO 項與排程  
5. [SEO_EXPERT_EVALUATION_2026-05-25.md](SEO_EXPERT_EVALUATION_2026-05-25.md) — 為何做這些、生產抽樣證據  

程式入口速查：`publish_safety.py`（閘門規則）、`scheduler_job_registry.py`（27 jobs）、`orchestrator.py`（產文圖）。

---

## 13. 修訂紀錄

| 日期 | 說明 |
|------|------|
| 2026-05-25 | 初版：整合 P0–P3 實作、部署事故、手動 SQL、生產驗證結果 |
| 2026-05-25 | 新增 Phase A Admin Agent 治理頁 |
| 2026-05-25 | 補充 HEAD Content-Length、agent-governance 時區 500 修復與接手閱讀順序 |

---

*維護建議：日後若僅改程式，更新本文件「第 6 節驗證日期」與「第 7 節時間軸」；若改 schema，同步更新第 5 節與 `SEO_P1_P3_IMPLEMENTATION`。*
