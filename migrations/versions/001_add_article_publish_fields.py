"""add published_at and target_word_count to articles

Revision ID: 001
Revises:
Create Date: 2026-04-13
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("published_at", sa.DateTime(), nullable=True))
    op.add_column("articles", sa.Column("target_word_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("articles", "target_word_count")
    op.drop_column("articles", "published_at")
