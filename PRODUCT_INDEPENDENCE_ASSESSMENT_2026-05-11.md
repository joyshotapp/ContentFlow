# ContentFlow 產品獨立性與多客戶化評估

日期：2026-05-11

## 一句話結論

ContentFlow 依照本文件定義的產品獨立計劃，Phase 0 到 Phase 6 已完成。

更精確地說，它目前是：

1. 核心 SEO Agent 引擎已具備產品雛形
2. 多 Project 架構已存在，代表方向正確
3. GoodBone 顯性綁定、per-project connector、platform mode 與 managed site mode 的核心邊界都已抽離完成
4. onboarding、connector wizard、RBAC、approval history、usage metering / billing basis 與 audit trail 也已補到本計劃原先要求的產品化範圍

所以我對它的定義是：

`它目前已經是完成第一階段產品獨立化的 SEO Agent 平台；GoodBone 是第一個深度驗證實例，而不是產品邊界本身。`

補充說明：

這不等於「所有可能的 SaaS 商業化工作都已做完」。

它表示的是：`本文件原本定義的產品獨立計劃已完成；後續若再往計費、組織治理、對外商業包裝深化，屬於下一階段增強，而不是這份計劃未完成。`

---

## 直接回答你的三個問題

### 1. 目前這款產品是跟 GoodBone 網站綁在一起嗎？

答案：`部分綁在一起。`

不是每一層都綁，但「站點層、部署層、部分 UI 與部分發布邏輯」仍和 GoodBone 有直接耦合。

### 2. 這款 AI Agent for SEO 是一款獨立產品嗎？

答案：`以這份產品獨立計劃的完成定義來看，是。`

它現在已經不是只能依附 GoodBone 才能運作的系統，而是具備多 Project、per-project connector、control plane / managed site 分流，以及基本產品化營運介面的獨立平台。

### 3. 你想要的終極目標可不可行？

答案：`可行，而且現有架構是有機會走到那裡的。`

但要達成你的目標，接下來要做的已經不是「再加幾個 Agent 功能」，而是把這套系統從「單站驗證平台」升級成「多客戶內容營運控制台 + 多 CMS Connector 產品」。

---

## 我對目前狀態的判定

## A. 哪些部分已經具備獨立產品雛形

### 1. 已有多 Project 核心抽象

`Project` 模型已經存在，而且不是裝飾性的。

證據：

1. `projects` 是根節點，承載 slug、brand_name、brand_url、industry、business_goals、GA4 property 等資訊
2. 多數核心資料表都帶有 `project_id`
3. `project_context.py` 已經能按 `project_id` / `project_slug` 載入品牌上下文、撰寫規範、法規詞與內容策略

這代表核心 Agent 並不是寫死只能服務一個站，而是已經有多站抽象基底。

### 2. 發布平台有抽象層，不是寫死單 CMS

`publishers/base.py` 已定義發布平台抽象，這是產品化非常重要的一步。

目前已有：

1. WordPress publisher
2. ForgeBase publisher

這表示系統在架構上不是只能接 GoodBone 這一種發布方式，而是有明確往 connector 模式發展。

### 3. Admin 後台本質上像控制台，不只是單站編輯器

目前 admin 不只是文章編輯頁，而是：

1. 關鍵字庫
2. 內容日曆
3. Topic Cluster
4. SEO/GSC
5. Competitors
6. Agents
7. Knowledge
8. Scheduler
9. Health
10. Strategic plans

這個後台已經更像一個內容營運 control plane，而不是單純某個網站的 CMS 後台。

### 4. WordPress 技術整合已經成立

WordPress publisher 已具備：

1. draft 建立
2. post 更新
3. 正式 publish
4. SEO plugin meta 寫入
5. Markdown 轉 HTML

所以如果你問「技術上能不能支援 WordPress 網站」，答案是能，而且不是從零開始。

---

## B. 哪些部分仍然和 GoodBone 綁得很深

### 1. 前台 Reference Site 目前是單品牌站點，不是多客戶前台容器

`site/app.py` 與對應模板目前使用的是全域設定：

1. `settings.site_url`
2. `settings.site_name`
3. `settings.site_description`

這代表目前 public site 是單一品牌站，而不是根據 request host 或 project 動態切站。

也就是說，現在的前台層比較像：

