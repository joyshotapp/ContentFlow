"""Content Refresh Agent — CF-06-01~06

職責：
  CF-06-01: ContentFetcher — 從 ForgeBase / WordPress 拉回既有文章原文與 meta
  CF-06-02: RefreshDiffAnalyzer — 比對新 SERP 與舊內容缺口（AI 分析）
  CF-06-03: 局部增補模式 — 產出補充段落 / FAQ（不重寫全文）
  CF-06-04: 更新發布 — 呼叫 publisher.update_post 推送更新版本
  CF-06-05: CompetitorThreatDetector (L3) — 偵測競品超越與防禦建議
  CF-06-06: FeaturedSnippetDetector — 偵測 Featured Snippet 被搶，推薦 FAQ/Table 格式

整個 Refresh Pipeline：
  1. fetch_article(url, platform) → FetchedArticle
  2. analyze_refresh_diff(fetched, keyword) → RefreshPlan
  3. apply_local_patches(fetched, plan) → str (patched_content)
  4. re-run SEO check
  5. publisher.update_post(post_id, patched_draft) → PublishResult
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from ..config import settings
from ..llm_client import chat_sync
from ..models.database import Article
from ..project_integrations import (
    build_forgebase_publisher,
    build_wordpress_publisher,
    resolve_forgebase_settings,
    resolve_site_profile,
    resolve_wordpress_settings,
)


# ─────────────────────────────────────────────────────────────────────────────
# 資料結構
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FetchedArticle:
    """從平台拉回的既有文章"""
    url: str
    platform: str              # "forgebase" / "wordpress"
    post_id: str               # 平台端的文章 ID
    title: str
    content_html: str          # HTML 原文
    content_text: str          # 純文字（供 AI 分析用）
    meta_title: str = ""
    meta_description: str = ""
    published_date: Optional[date] = None
    word_count: int = 0
    fetch_error: Optional[str] = None


@dataclass
class ContentGap:
    """單一內容缺口"""
    gap_type: str              # missing_faq / missing_section / weak_intro / outdated_data / missing_table
    description: str
    suggested_heading: str = ""
    suggested_content: str = ""  # AI 產出的補充段落（選填）


@dataclass
class RefreshPlan:
    """完整的 Refresh 計畫"""
    keyword: str
    article_title: str
    gaps: list[ContentGap] = field(default_factory=list)
    competitor_advantages: list[str] = field(default_factory=list)   # 競品有但我們沒有的
    overall_freshness_score: int = 0    # 0-100，越低越需要 Refresh
    recommendation: str = "maintain"    # maintain / patch / rewrite


@dataclass
class ThreatReport:
    """L3 競品威脅報告（CF-06-05）"""
    keyword: str
    threats: list[dict] = field(default_factory=list)  # [{domain, old_rank, new_rank, threat_level}]
    defense_suggestions: list[str] = field(default_factory=list)
    featured_snippet_seized: bool = False
    featured_snippet_suggestions: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-01: ContentFetcher
# ─────────────────────────────────────────────────────────────────────────────

class ContentFetcher:
    """從 ForgeBase 或 WordPress 拉回既有文章（CF-06-01）"""

    def __init__(self, timeout: int = 20):
        self._timeout = timeout

    async def fetch_forgebase(
        self,
        post_id: str,
        project_id: int | None = None,
        db: Session | None = None,
        api_base_url: str | None = None,
        api_token: str | None = None,
    ) -> FetchedArticle:
        """從 ForgeBase GET /api/v1/content/pages/{post_id} 拉回文章"""
        cfg = resolve_forgebase_settings(db=db, project_id=project_id)
        base = (api_base_url or cfg.base_url).rstrip("/")
        token = api_token or cfg.secret_value

        if not base or not token:
            return FetchedArticle(
                url="", platform="forgebase", post_id=post_id,
                title="", content_html="", content_text="",
                fetch_error="FORGEBASE_API_BASE_URL / FORGEBASE_API_TOKEN 未設定",
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(
                    f"{base}/api/v1/content/pages/{post_id}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                r.raise_for_status()
                data = r.json()

                html = data.get("body", "") or data.get("content", "") or ""
                text = re.sub(r"<[^>]+>", " ", html)   # 簡易 HTML → 純文字

                return FetchedArticle(
                    url=data.get("published_url", "") or data.get("url", ""),
                    platform="forgebase",
                    post_id=post_id,
                    title=data.get("title", ""),
                    content_html=html,
                    content_text=text.strip(),
                    meta_title=data.get("meta_title", ""),
                    meta_description=data.get("meta_description", ""),
                    word_count=len(re.findall(r"[\u4e00-\u9fff]|\b[a-zA-Z]+\b", text)),
                )
        except Exception as e:
            logger.error(f"[ContentFetcher] ForgeBase fetch {post_id} 失敗：{e}")
            return FetchedArticle(
                url="", platform="forgebase", post_id=post_id,
                title="", content_html="", content_text="",
                fetch_error=str(e),
            )

    async def fetch_wordpress(
        self,
        post_id: str,
        project_id: int | None = None,
        db: Session | None = None,
        site_url: str | None = None,
        username: str | None = None,
        app_password: str | None = None,
    ) -> FetchedArticle:
        """從 WordPress REST API GET /wp/v2/posts/{post_id} 拉回文章"""
        import base64

        cfg = resolve_wordpress_settings(db=db, project_id=project_id)
        _site = (site_url or cfg.base_url).rstrip("/")
        _user = username or cfg.username
        _pass = app_password or cfg.secret_value

        if not _site or not _user:
            return FetchedArticle(
                url="", platform="wordpress", post_id=post_id,
                title="", content_html="", content_text="",
                fetch_error="WORDPRESS 認證設定不完整",
            )

        auth = base64.b64encode(f"{_user}:{_pass}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(
                    f"{_site}/wp-json/wp/v2/posts/{post_id}",
                    headers={"Authorization": f"Basic {auth}"},
                )
                r.raise_for_status()
                data = r.json()

                html = (data.get("content") or {}).get("rendered", "")
                text = re.sub(r"<[^>]+>", " ", html)

                pub_date = None
                date_str = data.get("date_gmt") or data.get("date")
                if date_str:
                    try:
                        pub_date = date.fromisoformat(date_str[:10])
                    except ValueError:
                        pass

                return FetchedArticle(
                    url=data.get("link", ""),
                    platform="wordpress",
                    post_id=post_id,
                    title=(data.get("title") or {}).get("rendered", ""),
                    content_html=html,
                    content_text=text.strip(),
                    published_date=pub_date,
                    word_count=len(re.findall(r"[\u4e00-\u9fff]|\b[a-zA-Z]+\b", text)),
                )
        except Exception as e:
            logger.error(f"[ContentFetcher] WordPress fetch {post_id} 失敗：{e}")
            return FetchedArticle(
                url="", platform="wordpress", post_id=post_id,
                title="", content_html="", content_text="",
                fetch_error=str(e),
            )

    async def fetch_by_url(self, url: str) -> FetchedArticle:
        """
        fallback：直接 GET URL，解析 <article> / <main> 區塊的純文字。
        適合平台 API 不可用時的降級處理。
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": "ContentFlow-Refresh/1.0"},
            ) as client:
                r = await client.get(url)
                r.raise_for_status()
                html = r.text

                # 嘗試提取 <article> 或 <main>
                for tag in ("article", "main"):
                    m = re.search(
                        rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.DOTALL | re.IGNORECASE
                    )
                    if m:
                        inner_html = m.group(1)
                        text = re.sub(r"<[^>]+>", " ", inner_html)
                        text = re.sub(r"\s+", " ", text).strip()

                        # 提取 <title>
                        title_m = re.search(r"<title>([^<]+)</title>", html, re.IGNORECASE)
                        title = title_m.group(1).strip() if title_m else ""

                        return FetchedArticle(
                            url=url,
                            platform="url",
                            post_id=url,
                            title=title,
                            content_html=inner_html,
                            content_text=text,
                            word_count=len(re.findall(r"[\u4e00-\u9fff]|\b[a-zA-Z]+\b", text)),
                        )

                # 整頁 fallback
                text = re.sub(r"<[^>]+>", " ", html)
                text = re.sub(r"\s+", " ", text).strip()
                return FetchedArticle(
                    url=url, platform="url", post_id=url,
                    title="", content_html=html, content_text=text[:5000],
                    word_count=len(re.findall(r"[\u4e00-\u9fff]|\b[a-zA-Z]+\b", text)),
                )
        except Exception as e:
            logger.error(f"[ContentFetcher] fetch_by_url {url} 失敗：{e}")
            return FetchedArticle(
                url=url, platform="url", post_id=url,
                title="", content_html="", content_text="",
                fetch_error=str(e),
            )


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-02: RefreshDiffAnalyzer — AI 分析差距
# ─────────────────────────────────────────────────────────────────────────────

