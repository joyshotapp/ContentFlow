"""P0：自動發布安全閘與 JSON-LD headline 對齊。"""

import json

import pytest

from contentflow.models.schemas import ArticleStatus, ConfidenceLevel, FactCheckItem
from contentflow.utils.article_schema import sync_article_schema_headline
from contentflow.utils.publish_safety import (
    article_has_factcheck_risk,
    can_auto_publish_article,
    serialize_factcheck_flags,
)


class TestPublishSafety:
    def test_serialize_only_needs_review_items(self):
        items = [
            FactCheckItem(claim="違規宣稱", paragraph_index=1, confidence=ConfidenceLevel.HIGH, needs_review=True),
            FactCheckItem(claim="一般敘述", paragraph_index=2, confidence=ConfidenceLevel.HIGH, needs_review=False),
        ]
        raw = serialize_factcheck_flags(items)
        payload = json.loads(raw)
        assert len(payload) == 1
        assert payload[0]["claim"] == "違規宣稱"

    def test_can_auto_publish_when_approved_and_clean(self):
        assert can_auto_publish_article(
            pipeline_status=ArticleStatus.APPROVED,
            factcheck_flags_json="[]",
            auto_publish_enabled=True,
        )

    def test_blocks_review_required_status(self):
        assert not can_auto_publish_article(
            pipeline_status=ArticleStatus.REVIEW_REQUIRED,
            factcheck_flags_json="[]",
            auto_publish_enabled=True,
        )

    def test_blocks_when_factcheck_flags_present(self):
        flags = serialize_factcheck_flags([
            FactCheckItem(claim="需審", paragraph_index=0, confidence=ConfidenceLevel.LOW, needs_review=True),
        ])
        assert article_has_factcheck_risk(flags)
        assert not can_auto_publish_article(
            pipeline_status="approved",
            factcheck_flags_json=flags,
            auto_publish_enabled=True,
        )


class TestArticleSchemaSync:
    def test_headline_matches_meta_title(self):
        raw = json.dumps({"@context": "https://schema.org", "headline": "舊標題", "description": "舊描述"})
        synced = sync_article_schema_headline(
            raw,
            meta_title="落枕怎麼辦？快速緩解",
            title="落枕怎麼辦？完整指南",
            meta_description="新的 meta 描述文字",
        )
        schema = json.loads(synced)
        assert schema["headline"] == "落枕怎麼辦？快速緩解"
        assert schema["description"] == "新的 meta 描述文字"
