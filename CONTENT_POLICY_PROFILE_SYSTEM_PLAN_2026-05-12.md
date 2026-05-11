# ContentFlow Policy Profile System 完整實作規劃

日期：2026-05-12

## 一句話結論

ContentFlow 若要從「健康導向 SEO Agent 系統」升級為「可支援多種產業的通用內容營運產品」，最佳方案不是單一的 `industry_config.py`，而是建立一套 **Policy Profile System**。

這套系統應將目前散落在各 Agent 中的「產業偏見」「風險邏輯」「內容型態差異」「客戶客製化設定」抽離成可組合的政策層，讓文章生成流程不再依賴硬寫死的醫療語境。

本文件定義的是 **完整版本** 的落地方案，而不是止血型修補。

---

## 1. 為什麼單一 industry_config 不是最佳解

前一版提出的 `industry_config.py` 方案，適合快速移除明顯的醫療硬寫死，但不適合作為正式上線前的最終架構。

原因如下：

### 1.1 產業不是唯一決策維度

目前系統的差異行為其實同時來自四種不同來源：

1. **領域知識來源**：是否需要 PubMed、是否需要引用專業資料
2. **風險與合規要求**：是否需要免責聲明、是否需要專業審閱、FactCheck 強度
3. **內容型態**：知識文、情境文、產品文、教學文、比較文
4. **專案個別差異**：同樣是醫療客戶，品牌語氣、法規強度、CTA 與圖片風格也可能不同

把以上四種維度全部塞進單一 `industry_config`，會讓設定表不斷膨脹，最後變成新的技術債。

### 1.2 現有資料模型已經透露出多維度設計需求

目前系統內部已經有以下訊號：

1. `Project.industry` 存在，但只是自由輸入文字，無法安全作為正式控制欄位
2. `Article.article_type` 已存在，表示內容型態本來就是獨立維度
3. `reviewer_id` 已存在，但語義被醫療綁定
4. `LegalTerm` 已存在，表示合規內容應由資料驅動，而不是只靠硬編碼

### 1.3 真正的硬寫死分散在不同責任層

目前健康偏見並不是只存在一個地方，而是分散在多個層級：

1. **研究層**：PubMed 與醫療翻譯
2. **寫作層**：醫療免責聲明、醫療審閱者標籤、MedicalWebPage schema
3. **圖片層**：hero image 預設醫療視覺
4. **合規層**：FactCheck 與法規禁用詞目前預設站在醫療/保健語境

這些責任不應透過一個「產業設定字典」同時管理。

---

## 2. 最佳方案：Policy Profile System

### 2.1 核心原則

系統不再問：「這是不是健康產業？」

而是改問：

1. 這個專案屬於哪個 **領域 Domain**？
2. 這篇內容屬於哪種 **風險/合規級別 Compliance**？
3. 這篇內容屬於哪種 **內容型態 Format**？
4. 這個客戶有沒有 **Project Override**？

由這四層組合出最終政策，然後 Agent 只吃政策，不再自己猜測。

---

## 3. 四層模型定義

## 3.1 Domain Profile

用途：描述該專案屬於什麼領域，主要影響知識來源與品牌語境。

建議枚舉值：

1. `health`
2. `law`
3. `finance`
4. `ecommerce`
5. `tech`
6. `food`
7. `education`
8. `general`

負責：

1. 預設 evidence source
2. 預設 hero image 基調
3. 預設 schema 傾向
4. 預設 brand tone 提示

### 例子

| domain | 預設 evidence source | 預設視覺方向 |
|---|---|---|
| `health` | `pubmed` | clinical / clean / professional |
| `law` | `manual_reference` | formal / navy / trustworthy |
| `finance` | `manual_reference` | modern / data-driven / restrained |
| `ecommerce` | `none` | product / studio / conversion-oriented |
| `tech` | `none` | modern / editorial / software-oriented |
| `food` | `none` | warm / appetizing / lifestyle |
| `education` | `none` | educational / infographic |
| `general` | `none` | neutral editorial |

---

## 3.2 Compliance Profile

用途：描述該內容需要什麼程度的合規與審閱要求。

建議枚舉值：

1. `general`
2. `regulated_soft`
3. `ymyl_medical`
4. `ymyl_financial`
5. `ymyl_legal`

負責：