def _simple_chat(system: str, user: str, model: str | None = None) -> str:
    return chat_sync(
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=2048,
    )


class RefreshDiffAnalyzer:
    """比對舊文章與新 SERP，找出需補強的缺口（CF-06-02）"""

    SYSTEM_PROMPT = """你是資深 SEO 內容優化專家。
給定一篇舊文章的摘要與最新競品 SERP 摘要，分析舊文章需要補強的地方。

輸出嚴格 JSON 格式（純 JSON，無 markdown）：
{
  "overall_freshness_score": 65,
  "recommendation": "patch",
  "gaps": [
    {
      "gap_type": "missing_faq",
      "description": "競品普遍包含 5+ 個 FAQ，本文無 FAQ 區塊",
      "suggested_heading": "常見問題 FAQ"
    },
    {
      "gap_type": "outdated_data",
      "description": "文章中的統計數字已過時（2022 年數據）",
      "suggested_heading": ""
    }
  ],
  "competitor_advantages": [
    "競品提供中文藥名對照表",
    "競品有嵌入影片"
  ]
}

gap_type 可以是：missing_faq / missing_section / weak_intro / outdated_data / missing_table / thin_content
recommendation 可以是：maintain（不需動）/ patch（局部補強）/ rewrite（全文重寫）
overall_freshness_score：0-100，100 表示完全新鮮，0 表示嚴重過時"""

    def analyze(
        self,
        fetched: FetchedArticle,
        keyword: str,
        serp_summary: str,
    ) -> RefreshPlan:
        """
        Args:
            fetched: 從平台拉回的文章
            keyword: 目標關鍵字
            serp_summary: 最新 SERP 競品摘要（格式自由文字）
        """
        if fetched.fetch_error:
            logger.warning(f"[RefreshDiff] 文章拉取失敗，略過分析：{fetched.fetch_error}")
            return RefreshPlan(keyword=keyword, article_title=fetched.title,
                               recommendation="maintain")

        article_excerpt = fetched.content_text[:2000] if fetched.content_text else "(無內容)"

        user = f"""關鍵字：{keyword}

=== 既有文章摘要（前 2000 字）===
標題：{fetched.title}
字數：{fetched.word_count}
{article_excerpt}

=== 最新 SERP 競品摘要 ===
{serp_summary[:1500]}

請分析這篇文章需要哪些補強。"""

        raw = _simple_chat(self.SYSTEM_PROMPT, user)
        raw = raw.strip().lstrip("```json").lstrip("```").rstrip("```")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"[RefreshDiff] JSON 解析失敗，回傳保守預設")
            return RefreshPlan(keyword=keyword, article_title=fetched.title,
                               overall_freshness_score=50, recommendation="patch")

        gaps = [
            ContentGap(
                gap_type=g.get("gap_type", "unknown"),
                description=g.get("description", ""),
                suggested_heading=g.get("suggested_heading", ""),
            )
            for g in data.get("gaps", [])
        ]

        return RefreshPlan(
            keyword=keyword,
            article_title=fetched.title,
            gaps=gaps,
            competitor_advantages=data.get("competitor_advantages", []),
            overall_freshness_score=int(data.get("overall_freshness_score", 50)),
            recommendation=data.get("recommendation", "maintain"),
        )


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-03: 局部增補模式
# ─────────────────────────────────────────────────────────────────────────────

