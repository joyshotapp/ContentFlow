"""Writing Agent：根據研究報告 + 撰寫規範，自動產出 SEO 文章初稿

全程使用 GPT-4o-mini（低成本），每篇約 $0.02-0.05。
"""

from __future__ import annotations

import json
import re
from loguru import logger
from openai import OpenAI

from ..config import settings
from ..models import ResearchReport, ArticleDraft, ArticleOutline, ArticleStatus
from ..project_context import ProjectContext, load_project_context, project_uses_pubmed


def _get_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _chat(client: OpenAI, system: str, user: str, temperature: float = 0.7) -> str:
    """單次 GPT-4o-mini 呼叫"""
    resp = client.chat.completions.create(
        model=settings.llm_lite_model,  # gpt-4o-mini
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_completion_tokens=4096,
    )
    return resp.choices[0].message.content or ""


# ── 系統 Prompt 組裝 ──────────────────────────────────────────

def _build_brand_context_from_project(ctx: ProjectContext) -> str:
    """從專案上下文組裝品牌知識 Prompt"""
    return ctx.build_brand_prompt()


def _build_research_summary(report: ResearchReport) -> str:
    """將研究報告濃縮為寫作素材"""
    parts = []
    parts.append(f"# 研究報告：{report.article_title}")
    parts.append(f"關鍵字：{', '.join(report.keywords[:10])}")
    parts.append("")

    if report.pubmed_results:
        parts.append("## PubMed 文獻")
        for result in report.pubmed_results:
            for article in result.articles[:5]:
                parts.append(f"- [{article.pmid}] {article.title}")
                if article.abstract:
                    parts.append(f"  摘要：{article.abstract[:400]}")
        parts.append("")

    if report.serp_analysis:
        parts.append("## Google 搜尋結果分析")
        for r in report.serp_analysis.top_results[:5]:
            parts.append(f"- #{r.position} {r.title}")
            if r.headings:
                parts.append(f"  標題結構：{' | '.join(r.headings[:6])}")
        parts.append("")

        if report.serp_analysis.people_also_ask:
            parts.append("## People Also Ask")
            for paa in report.serp_analysis.people_also_ask[:5]:
                parts.append(f"- {paa.question}")
            parts.append("")

    if report.suggested_keywords:
        parts.append(f"## 推薦關鍵字：{', '.join(report.suggested_keywords[:15])}")

    return "\n".join(parts)


# ── 策略指引組裝 ──────────────────────────────────────────────

def _build_strategy_block(strategy_context: dict | None) -> str:
    """將 SEO 專員的策略欄位轉換為 LLM prompt 區塊"""
    if not strategy_context:
        return ""
    parts = ["# SEO 策略指引（來自 SEO 專員的選題分析）"]
    if strategy_context.get("search_intent"):
        parts.append(f"- 搜尋意圖：{strategy_context['search_intent']}")
    if strategy_context.get("target_audience"):
        parts.append(f"- 讀者切入點（痛點）：{strategy_context['target_audience']}")
    if strategy_context.get("writing_architecture"):
        parts.append(f"- 架構策略：{strategy_context['writing_architecture']}")
    if strategy_context.get("faq_questions"):
        parts.append(f"- 建議 FAQ：{strategy_context['faq_questions']}")
    if len(parts) == 1:
        return ""
    return "\n".join(parts) + "\n"


# ── Step 1: 生成大綱 ──────────────────────────────────────────

