"""add action_outcomes table

Revision ID: 006
Revises: 005
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _table_exists("action_outcomes"):
        return

    op.create_table(
        "action_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False, index=True),
        sa.Column("run_id", sa.String(), nullable=True, index=True),
        sa.Column("strategic_plan_id", sa.Integer(), sa.ForeignKey("strategic_plans.id"), nullable=True),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_date", sa.Date(), nullable=False, index=True),
        sa.Column("primary_keyword", sa.String(), nullable=False),
        # baseline
        sa.Column("baseline_rank", sa.Float(), nullable=True),
        sa.Column("baseline_impressions", sa.Integer(), nullable=True),
        sa.Column("baseline_clicks", sa.Integer(), nullable=True),
        sa.Column("baseline_ctr", sa.Float(), nullable=True),
        # 7d
        sa.Column("rank_after_7d", sa.Float(), nullable=True),
        sa.Column("impressions_after_7d", sa.Integer(), nullable=True),
        sa.Column("clicks_after_7d", sa.Integer(), nullable=True),
        sa.Column("ctr_after_7d", sa.Float(), nullable=True),
        sa.Column("checked_7d_at", sa.DateTime(), nullable=True),
        # 14d
        sa.Column("rank_after_14d", sa.Float(), nullable=True),
        sa.Column("impressions_after_14d", sa.Integer(), nullable=True),
        sa.Column("clicks_after_14d", sa.Integer(), nullable=True),
        sa.Column("ctr_after_14d", sa.Float(), nullable=True),
        sa.Column("checked_14d_at", sa.DateTime(), nullable=True),
        # 28d
        sa.Column("rank_after_28d", sa.Float(), nullable=True),
        sa.Column("impressions_after_28d", sa.Integer(), nullable=True),
        sa.Column("clicks_after_28d", sa.Integer(), nullable=True),
        sa.Column("ctr_after_28d", sa.Float(), nullable=True),
        sa.Column("checked_28d_at", sa.DateTime(), nullable=True),
        # verdict
        sa.Column("success_flag", sa.String(), nullable=True),
        sa.Column("rank_delta", sa.Float(), nullable=True),
        sa.Column("learning_confidence", sa.String(), server_default="low"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    if _table_exists("action_outcomes"):
        op.drop_table("action_outcomes")