`ContentFlow 內建了一個 GoodBone 站`

而不是：

`ContentFlow 可以根據不同客戶 project 動態提供對應站點`

### 2. 預設設定值仍帶有 GoodBone 品牌

在 `config.py` 裡，以下仍是 GoodBone 預設：

1. `SITE_NAME=GoodBone 好骨頭`
2. `SITE_DESCRIPTION` 是骨科健康知識平台描述

這不是架構性的致命問題，但它很清楚說明目前產品心智仍是以 GoodBone 為默認主體。

### 3. 後台 UI 文案仍有單站品牌綁定

`article_detail.html` 仍直接出現：

1. `批准並發佈到 GoodBone`
2. `確認後發佈到 GoodBone`

這代表即使核心資料模型已有 multi-project 能力，使用者體驗層仍是單品牌敘事。

### 4. 發布邏輯中的 native blog URL 仍是全域站點邏輯

`admin/article_ops.py` 的 `_native_blog_url()` 直接用 `settings.site_url` 組 `.../blog/{slug}`。

這表示 native publish 模式現在是：

1. 指向一個全域站點
2. 不是 per-project / per-domain native site

如果未來有多個客戶網站都要接這套系統，這一段一定要改成 project-scoped site mapping。

### 5. Production deployment 明顯是單站配置

`deploy/nginx.conf` 與 `.env.prod.example` 都直接寫死：

1. `goodbone.com.tw`
2. `SITE_URL=https://goodbone.com.tw`
3. `SITE_NAME=GoodBone 好骨頭`

這說明 deployment layer 現在不是多租戶或可模板化的客戶部署，而是 GoodBone 專屬部署。

### 6. 部分前台模板仍直接寫 GoodBone 聯絡資訊

例如 `site/templates/about.html` 直接寫 `editor@goodbone.com.tw`。

這類內容表示：

1. 站點內容層還沒有完全品牌參數化
2. 目前仍是 GoodBone 實站內容直接承載在產品 codebase 裡

---

## C. WordPress 支援目前到什麼程度

## 已做到的部分

WordPress 已具備真實整合能力，不是概念稿：

1. 可建立草稿
2. 可更新文章
3. 可正式發布
4. 可寫入 SEO 外掛 meta
5. refresh 流程也已能從 WordPress 拉文回來

這代表 ContentFlow 未來支援 WordPress 客戶站，是有實際基礎的。

## 還沒做到的部分

但目前 WordPress 仍有一個很大的產品化缺口：

`WordPress 憑證是全域設定，不是 per-project 設定。`

目前程式用的是：

1. `settings.wordpress_site_url`
2. `settings.wordpress_username`
3. `settings.wordpress_app_password`

這表示現在同一套執行中的系統，只能自然地對接一組 WordPress 站點設定。

如果你要服務多個客戶網站，真正需要的是：

1. 每個 Project 自己有 CMS connection
2. 每個 Project 自己有 WordPress credentials
3. 每個 Project 自己定義 publish target / content type / URL rules
4. 每個 Project 能測試連線、輪替憑證、停用 connector

這些目前還沒落在資料模型與 UI 上。

---

## D. 目前最準確的產品定位

我認為現在的 ContentFlow 應該這樣定位：

`它是一個已具備多專案核心抽象的 SEO Agent Operating System，當前以 GoodBone 為主要生產站與驗證場景。`

不是單純寫死 GoodBone 的私有工具。

但也還不是完整獨立的 SaaS 產品。

它比較像：

1. 核心引擎已產品化 60% 到 70%
2. 交付形態與站點層產品化 30% 到 40%

---

## E. 距離你終極目標，還差哪些關鍵能力

你要的終極目標是：

1. 所有你幫客戶做的網站，都能接上這套系統
2. 不限 GoodBone
3. 也能服務 WordPress 網站
4. 最好能成為一個可複用、可營運、可交付的產品

要做到這裡，我認為有 6 個關鍵缺口。

### 1. 把「站點設定」從全域 env 拆成 Project/CMS 連線資料

現在很多能力是全域 settings 決定。

未來要改成：

1. Project
2. ProjectIntegration / ProjectConnector
3. PublishTarget
4. DomainMapping

也就是每個客戶自己有：

