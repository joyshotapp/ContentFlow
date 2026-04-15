"""add reviewer_id column to articles

Revision ID: 005
Revises: 004
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if not _col_exists("articles", "reviewer_id"):
        op.add_column(
            "articles",
            sa.Column("reviewer_id", sa.Integer(), nullable=True),
        )
        if not _is_sqlite():
            op.create_foreign_key(
                "fk_articles_reviewer_id",
                "articles",
                "authors",
                ["reviewer_id"],
                ["id"],
            )


def downgrade() -> None:
    if _col_exists("articles", "reviewer_id"):
        if not _is_sqlite():
            op.drop_constraint("fk_articles_reviewer_id", "articles", type_="foreignkey")
        op.drop_column("articles", "reviewer_id")