def _generate_outline(
    client: OpenAI,
    report: ResearchReport,
    brand_context: str,
    writing_arch: str = "",
    target_word_count: int = 1800,
    strategy_context: dict | None = None,
) -> str:
    # 組裝策略指引區塊
    strategy_block = _build_strategy_block(strategy_context)

    system = f"""你是專業的 SEO 文章大綱規劃師。

{brand_context}

根據研究報告，產出一份 SEO 優化的文章大綱。

架構指引：{writing_arch if writing_arch else '依內容類型自動選擇（倒三角/金字塔SCQA/思維流程/敘事型）'}
{strategy_block}
要求：
1. 產出 JSON 格式，包含 title, meta_description, sections
2. 每個 section 包含 h2, h3s (array), keywords (array)
3. 建議字數 {target_word_count} 字
4. 必須包含 FAQ 段落（回答 People Also Ask 問題）
5. meta_description 控制在 120-155 字元
6. 標題包含主關鍵字、吸引點擊
7. 使用繁體中文
8. 嚴禁使用法規紅線中列出的禁用詞彙

回傳純 JSON，不要 markdown code block。"""

    research = _build_research_summary(report)
    user = f"研究報告：\n{research}\n\n請產出文章大綱 JSON。"
    raw = _chat(client, system, user, temperature=0.5)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


# ── Step 2: 逐段撰寫文章 ─────────────────────────────────────

def _write_section(
    client: OpenAI,
    section: dict,
    report: ResearchReport,
    brand_context: str,
    article_title: str,
    prev_sections_summary: str = "",
    strategy_context: dict | None = None,
) -> str:
    strategy_block = _build_strategy_block(strategy_context)

    system = f"""你是專業的 SEO 內容撰寫者。

{brand_context}
{strategy_block}
寫作風格：
- 繁體中文，口吻溫暖專業、像朋友聊天但有根據
- 如有學術文獻，適度引用（用括號標注來源）
- 使用短句、分段清楚、條列重點用 Markdown 清單（- 或 1.）
- 每段 200-400 字
- 嚴格遵守品牌核心原則與法規紅線

輸出格式規定（嚴格遵守）：
- 禁止使用任何 emoji 符號（❌✅💪🌱 等全部禁止）
- H3 標題（###）只用於結構性子段落，禁止用作編號清單項目（需要編號請用 1. 2. 3.）
- 輸出只有文章內容，禁止在結尾加任何對話語、確認語或問候語（「希望這段內容...」「如果有任何修改...」「隨時告訴我...」等全禁）
- 所有小節標題用 ### 但不超過 2 個層級（## 和 ### 即可）"""

    h3_list = "\n".join(f"  - H3: {h3}" for h3 in section.get("h3s", []))
    keywords = ", ".join(section.get("keywords", []))

    user = f"""文章標題：{article_title}

目前段落：
- H2: {section.get('h2', '')}
{h3_list}
- 需涵蓋關鍵字：{keywords}

{f'前文摘要：{prev_sections_summary}' if prev_sections_summary else ''}

研究素材（請自然引用）：
{_build_research_summary(report)[:3000]}

請撰寫這個段落的完整內容（Markdown 格式，含 H2/H3 標題）。"""

    raw = _chat(client, system, user, temperature=0.7).strip()
    # 去除 GPT 可能加上的 code fence（```markdown ... ``` 或 ``` ... ```）
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return _clean_gpt_artifacts(raw.strip())


# ── GPT 輸出清潔 ─────────────────────────────────────────────

import re as _re
import unicodedata as _ud

_GPT_ARTIFACT_PATTERNS = [
    # GPT 結尾問候/確認語（繁簡中文通用）
    _re.compile(r'^(希望|以上是|以上內容|如果有任何|如有任何|如需任何|隨時告訴|歡迎隨時|請隨時|若您有|如您有|如果您有|您有任何|任何問題).{0,60}[！!。]?\s*$', _re.MULTILINE),
    # 「希望這段內容能符合您的需求」變體
    _re.compile(r'^希望.{0,30}(需求|幫助|滿意|參考|有用|實用).{0,20}[！!。]?\s*$', _re.MULTILINE),
]

