# SEO P0 實作紀錄（2026-05-25）

依 [SEO_EXPERT_EVALUATION_2026-05-25.md](SEO_EXPERT_EVALUATION_2026-05-25.md) 優先改善清單完成三項 P0。

> **完整總覽（含部署、生產驗證、事故）**：[SEO_P0_P3_DEPLOYMENT_AND_VERIFICATION_2026-05-25.md](SEO_P0_P3_DEPLOYMENT_AND_VERIFICATION_2026-05-25.md)

## 1. 反關鍵字堆砌（SEO Check）

**檔案**：`src/contentflow/agents/seo_check_agent.py`

新增規則：

| 規則名稱 | 條件 | 權重 |
|----------|------|------|
| `first_paragraph_no_keyword_stuffing` | 首段主關鍵字 ≤ 2 次 | 2.5 |
| `opening_section_no_keyword_stuffing` | 開頭約 600 字內主關鍵字 ≤ 4 次 | 2.0 |

未通過會拉低 SEO 分數，並可觸發既有 SEO QA 修稿迴圈。

**測試**：`tests/test_seo_check_new_rules.py::test_first_paragraph_keyword_stuffing_fails`

## 2. JSON-LD headline 與可見標題一致

**檔案**：

- `src/contentflow/utils/article_schema.py` — `sync_article_schema_headline()`
- `src/contentflow/agents/writing_agent.py` — 產稿時以 `meta_title` 作為 `headline`
- `src/contentflow/site/app.py` — 渲染前再次同步（修正舊稿 headline 漂移）
- `src/contentflow/agents/strategic_agent.py`、`src/contentflow/api.py` — 回寫 DB 前同步

**測試**：`tests/test_publish_safety.py::TestArticleSchemaSync`

## 3. YMYL / 自動發布安全閘

**檔案**：`src/contentflow/utils/publish_safety.py`

| 函式 | 用途 |
|------|------|
| `serialize_factcheck_flags()` | 將 `fact_check_items` 寫入 `factcheck_flags_json` |
| `can_auto_publish_article()` | 僅 `approved` + 無 factcheck 風險 + `auto_publish_enabled` |
| `article_has_factcheck_risk()` | 排程與戰略發布共用 |

**行為變更**：

- `strategic_agent`：自動發布前必須通過 `can_auto_publish_article()`；pipeline 回寫 `factcheck_flags_json`
- `scheduler.check_scheduled_publishes`：**移除**「`review_required` 且分數達標直接發布」；僅發布 `approved` 且通過安全閘的文章
- `review_required` 近門檻補救仍可升級為 `approved`，但不會在未核准狀態下直接上線

**測試**：`tests/test_publish_safety.py`

## 部署建議

1. 部署後觀察 Admin：FactCheck 有旗標的稿件應停留在 `review_required`
2. 既有已發布文章：前台渲染會自動修正 JSON-LD `headline`（不需重跑 pipeline）
3. 新稿若首段堆砌，SEO 分數應下降並進入 SEO QA

## 未含於本次 P0

- Slug / topic URL 語意化（P1）
- HEAD 405 修正（P1）
- 醫療 Project 預設關閉 `auto_publish_enabled`（需營運設定，非程式預設變更）
