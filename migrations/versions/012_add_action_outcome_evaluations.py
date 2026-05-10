"""add action_outcome_evaluations table

Revision ID: 012
Revises: 011
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _table_exists("action_outcome_evaluations"):
        return

    op.create_table(
        "action_outcome_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_outcome_id", sa.Integer(), sa.ForeignKey("action_outcomes.id"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("evaluation_window_days", sa.Integer(), server_default="28", nullable=False),
        sa.Column("outcome_weight", sa.Float(), nullable=True),
        sa.Column("rank_delta", sa.Float(), nullable=True),
        sa.Column("click_delta", sa.Float(), nullable=True),
        sa.Column("ctr_delta", sa.Float(), nullable=True),
        sa.Column("control_rank_delta_median", sa.Float(), nullable=True),
        sa.Column("control_click_delta_median", sa.Float(), nullable=True),
        sa.Column("control_ctr_delta_median", sa.Float(), nullable=True),
        sa.Column("rank_advantage_vs_baseline", sa.Float(), nullable=True),
        sa.Column("click_advantage_vs_baseline", sa.Float(), nullable=True),
        sa.Column("ctr_advantage_vs_baseline", sa.Float(), nullable=True),
        sa.Column("control_adjustment", sa.Float(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_action_outcome_evaluations_action_outcome_id", "action_outcome_evaluations", ["action_outcome_id"], unique=True)
    op.create_index("ix_action_outcome_evaluations_project_id", "action_outcome_evaluations", ["project_id"], unique=False)
    op.create_index("ix_action_outcome_evaluations_article_id", "action_outcome_evaluations", ["article_id"], unique=False)
    op.create_index("ix_action_outcome_evaluations_action_type", "action_outcome_evaluations", ["action_type"], unique=False)
    op.create_index("ix_action_outcome_evaluations_evaluated_at", "action_outcome_evaluations", ["evaluated_at"], unique=False)


def downgrade() -> None:
    if not _table_exists("action_outcome_evaluations"):
        return

    op.drop_index("ix_action_outcome_evaluations_evaluated_at", table_name="action_outcome_evaluations")
    op.drop_index("ix_action_outcome_evaluations_action_type", table_name="action_outcome_evaluations")
    op.drop_index("ix_action_outcome_evaluations_article_id", table_name="action_outcome_evaluations")
    op.drop_index("ix_action_outcome_evaluations_project_id", table_name="action_outcome_evaluations")
    op.drop_index("ix_action_outcome_evaluations_action_outcome_id", table_name="action_outcome_evaluations")
    op.drop_table("action_outcome_evaluations")