_EMOJI_RANGES = [
    (0x1F600, 0x1F64F), (0x1F300, 0x1F5FF), (0x1F680, 0x1F6FF),
    (0x1F700, 0x1F77F), (0x1F780, 0x1F7FF), (0x1F800, 0x1F8FF),
    (0x1F900, 0x1F9FF), (0x1FA00, 0x1FA6F), (0x1FA70, 0x1FAFF),
    (0x2600,  0x26FF),  (0x2700,  0x27BF),  (0x23E9,  0x23FF),
    (0x231A,  0x231B),  (0x25AA,  0x25FE),  (0x2614,  0x2615),
    (0xFE00,  0xFE0F),  # variation selectors
]

def _strip_emoji(text: str) -> str:
    """移除所有 emoji 字元（保留中文、標點、一般符號）"""
    chars = []
    for ch in text:
        cp = ord(ch)
        is_emoji = any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)
        if not is_emoji:
            chars.append(ch)
    # 清除連續空白
    return _re.sub(r'  +', ' ', ''.join(chars))


def _clean_gpt_artifacts(text: str) -> str:
    """移除 GPT 生成的對話語、emoji、以及規範化 H3 編號標題"""
    # 1. 移除對話語
    for pattern in _GPT_ARTIFACT_PATTERNS:
        text = pattern.sub('', text)

    # 2. 移除 emoji
    text = _strip_emoji(text)

    # 3. 修正 ### 被用作編號清單的反模式：
    #    「### 1. 正文內容」→「### 正文內容」（但保留純結構標題）
    #    實際上：若 H3 標題以數字+點開頭，改為有序清單
    def fix_numbered_h3(m):
        level = m.group(1)  # ## or ###
        num   = m.group(2)  # 1. or 2.
        rest  = m.group(3).strip()
        # H2 不動；H3 + 數字 → 改為 H3（去掉數字，讓 GPT 的數字意圖保留在標題語意中）
        return f"{level} {rest}"
    text = _re.sub(r'^(#{2,3})\s+(\d+[.、])\s+(.+)$', fix_numbered_h3, text, flags=_re.MULTILINE)

    # 4. 清除多餘空行
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Step 3: Meta tags ─────────────────────────────────────────

def _generate_meta(client: OpenAI, title: str, content: str, keywords: list[str]) -> dict:
    system = """你是 SEO meta tag 專家。產出 JSON 格式：
{"meta_title": "...", "meta_description": "..."}

規則：
- meta_title: 30-60 字元，含主關鍵字，吸引點擊
- meta_description: 120-155 字元，含主關鍵字，有行動呼籲
- 使用繁體中文
回傳純 JSON。"""

    user = f"文章標題：{title}\n關鍵字：{', '.join(keywords[:5])}\n文章摘要：{content[:1000]}"
    raw = _chat(client, system, user, temperature=0.3)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"meta_title": title, "meta_description": ""}


# ── Step 4: SEO URL Slug ──────────────────────────────────────

def _generate_slug(client: OpenAI, article_title: str) -> str:
    """將文章標題轉換為 SEO 友善的英文 URL slug。"""
    try:
        resp = client.chat.completions.create(
            model=settings.llm_lite_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Convert the given Chinese article title to an SEO URL slug. "
                        "Rules: lowercase English only, 3-5 words, hyphens between words, "
                        "no stop words, no special characters. "
                        "Return ONLY the slug. Example: 'bone-spur-causes-treatment'"
                    ),
                },
                {"role": "user", "content": article_title},
            ],
        )
        raw = (resp.choices[0].message.content or "").strip().lower()
        slug = re.sub(r"[^a-z0-9-]", "-", raw)
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        return slug or "article"
    except Exception as e:
        logger.warning(f"[Writing Agent] slug 生成失敗：{e}")
        return "article"


# ── Step 5: FAQ JSON-LD Schema ────────────────────────────────

