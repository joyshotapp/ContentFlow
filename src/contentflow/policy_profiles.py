"""Policy profile definitions for multi-domain content generation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainProfile:
    key: str
    label: str
    evidence_policy: str
    hero_image_style: str
    hero_image_tone: str
    brand_tone_hint: str


@dataclass(frozen=True)
class ComplianceProfile:
    key: str
    label: str
    require_reviewer: bool
    reviewer_role_label: str
    disclaimer_template: str
    factcheck_mode: str
    use_pubmed: bool = False


@dataclass(frozen=True)
class ContentFormatProfile:
    key: str
    label: str
    base_schema_types: tuple[str, ...]
    hero_image_type_hint: str
    faq_preferred: bool = True
    howto_preferred: bool = False


DOMAIN_PROFILES: dict[str, DomainProfile] = {
    "health": DomainProfile(
        key="health",
        label="Health",
        evidence_policy="pubmed",
        hero_image_style="Professional medical illustration. Clean, trustworthy, clinical atmosphere.",
        hero_image_tone="Soft blue-white palette.",
        brand_tone_hint="專業、可信、清楚，避免誇大療效與過度情緒化語氣。",
    ),
    "law": DomainProfile(
        key="law",
        label="Law",
        evidence_policy="manual_reference",
        hero_image_style="Professional legal editorial illustration. Formal, credible and restrained.",
        hero_image_tone="Deep navy, neutral gray and gold accent palette.",
        brand_tone_hint="正式、精準、保守，避免過度保證式措辭。",
    ),
    "finance": DomainProfile(
        key="finance",
        label="Finance",
        evidence_policy="manual_reference",
        hero_image_style="Professional business editorial illustration. Modern, data-driven and restrained.",
        hero_image_tone="Blue-gray palette with clean corporate composition.",
        brand_tone_hint="清楚、理性、風險揭露完整，避免投資保證式語言。",
    ),
    "ecommerce": DomainProfile(
        key="ecommerce",
        label="Ecommerce",
        evidence_policy="none",
        hero_image_style="Conversion-oriented product visual. Clean, polished and commercially appealing.",
        hero_image_tone="Bright neutral palette with strong product focus.",
        brand_tone_hint="清楚、導購、聚焦價值與比較，不堆砌空泛形容。",
    ),
    "tech": DomainProfile(
        key="tech",
        label="Tech",
        evidence_policy="none",
        hero_image_style="Modern tech editorial illustration. Clean, sharp and product-literate.",
        hero_image_tone="Neutral dark-on-light palette with subtle blue accents.",
        brand_tone_hint="專業、直接、條理清楚，避免醫療或勵志式語氣。",
    ),
    "food": DomainProfile(
        key="food",
        label="Food",
        evidence_policy="none",
        hero_image_style="Warm food editorial photography and illustration. Natural and appetizing.",
        hero_image_tone="Warm natural lighting and fresh color palette.",
        brand_tone_hint="溫暖、具體、感官描述清楚，避免過度保健承諾。",
    ),
    "education": DomainProfile(
        key="education",
        label="Education",
        evidence_policy="none",
        hero_image_style="Educational infographic style. Clear hierarchy and explanatory composition.",
        hero_image_tone="Clean bright palette with structured layout.",
        brand_tone_hint="教學導向、拆解清楚、循序漸進。",
    ),
    "general": DomainProfile(
        key="general",
        label="General",
        evidence_policy="none",
        hero_image_style="Professional editorial illustration. Neutral, modern and broadly applicable.",
        hero_image_tone="Balanced neutral palette.",
        brand_tone_hint="清楚、專業、避免過度承諾。",
    ),
}


COMPLIANCE_PROFILES: dict[str, ComplianceProfile] = {
    "general": ComplianceProfile(
        key="general",
        label="General",
        require_reviewer=False,
        reviewer_role_label="",
        disclaimer_template="",
        factcheck_mode="light",
        use_pubmed=False,
    ),
    "regulated_soft": ComplianceProfile(
        key="regulated_soft",
        label="Regulated Soft",
        require_reviewer=False,
        reviewer_role_label="專業審閱",
        disclaimer_template="本文內容僅供一般資訊參考，實際使用與選擇仍應依個人情況審慎評估。",
        factcheck_mode="moderate",
        use_pubmed=False,
    ),
    "ymyl_medical": ComplianceProfile(
        key="ymyl_medical",
        label="YMYL Medical",
        require_reviewer=True,
        reviewer_role_label="醫療審閱",
        disclaimer_template="本文醫療保健資訊僅供教育參考，不構成醫療診斷或治療建議。如有健康疑慮，請諮詢合格醫師或藥師。",
        factcheck_mode="strict",
        use_pubmed=True,
    ),
    "ymyl_financial": ComplianceProfile(
        key="ymyl_financial",
        label="YMYL Financial",
        require_reviewer=True,
        reviewer_role_label="財務審閱",
        disclaimer_template="本文財務資訊僅供一般教育參考，不構成投資或理財建議。任何投資決策前，請諮詢合格財務顧問並自行承擔風險。",
        factcheck_mode="strict",
        use_pubmed=False,
    ),
    "ymyl_legal": ComplianceProfile(
        key="ymyl_legal",
        label="YMYL Legal",
        require_reviewer=True,
        reviewer_role_label="法律審閱",
        disclaimer_template="本文法律資訊僅供一般參考，不構成正式法律意見或個案建議。具體案件請諮詢合格律師。",
        factcheck_mode="strict",
        use_pubmed=False,
    ),
}


CONTENT_FORMAT_PROFILES: dict[str, ContentFormatProfile] = {
    "knowledge": ContentFormatProfile(
        key="knowledge",
        label="Knowledge",
        base_schema_types=("BlogPosting",),
        hero_image_type_hint="editorial knowledge illustration",
        faq_preferred=True,
        howto_preferred=False,
    ),
    "scenario": ContentFormatProfile(
        key="scenario",
        label="Scenario",
        base_schema_types=("BlogPosting",),
        hero_image_type_hint="lifestyle scenario image",
        faq_preferred=True,
        howto_preferred=False,
    ),
    "seasonal": ContentFormatProfile(
        key="seasonal",
        label="Seasonal",
        base_schema_types=("BlogPosting",),
        hero_image_type_hint="seasonal editorial visual",
        faq_preferred=True,
        howto_preferred=False,
    ),
    "product": ContentFormatProfile(
        key="product",
        label="Product",
        base_schema_types=("BlogPosting", "Product"),
        hero_image_type_hint="product photography",
        faq_preferred=True,
        howto_preferred=False,
    ),
    "comparison": ContentFormatProfile(
        key="comparison",
        label="Comparison",
        base_schema_types=("Article",),
        hero_image_type_hint="comparison editorial chart-like visual",
        faq_preferred=True,
        howto_preferred=False,
    ),
    "tutorial": ContentFormatProfile(
        key="tutorial",
        label="Tutorial",
        base_schema_types=("BlogPosting", "HowTo"),
        hero_image_type_hint="step-by-step tutorial visual",
        faq_preferred=True,
        howto_preferred=True,
    ),
    "faq_heavy": ContentFormatProfile(
        key="faq_heavy",
        label="FAQ Heavy",
        base_schema_types=("BlogPosting", "FAQPage"),
        hero_image_type_hint="faq infographic visual",
        faq_preferred=True,
        howto_preferred=False,
    ),
}


SUPPORTED_DOMAIN_PROFILES = tuple(DOMAIN_PROFILES.keys())
SUPPORTED_COMPLIANCE_PROFILES = tuple(COMPLIANCE_PROFILES.keys())
SUPPORTED_CONTENT_FORMAT_PROFILES = tuple(CONTENT_FORMAT_PROFILES.keys())