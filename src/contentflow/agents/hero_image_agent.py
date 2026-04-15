"""Hero Image Agent：使用 Gemini 生成文章 Hero Banner，上傳至 Cloudflare R2。

生成策略：
  - 模型：gemini-3.1-flash-image-preview（速度/品質/成本平衡最佳）
  - 比例：16:9（適合文章 hero banner）
  - 解析度：1K（1376×768，網頁足夠）
  - 風格：醫學插圖風，非寫真病患照，符合 YMYL 信任標準
  - 圖片格式：WebP（R2 儲存後以 CDN URL 提供）
"""

from __future__ import annotations

import io
import re
import time
import unicodedata
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config
from google import genai
from google.genai import types
from loguru import logger

from ..config import settings
from ..models import ArticleDraft


# ── 常數 ─────────────────────────────────────────────────────

GEMINI_MODEL = "gemini-3.1-flash-image-preview"
IMAGE_ASPECT_RATIO = "16:9"
IMAGE_SIZE = "1K"          # 1376×768
MAX_RETRIES = 2
RETRY_DELAY = 3             # 秒


# ── 內部工具 ─────────────────────────────────────────────────

def _gemini_client() -> genai.Client:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY 未設定，無法使用 Gemini 生圖")
    return genai.Client(api_key=settings.gemini_api_key)


def _r2_client():
    if not settings.r2_access_key_id or not settings.r2_secret_access_key:
        raise RuntimeError("R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY 未設定")
    return boto3.client(
        "s3",
        endpoint_url=settings.r2_endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def _slug_to_r2_key(slug: str, suffix: str = "hero") -> str:
    """將文章 slug 轉為 R2 物件鍵，如 images/knee-bone-spur/hero.webp。"""
    safe = re.sub(r"[^a-z0-9\-]", "", slug.lower().replace("_", "-"))
    return f"images/{safe}/{suffix}.webp"


def _build_prompt(title: str, primary_keyword: str, article_type: str) -> str:
    """根據文章主題建立 Gemini 生圖 prompt。"""
    style_guide = (
        "Professional medical illustration style. "
        "Clean, modern, clinical atmosphere. "
        "Soft blue-white color palette. "
        "No text, no watermarks, no people's faces. "
        "Suitable for a health knowledge website. "
        "High quality, 16:9 aspect ratio banner."
    )

    type_hints = {
        "知識": "educational infographic style, anatomical diagram elements",
        "情境": "lifestyle photography style, natural warm lighting, daily life scene",
        "節慶": "seasonal festive elements, warm colors",
        "product": "product photography style, clean white background, studio lighting",
    }
    type_hint = type_hints.get(article_type, "medical illustration")

    keyword_clean = primary_keyword.replace("_", " ") if primary_keyword else title

    return (
        f"Create a hero banner image for a health article titled '{title}'. "
        f"Main topic: {keyword_clean}. "
        f"Visual style: {type_hint}. "
        f"{style_guide}"
    )


def _upload_to_r2(image_bytes: bytes, r2_key: str) -> str:
    """上傳圖片到 Cloudflare R2，回傳公開 URL。"""
    client = _r2_client()
    client.put_object(
        Bucket=settings.r2_bucket_name,
        Key=r2_key,
        Body=image_bytes,
        ContentType="image/webp",
        CacheControl="public, max-age=31536000",
    )

    if settings.r2_public_url:
        base = settings.r2_public_url.rstrip("/")
        return f"{base}/{r2_key}"

    # 若沒設公開 URL，用 R2 endpoint + bucket 組合（需 bucket 設為公開）
    base = settings.r2_endpoint_url.rstrip("/")
    return f"{base}/{settings.r2_bucket_name}/{r2_key}"


# ── 主要函式 ─────────────────────────────────────────────────

async def generate_hero_image(
    title: str,
    primary_keyword: str = "",
    article_type: str = "知識",
    slug: str = "",
) -> Optional[str]:
    """
    呼叫 Gemini 生成 hero image，上傳至 R2，回傳公開 URL。

    Returns:
        圖片 URL（成功），或 None（失敗）
    """
    if not settings.gemini_api_key:
        logger.warning("[HeroImage] GEMINI_API_KEY 未設定，跳過生圖")
        return None

    prompt = _build_prompt(title, primary_keyword, article_type)
    r2_key = _slug_to_r2_key(slug or re.sub(r"[^a-z0-9\-]", "", title.lower()[:40].replace(" ", "-")))

    logger.info(f"[HeroImage] 開始生成：「{title}」")

    client = _gemini_client()
    image_bytes: Optional[bytes] = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=IMAGE_ASPECT_RATIO,
                        image_size=IMAGE_SIZE,
                    ),
                ),
            )

            for part in response.parts:
                if part.inline_data is not None:
                    image_bytes = part.inline_data.data
                    break

            if image_bytes:
                break

            logger.warning(f"[HeroImage] 第 {attempt} 次未取得圖片，重試…")
        except Exception as exc:
            logger.warning(f"[HeroImage] Gemini API 錯誤（第 {attempt} 次）：{exc}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    if not image_bytes:
        logger.error("[HeroImage] 生圖失敗，回傳 None")
        return None

    logger.info(f"[HeroImage] 生圖成功（{len(image_bytes):,} bytes），上傳至 R2…")

    try:
        url = _upload_to_r2(image_bytes, r2_key)
        logger.info(f"[HeroImage] 上傳完成：{url}")
        return url
    except Exception as exc:
        logger.error(f"[HeroImage] R2 上傳失敗：{exc}")
        return None


async def run_hero_image_agent(draft: ArticleDraft, article_type: str = "知識") -> ArticleDraft:
    """
    為文章草稿生成 hero image 並更新 draft.hero_image_url。

    Args:
        draft: 文章草稿
        article_type: 文章類型（知識/情境/節慶/product）

    Returns:
        更新 hero_image_url 的 draft
    """
    url = await generate_hero_image(
        title=draft.title,
        primary_keyword=getattr(draft, "primary_keyword", "") or "",
        article_type=article_type,
        slug=draft.slug or "",
    )
    if url:
        draft.hero_image_url = url
    return draft
