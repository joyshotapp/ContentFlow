"""多語系 / 多市場 SEO 設定包（P3）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketPack:
    key: str
    label: str
    locale: str
    serp_gl: str
    serp_hl: str
    language_instruction: str
    meta_title_length: tuple[int, int] = (10, 30)
    meta_description_length: tuple[int, int] = (30, 80)


MARKET_PACKS: dict[str, MarketPack] = {
    "zh-tw": MarketPack(
        key="zh-tw",
        label="台灣繁體中文",
        locale="zh-TW",
        serp_gl="tw",
        serp_hl="zh-tw",
        language_instruction="使用台灣繁體中文，語氣專業、清楚、符合在地用語。",
    ),
    "zh-hk": MarketPack(
        key="zh-hk",
        label="香港繁體中文",
        locale="zh-HK",
        serp_gl="hk",
        serp_hl="zh-tw",
        language_instruction="使用香港繁體中文，可適度使用港式用語。",
    ),
    "en-us": MarketPack(
        key="en-us",
        label="美國英語",
        locale="en-US",
        serp_gl="us",
        serp_hl="en",
        language_instruction="Write in American English for search intent clarity.",
        meta_title_length=(30, 60),
        meta_description_length=(70, 160),
    ),
    "ja-jp": MarketPack(
        key="ja-jp",
        label="日本語",
        locale="ja-JP",
        serp_gl="jp",
        serp_hl="ja",
        language_instruction="日本語で、検索意図に沿った専門的で読みやすい文章を書く。",
    ),
}


def resolve_market_pack(locale: str | None) -> MarketPack:
    key = (locale or "zh-tw").strip().lower().replace("_", "-")
    return MARKET_PACKS.get(key, MARKET_PACKS["zh-tw"])


def market_prompt_block(locale: str | None) -> str:
    pack = resolve_market_pack(locale)
    return (
        f"# 市場設定（{pack.label}）\n"
        f"- locale: {pack.locale}\n"
        f"- SERP: gl={pack.serp_gl}, hl={pack.serp_hl}\n"
        f"- {pack.language_instruction}\n"
    )
