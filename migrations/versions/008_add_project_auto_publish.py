"""add auto_publish fields to projects

Revision ID: 008
Revises: 007
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _column_exists("projects", "auto_publish_enabled"):
        op.add_column(
            "projects",
            sa.Column("auto_publish_enabled", sa.Boolean(), nullable=True, server_default="false"),
        )
    if not _column_exists("projects", "auto_publish_min_score"):
        op.add_column(
            "projects",
            sa.Column("auto_publish_min_score", sa.Integer(), nullable=True, server_default="85"),
        )


def downgrade() -> None:
    op.drop_column("projects", "auto_publish_min_score")
    op.drop_column("projects", "auto_publish_enabled")
