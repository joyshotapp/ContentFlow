"""add pipeline_runs, strategic_plans, reflection_logs for Enhanced B architecture

Revision ID: 002
Revises: 001
Create Date: 2026-04-15
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _table_exists("pipeline_runs"):
        op.create_table(
            "pipeline_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("run_id", sa.String(), nullable=False, unique=True, index=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True, index=True),
            sa.Column("calendar_id", sa.Integer(), sa.ForeignKey("content_calendar.id"), nullable=True),
            sa.Column("trigger", sa.String(), server_default="manual"),
            sa.Column("current_step", sa.String(), server_default="pending"),
            sa.Column("status", sa.String(), server_default="running"),
            sa.Column("state_json", sa.Text(), server_default="{}"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("total_llm_calls", sa.Integer(), server_default="0"),
            sa.Column("total_cost", sa.Float(), server_default="0.0"),
            sa.Column("seo_score", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists("strategic_plans"):
        op.create_table(
            "strategic_plans",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
            sa.Column("plan_date", sa.Date(), nullable=False, index=True),
            sa.Column("plan_type", sa.String(), server_default="daily"),
            sa.Column("actions_json", sa.Text(), server_default="[]"),
            sa.Column("summary", sa.Text(), server_default=""),
            sa.Column("context_snapshot", sa.Text(), server_default="{}"),
            sa.Column("executed_count", sa.Integer(), server_default="0"),
            sa.Column("total_count", sa.Integer(), server_default="0"),
            sa.Column("status", sa.String(), server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )

    if not _table_exists("reflection_logs"):
        op.create_table(
            "reflection_logs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=True, index=True),
            sa.Column("run_id", sa.String(), nullable=True, index=True),
            sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True),
            sa.Column("reflection_type", sa.String(), server_default="post_pipeline"),
            sa.Column("insights_json", sa.Text(), server_default="[]"),
            sa.Column("knowledge_updates", sa.Integer(), server_default="0"),
            sa.Column("writing_rule_updates", sa.Integer(), server_default="0"),
            sa.Column("session_summary", sa.Text(), server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    op.drop_table("reflection_logs")
    op.drop_table("strategic_plans")
    op.drop_table("pipeline_runs")
