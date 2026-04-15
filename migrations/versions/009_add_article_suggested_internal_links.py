"""add suggested_internal_links to articles

Revision ID: 009
Revises: 008
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("articles", "suggested_internal_links"):
        op.add_column(
            "articles",
            sa.Column("suggested_internal_links", sa.Text(), nullable=True, server_default="[]"),
        )


def downgrade() -> None:
    if _column_exists("articles", "suggested_internal_links"):
        op.drop_column("articles", "suggested_internal_links")