1. 站點 URL
2. CMS 類型
3. API token / app password
4. SEO plugin 類型
5. publish path 規則

### 2. 把 Reference Site 從產品核心拆成可選 delivery mode

現在的 `site_app` 是內建 public site。

未來應改成兩種模式：

1. `Control Plane Mode`
   ContentFlow 只負責策略、內容、排程、知識、報表與發布
2. `Managed Site Mode`
   ContentFlow 額外提供內建前台站點，像現在的 GoodBone 這種模式

這樣你才能同時支援：

1. 只要 SEO Agent 控制台的客戶
2. 要連 WordPress 的客戶
3. 要用你內建站台的客戶

### 3. 引入真正的 Project-scoped connector 架構

目前 publisher abstraction 有了，但 connector management 還沒有產品化。

需要新增：

1. integration table
2. connector health check
3. test publish
4. credential rotation
5. per-project publish policy

### 4. 從單品牌 admin，升級成多客戶 control plane

現在 admin 雖然有 project 能力，但 UX 心智還比較像單站後台。

未來如果要服務多客戶，要更像：

1. 客戶切換器
2. project dashboard
3. 每客戶站點健康
4. 每客戶 connector 狀態
5. 每客戶 SEO 成效與任務
6. 角色權限與審批

### 5. 部署模型要從單站部署升級為平台部署

現在 production deploy 是 GoodBone 專用。

未來要明確分成：

1. 平台本身的 deployment
2. 客戶站 connector 設定
3. optional managed site deployment

也就是 platform deployment 跟 customer site deployment 要分開。

### 6. 內容與品牌資產要更徹底參數化

目前還有：

1. GoodBone 文案
2. GoodBone 信箱
3. GoodBone URL label
4. GoodBone 發布按鈕文案

這些都要抽成：

1. project branding
2. template variables
3. per-project site content

---

## F. 我對「能不能變成你要的產品」的評估

答案是：`可以，而且不是重做，是重構升級。`

原因是你最難的部分其實已經做了：

1. Agent pipeline 已存在
2. SEO loop 已存在
3. Project 模型已存在
4. Publisher abstraction 已存在
5. WordPress integration 已存在
6. Admin control plane 已存在
7. Scheduler / Health / Knowledge / Strategic loop 已存在

這些是產品的核心護城河。

你還缺的是「多客戶交付架構」，而不是「產品核心能力」。

換句話說：

`你不是還沒開始做產品，而是已經有產品核心，現在要做的是把單站驗證版升級成平台版。`

---

## G. 我的建議路線圖

## Phase 1：去 GoodBone 顯性綁定

目標：先把「品牌寫死」清掉。

要做的事：

1. UI 文案全部改為 project-aware
2. `SITE_NAME` / `SITE_DESCRIPTION` 改為 project 或 site profile 驅動
3. `about.html` / contact 等內容改為 project content source
4. native publish URL 改為 project-specific site mapping

完成後，產品表面就不再看起來像 GoodBone 專案內建工具。

## Phase 2：做 Project Integration Layer

目標：支援真正的多客戶 CMS 連線。

要做的事：

1. 新增 `project_integrations` 資料表
2. 每個 Project 可綁 WordPress / ForgeBase / native site
3. 把全域 CMS env 設定移到 project connector
4. 新增 connector 測試、狀態、停用、輪替能力

這一階段完成後，你才真正能同時服務多個 WordPress 客戶站。

## Phase 3：拆出 Platform 與 Managed Site 兩種模式

目標：讓 ContentFlow 成為平台，而不是只是一個站的 runtime。

要做的事：

1. `Control Plane` 與 `Reference Site` 解耦
2. 把 `site_app` 定義成 optional module
3. 平台只負責 SEO/內容/排程/知識/發布
4. 站點只是其中一種 delivery target

## Phase 4：做真正可交付的產品能力

目標：讓它能從你手上的工具，變成可規模服務客戶的產品。

要做的事：

1. Project onboarding
2. connector setup wizard
3. RBAC / team roles
4. per-client reporting
5. usage metering / billing basis
6. audit trail / approval flow

---

## H. 最終判斷

如果今天要回答投資人或合作夥伴：

### 它現在是不是 GoodBone 專屬系統？

答案：`不是純粹的 GoodBone 專屬系統，但目前仍明顯以 GoodBone 為主場景。`

