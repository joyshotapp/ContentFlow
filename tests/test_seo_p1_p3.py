"""P1-P3 SEO 增強單元測試。"""

import json

from contentflow.market_packs import resolve_market_pack
from contentflow.tools.intent_match import score_intent_match
from contentflow.utils.slug_governance import is_weak_slug, normalize_slug, slugify_topic_keyword


class TestSlugGovernance:
    def test_weak_slug_detects_placeholders(self):
        assert is_weak_slug("article-10")
        assert is_weak_slug("c")
        assert not is_weak_slug("knee-pain-relief-guide")

    def test_normalize_slug(self):
        assert normalize_slug("Hello World!") == "hello-world"


class TestIntentMatch:
    def test_high_score_when_queries_align(self):
        score, _ = score_intent_match(
            "落枕怎麼辦",
            [{"query": "落枕怎麼辦", "impressions": 100}],
        )
        assert score >= 80


class TestMarketPack:
    def test_en_us_pack(self):
        pack = resolve_market_pack("en-us")
        assert pack.serp_gl == "us"
        assert pack.locale == "en-US"