1. 是否需要 disclaimer
2. disclaimer 模板
3. 是否需要 reviewer
4. reviewer label
5. fact check 強度
6. evidence policy
7. forbidden words 是否以 error/warning 呈現

### 例子

| compliance | reviewer required | disclaimer | factcheck mode |
|---|---|---|---|
| `general` | 否 | 無 | `light` |
| `regulated_soft` | 否 | 視內容而定 | `moderate` |
| `ymyl_medical` | 是 | 醫療免責聲明 | `strict` |
| `ymyl_financial` | 是 | 財務免責聲明 | `strict` |
| `ymyl_legal` | 是 | 法律免責聲明 | `strict` |

---

## 3.3 Content Format Profile

用途：描述文章的呈現型態，而不是領域。

建議枚舉值：

1. `knowledge`
2. `scenario`
3. `seasonal`
4. `product`
5. `comparison`
6. `tutorial`
7. `faq_heavy`

負責：

1. Hero image 構圖與提示詞方向
2. JSON-LD 主型別
3. FAQ / HowTo 偏好
4. CTA 形式
5. 寫作架構偏好

### 例子

| format | 主 schema | 圖像方向 |
|---|---|---|
| `knowledge` | `BlogPosting` | editorial / informative |
| `product` | `Product` + `BlogPosting` | product photography |
| `tutorial` | `HowTo` + `BlogPosting` | step-by-step / practical |
| `comparison` | `Article` | comparative / tabular / neutral |
| `faq_heavy` | `FAQPage` + `BlogPosting` | infographic / explanatory |

---

## 3.4 Project Override

用途：讓個別客戶覆蓋預設策略。

可覆寫項目：

1. `disclaimer_template`
2. `reviewer_role_label`
3. `image_style_override`
4. `evidence_policy`
5. `extra_schema_types_json`
6. `factcheck_mode`

此層的優先權最高。

---

## 4. 最終決策流程

每次文章生成時，統一透過一個 resolver 產出最終政策：

```text
Project
  ├─ domain_profile
  ├─ compliance_profile
  ├─ default_content_format
  └─ overrides...

Article / Calendar Entry
  └─ article_type

Resolver
  ├─ merge domain defaults
  ├─ merge compliance defaults
  ├─ merge content format defaults
  └─ apply project overrides

=> ResolvedPolicy
```

Agent 不再自行推論醫療或非醫療，而是只依 `ResolvedPolicy` 做事。

---

## 5. 建議新增的資料模型欄位

## 5.1 Project 表新增欄位

在 `projects` 表新增：

1. `domain_profile`：`String`，預設 `general`
2. `compliance_profile`：`String`，預設 `general`
3. `default_content_format`：`String`，預設 `knowledge`
4. `reviewer_role_label`：`String`，預設空字串
5. `disclaimer_template`：`Text`，預設空字串
6. `evidence_policy`：`String`，預設 `default`
7. `image_style_override`：`Text`，預設空字串
8. `extra_schema_types_json`：`Text`，預設 `[]`
9. `factcheck_mode_override`：`String`，預設空字串

### 為什麼不只用 `industry`

因為 `industry` 應退回成描述性欄位，用於商業分析、UI 顯示、客戶溝通，不應再作為嚴格行為控制欄位。

---

## 5.2 作者/審閱角色模型的調整

目前 `Author.is_medical_reviewer` 命名過於醫療限定。

完整版建議新增：

1. `reviewer_role`：`String`，例如 `medical` / `legal` / `financial`
2. 保留 `is_medical_reviewer` 一段時間作兼容欄位，migration 後逐步淘汰

### 過渡期策略

1. 新程式邏輯優先讀 `reviewer_role`
2. 若 `reviewer_role` 為空且 `is_medical_reviewer=True`，則視為 `medical`
3. 等資料轉完後再清理舊欄位

這樣可避免一次性大破壞。

---

## 6. 建議新增的模組

## 6.1 `src/contentflow/policy_profiles.py`

內容：定義三套 profile 的預設值。

### 結構示意

```python
DOMAIN_PROFILES = {...}
COMPLIANCE_PROFILES = {...}
CONTENT_FORMAT_PROFILES = {...}
```

---

## 6.2 `src/contentflow/policy_resolver.py`

內容：對外提供單一入口：