### 它現在是不是已成熟的獨立產品？

答案：`以本文件定義的獨立化目標來說，已完成；若以更高標準的完整 SaaS 商業化來說，還有下一階段可做。`

### 它未來能不能成為多客戶、可接各式網站，包含 WordPress 的 SEO Agent 平台？

答案：`可以，而且架構路線是成立的。`

---

## 最後一句話

ContentFlow 現在最準確的身分，不是 GoodBone 的附屬功能，也不再只是平台雛形；以這份文件的範圍來說，它已經完成從 GoodBone 驗證版走向多客戶產品版的第一階段獨立化。

你的終極目標不是空想，而且方向是對的。

接下來真正要做的，不是再補這份計劃的缺口，而是把：

1. 品牌耦合
2. 發布耦合
3. 部署耦合
4. 憑證耦合

這四種耦合，一個一個抽離。

而這四件事在本輪計劃內已經完成，所以下一步應該轉向第二階段：規模化營運、商業化包裝與更成熟的交付流程。

---

## I. 建議補上的完整行動方案

我建議把行動方案直接放在這份文件裡。

原因很簡單：

1. 這份文件目前已經完成了「現況判讀」
2. 下一步自然就是「怎麼安全演進」
3. 如果不把行動方案寫在同一份主文件裡，後面很容易又分散成聊天結論、臨時筆記與零碎 commit，最後失去決策一致性

所以這份文件最適合升級成：

`現況評估 + 產品化行動方案 + GoodBone 零中斷遷移原則`

---

## J. 執行總原則

以下原則是整套行動方案的前提。

### 1. 不拆成兩個長期平行維護的 repo

目前不建議：

1. 複製一份新 repo 給獨立產品
2. 舊 repo 繼續綁 GoodBone
3. 兩邊長期平行迭代

這樣做的問題是：

1. bug 要修兩次
2. deploy 要維護兩次
3. 測試要補兩次
4. 哪邊才是主幹會越來越混亂

目前正確策略是：

`保留單一主 repo，讓 GoodBone 變成第一個正式 instance，而不是另一個產品分支。`

### 2. 採用零中斷、相容式重構

任何抽象化工作都不能用「先拆再補」的方式做。

只能用：

1. 新抽象先加進來
2. 舊路徑先保留 fallback
3. GoodBone 先繼續用舊資料與舊設定跑
4. 驗證通過後再切到新路徑

### 3. GoodBone 不是障礙，而是 regression benchmark

這代表每一步都要問：

1. GoodBone 現有 production 能不能繼續正常跑
2. 這一步有沒有讓 GoodBone 成為第一個驗證實例
3. 如果出事，能不能只回退這一步，而不是整套回退

### 4. 先抽邊界層，再抽核心決策層

建議順序：

1. 文案 / 品牌 / 設定 / 部署
2. site profile / domain mapping / connector config
3. publish decision path / refresh path / strategic auto-publish path
4. platform mode vs managed site mode

這樣風險最低。

---

## K. GoodBone 零中斷行動方案

以下是我建議的實際執行順序。

## Phase 0：建立基準面與保護欄

目標：在開始抽象化前，先把 GoodBone 當前可運作狀態固化成驗證基準。

### 要做的事

1. 固定一份 production smoke check 清單
2. 固定 admin 核心頁面清單與檢查方式
3. 固定 deploy 後必跑的 health / admin / static / scheduler heartbeat 驗證
4. 把 GoodBone 當前 deployment profile 明確標成 `goodbone`
5. 把現有 production env / nginx / domain mapping 歸檔到 `deploy/goodbone/`

### 驗收標準

1. 每次重構後都能快速確認 GoodBone 無回歸
2. deployment 不再混雜「平台共用」與「GoodBone 專屬」設定

### 風險

低。

### 對 GoodBone 影響

幾乎沒有，只是先把既有狀態制度化。

---

## Phase 1：去除 GoodBone 顯性耦合

目標：先把最表面的單品牌綁定拔掉，但不改 runtime 決策主路徑。

### 要做的事

