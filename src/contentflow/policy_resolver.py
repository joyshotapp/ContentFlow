"""Resolve project and article content policy into a single effective object."""

from __future__ import annotations

import json
from dataclasses import dataclass

from contentflow.policy_profiles import (
    COMPLIANCE_PROFILES,
    CONTENT_FORMAT_PROFILES,
    DOMAIN_PROFILES,
)


@dataclass(frozen=True)
class ResolvedPolicy:
    domain_profile: str
    compliance_profile: str
    content_format: str
    use_pubmed: bool
    evidence_policy: str
    require_reviewer: bool
    reviewer_role_label: str
    disclaimer_template: str
    factcheck_mode: str
    base_schema_types: tuple[str, ...]
    extra_schema_types: tuple[str, ...]
    hero_image_style: str
    hero_image_type_hint: str
    brand_tone_hint: str
    faq_preferred: bool
    howto_preferred: bool

    @property
    def all_schema_types(self) -> tuple[str, ...]:
        seen: list[str] = []
        for schema_type in list(self.base_schema_types) + list(self.extra_schema_types):
            if schema_type and schema_type not in seen:
                seen.append(schema_type)
        return tuple(seen)


_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "health": ("保健", "健康", "醫療", "生技", "營養", "補充", "藥", "骨科", "health", "medical", "wellness", "nutrition"),
    "law": ("法律", "律師", "法務", "law", "legal"),
    "finance": ("理財", "金融", "投資", "保險", "finance", "financial"),
    "ecommerce": ("電商", "零售", "購物", "商品", "ecommerce", "retail", "shop"),
    "tech": ("科技", "軟體", "saas", "tech", "software", "ai", "程式"),
    "food": ("餐飲", "食譜", "料理", "食品", "food", "recipe"),
    "education": ("教育", "學習", "課程", "education", "learning"),
}

_ARTICLE_TYPE_TO_FORMAT = {
    "知識": "knowledge",
    "knowledge": "knowledge",
    "educational": "knowledge",
    "scenario": "scenario",
    "情境": "scenario",
    "seasonal": "seasonal",
    "節慶": "seasonal",
    "product": "product",
    "comparison": "comparison",
    "比較": "comparison",
    "tutorial": "tutorial",
    "教學": "tutorial",
    "how-to": "tutorial",
    "faq": "faq_heavy",
    "faq_heavy": "faq_heavy",
}


def _get_attr(obj, key: str, default=""):
    return getattr(obj, key, default)


def _infer_domain_profile(project_ctx) -> str:
    explicit = (_get_attr(project_ctx, "domain_profile", "") or "").strip().lower()
    if explicit in DOMAIN_PROFILES:
        return explicit

    industry = (_get_attr(project_ctx, "industry", "") or "").strip().lower()
    if industry in DOMAIN_PROFILES:
        return industry

    haystack = "\n".join(
        filter(
            None,
            [
                industry,
                (_get_attr(project_ctx, "name", "") or "").lower(),
                (_get_attr(project_ctx, "brand_name", "") or "").lower(),
                (_get_attr(project_ctx, "brand_description", "") or "").lower(),
                (_get_attr(project_ctx, "writing_principles", "") or "").lower(),
            ],
        )
    )
    for key, markers in _DOMAIN_KEYWORDS.items():
        if any(marker in haystack for marker in markers):
            return key
    return "general"


def _infer_compliance_profile(project_ctx, domain_profile: str) -> str:
    explicit = (_get_attr(project_ctx, "compliance_profile", "") or "").strip().lower()
    if explicit in COMPLIANCE_PROFILES:
        return explicit

    if domain_profile == "health":
        return "ymyl_medical"
    if domain_profile == "law":
        return "ymyl_legal"
    if domain_profile == "finance":
        return "ymyl_financial"
    return "general"


def _resolve_content_format(project_ctx, article_type: str | None = None) -> str:
    if article_type:
        key = _ARTICLE_TYPE_TO_FORMAT.get(article_type.strip().lower())
        if key in CONTENT_FORMAT_PROFILES:
            return key
    explicit = (_get_attr(project_ctx, "default_content_format", "") or "").strip().lower()
    if explicit in CONTENT_FORMAT_PROFILES:
        return explicit
    return "knowledge"


def _parse_extra_schema_types(raw_value) -> tuple[str, ...]:
    if not raw_value:
        return ()
    if isinstance(raw_value, (list, tuple)):
        values = raw_value
    else:
        try:
            values = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ()
    if not isinstance(values, list):
        return ()
    seen: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.append(value)
    return tuple(seen)


def resolve_policy(project_ctx, article_type: str | None = None) -> ResolvedPolicy:
    domain_key = _infer_domain_profile(project_ctx)
    compliance_key = _infer_compliance_profile(project_ctx, domain_key)
    format_key = _resolve_content_format(project_ctx, article_type)

    domain = DOMAIN_PROFILES[domain_key]
    compliance = COMPLIANCE_PROFILES[compliance_key]
    format_profile = CONTENT_FORMAT_PROFILES[format_key]

    evidence_policy = (_get_attr(project_ctx, "evidence_policy", "") or "").strip() or domain.evidence_policy
    reviewer_role_label = (_get_attr(project_ctx, "reviewer_role_label", "") or "").strip() or compliance.reviewer_role_label
    disclaimer_template = (_get_attr(project_ctx, "disclaimer_template", "") or "").strip() or compliance.disclaimer_template
    factcheck_mode = (_get_attr(project_ctx, "factcheck_mode_override", "") or "").strip() or compliance.factcheck_mode
    image_style_override = (_get_attr(project_ctx, "image_style_override", "") or "").strip()
    extra_schema_types = _parse_extra_schema_types(_get_attr(project_ctx, "extra_schema_types_json", "[]"))

    hero_image_style = image_style_override or f"{domain.hero_image_style} {domain.hero_image_tone}".strip()
    use_pubmed = evidence_policy == "pubmed" or compliance.use_pubmed

    return ResolvedPolicy(
        domain_profile=domain_key,
        compliance_profile=compliance_key,
        content_format=format_key,
        use_pubmed=use_pubmed,
        evidence_policy=evidence_policy,
        require_reviewer=compliance.require_reviewer,
        reviewer_role_label=reviewer_role_label,
        disclaimer_template=disclaimer_template,
        factcheck_mode=factcheck_mode,
        base_schema_types=format_profile.base_schema_types,
        extra_schema_types=extra_schema_types,
        hero_image_style=hero_image_style,
        hero_image_type_hint=format_profile.hero_image_type_hint,
        brand_tone_hint=domain.brand_tone_hint,
        faq_preferred=format_profile.faq_preferred,
        howto_preferred=format_profile.howto_preferred,
    )