def _generate_faq_schema(content_markdown: str) -> str:
    """從文章 Markdown 中的 FAQ 段落，產出 FAQPage JSON-LD structured data。

    解析規則：
    - 找到 ## FAQ 或 ## 常見問題 段落
    - 每個 ### 標題視為一個問題
    - ### 標題下方的段落文字視為答案
    """
    faq_match = re.search(
        r'^##\s+(?:FAQ|常見問題)[^\n]*\n(.*?)(?=^##\s|\Z)',
        content_markdown,
        re.MULTILINE | re.DOTALL,
    )
    if not faq_match:
        return ""

    faq_block = faq_match.group(1)
    parts = re.split(r'^###\s+', faq_block, flags=re.MULTILINE)

    qa_pairs = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        lines = part.splitlines()
        # 第一行是問題（去除前置編號/Q:）
        question = re.sub(r'^[QqAa]?\d*[.、：:\s]+', '', lines[0]).strip()
        # 收集答案段落（最多 150 字）
        answer_lines = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                break
            if stripped.startswith(("- ", "* ")):
                stripped = stripped[2:]
            if stripped:
                answer_lines.append(stripped)
        answer = " ".join(answer_lines)[:200].strip()
        if question and answer and len(question) >= 3:
            qa_pairs.append({"q": question, "a": answer})

    if not qa_pairs:
        return ""

    schema = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": pair["q"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": pair["a"],
                },
            }
            for pair in qa_pairs
        ],
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


# ── Step 5b: Article/BlogPosting JSON-LD ──────────────────────

def _generate_article_schema(
    title: str,
    meta_description: str,
    slug: str,
    word_count: int,
    ctx: ProjectContext,
) -> str:
    """產出 Article (BlogPosting) JSON-LD structured data。

    包含 headline, description, author, publisher, datePublished 等
    Google 識別文章所需的基本欄位。
    """
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "BlogPosting",
        "headline": title[:110],
        "description": meta_description[:200],
        "wordCount": word_count,
        "inLanguage": ctx.locale or "zh-TW",
    }

    # 發布 URL（若有 slug + 品牌 URL 可組合）
    if slug and ctx.brand_url:
        base = ctx.brand_url.rstrip("/")
        schema["url"] = f"{base}/blog/{slug}"
        schema["mainEntityOfPage"] = {"@type": "WebPage", "@id": schema["url"]}

    # 作者佔位（CMS 發布時替換）
    schema["author"] = {
        "@type": "Person",
        "name": "<!-- TODO: 作者姓名 -->",
    }

    # 出版者（品牌資訊）
    if ctx.brand_name:
        publisher: dict = {"@type": "Organization", "name": ctx.brand_name}
        if ctx.brand_url:
            publisher["url"] = ctx.brand_url
        schema["publisher"] = publisher

    # 日期佔位
    schema["datePublished"] = "<!-- TODO: 發布日期 YYYY-MM-DD -->"
    schema["dateModified"] = "<!-- TODO: 修改日期 YYYY-MM-DD -->"

    # YMYL 醫療類加上 MedicalWebPage type
    if project_uses_pubmed(ctx):
        schema["@type"] = ["BlogPosting", "MedicalWebPage"]

    return json.dumps(schema, ensure_ascii=False, indent=2)


# ── Step 5c: HowTo JSON-LD Schema ─────────────────────────────

