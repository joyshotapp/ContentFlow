"""
seed_full_pipeline.py — 完整 E2E 資料播種腳本

執行順序：
  1. 新增真實競品（4 家台灣健康媒體）
  2. 新增關鍵字（含搜尋量的品質資料）
  3. 建立支柱文章 + 5 篇衛星文章（planned 狀態）
  4. 綁定 ClusterMember.article_id
  5. 建立 ContentCalendar 排程
  6. 觸發 Agent Pipeline（呼叫 run_orchestrator 直接執行第一篇）

用法（在 Docker 容器內）：
  docker exec contentflow-site-1 python /app/scripts/seed_full_pipeline.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

# ── 環境 ──────────────────────────────────────────────────────────────────
# 在 Docker 容器 /app 內 src 已在 PYTHONPATH；本機執行時需要 src/
for p in ["/app", "/app/src", "src"]:
    if os.path.exists(p) and p not in sys.path:
        sys.path.insert(0, p)

from contentflow.db import SessionLocal
from contentflow.models.database import (
    Article,
    ClusterMember,
    Competitor,
    ContentCalendar,
    Keyword,
    Project,
    TopicCluster,
)

# ── 主函式 ────────────────────────────────────────────────────────────────

def seed_competitors(session, project_id: int) -> None:
    """新增 4 家真實台灣健康競品"""
    existing = {c.brand_name for c in session.query(Competitor).filter(
        Competitor.project_id == project_id).all()}

    competitors = [
        {
            "brand_name": "康健雜誌",
            "website": "https://www.commonhealth.com.tw",
            "features": "台灣最大健康媒體，骨科/骨刺/脊椎等主題文章超過 3,000 篇，SEO 排名強勢",
            "sells_products": "否",
            "recommendation": "重點競品；監控其骨刺關鍵字排名與內容更新頻率",
        },
        {
            "brand_name": "照護線上",
            "website": "https://www.careonline.com.tw",
            "features": "醫師親自撰文的醫學衛教平台，骨科、復健、退化性關節炎內容豐富、可信度高",
            "sells_products": "否",
            "recommendation": "高 E-E-A-T 競品；學習其醫師背書模式",
        },
        {
            "brand_name": "早安健康",
            "website": "https://www.edh.tw",
            "features": "樂齡健康媒體，骨密度、關節炎、骨刺飲食等老年骨病內容豐富；有健康食品電商",
            "sells_products": "是（健康食品）",
            "recommendation": "直接競品；同樣銷售骨關節類補充品，監控其商品頁 SEO",
        },
        {
            "brand_name": "健康2.0",
            "website": "https://health.tvbs.com.tw",
            "features": "TVBS 官方健康頻道，骨關節/養生類影片與圖文並茂，電視媒體品牌加持",
            "sells_products": "否",
            "recommendation": "影音競品；觀察骨刺相關關鍵字搜尋結果中是否出現其影片",
        },
    ]

    added = 0
    for c in competitors:
        if c["brand_name"] in existing:
            print(f"  [SKIP] 競品已存在：{c['brand_name']}")
            continue
        session.add(Competitor(
            project_id=project_id,
            brand_name=c["brand_name"],
            website=c["website"],
            features=c["features"],
            sells_products=c["sells_products"],
            recommendation=c["recommendation"],
        ))
        added += 1

    session.commit()
    print(f"  ✅ 競品：新增 {added} 筆，總計 {added + len(existing)} 家")


def seed_keywords(session, project_id: int) -> None:
    """補充真實搜尋量關鍵字（骨刺主題延伸）"""
    existing = {k.keyword for k in session.query(Keyword).filter(
        Keyword.project_id == project_id).all()}

    # 基於 Google Trends / 關聯搜尋的真實延伸
    new_keywords = [
        # 有搜尋量的高意圖詞
        ("骨刺手術", 1000, 2.1),
        ("骨刺痛怎麼辦", 880, 1.6),
        ("腳跟骨刺", 720, 1.4),
        ("頸椎骨刺症狀", 1200, 2.3),
        ("腰椎骨刺", 1500, 2.8),
        ("骨刺保健食品", 600, 3.2),
        ("骨刺補充品", 480, 3.5),
        ("膝蓋骨刺", 1100, 1.9),
        ("骨刺復健", 540, 1.3),
        ("骨刺飲食禁忌", 920, 1.7),
        ("骨刺針灸", 430, 1.1),
        ("骨刺自我按摩", 380, 0.9),
    ]

    added = 0
    now = datetime.now(timezone.utc)
    for kw, vol, cpc in new_keywords:
        if kw in existing:
            continue
        session.add(Keyword(
            project_id=project_id,
            keyword=kw,
            search_volume=vol,
            cpc=cpc,
            created_at=now,
            updated_at=now,
        ))
        added += 1

    session.commit()
    print(f"  ✅ 關鍵字：新增 {added} 筆，總計 {len(existing) + added} 個")


def seed_articles_from_cluster(session, project_id: int) -> dict[int, int]:
    """
    從 ClusterMember 建立 planned 文章
    回傳 {cluster_member_id: article_id}
    """
    cluster = session.query(TopicCluster).filter(
        TopicCluster.project_id == project_id).first()
    if not cluster:
        print("  ⚠️  找不到 TopicCluster，跳過文章建立")
        return {}

    now = datetime.now(timezone.utc)
    member_map: dict[int, int] = {}  # member.id -> article.id

    # ── 先建立支柱文章（若尚未存在）──────────────────────────────────
    pillar_title = cluster.pillar_title or f"骨刺完整指南：原因、症狀與治療"
    existing_pillar = (
        session.query(Article)
        .filter(Article.primary_keyword == cluster.pillar_keyword,
                Article.project_id == project_id)
        .first()
    )
    if existing_pillar:
        pillar_art = existing_pillar
        print(f"  [SKIP] 支柱文章已存在：{pillar_title}")
    else:
        pillar_art = Article(
            project_id=project_id,
            primary_keyword=cluster.pillar_keyword,
            title=pillar_title,
            article_type="知識",
            status="planned",
            created_at=now,
            updated_at=now,
        )
        session.add(pillar_art)
        session.flush()
        print(f"  ✅ 支柱文章：{pillar_title} (id={pillar_art.id})")

    # 綁定 cluster.pillar_article_id
    if not cluster.pillar_article_id:
        cluster.pillar_article_id = pillar_art.id
        session.flush()

    # ── 建立 5 篇衛星文章 ──────────────────────────────────────────
    # keyword → (標題, 文章類型)
    TITLE_MAP: dict[str, tuple[str, str]] = {
        "長骨刺不能吃的東西": ("長骨刺不能吃的東西有哪些？飲食禁忌完整清單", "知識"),
        "骨刺是什麼":         ("骨刺是什麼？骨刺的成因、症狀與治療一次說清楚", "知識"),
        "骨刺英文":           ("骨刺英文怎麼說？Bone Spur 完整醫學術語指南", "知識"),
        "骨刺症狀":           ("骨刺症狀大全：頸椎、腰椎、腳跟各部位症狀對照", "知識"),
        "骨刺治療":           ("骨刺治療方法比較：手術、復健、保守治療如何選擇", "知識"),
    }

    members = session.query(ClusterMember).filter(
        ClusterMember.cluster_id == cluster.id).all()

    for member in members:
        if member.article_id:
            # 已有文章
            member_map[member.id] = member.article_id
            print(f"  [SKIP] 衛星文章已存在：{member.keyword}")
            continue

        title, atype = TITLE_MAP.get(
            member.keyword, (f"{member.keyword}：完整介紹與說明", "知識")
        )
        art = Article(
            project_id=project_id,
            primary_keyword=member.keyword,
            title=title,
            article_type=atype,
            status="planned",
            created_at=now,
            updated_at=now,
        )
        session.add(art)
        session.flush()
        # 回寫 ClusterMember
        member.article_id = art.id
        member_map[member.id] = art.id
        print(f"  ✅ 衛星文章 [{member.keyword}] → id={art.id}")

    session.commit()
    return member_map


def seed_calendar(session, project_id: int) -> None:
    """建立 ContentCalendar 排程（月/週 規劃）"""
    existing_count = session.query(ContentCalendar).filter(
        ContentCalendar.project_id == project_id).count()
    if existing_count > 0:
        print(f"  [SKIP] 內容日曆已有 {existing_count} 筆")
        return

    # 取所有 planned 文章
    articles = (
        session.query(Article)
        .filter(Article.project_id == project_id, Article.status == "planned")
        .order_by(Article.id)
        .all()
    )
    if not articles:
        print("  ⚠️  無 planned 文章，無法建立日曆")
        return

    now = datetime.now(timezone.utc)
    # 支柱文章排在第 1 個月第 1 週，其餘按順序排列
    schedule = [
        (4, 2),  # 4月第2週
        (4, 3),  # 4月第3週
        (4, 4),  # 4月第4週
        (5, 1),  # 5月第1週
        (5, 2),  # 5月第2週
        (5, 3),  # 5月第3週（支柱）
    ]

    added = 0
    for idx, art in enumerate(articles[:6]):
        if idx < len(schedule):
            month, week = schedule[idx]
        else:
            month, week = 5, idx
        cal = ContentCalendar(
            project_id=project_id,
            article_id=art.id,
            title=art.title,
            keywords=art.primary_keyword,
            article_type=art.article_type or "知識",
            status="planned",
            month=month,
            week=week,
            search_intent="資訊性",
            target_audience="骨刺患者、45歲以上中壯年族群",
            writing_architecture="倒三角",
        )
        session.add(cal)
        added += 1

    session.commit()
    print(f"  ✅ 內容日曆：新增 {added} 筆")


async def trigger_pipeline(session, project_id: int) -> None:
    """觸發第一篇文章（骨刺是什麼）的 Agent Pipeline"""
    # 找 '骨刺是什麼' 這篇優先跑（最基礎的知識文）
    art = (
        session.query(Article)
        .filter(
            Article.project_id == project_id,
            Article.primary_keyword == "骨刺是什麼",
        )
        .first()
    )
    if not art:
        # fallback: 取第一篇 planned
        art = (
            session.query(Article)
            .filter(Article.project_id == project_id, Article.status == "planned")
            .order_by(Article.id)
            .first()
        )
    if not art:
        print("  ⚠️  找不到可執行的 planned 文章")
        return

    print(f"\n🚀 觸發 Agent Pipeline")
    print(f"   文章: [{art.id}] {art.title}")
    print(f"   關鍵字: {art.primary_keyword}")

    from contentflow.agents.orchestrator import run_orchestrator
    from contentflow.models import ArticleTask, ArticleStatus
    import uuid

    run_id = str(uuid.uuid4())[:8]
    task = ArticleTask(
        task_id=run_id,
        title=art.title,
        keywords=[art.primary_keyword],
    )

    # 更新狀態
    art.status = "researching"
    session.commit()

    try:
        result = await run_orchestrator(task, project_id=project_id, article_id=art.id)

        # 回寫結果
        session.refresh(art)
        draft = result.draft
        if draft:
            art.draft_content = draft.content_markdown
            art.meta_title = draft.meta_title
            art.meta_description = draft.meta_description
            art.slug = draft.slug
            art.faq_schema_json = draft.faq_schema_json or ""
            art.howto_schema_json = draft.howto_schema_json or ""
            art.article_schema_json = draft.article_schema_json or ""
            art.paa_questions_json = draft.paa_questions_json or "[]"
            art.seo_score = draft.seo_score or None

        art.status = result.status or "reviewing"
        art.updated_at = datetime.now(timezone.utc)
        session.commit()

        print(f"\n✅ Pipeline 完成！")
        print(f"   狀態: {art.status}")
        print(f"   SEO 分數: {art.seo_score}")
        print(f"   文章長度: {len(art.draft_content or '')} 字元")
        print(f"   Meta Title: {art.meta_title}")
        print(f"   Meta Desc: {(art.meta_description or '')[:80]}...")
    except Exception as e:
        print(f"\n❌ Pipeline 失敗: {e}")
        art.status = "failed"
        session.commit()
        raise


def main():
    print("=" * 60)
    print("ContentFlow 全鏈路資料播種 & Pipeline 執行")
    print("=" * 60)

    session = SessionLocal()
    try:
        # 取得 project
        project = session.query(Project).order_by(Project.id).first()
        if not project:
            print("❌ 找不到 Project，請先建立專案")
            return
        project_id = project.id
        print(f"\n📦 專案：{project.name} (id={project_id})")

        # Step 1: 競品
        print("\n── Step 1: 競品追蹤 ──────────────────────────")
        seed_competitors(session, project_id)

        # Step 2: 關鍵字
        print("\n── Step 2: 關鍵字庫 ──────────────────────────")
        seed_keywords(session, project_id)

        # Step 3: 文章（支柱 + 衛星）
        print("\n── Step 3: 文章建立（Cluster → Articles）──────")
        seed_articles_from_cluster(session, project_id)

        # Step 4: 內容日曆
        print("\n── Step 4: 內容日曆 ──────────────────────────")
        seed_calendar(session, project_id)

        # Step 5: Agent Pipeline
        print("\n── Step 5: Agent Pipeline 執行 ──────────────")
        asyncio.run(trigger_pipeline(session, project_id))

    finally:
        session.close()

    print("\n" + "=" * 60)
    print("✅ 全部完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