```python
resolve_policy(project_ctx: ProjectContext, article_type: str | None = None) -> ResolvedPolicy
```

建議使用 dataclass：

```python
@dataclass
class ResolvedPolicy:
    domain_profile: str
    compliance_profile: str
    content_format: str
    use_pubmed: bool
    evidence_policy: str
    require_reviewer: bool
    reviewer_role_label: str
    disclaimer_template: str
    factcheck_mode: str
    base_schema_types: list[str]
    extra_schema_types: list[str]
    hero_image_style: str
    hero_image_type_hint: str
```

此物件是各 Agent 共同依賴的唯一政策來源。

---

## 7. 各模組應如何改造

## 7.1 `project_context.py`

### 現況問題

`project_uses_pubmed(ctx)` 目前透過關鍵字猜測專案是否屬於健康/醫療。

### 完整版改法

1. 保留 `industry` 作為描述性資訊
2. 新增 profile 欄位載入到 `ProjectContext`
3. `project_uses_pubmed(ctx)` 改為：
   - `resolve_policy(ctx).use_pubmed`

### 預期效果

是否使用 PubMed 不再依賴字串猜測，而是明確由 policy 控制。

---

## 7.2 `research_agent.py`

### 現況問題

PubMed 與醫療翻譯邏輯本身正確，但啟用依據過於隱性。

### 完整版改法

1. `use_pubmed` 預設不再靠外部猜測
2. 若呼叫端未傳入，則由 `ResolvedPolicy.use_pubmed` 決定
3. `_translate_keywords_for_pubmed()` 只在 `use_pubmed=True` 時啟用
4. 若 `evidence_policy` 是 `manual_reference`，則未來可切至法律條文、金融資料等其他來源

---

## 7.3 `writing_agent.py`

### 需要改的三個核心區塊

#### A. Article Schema

目前：健康類才追加 `MedicalWebPage`

改法：

1. 基底 schema 類型來自 `ResolvedPolicy.base_schema_types`
2. project override 可再附加 `extra_schema_types`
3. `MedicalWebPage` 不再寫死在 writing agent

#### B. E-E-A-T 區塊

目前：健康類才追加，而且 reviewer label 與 disclaimer 都寫死醫療語言

改法：

1. 是否需要 E-E-A-T 區塊由 `ResolvedPolicy.require_reviewer` 或 `disclaimer_template` 決定
2. reviewer 標籤由 `ResolvedPolicy.reviewer_role_label` 決定
3. disclaimer 內容由 `ResolvedPolicy.disclaimer_template` 決定
4. 若兩者皆無，則不插入區塊

#### C. CTA 與內容語氣

目前 CTA 只依 funnel stage 決定，與產業風險無關

改法：

1. 短期不需要大改
2. 僅保留未來可由 policy 調整 CTA 語氣與行動門檻

---

## 7.4 `hero_image_agent.py`

### 現況問題

目前 prompt 與風格完整寫死在醫療語境。

### 完整版改法

圖片最終提示詞不應只看 domain，而應同時看：

1. `content_format`
2. `domain_profile`
3. `image_style_override`

### 決策順序

1. 若 Project 有 `image_style_override`，直接使用
2. 否則先取 `content_format` 的主構圖方向
3. 再用 `domain_profile` 做語境修飾

### 範例

| domain | format | 圖像結果 |
|---|---|---|
| `health` | `knowledge` | clinical infographic |
| `health` | `scenario` | wellness lifestyle scene |
| `ecommerce` | `product` | studio product shot |
| `law` | `knowledge` | formal editorial illustration |
| `tech` | `tutorial` | modern software tutorial visual |

這樣圖片風格才不會被產業單一維度綁死。

---

## 7.5 `factcheck_agent.py`

### 現況問題

禁用詞表與審核語氣偏向醫療/保健，但其實基礎結構已經足夠。

### 完整版改法

1. `_check_forbidden_words()` 的嚴格程度改由 `ResolvedPolicy.factcheck_mode` 控制
2. `supporting_evidence` 與 reviewer note 的模板改由 compliance profile 決定
3. 法規資料來源仍優先來自 DB `LegalTerm`
4. 合規 profile 只決定「怎麼處理」，不取代實際資料

這是非常重要的原則：

**policy 決定處理方式，資料表提供真實規則內容。**

---