def generate_patch_content(
    fetched: FetchedArticle,
    gap: ContentGap,
    keyword: str,
    gsc_context: dict[str, Any] | None = None,
) -> str:
    """
    針對單一缺口（ContentGap）產出補充段落（CF-06-03）。
    這只是局部增補，不重寫全文。
    """
    section_type_map = {
        "missing_faq": "一個包含 5 個問答的 FAQ 區塊（Markdown 格式）",
        "missing_section": f"一段關於「{gap.suggested_heading}」的補充段落（200-300字，Markdown）",
        "weak_intro": "一段更有力的文章開頭（100-150字，Markdown）",
        "outdated_data": "一段更新數據的段落，注明約略年份（Markdown）",
        "missing_table": f"一個關於「{gap.suggested_heading or gap.description[:30]}」的比較表格（Markdown table）",
        "thin_content": f"一段擴充文章深度的段落（300字，Markdown）",
    }
    task = section_type_map.get(gap.gap_type, "一段補充段落（200字，Markdown）")

    system = """你是繁體中文 SEO 文章寫手。你的任務是針對指定缺口產出局部補充內容。
只輸出補充內容本身（Markdown 格式），不要解釋、不要前言。"""

    gsc_note = ""
    if gsc_context:
        query_lines = []
        for query in (gsc_context.get("low_ctr_queries", []) or [])[:3]:
            query_lines.append(
                f"- {query.get('query', '')}：曝光 {int(query.get('impressions', 0) or 0)}、CTR {round(float(query.get('ctr', 0.0) or 0.0) * 100, 2)}%"
            )
        if query_lines:
            gsc_note = "\nGSC 查詢詞缺口：\n" + "\n".join(query_lines)

    user = f"""關鍵字：{keyword}
文章標題：{fetched.title}
缺口描述：{gap.description}
{gsc_note}
請產出：{task}"""

    content = _simple_chat(system, user)
    return content.strip()


