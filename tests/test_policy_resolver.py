from contentflow.policy_resolver import resolve_policy
from contentflow.project_context import ProjectContext


def test_health_project_resolves_pubmed_and_medical_defaults():
    ctx = ProjectContext(
        project_id=1,
        slug="health",
        name="Health",
        industry="保健食品",
    )

    policy = resolve_policy(ctx, article_type="知識")

    assert policy.domain_profile == "health"
    assert policy.compliance_profile == "ymyl_medical"
    assert policy.use_pubmed is True
    assert policy.reviewer_role_label == "醫療審閱"
    assert "Medical" not in policy.all_schema_types  # medical type injected by writing policy layer


def test_ecommerce_project_resolves_product_without_medical_defaults():
    ctx = ProjectContext(
        project_id=2,
        slug="shop",
        name="Shop",
        industry="電商零售",
    )

    policy = resolve_policy(ctx, article_type="product")

    assert policy.domain_profile == "ecommerce"
    assert policy.compliance_profile == "general"
    assert policy.use_pubmed is False
    assert policy.content_format == "product"
    assert "Product" in policy.all_schema_types
    assert "medical" not in policy.hero_image_style.lower()


def test_project_override_wins_over_defaults():
    ctx = ProjectContext(
        project_id=3,
        slug="custom",
        name="Custom",
        industry="科技媒體",
    )
    ctx.domain_profile = "tech"
    ctx.compliance_profile = "ymyl_legal"
    ctx.default_content_format = "tutorial"
    ctx.reviewer_role_label = "資深法務審閱"
    ctx.disclaimer_template = "自訂免責聲明"
    ctx.evidence_policy = "none"
    ctx.image_style_override = "Custom image style"
    ctx.extra_schema_types_json = '["FAQPage"]'
    ctx.factcheck_mode_override = "moderate"

    policy = resolve_policy(ctx)

    assert policy.domain_profile == "tech"
    assert policy.compliance_profile == "ymyl_legal"
    assert policy.content_format == "tutorial"
    assert policy.reviewer_role_label == "資深法務審閱"
    assert policy.disclaimer_template == "自訂免責聲明"
    assert policy.evidence_policy == "none"
    assert policy.hero_image_style == "Custom image style"
    assert policy.factcheck_mode == "moderate"
    assert "FAQPage" in policy.all_schema_types