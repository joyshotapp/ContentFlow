"""add project audit logs

Revision ID: 015
Revises: 014
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _index_exists(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(index.get("name") == index_name for index in insp.get_indexes(table))


def upgrade() -> None:
    if not _table_exists("project_audit_logs"):
        op.create_table(
            "project_audit_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("actor", sa.String(), server_default="system", nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("summary", sa.Text(), server_default="", nullable=False),
            sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    if _table_exists("project_audit_logs") and not _index_exists("project_audit_logs", "ix_project_audit_logs_project_id"):
        op.create_index("ix_project_audit_logs_project_id", "project_audit_logs", ["project_id"], unique=False)
    if _table_exists("project_audit_logs") and not _index_exists("project_audit_logs", "ix_project_audit_logs_action_type"):
        op.create_index("ix_project_audit_logs_action_type", "project_audit_logs", ["action_type"], unique=False)
    if _table_exists("project_audit_logs") and not _index_exists("project_audit_logs", "ix_project_audit_logs_created_at"):
        op.create_index("ix_project_audit_logs_created_at", "project_audit_logs", ["created_at"], unique=False)


def downgrade() -> None:
    if _table_exists("project_audit_logs") and _index_exists("project_audit_logs", "ix_project_audit_logs_created_at"):
        op.drop_index("ix_project_audit_logs_created_at", table_name="project_audit_logs")
    if _table_exists("project_audit_logs") and _index_exists("project_audit_logs", "ix_project_audit_logs_action_type"):
        op.drop_index("ix_project_audit_logs_action_type", table_name="project_audit_logs")
    if _table_exists("project_audit_logs") and _index_exists("project_audit_logs", "ix_project_audit_logs_project_id"):
        op.drop_index("ix_project_audit_logs_project_id", table_name="project_audit_logs")
    if _table_exists("project_audit_logs"):
        op.drop_table("project_audit_logs")