def _generate_howto_schema(content_markdown: str, title: str) -> str:
    """從文章 Markdown 中偵測步驟型內容，產出 HowTo JSON-LD structured data。

    偵測規則：
    - 文中存在一個 H2 段落，內容含有「步驟」「方法」「做法」「如何」「教學」「流程」
    - 該段落下有至少 3 個有序清單項目（1. / 2. 開頭）或 H3 小節
    - 符合條件才產出 HowTo，避免誤判說明性文章
    """
    # 找出含有步驟意圖的 H2 段落
    step_intent_re = re.compile(
        r'^(##\s+(?:[^\n]*(?:步驟|方法|做法|如何|教學|流程|操作|技巧)[^\n]*)\n)(.*?)(?=^##\s|\Z)',
        re.MULTILINE | re.DOTALL,
    )
    match = step_intent_re.search(content_markdown)
    if not match:
        return ""

    section_header = match.group(1).strip().lstrip('#').strip()
    section_body = match.group(2)

    # 嘗試提取有序清單步驟
    ol_steps = re.findall(r'^\d+[.、]\s+(.+)', section_body, re.MULTILINE)

    # 嘗試提取 H3 作為步驟
    h3_steps: list[str] = []
    h3_blocks = re.split(r'^###\s+', section_body, flags=re.MULTILINE)
    for block in h3_blocks[1:]:  # skip leading text before first H3
        lines = block.splitlines()
        if lines:
            step_title = lines[0].strip()
            step_text = ' '.join(
                l.strip() for l in lines[1:] if l.strip() and not l.startswith('#')
            )[:200]
            h3_steps.append((step_title, step_text))

    # 優先使用 H3 步驟（結構更完整），其次才用有序清單
    if len(h3_steps) >= 3:
        how_to_steps = [
            {
                "@type": "HowToStep",
                "name": s[0],
                "text": s[1] if s[1] else s[0],
            }
            for s in h3_steps
        ]
    elif len(ol_steps) >= 3:
        how_to_steps = [
            {"@type": "HowToStep", "text": s}
            for s in ol_steps
        ]
    else:
        return ""  # not enough steps → skip

    schema = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": title,
        "step": how_to_steps,
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


# ── Step 5d: CTA 注入（SEO × CRO）──────────────────────────────

_CTA_TEMPLATES: dict[str, dict] = {
    "informational": {
        "heading": "延伸學習",
        "text": (
            "如果你想深入了解，歡迎參閱我們的完整指南，"
            "裡面涵蓋更多實用資訊與工具建議。"
        ),
        "link_text": "查看完整指南",
        "link_placeholder": "<!-- TODO: 填入指南連結 -->",
    },
    "investigational": {
        "heading": "免費諮詢",
        "text": (
            "還有疑問？歡迎預約免費諮詢，"
            "專業團隊將根據你的情況提供個人化建議。"
        ),
        "link_text": "預約免費諮詢",
        "link_placeholder": "<!-- TODO: 填入諮詢連結 -->",
    },
    "transactional": {
        "heading": "立即行動",
        "text": (
            "準備好開始了嗎？點擊下方按鈕，"
            "了解我們的方案與價格，或直接預約服務。"
        ),
        "link_text": "查看方案與價格",
        "link_placeholder": "<!-- TODO: 填入購買/預約連結 -->",
    },
}

# 漏斗階段 → CTA 類型對照
_FUNNEL_TO_CTA: dict[str, str] = {
    "tofu": "informational",
    "mofu": "investigational",
    "bofu": "transactional",
    "informational": "informational",
    "investigational": "investigational",
    "transactional": "transactional",
    "navigational": "informational",
}