## 8. Admin 設定頁如何改

目前 `industry` 是一個自由輸入欄位，不夠正式。

完整版應在設定頁新增以下欄位：

1. `domain_profile`：下拉選單
2. `compliance_profile`：下拉選單
3. `default_content_format`：下拉選單
4. `reviewer_role_label`：文字輸入
5. `disclaimer_template`：textarea
6. `evidence_policy`：下拉選單
7. `image_style_override`：textarea
8. `extra_schema_types_json`：textarea
9. `factcheck_mode_override`：下拉選單

### `industry` 欄位的處理

保留，但降級為「描述性資訊」：

1. 客戶產業描述
2. 對外商業報表
3. 搜尋與篩選

不再作為嚴格邏輯依據。

---

## 8.1 Admin 後台介面規劃

這一段不是單純「加幾個欄位」，而是完整定義 **上線版管理介面的資訊架構與操作流程**。

核心目標只有三個：

1. **最少必要手動設定**：建立專案時只填會影響風險與品質的主欄位
2. **高風險設定要明確可見**：合規、免責聲明、審閱角色不可隱性推論
3. **進階客製化不干擾一般使用者**：大多數客戶只需要預設值，少數客戶才進入 advanced mode

---

## 8.2 設定頁資訊架構

現有設定頁已經有良好的基本骨架：

1. 專案資訊
2. 內容策略
3. 撰寫規範
4. 法規合規
5. 整合設定

完整版不需要推翻重做，而是在 `專案資訊` 頁籤中新增一個 **Policy Setup 區塊**，並在頁面上拆成三層。

### Layer A：Project Basics

保留目前已存在的欄位：

1. 專案名稱
2. Slug
3. 品牌名稱
4. 品牌網址
5. 站點聯絡信箱
6. 文章路徑前綴
7. 品牌描述
8. SERP 國家 / 語言

這一層的定位是「品牌與站點基本資料」，不放政策欄位。

### Layer B：Policy Setup

新增一個明確的卡片區塊，名稱建議為：

`內容政策設定 Content Policy`

這一層只放 3 個 **必填主欄位**：

1. `domain_profile`
2. `compliance_profile`
3. `default_content_format`

這三個欄位決定 80% 以上的行為差異，應該在 onboarding 時明確設定。

### Layer C：Advanced Overrides

預設折疊，名稱建議為：

`進階覆寫 Advanced Overrides`

只放少數客戶才需要的設定：

1. `reviewer_role_label`
2. `disclaimer_template`
3. `evidence_policy`
4. `image_style_override`
5. `extra_schema_types_json`
6. `factcheck_mode_override`

這樣可以避免一般使用者一進設定頁就看到過多欄位。

---

## 8.3 建立新專案的 Onboarding UI

不建議在「新增專案」小面板一次塞所有欄位。最佳做法是改成 **兩階段建立**。

### Step 1：快速建立專案

建立時只填：

1. 專案名稱
2. Slug
3. 品牌網址
4. 品牌名稱

建立成功後，自動導到：

`/admin/settings?project_id=...#policy-setup`

### Step 2：政策設定精靈

建立後立即顯示一個 `Policy Setup Wizard`，用 3 個步驟完成高風險設定：

1. 選擇 Domain
2. 選擇 Compliance
3. 選擇 Default Content Format

每一步都應提供：

1. 簡短說明
2. 適用範例
3. 會啟用哪些功能

例如：

| 欄位 | 選項 | UI 說明 |
|---|---|---|
| Domain | `health` | 啟用學術證據來源與健康類預設語境 |
| Domain | `ecommerce` | 關閉學術資料，偏向產品與轉換導向內容 |
| Compliance | `ymyl_medical` | 加入醫療免責聲明、要求專業審閱、FactCheck 嚴格 |
| Compliance | `general` | 不加高風險免責聲明，使用一般內容審核 |
| Format | `knowledge` | 一般知識型文章，預設 BlogPosting |
| Format | `product` | 產品介紹頁，偏 Product schema 與產品型圖片 |

---

## 8.4 欄位設計：必填、選填、系統推導

### 必填欄位

這些欄位必須由管理者明確選擇，不應完全自動猜測：

1. `domain_profile`
2. `compliance_profile`
3. `default_content_format`

原因：

