"""add hero_image_url to articles

Revision ID: 010
Revises: 009
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("articles", "hero_image_url"):
        op.add_column(
            "articles",
            sa.Column("hero_image_url", sa.String(), nullable=True, server_default=""),
        )


def downgrade() -> None:
    if _column_exists("articles", "hero_image_url"):
        op.drop_column("articles", "hero_image_url")