def _inject_cta_blocks(content_markdown: str, strategy_context: dict | None) -> str:
    """在文章適當位置注入 CTA 區塊（SEO × CRO Phase 15）。

    策略：
    - 在 FAQ 段落之前（若存在）插入 CTA，使讀者在看完內容後有明確行動出口
    - 若沒有 FAQ，則在文章結尾（E-E-A-T 聲明之前）插入
    - 根據 strategy_context 的 funnel_stage / search_intent 選擇 CTA 類型
    - 若已有 CTA（避免冪等重複注入），則跳過
    """
    # 冪等保護：若已含 CTA 標記則跳過
    if "<!-- CTA_BLOCK -->" in content_markdown:
        return content_markdown

    # 決定 CTA 類型
    cta_type = "informational"
    if strategy_context:
        funnel = (strategy_context.get("funnel_stage") or
                  strategy_context.get("search_intent") or "").lower()
        cta_type = _FUNNEL_TO_CTA.get(funnel, "informational")

    tpl = _CTA_TEMPLATES[cta_type]
    cta_block = (
        f"\n\n<!-- CTA_BLOCK -->\n"
        f"> **{tpl['heading']}**\n>\n"
        f"> {tpl['text']}\n>\n"
        f"> [{tpl['link_text']}]({tpl['link_placeholder']})\n"
    )

    # 插入位置：FAQ 前
    faq_pattern = re.compile(r'^(##\s+(?:FAQ|常見問題)[^\n]*)', re.MULTILINE)
    faq_match = faq_pattern.search(content_markdown)
    if faq_match:
        insert_pos = faq_match.start()
        return content_markdown[:insert_pos] + cta_block + "\n" + content_markdown[insert_pos:]

    # 插入位置：E-E-A-T 聲明前
    eeat_pattern = re.compile(r'^---\s*\n## 關於本文審閱', re.MULTILINE)
    eeat_match = eeat_pattern.search(content_markdown)
    if eeat_match:
        insert_pos = eeat_match.start()
        return content_markdown[:insert_pos] + cta_block + "\n" + content_markdown[insert_pos:]

    # 插入位置：文章結尾
    return content_markdown.rstrip() + cta_block


# ── Step 6: E-E-A-T 作者聲明（醫療類）──────────────────────────

def _append_eeat_section(content_markdown: str, ctx: ProjectContext) -> str:
    """為醫療保健類文章（YMYL）在結尾附加 E-E-A-T 作者聲明佔位區塊。

    - 只對 project_uses_pubmed(ctx) == True 的專案加入
    - 若文章已有「關於本文審閱」段落則跳過（冪等）
    """
    if not project_uses_pubmed(ctx):
        return content_markdown
    if "關於本文審閱" in content_markdown:
        return content_markdown

    eeat_block = (
        "\n\n---\n\n"
        "## 關於本文審閱\n\n"
        "> **作者：**"
        "<!-- TODO: 填入作者姓名與資歷，例如「健康編輯 陳○○」 -->\n>\n"
        "> **醫療審閱：**"
        "<!-- TODO: 填入審閱醫師，例如「家醫科醫師 林○○ 醫師（執照字號：...）」 -->\n>\n"
        "> **免責聲明：** 本文醫療保健資訊僅供教育參考，不構成醫療診斷或治療建議。"
        "如有健康疑慮，請諮詢合格醫師或藥師。\n"
    )
    return content_markdown.rstrip() + eeat_block