def apply_local_patches(
    fetched: FetchedArticle,
    plan: RefreshPlan,
    keyword: str,
    generate_content: bool = True,
    gsc_context: dict[str, Any] | None = None,
) -> str:
    """
    根據 RefreshPlan 對原文做局部增補，回傳新的 Markdown 內容（CF-06-03）。

    策略：
    - 在原文末尾附加新增的段落 / FAQ
    - 不刪除原有內容（避免 SEO 消失的句子）
    - 只補不刪
    
    generate_content: 若 False，只附上 [待補充] 佔位符（測試用 / 預覽用）
    """
    # 以原文純文字為基礎返回 Markdown
    base = fetched.content_text or ""

    patches: list[str] = []
    for gap in plan.gaps:
        if gap.gap_type == "maintain" or plan.recommendation == "maintain":
            continue

        heading = gap.suggested_heading or f"【補充：{gap.gap_type}】"
        if generate_content:
            try:
                content = generate_patch_content(fetched, gap, keyword, gsc_context=gsc_context)
                patches.append(f"\n\n## {heading}\n\n{content}")
            except Exception as e:
                logger.warning(f"[RefreshPatch] 產出 {gap.gap_type} 失敗：{e}")
                patches.append(f"\n\n## {heading}\n\n[待補充]")
        else:
            patches.append(f"\n\n## {heading}\n\n[待補充：{gap.description}]")

    return base + "".join(patches)


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-04: Refresh 後再發布
# ─────────────────────────────────────────────────────────────────────────────

