"""add project policy profiles and article override fields

Revision ID: 017
Revises: 016
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(col.get("name") == column for col in insp.get_columns(table))


def _backfill_project_profiles() -> None:
    bind = op.get_bind()
    projects = sa.table(
        "projects",
        sa.column("id", sa.Integer()),
        sa.column("industry", sa.String()),
        sa.column("name", sa.String()),
        sa.column("brand_name", sa.String()),
        sa.column("brand_description", sa.Text()),
        sa.column("writing_principles", sa.Text()),
        sa.column("domain_profile", sa.String()),
        sa.column("compliance_profile", sa.String()),
        sa.column("default_content_format", sa.String()),
    )
    rows = bind.execute(
        sa.select(
            projects.c.id,
            projects.c.industry,
            projects.c.name,
            projects.c.brand_name,
            projects.c.brand_description,
            projects.c.writing_principles,
        )
    ).fetchall()
    health_markers = ("保健", "健康", "醫療", "生技", "藥", "骨科", "health", "medical", "wellness")
    law_markers = ("法律", "律師", "法務", "law", "legal")
    finance_markers = ("金融", "理財", "投資", "finance", "financial")
    ecommerce_markers = ("電商", "零售", "購物", "ecommerce", "retail", "shop")
    tech_markers = ("科技", "軟體", "saas", "tech", "software", "ai")

    for row in rows:
        haystack = "\n".join(filter(None, [row.industry, row.name, row.brand_name, row.brand_description, row.writing_principles])).lower()
        domain_profile = "general"
        compliance_profile = "general"
        if any(marker in haystack for marker in health_markers):
            domain_profile = "health"
            compliance_profile = "ymyl_medical"
        elif any(marker in haystack for marker in law_markers):
            domain_profile = "law"
            compliance_profile = "ymyl_legal"
        elif any(marker in haystack for marker in finance_markers):
            domain_profile = "finance"
            compliance_profile = "ymyl_financial"
        elif any(marker in haystack for marker in ecommerce_markers):
            domain_profile = "ecommerce"
        elif any(marker in haystack for marker in tech_markers):
            domain_profile = "tech"
        bind.execute(
            sa.update(projects)
            .where(projects.c.id == row.id)
            .values(
                domain_profile=domain_profile,
                compliance_profile=compliance_profile,
                default_content_format="knowledge",
            )
        )


def upgrade() -> None:
    if _table_exists("projects") and not _column_exists("projects", "domain_profile"):
        op.add_column("projects", sa.Column("domain_profile", sa.String(), server_default="general", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "compliance_profile"):
        op.add_column("projects", sa.Column("compliance_profile", sa.String(), server_default="general", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "default_content_format"):
        op.add_column("projects", sa.Column("default_content_format", sa.String(), server_default="knowledge", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "reviewer_role_label"):
        op.add_column("projects", sa.Column("reviewer_role_label", sa.String(), server_default="", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "disclaimer_template"):
        op.add_column("projects", sa.Column("disclaimer_template", sa.Text(), server_default="", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "evidence_policy"):
        op.add_column("projects", sa.Column("evidence_policy", sa.String(), server_default="default", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "image_style_override"):
        op.add_column("projects", sa.Column("image_style_override", sa.Text(), server_default="", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "extra_schema_types_json"):
        op.add_column("projects", sa.Column("extra_schema_types_json", sa.Text(), server_default="[]", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "factcheck_mode_override"):
        op.add_column("projects", sa.Column("factcheck_mode_override", sa.String(), server_default="", nullable=False))

    if _table_exists("articles") and not _column_exists("articles", "content_format_override"):
        op.add_column("articles", sa.Column("content_format_override", sa.String(), server_default="", nullable=False))
    if _table_exists("articles") and not _column_exists("articles", "reviewer_required_override"):
        op.add_column("articles", sa.Column("reviewer_required_override", sa.Boolean(), nullable=True))
    if _table_exists("articles") and not _column_exists("articles", "custom_disclaimer"):
        op.add_column("articles", sa.Column("custom_disclaimer", sa.Text(), server_default="", nullable=False))
    if _table_exists("articles") and not _column_exists("articles", "extra_schema_types_override_json"):
        op.add_column("articles", sa.Column("extra_schema_types_override_json", sa.Text(), server_default="[]", nullable=False))

    if _table_exists("projects"):
        _backfill_project_profiles()


def downgrade() -> None:
    if _table_exists("articles") and any(
        _column_exists("articles", column)
        for column in (
            "extra_schema_types_override_json",
            "custom_disclaimer",
            "reviewer_required_override",
            "content_format_override",
        )
    ):
        with op.batch_alter_table("articles") as batch_op:
            if _column_exists("articles", "extra_schema_types_override_json"):
                batch_op.drop_column("extra_schema_types_override_json")
            if _column_exists("articles", "custom_disclaimer"):
                batch_op.drop_column("custom_disclaimer")
            if _column_exists("articles", "reviewer_required_override"):
                batch_op.drop_column("reviewer_required_override")
            if _column_exists("articles", "content_format_override"):
                batch_op.drop_column("content_format_override")

    if _table_exists("projects") and any(
        _column_exists("projects", column)
        for column in (
            "factcheck_mode_override",
            "extra_schema_types_json",
            "image_style_override",
            "evidence_policy",
            "disclaimer_template",
            "reviewer_role_label",
            "default_content_format",
            "compliance_profile",
            "domain_profile",
        )
    ):
        with op.batch_alter_table("projects") as batch_op:
            if _column_exists("projects", "factcheck_mode_override"):
                batch_op.drop_column("factcheck_mode_override")
            if _column_exists("projects", "extra_schema_types_json"):
                batch_op.drop_column("extra_schema_types_json")
            if _column_exists("projects", "image_style_override"):
                batch_op.drop_column("image_style_override")
            if _column_exists("projects", "evidence_policy"):
                batch_op.drop_column("evidence_policy")
            if _column_exists("projects", "disclaimer_template"):
                batch_op.drop_column("disclaimer_template")
            if _column_exists("projects", "reviewer_role_label"):
                batch_op.drop_column("reviewer_role_label")
            if _column_exists("projects", "default_content_format"):
                batch_op.drop_column("default_content_format")
            if _column_exists("projects", "compliance_profile"):
                batch_op.drop_column("compliance_profile")
            if _column_exists("projects", "domain_profile"):
                batch_op.drop_column("domain_profile")
