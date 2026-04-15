"""add performance_grade to articles

Revision ID: 007
Revises: 006
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = [c["name"] for c in insp.get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _column_exists("articles", "performance_grade"):
        op.add_column(
            "articles",
            sa.Column("performance_grade", sa.String(2), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("articles", "performance_grade")