1. 把 admin UI 中的 `發佈到 GoodBone` 改成 project-aware 文案
2. 把站台模板中的聯絡資訊、品牌名稱、站點描述改成可配置內容
3. 把 `SITE_NAME` / `SITE_DESCRIPTION` 從硬編碼預設轉成 site profile 或 project branding fallback
4. 把 GoodBone 專屬文字與 URL 從模板抽成變數

### 產出物

1. project-aware branding context
2. 可參數化的 site/about/contact 模板
3. GoodBone 品牌資料作為一組 profile，而不是硬寫在程式碼中

### 驗收標準

1. 看起來不再像 GoodBone 專屬工具
2. GoodBone production 頁面輸出不變或只做安全文案替換

### 風險

低。

### 對 GoodBone 影響

很低，只會影響顯示層，不應影響資料或發布流程。

---

## Phase 2：建立 Project-scoped Site Profile

目標：把目前全域 `site_url` / `site_name` / `site_description` 的站點概念，改成 project-aware 的 site profile。

### 要做的事

1. 新增 `site_profiles` 或等價結構
2. 每個 Project 可定義：
   - domain
   - site_name
   - site_description
   - contact_email
   - blog path 規則
   - canonical base URL
3. `admin/article_ops.py` 的 native blog URL 改成 project-scoped site mapping
4. `site_app` 優先讀 project/site profile，缺值時才 fallback 到舊 settings

### 產出物

1. 每個 project 對應自己的站點 profile
2. native publish 不再依賴單一全域站點

### 驗收標準

1. GoodBone 可透過自己的 profile 正常運作
2. 新增第二個 project 時，不需改全域 env 才能有不同站點資訊

### 風險

中低。

### 對 GoodBone 影響

可控，但需雙軌 fallback。

不能直接刪掉舊 `settings.site_url` 讀法，必須先做：

1. project profile 存在時用新路徑
2. 不存在時沿用舊路徑

---

## Phase 3：建立 Project Integration Layer

目標：讓 WordPress / ForgeBase / native site 都成為 per-project connector，而不是全域設定。

### 要做的事

1. 新增 `project_integrations` 或 `project_connectors` 資料表
2. 每個 Project 可掛多種 integration：
   - wordpress
   - forgebase
   - native_site
3. 每個 integration 儲存：
   - base_url
   - credentials reference
   - plugin type
   - publish mode
   - enabled / disabled
   - last health check
4. admin 新增 connector 管理 UI
5. `publishers/wordpress.py` 與 `publishers/forgebase.py` 從 project connector 讀配置，而不是只吃 global settings

### 產出物

1. 真正可多客戶的 CMS 連線模型
2. GoodBone 與未來客戶站可以共存於同一平台 runtime

### 驗收標準

1. 同一套系統能同時管理不同客戶的 WordPress / ForgeBase 站
2. 不必為每個客戶改 `.env` 才能發布

### 風險

中。

### 對 GoodBone 影響

中等，因為這一步開始碰到真實發布路徑。

安全做法是：

1. connector 路徑先新增
2. GoodBone 先自動 mirror 一份現有 global config 到 connector
3. strategic / refresh / publish 先做 `connector > settings fallback`
4. 確認 GoodBone 正常後，再逐步拔掉 global settings 依賴

---

## Phase 4：改造發布決策與刷新決策路徑

目標：把目前依 global settings 判斷 WordPress / ForgeBase / native 的邏輯，改成 per-project decision path。

### 要做的事

1. strategic auto-publish 改為 project connector-driven
2. refresh fetch / publish 改為 project connector-driven
3. article publish flow 改為從 project integration 決定：
   - 哪個平台
   - 哪個站點
   - 哪個 URL policy
4. 加入 connector health check 與 fail-safe

### 驗收標準

1. 不同 project 的文章能被導向各自的 connector
2. GoodBone 仍能正常發布與 refresh

### 風險

中高。

### 對 GoodBone 影響

這是第一個真正碰到 production 決策主路徑的階段。

因此必須：

1. 先在 staging / local fixture 做 connector path 驗證
2. 再在 GoodBone production 做受控 smoke
3. 任何切換都要保留 fallback

---

## Phase 5：拆分 Platform Mode 與 Managed Site Mode

目標：讓 ContentFlow 不再預設自己一定要帶一個內建 public site。

狀態：`已完成`

### 已完成項目