async def publish_refreshed_article(
    article: Article,
    patched_content: str,
    session: Session,
    platform: str | None = None,
) -> dict:
    """
    將補強後的內容推送回平台（CF-06-04）。
    
    platform 判斷優先序：
    1. 若明確傳入 platform 參數，直接使用
    2. 若 publish_url 含 /wp-json/ 或 ?p= → "wordpress"
    3. 否則 → "forgebase"
    
    回傳：{"success": bool, "url": str, "error": str | None}
    """
    from ..models.schemas import ArticleDraft

    # 建立更新用的 ArticleDraft
    draft = ArticleDraft(
        title=article.title,
        content_markdown=patched_content,
        meta_title=article.meta_title or article.title,
        meta_description=article.meta_description or "",
        slug=article.slug or "",
    )

    if platform is None:
        # 自動推斷平台
        _url = article.publish_url or ""
        _site_profile = resolve_site_profile(db=session, project_id=article.project_id)
        _site_base = _site_profile.site_url.rstrip("/") if _site_profile.site_url else ""
        if "wp-json" in _url or re.search(r"[?&]p=\d+", _url):
            platform = "wordpress"
        elif not _url or (_site_base and _url.startswith(_site_base)):
            platform = "native"  # 原生 blog（無 URL 或 URL 屬於本站）
        else:
            # 外部 URL：嘗試 ForgeBase（post_id 為空時函式內部會回傳 error）
            platform = "forgebase"

    # 原生 blog：只更新本地 DB，無需推送外部 API
    if platform == "native":
        article.draft_content = patched_content
        session.commit()
        logger.info(f"[RefreshPublish] article={article.id} 原生 blog 更新 DB 成功")
        return {"success": True, "url": article.publish_url or "", "error": None}

    try:
        if platform == "wordpress":
            pub = build_wordpress_publisher(db=session, project_id=article.project_id)
            post_id = _extract_wp_post_id(article.publish_url or "")
            if not post_id:
                return {"success": False, "url": article.publish_url or "",
                        "error": "無法從 publish_url 取得 WP post ID"}
            result = await pub.update_post(post_id, draft)
        else:
            pub = build_forgebase_publisher(db=session, project_id=article.project_id)
            post_id = _extract_forgebase_post_id(article.publish_url or "", article.slug or "")
            if not post_id:
                return {"success": False, "url": article.publish_url or "",
                        "error": "無法從 publish_url / slug 取得 ForgeBase post ID"}
            result = await pub.update_post(post_id, draft)

        # 回寫 DB
        if result.success:
            article.draft_content = patched_content
            session.commit()
            logger.info(f"[RefreshPublish] article={article.id} 更新成功：{result.publish_url}")

        return {
            "success": result.success,
            "url": result.publish_url or article.publish_url or "",
            "error": result.error,
        }
    except Exception as e:
        logger.error(f"[RefreshPublish] article={article.id} 更新失敗：{e}")
        return {"success": False, "url": article.publish_url or "", "error": str(e)}


def _extract_wp_post_id(url: str) -> str:
    """從 WP REST API URL 或 ?p= 參數提取 post_id"""
    # /wp-json/wp/v2/posts/123
    m = re.search(r"/posts/(\d+)", url)
    if m:
        return m.group(1)
    # ?p=123
    m = re.search(r"[?&]p=(\d+)", url)
    if m:
        return m.group(1)
    return ""


def _extract_forgebase_post_id(url: str, slug: str) -> str:
    """
    ForgeBase post ID 推斷策略：
    1. URL 路徑最後一段（/blog/my-article-123 → my-article-123）
    2. 若 slug 已知直接使用
    """
    if slug:
        return slug
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else ""


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-05: L3 競品威脅偵測
# ─────────────────────────────────────────────────────────────────────────────

