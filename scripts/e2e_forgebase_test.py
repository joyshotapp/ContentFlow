"""End-to-end integration test: ContentFlow ForgeBasePublisher → ForgeBase API.

This script simulates the exact flow that ContentFlow's orchestrator uses:
  Step 1: POST /api/v1/content/briefs  → create PageBrief
  Step 2: POST /api/v1/content/pages   → create Page (draft)
  Step 3: POST /api/v1/content/pages/{id}/publish → publish
"""
import asyncio
import sys
import os

# Add ContentFlow to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from contentflow.publishers.forgebase import ForgeBasePublisher


async def main():
    # Use the settings from .env (already loaded via dotenv)
    from contentflow.config import settings

    print("=" * 60)
    print("ContentFlow → ForgeBase 端對端整合測試")
    print("=" * 60)
    print(f"ForgeBase URL: {settings.forgebase_api_base_url}")
    print(f"API Token:     {settings.forgebase_api_token[:8]}...")
    print()

    fb = ForgeBasePublisher()

    # Create a test article draft
    from contentflow.models.schemas import ArticleDraft

    draft = ArticleDraft(
        title="膝蓋長骨刺怎麼辦？完整治療與預防指南",
        content_markdown=(
            "## 什麼是膝蓋骨刺？\n\n膝蓋骨刺（又稱骨贅）是關節邊緣因退化性關節炎而增生的骨質突起...\n\n"
            "## 常見症狀\n\n- 膝蓋疼痛，尤其在活動後加劇\n- 關節僵硬\n- 活動範圍受限\n\n"
            "## 治療方法\n\n### 1. 保守治療\n\n- 物理治療\n- 藥物治療\n- 注射療法\n\n"
            "### 2. 手術治療\n\n當保守治療無效時，可考慮關節鏡手術或人工膝關節置換。\n\n"
            "## 預防建議\n\n- 維持適當體重\n- 規律運動\n- 避免長時間蹲跪"
        ),
        word_count=350,
        meta_title="膝蓋長骨刺怎麼辦？2026完整治療預防指南",
        meta_description="膝蓋長骨刺是退化性關節炎常見症狀。本文完整介紹骨刺成因、症狀、治療方法及預防建議。",
        slug="knee-bone-spur-treatment-guide",
    )

    # Manually test step 1 first to see full response
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        brief_payload = {
            "target_page_type": "blog_post",
            "target_slug": draft.slug,
            "title_draft": draft.title,
            "primary_keyword": "膝蓋長骨刺",
            "secondary_keywords": "[]",
            "word_count_target": 350,
            "locale": "zh-tw",
        }
        r = await client.post(
            f"{settings.forgebase_api_base_url}/api/v1/content/briefs",
            json=brief_payload,
            headers={"X-API-Key": settings.forgebase_api_token, "Content-Type": "application/json"},
        )
        print(f"    Step1 raw status: {r.status_code}")
        print(f"    Step1 raw body:   {r.text[:500]}")
        print()

    # --- Step 1+2: publish_draft (creates Brief + Page) ---
    print(">>> Step 1+2: publish_draft (Brief + Page draft)")
    result = await fb.publish_draft(draft, primary_keyword="膝蓋長骨刺")
    print(f"    success:     {result.success}")
    print(f"    post_id:     {result.post_id}")
    print(f"    error:       {result.error}")
    print(f"    metadata:    {result.metadata}")
    print()

    if not result.success:
        print(f"❌ FAILED at draft stage: {result.error}")
        return False

    page_id = result.post_id
    brief_id = result.metadata.get("brief_id")
    print(f"    ✅ Brief created: {brief_id}")
    print(f"    ✅ Page draft created: {page_id}")
    print()

    # --- Step 3: publish_page ---
    print(f">>> Step 3: publish_page({page_id})")
    pub_result = await fb.publish_page(page_id)
    print(f"    success:     {pub_result.success}")
    print(f"    publish_url: {pub_result.publish_url}")
    print(f"    error:       {pub_result.error}")
    print()

    if not pub_result.success:
        print(f"❌ FAILED at publish stage: {pub_result.error}")
        return False

    # --- Verify: get_post_url ---
    print(f">>> Verify: get_post_url({page_id})")
    url = await fb.get_post_url(page_id)
    print(f"    URL: {url}")
    print()

    print("=" * 60)
    print("✅ 端對端閉環測試通過！")
    print(f"   Brief:  {brief_id}")
    print(f"   Page:   {page_id}")
    print(f"   URL:    {pub_result.publish_url or url}")
    print("=" * 60)
    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