1. 猜錯代價高
2. 變動頻率低
3. 對整體輸出影響最大

### 選填欄位

這些欄位只在需要客製化時才輸入：

1. `reviewer_role_label`
2. `disclaimer_template`
3. `image_style_override`
4. `extra_schema_types_json`
5. `factcheck_mode_override`

### 系統推導欄位

這些不應要求使用者手動逐篇填寫：

1. Hero image 細部構圖
2. FAQ / HowTo 偏好
3. CTA 類型
4. Article schema 細節
5. 文章層是否採用 Product / Tutorial 傾向

這些應由 policy resolver 根據 project + article_type 自動推導。

---

## 8.5 建議的表單元件設計

### `domain_profile`

UI 元件：單選卡片或下拉選單。

若選單項目不超過 6 個，建議使用 **卡片式單選**，比一般 select 更清楚。

建議顯示：

1. 標題：`Health` / `Law` / `Finance`
2. 副標：一句說明
3. 啟用功能提示，例如 `PubMed / 高風險審閱 / Product-first`

### `compliance_profile`

UI 元件：強提示單選卡片。

這是高風險欄位，不能藏在普通 select。

每個選項應顯示：

1. 是否要求 reviewer
2. 是否加入 disclaimer
3. FactCheck 強度

### `default_content_format`

UI 元件：tab-like segmented control 或 select。

因為選項屬於內容風格，使用 segmented control 會比冗長表單更直觀。

### `disclaimer_template`

UI 元件：textarea，旁邊要有「使用預設模板 / 自訂模板」切換。

建議預設狀態：

1. `Use compliance default` 為預設
2. 只有勾選 `Custom` 才展開 textarea

### `extra_schema_types_json`

UI 元件：不建議直接暴露原始 JSON 給一般使用者。

建議做法：

1. 簡化為多選 checklist，例如 `Product`, `FAQPage`, `HowTo`, `MedicalWebPage`
2. 後端再轉成 JSON 存儲

這樣可降低輸入錯誤。

---

## 8.6 角色權限規劃

這些欄位不是所有角色都能修改。

建議權限如下：

| 欄位區塊 | owner | reviewer | editor |
|---|---|---|---|
| Project Basics | 可編輯 | 唯讀 | 唯讀 |
| Policy Setup | 可編輯 | 唯讀 | 唯讀 |
| Advanced Overrides | 可編輯 | 唯讀 | 隱藏或唯讀 |
| Preview / effective policy | 可查看 | 可查看 | 可查看 |

理由：

1. Policy 設定會直接影響對外內容風險，不應由 editor 任意變更
2. Reviewer 應看得到有效政策，以理解為何某篇文章被套上某種審閱與免責聲明

---

## 8.7 必要的即時預覽功能

如果要讓後台介面真正可用，不能只給表單，一定要有 **effective policy preview**。

建議在 `Policy Setup` 卡片右側加一個預覽面板，顯示當前設定會產生什麼結果：

1. 是否啟用 PubMed：Yes / No
2. FactCheck mode：light / moderate / strict
3. Reviewer label：例如 醫療審閱 / 法律審閱 / 無
4. Disclaimer：使用預設 / 自訂 / 無
5. Hero image style：顯示文字摘要
6. Schema 預設：BlogPosting / Product / MedicalWebPage ...

這樣管理者不用腦內推理設定結果。

---

## 8.8 文章層級的 Override UI

大部分設定應停留在 project 層，但仍應保留文章層的少量 override。

建議放在文章編輯頁的「進階設定」區塊，而不是主表單。

文章層只開放：

1. content format override
2. reviewer required override
3. custom disclaimer override
4. extra schema types override

不建議文章層開放：

1. domain_profile override
2. compliance_profile 完整重選

除非是 internal admin，否則會讓行為過於混亂。

---

## 8.9 表單驗證與保護機制

為了避免設定錯誤，後台需要明確保護：

1. `domain_profile` / `compliance_profile` / `default_content_format` 必填
2. `reviewer_role_label` 若填寫，限制長度與字符集
3. `disclaimer_template` 若自訂，不可為空白
4. `extra_schema_types_json` 若仍採 JSON，必須後端驗證為 list of strings
5. `factcheck_mode_override` 只能是受控枚舉值

另外要有邏輯警告：