class CompetitorThreatDetector:
    """
    L3 競品適應：偵測競品超越我們排名的情形，並產出防禦建議（CF-06-05）。
    
    分析方式：
    - 比對同一 keyword 的歷史 SEORanking 數據
    - 若競品域名排名近期大幅上升 → 標記為威脅
    - 若我們的排名同步下滑 → 提升威脅等級
    """

    def detect(
        self,
        project_id: int,
        keyword: str,
        session: Session,
        brand_url: str = "",
    ) -> ThreatReport:
        from ..models.database import SEORanking, Project
        from datetime import timedelta, date as date_cls
        from collections import defaultdict

        # 若未傳入則嘗試從 DB 取得
        if not brand_url:
            project = session.query(Project).filter(Project.id == project_id).first()
            brand_url = (project.brand_url or "") if project else ""

        cutoff = date_cls.today() - timedelta(days=30)
        rows = (
            session.query(SEORanking)
            .filter(
                SEORanking.project_id == project_id,
                SEORanking.keyword == keyword,
                SEORanking.tracked_date >= cutoff,
            )
            .order_by(SEORanking.tracked_date)
            .all()
        )

        if not rows:
            return ThreatReport(keyword=keyword)

        # 我們的文章 landing_page（project 內排名最高的）
        our_pages = {r.landing_page for r in rows
                     if r.landing_page and brand_url and
                     brand_url.rstrip("/") in (r.landing_page or "")}

        # 按 landing_page 分組，找排名趨勢
        page_ranks: dict[str, list[tuple]] = defaultdict(list)
        for r in rows:
            if r.landing_page and r.position:
                page_ranks[r.landing_page].append((r.tracked_date, r.position))

        threats = []
        for page, rank_history in page_ranks.items():
            if page in our_pages:
                continue  # 跳過自己
            if len(rank_history) < 2:
                continue

            sorted_history = sorted(rank_history, key=lambda x: x[0])
            earliest_rank = sorted_history[0][1]
            latest_rank = sorted_history[-1][1]
            rank_change = earliest_rank - latest_rank   # 正值 = 排名上升（數字減少）

            if rank_change >= 3 and latest_rank <= 15:   # 上升 3+ 且進入前 15
                threat_level = "high" if rank_change >= 8 else "medium"
                threats.append({
                    "domain": page,
                    "old_rank": earliest_rank,
                    "new_rank": latest_rank,
                    "rank_change": rank_change,
                    "threat_level": threat_level,
                })

        defense_suggestions = []
        if threats:
            high_threats = [t for t in threats if t["threat_level"] == "high"]
            if high_threats:
                defense_suggestions.append(
                    f"關鍵字「{keyword}」有 {len(high_threats)} 個競品大幅上升，"
                    "建議立即排入 Content Refresh 佇列"
                )
            defense_suggestions.append("分析競品新增內容：字數、FAQ、圖片、Schema markup")
            defense_suggestions.append("確認 Internal link 指向目標文章的數量是否足夠")

        return ThreatReport(
            keyword=keyword,
            threats=threats,
            defense_suggestions=defense_suggestions,
        )


# ─────────────────────────────────────────────────────────────────────────────
# CF-06-06: Featured Snippet 偵測
# ─────────────────────────────────────────────────────────────────────────────

