"""add operations snapshots and strategic feedback logs

Revision ID: 013
Revises: 012
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"
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
    if not _table_exists("operations_health_snapshots"):
        op.create_table(
            "operations_health_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("snapshot_type", sa.String(), server_default="daily", nullable=False),
            sa.Column("overall_status", sa.String(), server_default="healthy", nullable=False),
            sa.Column("stale_sources", sa.Integer(), server_default="0", nullable=False),
            sa.Column("scheduler_success_rate", sa.Float(), nullable=True),
            sa.Column("pipeline_success_rate", sa.Float(), nullable=True),
            sa.Column("outcome_improved_rate", sa.Float(), nullable=True),
            sa.Column("alert_count", sa.Integer(), server_default="0", nullable=False),
            sa.Column("summary_json", sa.Text(), server_default="{}", nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    if not _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_snapshot_date"):
        op.create_index("ix_operations_health_snapshots_snapshot_date", "operations_health_snapshots", ["snapshot_date"], unique=False)
    if not _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_snapshot_type"):
        op.create_index("ix_operations_health_snapshots_snapshot_type", "operations_health_snapshots", ["snapshot_type"], unique=False)
    if not _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_created_at"):
        op.create_index("ix_operations_health_snapshots_created_at", "operations_health_snapshots", ["created_at"], unique=False)

    if not _table_exists("strategic_feedback_logs"):
        op.create_table(
            "strategic_feedback_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("strategic_plan_id", sa.Integer(), sa.ForeignKey("strategic_plans.id"), nullable=False),
            sa.Column("action_index", sa.Integer(), nullable=False),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("feedback_type", sa.String(), server_default="review", nullable=False),
            sa.Column("review_status", sa.String(), server_default="pending", nullable=False),
            sa.Column("note", sa.Text(), server_default="", nullable=False),
            sa.Column("payload_json", sa.Text(), server_default="{}", nullable=False),
            sa.Column("promoted_asset_type", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        )
    if not _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_project_id"):
        op.create_index("ix_strategic_feedback_logs_project_id", "strategic_feedback_logs", ["project_id"], unique=False)
    if not _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_strategic_plan_id"):
        op.create_index("ix_strategic_feedback_logs_strategic_plan_id", "strategic_feedback_logs", ["strategic_plan_id"], unique=False)
    if not _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_article_id"):
        op.create_index("ix_strategic_feedback_logs_article_id", "strategic_feedback_logs", ["article_id"], unique=False)
    if not _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_action_type"):
        op.create_index("ix_strategic_feedback_logs_action_type", "strategic_feedback_logs", ["action_type"], unique=False)
    if not _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_created_at"):
        op.create_index("ix_strategic_feedback_logs_created_at", "strategic_feedback_logs", ["created_at"], unique=False)


def downgrade() -> None:
    if _table_exists("strategic_feedback_logs") and _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_created_at"):
        op.drop_index("ix_strategic_feedback_logs_created_at", table_name="strategic_feedback_logs")
    if _table_exists("strategic_feedback_logs") and _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_action_type"):
        op.drop_index("ix_strategic_feedback_logs_action_type", table_name="strategic_feedback_logs")
    if _table_exists("strategic_feedback_logs") and _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_article_id"):
        op.drop_index("ix_strategic_feedback_logs_article_id", table_name="strategic_feedback_logs")
    if _table_exists("strategic_feedback_logs") and _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_strategic_plan_id"):
        op.drop_index("ix_strategic_feedback_logs_strategic_plan_id", table_name="strategic_feedback_logs")
    if _table_exists("strategic_feedback_logs") and _index_exists("strategic_feedback_logs", "ix_strategic_feedback_logs_project_id"):
        op.drop_index("ix_strategic_feedback_logs_project_id", table_name="strategic_feedback_logs")
    if _table_exists("strategic_feedback_logs"):
        op.drop_table("strategic_feedback_logs")

    if _table_exists("operations_health_snapshots") and _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_created_at"):
        op.drop_index("ix_operations_health_snapshots_created_at", table_name="operations_health_snapshots")
    if _table_exists("operations_health_snapshots") and _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_snapshot_type"):
        op.drop_index("ix_operations_health_snapshots_snapshot_type", table_name="operations_health_snapshots")
    if _table_exists("operations_health_snapshots") and _index_exists("operations_health_snapshots", "ix_operations_health_snapshots_snapshot_date"):
        op.drop_index("ix_operations_health_snapshots_snapshot_date", table_name="operations_health_snapshots")
    if _table_exists("operations_health_snapshots"):
        op.drop_table("operations_health_snapshots")