1. 若 `compliance_profile = ymyl_medical` 但專案沒有 reviewer，可顯示 warning
2. 若 `domain_profile = health` 但 evidence policy 被關閉，也要顯示 warning
3. 若 `default_content_format = product` 但沒有任何 publish connector，也可以提示使用者

---

## 8.10 正式上線版 UI 必備範圍

本案既然是下個月正式對外販售的產品，後台介面不應以 MVP 標準交付，而應以 **正式商用上線標準** 實作。

正式上線版後台至少必須包含：

1. `Policy Setup` 區塊
2. 3 個必填主欄位（`domain_profile` / `compliance_profile` / `default_content_format`）
3. `Advanced Overrides` 折疊區塊
4. `Effective Policy Preview` 摘要框
5. 欄位級 validation
6. 邏輯級 warning
7. onboarding wizard
8. role-based permissions
9. article-level override UI
10. 儲存後的 effective policy 回顯

缺少以上任一項，都不應視為正式完成的上線版介面。

---

## 8.11 最終 UI 判定原則

這套 Admin 介面應遵守以下原則：

1. **高風險設定要顯眼**，不能埋在自由文字欄位裡
2. **進階客製化要可做，但預設要簡單**
3. **設定後要能看見結果**，不能只有表單沒有 preview
4. **Project 層為主，Article 層為輔**，避免每篇文章都重設政策
5. **policy 是產品能力，不是工程內部概念**，所以後台必須把它做成可理解的語言與流程

---

## 9. Migration 規劃

## 9.1 新增 migration：Project policy 欄位

新增 migration，例如：

`017_add_project_policy_profiles.py`

內容：

1. projects 增加 9 個欄位
2. 對既有專案做 backfill

### backfill 策略

對現有資料：

1. 若 `industry`、品牌描述、寫作規範中出現健康/醫療訊號，預設：
   - `domain_profile = health`
   - `compliance_profile = ymyl_medical`
   - `default_content_format = knowledge`
2. 其他專案：
   - `domain_profile = general`
   - `compliance_profile = general`
   - `default_content_format = knowledge`

這樣 GoodBone 可自動延續目前行為，不會因 migration 破壞。

## 9.2 新增 migration：Author reviewer role

例如：

`018_add_author_reviewer_role.py`

內容：

1. authors 增加 `reviewer_role`
2. 將 `is_medical_reviewer=True` 的資料回填為 `medical`

### 過渡期兼容

舊欄位先保留，不立刻移除。

---

## 10. 實作順序（完整版本）

## Phase A：建立政策核心

1. 新增 `policy_profiles.py`
2. 新增 `policy_resolver.py`
3. 擴充 `ProjectContext`，加入新的 profile 欄位
4. 撰寫核心 resolver 測試

## Phase B：資料模型與 migration

1. 更新 `Project` ORM
2. 更新 `Author` ORM
3. 新增 Alembic migration `017`
4. 新增 Alembic migration `018`
5. 更新 `save_project` 後台儲存邏輯
6. 更新設定頁表單欄位

## Phase C：改 Agent 接點

1. `project_context.py`
2. `research_agent.py`
3. `writing_agent.py`
4. `hero_image_agent.py`
5. `factcheck_agent.py`

## Phase D：回歸測試與驗證

1. 新增政策單元測試
2. 新增 hero image prompt 測試
3. 新增 E-E-A-T / disclaimer 測試
4. 新增 schema type 測試
5. 新增 health / legal / ecommerce 三個代表案例測試

---

## 11. 驗收標準

完整版本完成後，至少應滿足以下條件：

### A. 健康類專案

1. 仍會啟用 PubMed
2. 仍會加上醫療 disclaimer
3. 仍會加上 `MedicalWebPage`
4. Hero image 仍符合醫療可信風格

### B. 法律類專案

1. 不會啟用 PubMed
2. 會加上法律 disclaimer
3. reviewer label 顯示為法律審閱
4. Hero image 不會出現醫療視覺

### C. 電商類專案

1. 不會啟用 PubMed
2. 預設不加 YMYL disclaimer
3. `product` 文章可套 `Product` 類 schema
4. Hero image 會偏向產品攝影，而不是醫療插圖

### D. 一般內容專案

1. 不會被誤套醫療語氣
2. 不會被誤加醫療 disclaimer
3. 圖片與 schema 皆為中性預設