class FeaturedSnippetDetector:
    """
    偵測 Featured Snippet 被競品搶走，並給出格式調整建議（CF-06-06）。
    
    判斷規則（基於 SERP 數據）：
    - 我們的文章排名在 1-3 但 CTR < 3% → 可能有 Featured Snippet 被搶（正常 CTR 應更高）
    - SERP 數據顯示 impressions 高但 clicks 低 → Featured Snippet 存在但不是我們的
    """

    def detect(self, project_id: int, keyword: str, session: Session) -> ThreatReport:
        from ..models.database import SEORanking
        from datetime import timedelta, date as date_cls

        cutoff = date_cls.today() - timedelta(days=28)
        rows = (
            session.query(SEORanking)
            .filter(
                SEORanking.project_id == project_id,
                SEORanking.keyword == keyword,
                SEORanking.tracked_date >= cutoff,
            )
            .all()
        )

        snippet_seized = False
        suggestions = []

        for r in rows:
            if not r.position or not r.ctr:
                continue
            # 排名進前 3 但 CTR < 3%，懷疑有 Featured Snippet 被搶
            if r.position <= 3.0 and r.ctr < 0.03:
                snippet_seized = True
                suggestions.extend([
                    "在文章開頭補上直接回答問題的「答案框」段落（40-60字）",
                    "新增 FAQ SchemaMarkup，格式為 Question → 簡短 Answer",
                    "用有序列表（<ol>）呈現步驟式內容（符合 Featured Snippet 提取格式）",
                    "確認頁面 H1 包含完整問題句（例：「膝蓋長骨刺怎麼辦？」）",
                ])
                break

        return ThreatReport(
            keyword=keyword,
            featured_snippet_seized=snippet_seized,
            featured_snippet_suggestions=suggestions,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 高層 Refresh Pipeline（整合 CF-06-01~04）
# ─────────────────────────────────────────────────────────────────────────────

async def run_refresh_pipeline(
    article: Article,
    keyword: str,
    session: Session,
    serp_summary: str = "",
    platform: str = "forgebase",
    post_id: str | None = None,
    generate_content: bool = False,
    publish: bool = False,
    gsc_context: dict[str, Any] | None = None,
) -> dict:
    """
    執行完整的 Content Refresh 流程。
    
    Args:
        article: 要 Refresh 的 Article ORM 物件
        keyword: 主關鍵字
        session: SQLAlchemy session
        serp_summary: 最新 SERP 競品摘要（可由外部傳入）
        platform: "forgebase" / "wordpress"
        post_id: 平台 post ID（若 None 則嘗試從 article.slug 推斷）
        generate_content: 是否實際呼叫 GPT 產出補充內容（False → 只分析缺口）
        publish: 是否在分析完成後直接推送更新
    
    Returns:
        {
          "fetched": FetchedArticle,
          "plan": RefreshPlan,
          "patched_content": str,
          "publish_result": dict | None,
        }
    """
    fetcher = ContentFetcher()
    pid = post_id or article.slug or str(article.id)

    # Step 1: 拉回文章
    logger.info(f"[RefreshPipeline] Step 1 — 拉回文章: article={article.id} platform={platform}")
    if platform == "wordpress":
        fetched = await fetcher.fetch_wordpress(pid, project_id=article.project_id, db=session)
    elif platform == "url" and article.publish_url:
        fetched = await fetcher.fetch_by_url(article.publish_url)
    else:
        fetched = await fetcher.fetch_forgebase(pid, project_id=article.project_id, db=session)

    gsc_summary = ""
    if gsc_context:
        query_lines = []
        for query in (gsc_context.get("low_ctr_queries", []) or [])[:3]:
            query_lines.append(
                f"- {query.get('query', '')}：曝光 {int(query.get('impressions', 0) or 0)}、CTR {round(float(query.get('ctr', 0.0) or 0.0) * 100, 2)}%"
            )
        if query_lines:
            gsc_summary = "GSC 顯示的高曝光低 CTR 查詢詞：\n" + "\n".join(query_lines)

    combined_serp_summary = serp_summary.strip()
    if gsc_summary:
        combined_serp_summary = "\n\n".join(part for part in [combined_serp_summary, gsc_summary] if part)

    # Step 2: AI 分析差距
    logger.info(f"[RefreshPipeline] Step 2 — 分析差距")
    analyzer = RefreshDiffAnalyzer()
    plan = analyzer.analyze(fetched, keyword, combined_serp_summary)

    logger.info(f"[RefreshPipeline] 新鮮度分數={plan.overall_freshness_score} "
                f"建議={plan.recommendation} 缺口={len(plan.gaps)} 個")

    # Step 3: 局部增補
    patched_content = ""
    if plan.recommendation in ("patch", "rewrite") and plan.gaps:
        logger.info(f"[RefreshPipeline] Step 3 — 局部增補 {len(plan.gaps)} 個缺口")
        patched_content = apply_local_patches(
            fetched,
            plan,
            keyword,
            generate_content=generate_content,
            gsc_context=gsc_context,
        )
    else:
        patched_content = fetched.content_text

    # Step 4: 發布（可選）
    publish_result = None
    if publish and patched_content and plan.recommendation != "maintain":
        logger.info(f"[RefreshPipeline] Step 4 — 推送更新")
        publish_result = await publish_refreshed_article(article, patched_content, session)

    return {
        "fetched": fetched,
        "plan": plan,
        "patched_content": patched_content,
        "publish_result": publish_result,
    }