1. 將 `site_app` 明確視為 optional delivery mode，依 `PLATFORM_MODE` 與 `MANAGED_SITE_ENABLED` 決定是否掛載
2. 平台核心保留：
   - admin
   - scheduler
   - strategy
   - knowledge
   - reporting
   - publisher connectors
3. `managed_site` 已成為可開可關的能力，control plane 可以不掛公開站點
4. 部署已分為：
   - control plane deployment
   - managed site deployment

### 驗收標準

1. 平台可服務外部 WordPress 客戶，而不需要自己提供前台站點
2. GoodBone 繼續作為 managed site instance 存在

### 風險

中高。

### 對 GoodBone 影響

若前面幾階段做得正確，這一步對 GoodBone 的影響應該可控。

---

## Phase 6：產品化能力補齊

目標：讓這套系統從工程平台升級成可營運產品。

狀態：`已完成`

### 已完成項目

1. project onboarding flow 已補上 onboarding checklist 與 onboarding wizard
2. connector setup wizard 已補上 connector wizard 與 per-project connector 設定介面
3. connector test / diagnostics 已具備 health status、last diagnostic 與測試動作
4. RBAC / role-based approval 已補上 editor / reviewer / owner 角色與 review gate
5. per-client dashboard / reporting 已補上 project-scoped usage、goal alignment 與 approval history 視圖
6. usage metering / billing basis 已補上 pipeline runs、LLM calls、cost 與 projected monthly cost 基礎
7. audit trail / approval history 已補上 project audit trail 與 approval history 呈現

### 驗收標準

1. 新客戶不需要工程師手改大量設定才能接入
2. 客戶層級的營運與風險控管完整

### 風險

中，但這時風險偏產品交付，不再是 GoodBone 維運風險。

---

## L. 對 GoodBone 風險等級判定

### 幾乎不影響 GoodBone 的工作

1. UI 文案去 GoodBone 化
2. 品牌文案參數化
3. deploy 設定檔整理到 `deploy/goodbone/`
4. 新資料模型先新增但不切換 runtime 讀法

### 需要雙軌相容的工作

1. site profile 導入
2. native publish URL project-aware 化
3. connector data model 導入
4. per-project publish policy 導入

### 現階段不應直接硬切 production 的工作

1. 一次拔掉 global settings 發布設定
2. 一次重寫 site_app 為多租戶 runtime
3. 一次重做 production deployment 模型
4. 一次切換所有文章發布與 refresh 路徑

---

## M. 建議的實際執行順序

如果以「不影響 GoodBone production」為最高原則，這次實際完成的順序如下：

1. Phase 0：建立保護欄與基準面
2. Phase 1：先去掉顯性 GoodBone 綁定
3. Phase 2：導入 site profile，但保留 settings fallback
4. Phase 3：導入 project connectors，但先 mirror GoodBone 現有設定
5. Phase 4：逐步切 strategic / refresh / publish decision path
6. Phase 5：拆出 platform / managed site
7. Phase 6：補齊產品化交付能力

這個順序的核心好處是：

1. 先做低風險高收益
2. 讓 GoodBone 一直能穩定跑
3. 每一步都能用 GoodBone 當 regression benchmark
4. 最後在不拆 repo 的前提下完成第一階段產品獨立化

---

## N. 什麼時候才考慮拆成獨立 repo

只有當以下條件成立，才值得考慮拆 repo：

1. GoodBone 已經只是其中一個 instance，而不是程式碼默認主體
2. connector 已完全 project-scoped
3. 平台核心與 managed site 邊界清楚
4. release cadence 已明顯分離

在這之前，不建議拆成兩個長期平行 repo。

---

## O. 最終執行建議

這份文件到今天為止，已完成它作為第一階段主導文件的任務。

也就是：

1. 上半部是現況判讀
2. 下半部是實際路線圖
3. 而現在 Phase 0 到 Phase 6 已全部完成

因此接下來比較合理的做法，不是再把它當成未完成計劃，而是把它視為第一階段結案文件，並在下一份文件裡規劃第二階段議題，例如：

1. 商業化 pricing / packaging
2. 更細緻的 team / org 管理
3. 外部客戶 onboarding automation
4. 更完整的部署自動化與營運手冊

`換句話說，這份文件現在比較適合被視為：ContentFlow 完成第一階段產品獨立化的結案文件。`