---

## 12. 風險與注意事項

### 12.1 最大風險不是 migration，而是遺漏 agent 分支

若只改資料模型，但忘記某個 agent 裡的硬寫死，最後會出現：

1. DB 看起來很完整
2. 但實際輸出仍帶醫療語氣

因此 implementation 一定要以「從 resolver 出發」的方式逐模組替換，而不是只加欄位。

### 12.2 GoodBone 相容性

本案明確不以 GoodBone 為最終產品，但 migration 與預設值仍應讓 GoodBone 在過渡期可正常工作。

也就是：

1. GoodBone 可以被視為既有健康類客戶
2. 但整套系統最終目標不是繼續圍繞 GoodBone 最佳化

### 12.3 正式上線範圍要明確，不做假性全產業承諾

完整版本不代表第一天就支援 30 種產業，而是代表：

1. **有明確的正式支援範圍**
2. **被列入支援範圍的產業是 production-ready**
3. **不在支援清單內的產業，不對外銷售承諾**

因此正式上線版建議明確支援：

1. `health`
2. `law`
3. `finance`
4. `ecommerce`
5. `tech`
6. `general`

這六類不是「試做」，而是 **Release 1 正式支援矩陣**。

若未來要擴充 `food`、`education` 等其他 domain，屬於 Release 2 之後的產品擴編，而不是拿未完成支援去對外販售。

---

## 13. 最終判定

若目標是「上線前做出真正可擴展、可賣、可支援多客戶多產業的產品」，

**最佳方案不是單一 industry_config，而是 Policy Profile System。**

這個方案的優點是：

1. 不會把不同責任混在一起
2. 與現有資料模型相容
3. 能在既有架構上完整落地，不需要推翻全系統重寫
4. 能讓 Agent 的邏輯變得簡單：只依政策，不自己猜
5. 為未來白牌、SaaS、自助開戶與多產業擴展保留空間

---

## 14. 正式上線完成定義

這份規劃應被視為 **正式商用上線版的完整實作規格**，不是 MVP。

要達到「完整實作」而非「MVP」的標準，至少必須同時完成以下四層：

### A. 資料層

1. `projects` policy 欄位 migration 完成
2. `authors.reviewer_role` migration 完成
3. 既有資料 backfill 完成
4. ORM / schema / persistence 全部對齊

### B. 政策層

1. `policy_profiles.py` 完成
2. `policy_resolver.py` 完成
3. Domain / Compliance / Format / Override 的 merge 規則完成
4. 全部受控枚舉與 validation 完成

### C. 介面層

1. Admin 設定頁完成
2. onboarding wizard 完成
3. effective policy preview 完成
4. article-level override UI 完成
5. 角色權限控管完成

### D. 執行層

1. `project_context.py` 完成切換
2. `research_agent.py` 完成切換
3. `writing_agent.py` 完成切換
4. `hero_image_agent.py` 完成切換
5. `factcheck_agent.py` 完成切換

只完成其中一部分，不得宣稱此計畫已完整落地。

---

## 15. Release 1 商用驗收清單

若下個月要正式上線對外販售，建議將以下列為 release gate：

1. 六類正式支援 domain 的代表案例測試全部通過
2. 健康類不退化，非健康類不再誤用醫療語境
3. 後台 owner 可完整設定 policy，reviewer 可查看 effective policy
4. 新建專案可在 onboarding 流程中完成 policy 設定
5. 所有 migration 在 PostgreSQL 正式環境可無痛執行
6. 398+ 測試維持綠燈，並新增 policy system 專屬測試
7. 至少完成一輪 staging 模擬：建立新 domain 專案、生成文章、驗證 schema、驗證 disclaimer、驗證 hero image prompt

未達以上 release gate，不建議以「正式對外販售版本」名義上線。

---

## 16. 直接執行建議

若要正式開始完整版本實作，建議按以下順序開工：

1. 先建立 `policy_profiles.py` + `policy_resolver.py`
2. 再補 `Project` 與 `Author` 的政策欄位 migration
3. 接著改 `project_context.py`、`writing_agent.py`、`hero_image_agent.py`
4. 最後再改 `research_agent.py` 與 `factcheck_agent.py`

這個順序可以最快把「醫療硬寫死」移除，同時讓新架構站穩。