async def run_writing_agent(
    report: ResearchReport,
    target_word_count: int = 1800,
    writing_architecture: str = "",
    strategy_context: dict | None = None,
    project_id: int | None = None,
) -> ArticleDraft:
    """
    根據研究報告生成完整 SEO 文章。
    全程使用 GPT-4o-mini，每篇約 $0.02-0.05。

    strategy_context 可包含：
      - search_intent: 搜尋意圖（資訊性/交易性啟發）
      - target_audience: 讀者切入點（痛點描述）
      - writing_architecture: 策略與架構指引
      - faq_questions: SEO 專員建議的 FAQ
    """
    logger.info(f"[Writing Agent] 啟動：「{report.article_title}」")
    client = _get_client()

    # 1. 載入專案品牌知識
    ctx = load_project_context(project_id)
    brand_context = _build_brand_context_from_project(ctx)
    logger.info(
        f"[Writing Agent] 專案「{ctx.name}」：{len(ctx.writing_rules)} 規範, "
        f"{len(ctx.strategies)} 策略, {len(ctx.legal_terms)} 法規"
    )

    # 2. 生成大綱
    logger.info("[Writing Agent] Step 1/3 — 生成大綱...")
    outline_json = _generate_outline(
        client, report, brand_context, writing_architecture, target_word_count,
        strategy_context=strategy_context,
    )
    try:
        outline_data = json.loads(outline_json)
    except json.JSONDecodeError:
        logger.error("[Writing Agent] 大綱 JSON 解析失敗，使用預設結構")
        outline_data = {
            "title": report.article_title,
            "meta_description": "",
            "sections": [{"h2": report.article_title, "h3s": [], "keywords": report.keywords[:5]}],
        }

    article_title = outline_data.get("title", report.article_title)
    sections = outline_data.get("sections", [])
    logger.info(f"[Writing Agent] 大綱完成：{article_title}（{len(sections)} 段）")

    # 3. 逐段撰寫
    logger.info("[Writing Agent] Step 2/3 — 逐段撰寫文章...")
    content_parts = []
    prev_summary = ""

    for i, section in enumerate(sections):
        logger.info(f"[Writing Agent] 撰寫段落 {i+1}/{len(sections)}: {section.get('h2', '')}")
        section_content = _write_section(
            client, section, report, brand_context, article_title, prev_summary,
            strategy_context=strategy_context,
        )
        content_parts.append(section_content)
        prev_summary = section_content[:200]

    full_content = _clean_gpt_artifacts("\n\n".join(content_parts))
    word_count = len(full_content)

    # 4. 生成 Meta tags
    logger.info("[Writing Agent] Step 3/3 — 生成 Meta tags...")
    meta = _generate_meta(client, article_title, full_content, report.keywords)

    # 5. 生成 SEO URL Slug
    slug = _generate_slug(client, article_title)
    logger.info(f"[Writing Agent] Slug：{slug}")

    # 6. 注入 CTA 區塊（SEO × CRO）
    full_content = _inject_cta_blocks(full_content, strategy_context)
    logger.info("[Writing Agent] CTA 區塊已注入")

    # 7. 產出 FAQ JSON-LD structured data
    faq_schema = _generate_faq_schema(full_content)
    if faq_schema:
        logger.info(f"[Writing Agent] FAQ Schema：提取到 {faq_schema.count('@type')-1} 個問答對")
    else:
        logger.info("[Writing Agent] FAQ Schema：未找到 FAQ 段落，跳過")

    # 7b. 產出 HowTo JSON-LD（若文章含步驟型段落）
    howto_schema = _generate_howto_schema(full_content, article_title)
    if howto_schema:
        logger.info("[Writing Agent] HowTo Schema 已產出")
    else:
        logger.info("[Writing Agent] HowTo Schema：無步驟型段落，跳過")

    # 8. E-E-A-T 作者聲明（醫療保健類）
    full_content = _append_eeat_section(full_content, ctx)
    word_count = len(full_content)

    # 9. Article/BlogPosting JSON-LD
    article_schema = _generate_article_schema(
        title=article_title,
        meta_description=meta.get("meta_description", ""),
        slug=slug,
        word_count=word_count,
        ctx=ctx,
    )
    logger.info("[Writing Agent] Article JSON-LD 已產出")

    # 10. PAA 問題提取並持久化
    paa_list: list[str] = []
    if report.serp_analysis and report.serp_analysis.people_also_ask:
        paa_list = [p.question for p in report.serp_analysis.people_also_ask]
    elif report.paa_questions:
        paa_list = report.paa_questions
    paa_questions_json = json.dumps(paa_list, ensure_ascii=False)
    if paa_list:
        logger.info(f"[Writing Agent] PAA 問題已提取：{len(paa_list)} 條")

    # 11. 組裝 ArticleDraft
    draft = ArticleDraft(
        title=article_title,
        meta_title=meta.get("meta_title", article_title),
        meta_description=meta.get("meta_description", outline_data.get("meta_description", "")),
        content_markdown=full_content,
        word_count=word_count,
        slug=slug,
        faq_schema_json=faq_schema,
        howto_schema_json=howto_schema,
        article_schema_json=article_schema,
        paa_questions_json=paa_questions_json,
        status=ArticleStatus.WRITING,
    )

    logger.info(f"[Writing Agent] 完成！標題：{draft.title}，字數：{draft.word_count}")
    return draft
