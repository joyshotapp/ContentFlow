"""Strategy Agent：自動分析關鍵字策略，取代 SEO 專員的選題分析工作

輸入：一個主關鍵字（+ 可選的副關鍵字）
輸出：StrategyReport — 搜尋意圖、讀者痛點、寫作架構、FAQ 建議、競品差異分析

資料來源：
1. SERP 前 10 名結果 —— 判斷搜尋意圖 + 競品結構
2. PAA (People Also Ask) —— 生成 FAQ 建議
3. GPT-4o-mini 推理 —— 讀者痛點 + 架構建議 + 差異化分析

全程使用 GPT-4o-mini，單次分析約 $0.005-0.01。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from loguru import logger
from openai import OpenAI

from ..config import settings
from ..models import SerpAnalysis
from ..project_context import ProjectContext, load_project_context


@dataclass
class StrategyReport:
    """SEO 策略分析報告"""
    keyword: str
    search_intent: str           # 資訊性 / 商業調查 / 交易性 / 導航性
    target_audience: str         # 讀者輪廓 + 痛點描述
    writing_architecture: str    # 寫廣/寫深 + 架構類型
    faq_questions: list[str]     # 建議的 FAQ 問題
    competitor_gap: str          # 競品缺口分析
    content_angle: str           # 建議的差異化切角
    confidence: float            # 分析信心度 0-1

    def to_strategy_context(self) -> dict:
        """轉換為 writing_agent 可用的 strategy_context dict"""
        # 從 writing_architecture 推導 format_type（供 decision log 顯示）
        arch = self.writing_architecture or ""
        if "比較" in arch or "對比" in arch:
            fmt = "comparison"
        elif "步驟" in arch or "how-to" in arch.lower():
            fmt = "howto"
        elif "問答" in arch or "FAQ" in arch:
            fmt = "faq"
        else:
            fmt = "guide"
        # 從 writing_architecture 推導目標字數
        wc = 2500
        if "2000" in arch:
            wc = 2000
        elif "3000" in arch:
            wc = 3000
        elif "4000" in arch or "長" in arch:
            wc = 4000
        elif "1500" in arch:
            wc = 1500
        return {
            "search_intent": self.search_intent,
            "target_audience": self.target_audience,
            "writing_architecture": self.writing_architecture,
            "content_angle": self.content_angle,
            "competitor_gap": self.competitor_gap,
            "format_type": fmt,
            "target_word_count": wc,
            "faq_questions": " ".join(
                f"{i+1}.{q}" for i, q in enumerate(self.faq_questions[:6])
            ),
        }

    def to_display_dict(self) -> dict:
        """轉換為 UI 顯示用的 dict"""
        return {
            "關鍵字": self.keyword,
            "搜尋意圖": self.search_intent,
            "讀者輪廓與痛點": self.target_audience,
            "寫作架構建議": self.writing_architecture,
            "建議 FAQ": self.faq_questions,
            "競品缺口": self.competitor_gap,
            "差異化切角": self.content_angle,
            "分析信心度": f"{self.confidence:.0%}",
        }


def _get_client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _chat(client: OpenAI, system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=settings.llm_lite_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_completion_tokens=2048,
    )
    return resp.choices[0].message.content or ""


def _build_serp_summary(serp: SerpAnalysis) -> str:
    """將 SERP 結果整理為文字摘要供 GPT 分析"""
    parts = []
    parts.append(f"搜尋查詢：{serp.query}")
    parts.append(f"共 {len(serp.top_results)} 筆結果\n")

    for r in serp.top_results[:10]:
        parts.append(f"#{r.position} {r.title}")
        parts.append(f"   URL: {r.url}")
        if r.snippet:
            parts.append(f"   摘要: {r.snippet[:150]}")
        parts.append("")

    if serp.people_also_ask:
        parts.append("People Also Ask:")
        for paa in serp.people_also_ask:
            parts.append(f"  Q: {paa.question}")
            if paa.answer:
                parts.append(f"  A: {paa.answer[:100]}")
        parts.append("")

    if serp.related_searches:
        parts.append(f"相關搜尋：{', '.join(serp.related_searches[:10])}")

    return "\n".join(parts)


async def run_strategy_agent(
    keyword: str,
    secondary_keywords: list[str] | None = None,
    serp: SerpAnalysis | None = None,
    paa_questions: list[str] | None = None,
    project_id: int | None = None,
) -> StrategyReport:
    """
    分析關鍵字並產出 SEO 策略報告。

    可接收已有的 SERP/PAA 資料（避免重複查詢），
    也可只給 keyword 自動抓取。
    """
    logger.info(f"[Strategy Agent] 啟動：「{keyword}」")
    client = _get_client()
    ctx = load_project_context(project_id)

    # ── Step 1: 如果沒有 SERP 資料，先抓取 ──────────────────
    if serp is None:
        from ..tools.serp import search_serp
        serp = await search_serp(keyword)
        logger.info(f"[Strategy Agent] SERP 取得 {len(serp.top_results)} 筆結果")

    serp_summary = _build_serp_summary(serp)

    # 合併 PAA（從 serp + 外部傳入）
    all_paa = []
    if serp.people_also_ask:
        all_paa.extend(paa.question for paa in serp.people_also_ask)
    if paa_questions:
        for q in paa_questions:
            if q not in all_paa:
                all_paa.append(q)

    # ── Step 1.5: 查詢知識庫（KB）注入學習成果 ──────────────
    kb_context = ""
    if project_id is not None:
        try:
            from ..tools.knowledge_base import query_kb, format_kb_context
            from ..db import SessionLocal
            with SessionLocal() as _kb_sess:
                kb_results = query_kb(project_id, keyword, top_k=5, session=_kb_sess)
            kb_context = format_kb_context(kb_results, keyword)
            if kb_context:
                logger.info(f"[Strategy Agent] 注入 {len(kb_results)} 條 KB 知識")
        except Exception as _kb_err:
            logger.debug(f"[Strategy Agent] KB 查詢略過：{_kb_err}")

    # ── Step 2: GPT 策略分析 ──────────────────────────────────
    logger.info("[Strategy Agent] Step 1/1 — GPT 策略分析...")

    system = """你是資深 SEO 策略分析師，專精繁體中文市場。
