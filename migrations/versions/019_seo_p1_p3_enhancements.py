"""SEO P1-P3: daily GSC, topic slug, intent match, outreach, experiments, CWV logs

Revision ID: 019
Revises: 018
Create Date: 2026-05-25
"""

from alembic import op
import sqlalchemy as sa


revision = "019"
down_revision = "018"
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


def upgrade() -> None:
    if _table_exists("topic_clusters") and not _column_exists("topic_clusters", "slug"):
        op.add_column("topic_clusters", sa.Column("slug", sa.String(), server_default="", nullable=False))

    if _table_exists("articles"):
        if not _column_exists("articles", "intent_match_score"):
            op.add_column("articles", sa.Column("intent_match_score", sa.Float(), nullable=True))
        if not _column_exists("articles", "intent_match_checked_at"):
            op.add_column("articles", sa.Column("intent_match_checked_at", sa.DateTime(), nullable=True))

    if not _table_exists("gsc_daily_metrics"):
        op.create_table(
            "gsc_daily_metrics",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("keyword", sa.String(), server_default=""),
            sa.Column("landing_page", sa.String(), server_default=""),
            sa.Column("metric_date", sa.Date(), nullable=False, index=True),
            sa.Column("clicks", sa.Integer(), server_default="0"),
            sa.Column("impressions", sa.Integer(), server_default="0"),
            sa.Column("ctr", sa.Float(), nullable=True),
            sa.Column("position", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_gsc_daily_unique",
            "gsc_daily_metrics",
            ["project_id", "keyword", "landing_page", "metric_date"],
            unique=True,
        )

    if not _table_exists("brand_mention_snapshots"):
        op.create_table(
            "brand_mention_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("brand_query", sa.String(), server_default=""),
            sa.Column("mention_url", sa.String(), server_default=""),
            sa.Column("mention_title", sa.String(), server_default=""),
            sa.Column("mention_snippet", sa.Text(), server_default=""),
            sa.Column("tracked_date", sa.Date(), nullable=True, index=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists("outreach_tasks"):
        op.create_table(
            "outreach_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("task_type", sa.String(), server_default="brand_mention"),
            sa.Column("target_url", sa.String(), server_default=""),
            sa.Column("target_domain", sa.String(), server_default=""),
            sa.Column("suggested_action", sa.Text(), server_default=""),
            sa.Column("status", sa.String(), server_default="open"),
            sa.Column("priority", sa.Integer(), server_default="3"),
            sa.Column("metadata_json", sa.Text(), server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists("content_experiments"):
        op.create_table(
            "content_experiments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True, index=True),
            sa.Column("experiment_key", sa.String(), server_default=""),
            sa.Column("variant", sa.String(), server_default="control"),
            sa.Column("holdout", sa.Boolean(), server_default=sa.false()),
            sa.Column("baseline_metric_json", sa.Text(), server_default="{}"),
            sa.Column("result_metric_json", sa.Text(), server_default="{}"),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("ended_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(), server_default="running"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists("cwv_snapshots"):
        op.create_table(
            "cwv_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("url", sa.String(), server_default=""),
            sa.Column("strategy", sa.String(), server_default="mobile"),
            sa.Column("lcp", sa.Float(), nullable=True),
            sa.Column("inp", sa.Float(), nullable=True),
            sa.Column("cls", sa.Float(), nullable=True),
            sa.Column("performance_score", sa.Integer(), nullable=True),
            sa.Column("tracked_date", sa.Date(), nullable=True, index=True),
            sa.Column("error", sa.String(), server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    for table in (
        "cwv_snapshots",
        "content_experiments",
        "outreach_tasks",
        "brand_mention_snapshots",
        "gsc_daily_metrics",
    ):
        if _table_exists(table):
            op.drop_table(table)
    if _table_exists("topic_clusters") and _column_exists("topic_clusters", "slug"):
        op.drop_column("topic_clusters", "slug")
    if _table_exists("articles"):
        if _column_exists("articles", "intent_match_checked_at"):
            op.drop_column("articles", "intent_match_checked_at")
        if _column_exists("articles", "intent_match_score"):
            op.drop_column("articles", "intent_match_score")
