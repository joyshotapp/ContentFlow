"""add clicks, impressions, ctr columns to seo_rankings

Revision ID: 003
Revises: 002
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    """Check if column already exists (safe for repeated runs)."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    cols = [
        ("keyword", sa.String(), ""),
        ("position", sa.Float(), None),
        ("landing_page", sa.String(), ""),
        ("search_engine", sa.String(), "Google"),
        ("tracked_date", sa.Date(), None),
        ("impressions", sa.Integer(), None),
        ("clicks", sa.Integer(), None),
        ("ctr", sa.Float(), None),
    ]
    for name, type_, default in cols:
        if not _col_exists("seo_rankings", name):
            op.add_column(
                "seo_rankings",
                sa.Column(name, type_, nullable=True, server_default=str(default) if default is not None else None),
            )


def downgrade() -> None:
    for name in ("ctr", "clicks", "impressions", "tracked_date", "search_engine", "landing_page", "position", "keyword"):
        if _col_exists("seo_rankings", name):
            op.drop_column("seo_rankings", name)