你的任務是分析 Google 搜尋結果（SERP），為內容團隊產出精準的 SEO 策略報告。

分析框架：

1. **搜尋意圖判斷**：根據 SERP 前 10 名結果的類型來判斷
   - 全為衛教/知識文章 → 「資訊性」
   - 混合商品頁+知識文章 → 「商業調查」
   - 多數為商品/服務頁 → 「交易性」
   - 品牌官網佔多數 → 「導航性」

2. **讀者輪廓與痛點**：從搜尋這個關鍵字的人的角度思考
   - 他們正面臨什麼問題？
   - 什麼情緒驅使他們搜尋？（焦慮、恐懼、好奇、急迫...）
   - 他們在搜尋之前可能已經嘗試過什麼？

3. **寫作架構建議**：
   - 「寫廣」= 讀者處於認知初期，需要全面介紹 → 適合「倒三角」或「思維流程」
   - 「寫深」= 讀者已有基本認知，需要深入解答 → 適合「金字塔(SCQA)」或「敘事型」

4. **FAQ 建議**：結合 PAA 問題 + 你的專業判斷，產出 6 個最有價值的 FAQ

5. **競品缺口分析**：SERP 前 10 名的共同缺陷或遺漏是什麼？

6. **差異化切角**：基於品牌定位，建議一個獨特的內容切入角度

回傳嚴格 JSON 格式（純 JSON，無 markdown code block）：
{
  "search_intent": "資訊性|商業調查|交易性|導航性",
  "target_audience": "讀者輪廓與痛點描述（100-200字）",
  "writing_architecture": "寫廣或寫深 + 建議架構（倒三角/金字塔SCQA/思維流程/敘事型）",
  "faq_questions": ["問題1", "問題2", ..., "問題6"],
  "competitor_gap": "競品缺口分析（50-100字）",
  "content_angle": "差異化切角建議（50-100字）",
  "confidence": 0.85
}"""

    secondary_info = ""
    if secondary_keywords:
        secondary_info = f"\n副關鍵字：{', '.join(secondary_keywords[:5])}"

    paa_info = ""
    if all_paa:
        paa_info = f"\n\nPeople Also Ask 問題：\n" + "\n".join(
            f"- {q}" for q in all_paa[:10]
        )

    # 品牌定位資訊（用於差異化切角）
    brand_info = ""
    if ctx.brand_name:
        brand_info = f"\n\n品牌定位參考：\n- 品牌：{ctx.brand_name}"
        if ctx.brand_description:
            brand_info += f"\n- 定位：{ctx.brand_description}"
        if ctx.industry:
            brand_info += f"\n- 產業：{ctx.industry}"

    user = f"""請分析以下關鍵字的 SEO 策略：

主關鍵字：{keyword}{secondary_info}

以下是 Google SERP 實際搜尋結果：

{serp_summary}{paa_info}{brand_info}
{kb_context}
請根據以上資料，產出完整的 SEO 策略分析報告（JSON 格式）。"""

    raw = _chat(client, system, user)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]

    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        logger.error(f"[Strategy Agent] JSON 解析失敗，使用預設值")
        data = {
            "search_intent": "資訊性",
            "target_audience": f"搜尋「{keyword}」的使用者，可能正在尋找相關資訊",
            "writing_architecture": "寫廣（倒三角）",
            "faq_questions": all_paa[:6] if all_paa else [f"什麼是{keyword}？"],
            "competitor_gap": "需人工分析",
            "content_angle": f"以{ctx.brand_description or '專業觀點'}切入" if ctx.brand_description else "提供差異化觀點",
            "confidence": 0.5,
        }

    # ── Step 3: 組裝報告 ─────────────────────────────────────
    report = StrategyReport(
        keyword=keyword,
        search_intent=data.get("search_intent", "資訊性"),
        target_audience=data.get("target_audience", ""),
        writing_architecture=data.get("writing_architecture", ""),
        faq_questions=data.get("faq_questions", [])[:6],
        competitor_gap=data.get("competitor_gap", ""),
        content_angle=data.get("content_angle", ""),
        confidence=float(data.get("confidence", 0.7)),
    )

    logger.info(
        f"[Strategy Agent] 完成！意圖={report.search_intent}, "
        f"架構={report.writing_architecture}, "
        f"FAQ={len(report.faq_questions)}題, "
        f"信心={report.confidence:.0%}"
    )
    return report
