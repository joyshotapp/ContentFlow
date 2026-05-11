"""add project site profile fields and integrations

Revision ID: 014
Revises: 013
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "014"
down_revision = "013"
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


def _index_exists(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(index.get("name") == index_name for index in insp.get_indexes(table))


def _unique_constraint_exists(table: str, constraint_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(constraint.get("name") == constraint_name for constraint in insp.get_unique_constraints(table))


def _deduplicate_project_integrations() -> None:
    bind = op.get_bind()
    table = sa.table(
        "project_integrations",
        sa.column("id", sa.Integer()),
        sa.column("project_id", sa.Integer()),
        sa.column("integration_type", sa.String()),
    )
    rows = bind.execute(
        sa.select(table.c.id, table.c.project_id, table.c.integration_type)
        .order_by(table.c.project_id, table.c.integration_type, table.c.id.desc())
    ).fetchall()
    seen: set[tuple[int, str]] = set()
    delete_ids: list[int] = []
    for row in rows:
        key = (row.project_id, row.integration_type)
        if key in seen:
            delete_ids.append(row.id)
        else:
            seen.add(key)
    if delete_ids:
        bind.execute(sa.delete(table).where(table.c.id.in_(delete_ids)))


def upgrade() -> None:
    if _table_exists("projects") and not _column_exists("projects", "site_contact_email"):
        op.add_column("projects", sa.Column("site_contact_email", sa.String(), server_default="", nullable=False))
    if _table_exists("projects") and not _column_exists("projects", "site_blog_path"):
        op.add_column("projects", sa.Column("site_blog_path", sa.String(), server_default="/blog", nullable=False))

    if not _table_exists("project_integrations"):
        op.create_table(
            "project_integrations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("integration_type", sa.String(), nullable=False),
            sa.Column("label", sa.String(), server_default="", nullable=False),
            sa.Column("base_url", sa.String(), server_default="", nullable=False),
            sa.Column("username", sa.String(), server_default="", nullable=False),
            sa.Column("secret_value", sa.Text(), server_default="", nullable=False),
            sa.Column("seo_plugin", sa.String(), server_default="yoast", nullable=False),
            sa.Column("publish_mode", sa.String(), server_default="publish", nullable=False),
            sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
            sa.Column("health_status", sa.String(), server_default="unknown", nullable=False),
            sa.Column("last_checked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    if _table_exists("project_integrations") and not _index_exists("project_integrations", "ix_project_integrations_project_id"):
        op.create_index("ix_project_integrations_project_id", "project_integrations", ["project_id"], unique=False)
    if _table_exists("project_integrations") and not _index_exists("project_integrations", "ix_project_integrations_integration_type"):
        op.create_index("ix_project_integrations_integration_type", "project_integrations", ["integration_type"], unique=False)
    if _table_exists("project_integrations") and not _unique_constraint_exists("project_integrations", "uq_project_integrations_project_type"):
        _deduplicate_project_integrations()
        with op.batch_alter_table("project_integrations") as batch_op:
            batch_op.create_unique_constraint(
                "uq_project_integrations_project_type",
                ["project_id", "integration_type"],
            )


def downgrade() -> None:
    if _table_exists("project_integrations") and _unique_constraint_exists("project_integrations", "uq_project_integrations_project_type"):
        with op.batch_alter_table("project_integrations") as batch_op:
            batch_op.drop_constraint("uq_project_integrations_project_type", type_="unique")
    if _table_exists("project_integrations") and _index_exists("project_integrations", "ix_project_integrations_integration_type"):
        op.drop_index("ix_project_integrations_integration_type", table_name="project_integrations")
    if _table_exists("project_integrations") and _index_exists("project_integrations", "ix_project_integrations_project_id"):
        op.drop_index("ix_project_integrations_project_id", table_name="project_integrations")
    if _table_exists("project_integrations"):
        op.drop_table("project_integrations")
    if _table_exists("projects") and (_column_exists("projects", "site_contact_email") or _column_exists("projects", "site_blog_path")):
        with op.batch_alter_table("projects") as batch_op:
            if _column_exists("projects", "site_blog_path"):
                batch_op.drop_column("site_blog_path")
            if _column_exists("projects", "site_contact_email"):
                batch_op.drop_column("site_contact_email")