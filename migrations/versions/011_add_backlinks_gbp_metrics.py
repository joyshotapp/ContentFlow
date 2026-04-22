"""add backlink_snapshots and google_business_metrics tables

Revision ID: 011
Revises: 010
Create Date: 2026-05-01
"""
from alembic import op
import sqlalchemy as sa

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _table_exists("backlink_snapshots"):
        op.create_table(
            "backlink_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("target_url", sa.String(), nullable=False),
            sa.Column("total_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("referring_domains", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("new_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("lost_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("domain_rank", sa.Float(), nullable=True),
            sa.Column("broken_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("nofollow_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("dofollow_backlinks", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("top_anchors_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("top_referring_domains_json", sa.Text(), nullable=True, server_default="[]"),
            sa.Column("tracked_date", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_backlink_snapshots_project_id", "backlink_snapshots", ["project_id"])
        op.create_index("ix_backlink_snapshots_tracked_date", "backlink_snapshots", ["tracked_date"])

    if not _table_exists("google_business_metrics"):
        op.create_table(
            "google_business_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("location_id", sa.String(), nullable=False),
            sa.Column("location_name", sa.String(), nullable=True, server_default=""),
            sa.Column("views_search", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("views_maps", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("clicks_website", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("clicks_phone", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("clicks_directions", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("reviews_total", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("reviews_avg_rating", sa.Float(), nullable=True),
            sa.Column("new_reviews", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("tracked_date", sa.Date(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_google_business_metrics_project_id", "google_business_metrics", ["project_id"])
        op.create_index("ix_google_business_metrics_location_id", "google_business_metrics", ["location_id"])
        op.create_index("ix_google_business_metrics_tracked_date", "google_business_metrics", ["tracked_date"])


def downgrade() -> None:
    if _table_exists("google_business_metrics"):
        op.drop_table("google_business_metrics")
    if _table_exists("backlink_snapshots"):
        op.drop_table("backlink_snapshots")
