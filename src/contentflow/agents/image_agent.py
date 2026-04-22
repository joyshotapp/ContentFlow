"""Image Agent：分析文章段落，生成配圖 Prompt、Alt Text 及 SEO 語義檔名。"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from pathlib import Path
from loguru import logger

from ..config import settings
from ..llm_client import chat_sync
from ..models import ArticleDraft


def _extract_sections(markdown: str) -> list[dict]:
    """從 Markdown 提取 H2 段落標題與內文摘要。"""
    sections = []
    parts = re.split(r"^(## .+)$", markdown, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        heading = parts[i].strip("# ").strip()
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        # 取前 200 字作為摘要
        summary = body[:200].replace("\n", " ")
        sections.append({"heading": heading, "summary": summary})
    return sections


def _generate_image_prompts(title: str, sections: list[dict]) -> list[str]:
    """用 LLM 為每個段落生成圖片 prompt（供 Gemini 圖片生成使用）。"""
    section_text = "\n".join(
        f"- {s['heading']}: {s['summary']}" for s in sections[:8]
    )

    raw = chat_sync(
        messages=[
            {
                "role": "system",
                "content": (
                    "You generate image prompts for blog article illustrations. "
                    "Each prompt should be a detailed image generation prompt in English, "
                    "describing a professional, clean illustration suitable for a health/lifestyle blog. "
                    "Avoid text in images. Use flat illustration or photography style.\n\n"
                    "Return a JSON array of objects: [{\"section\": \"heading\", \"prompt\": \"...\", \"alt_text\": \"...\", \"filename\": \"...\"}]\n"
                    "- alt_text: concise descriptive alt text in Traditional Chinese (within 80 chars)\n"
                    "- filename: SEO-friendly English slug for the image file (no extension, kebab-case, include main keyword)\n"
                    "Generate prompts ONLY for sections that benefit from an illustration (skip intro/conclusion). "
                    "Return ONLY the JSON array."
                ),
            },
            {
                "role": "user",
                "content": f"Article: {title}\n\nSections:\n{section_text}",
            },
        ],
        max_tokens=1024,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]

    try:
        items = json.loads(raw.strip())
        return items  # Return full dicts now (prompt + alt_text + filename)
    except (json.JSONDecodeError, KeyError):
        logger.warning("[Image Agent] Prompt 生成 JSON 解析失敗")
        return []


def _to_seo_filename(title: str, primary_keyword: str, index: int) -> str:
    """Generate a safe, SEO-friendly kebab-case filename from keyword + title."""
    base = f"{primary_keyword}-{title}" if primary_keyword else title
    # Normalize unicode, strip non-ascii for safety in filenames
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", base.lower())
    base = base.strip("-")[:60]
    return f"{base}-{index:02d}" if base else f"image-{index:02d}"


async def _generate_image_gemini(prompt: str) -> bytes | None:
    """使用 Gemini gemini-3.1-flash-image-preview 生成圖片，回傳 WebP bytes。"""
    from google import genai
    from google.genai import types

    try:
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(
                    aspect_ratio="16:9",
                    image_size="1K",
                ),
            ),
        )
        for part in response.parts:
            if part.inline_data is not None:
                image = part.as_image()
                buf = io.BytesIO()
                image.save(buf, format="WEBP")
                return buf.getvalue()
    except Exception as e:
        logger.warning(f"[Image Agent] Gemini 圖片生成失敗：{e}")
    return None


async def run_image_agent(
    draft: ArticleDraft,
    output_dir: Path | None = None,
    generate_images: bool = False,
) -> ArticleDraft:
    """
    分析文章段落，生成配圖 Prompt。

    Args:
        draft: 文章草稿
        output_dir: 圖片輸出目錄（僅 generate_images=True 時使用）
        generate_images: 是否實際呼叫 Gemini gemini-3.1-flash-image-preview 生成圖片

    Returns:
        更新 image_prompts 欄位的 draft
    """
    logger.info(f"[Image Agent] 啟動：「{draft.title}」")

    sections = _extract_sections(draft.content_markdown)
    if not sections:
        logger.warning("[Image Agent] 未找到 H2 段落，跳過")
        return draft

    logger.info(f"[Image Agent] 找到 {len(sections)} 個段落，生成配圖 Prompt…")

    prompt_items = _generate_image_prompts(draft.title, sections)
    # Support both old (list of strings) and new (list of dicts) formats
    prompts = []
    image_seo_metadata: list[dict] = []
    for i, item in enumerate(prompt_items):
        if isinstance(item, dict):
            prompts.append(item.get("prompt", ""))
            image_seo_metadata.append({
                "section": item.get("section", ""),
                "prompt": item.get("prompt", ""),
                "alt_text": item.get("alt_text", ""),
                "filename": (item.get("filename", "") or
                             _to_seo_filename(draft.title, draft.primary_keyword or "", i + 1)) + ".webp",
            })
        else:
            prompts.append(str(item))
            image_seo_metadata.append({
                "section": "",
                "prompt": str(item),
                "alt_text": draft.title,
                "filename": _to_seo_filename(draft.title, draft.primary_keyword or "", i + 1) + ".webp",
            })

    draft.image_prompts = prompts
    # Store full SEO metadata as JSON in image_seo_metadata field if it exists
    if hasattr(draft, "image_seo_metadata"):
        draft.image_seo_metadata = json.dumps(image_seo_metadata, ensure_ascii=False)
    logger.info(f"[Image Agent] 生成 {len(prompts)} 個配圖 Prompt（含 alt text + WebP 檔名）")

    # 可選：實際生成圖片
    if generate_images and prompts and output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        generated = 0
        for i, prompt in enumerate(prompts[:5]):  # 最多 5 張
            try:
                img_bytes = await _generate_image_gemini(prompt)
                if img_bytes:
                    seo_fname = (image_seo_metadata[i]["filename"]
                                 if i < len(image_seo_metadata) else f"image-{i+1:02d}.webp")
                    img_path = output_dir / seo_fname
                    img_path.write_bytes(img_bytes)
                    generated += 1
                    logger.info(f"[Image Agent] 圖片 {i+1} 已保存：{img_path}")
            except Exception as e:
                logger.warning(f"[Image Agent] 圖片 {i+1} 生成失敗：{e}")

        logger.info(f"[Image Agent] 共生成 {generated}/{len(prompts)} 張圖片（WebP 命名）")

    return draft
