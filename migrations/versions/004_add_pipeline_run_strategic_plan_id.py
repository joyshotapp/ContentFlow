"""add strategic_plan_id column to pipeline_runs

Revision ID: 004
Revises: 003
Create Date: 2026-04-14
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return column in {c["name"] for c in insp.get_columns(table)}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if not _col_exists("pipeline_runs", "strategic_plan_id"):
        op.add_column(
            "pipeline_runs",
            sa.Column("strategic_plan_id", sa.Integer(), nullable=True),
        )
        op.create_index(
            "ix_pipeline_runs_strategic_plan_id",
            "pipeline_runs",
            ["strategic_plan_id"],
        )
        if not _is_sqlite():
            op.create_foreign_key(
                "fk_pipeline_runs_strategic_plan_id",
                "pipeline_runs",
                "strategic_plans",
                ["strategic_plan_id"],
                ["id"],
            )


def downgrade() -> None:
    if _col_exists("pipeline_runs", "strategic_plan_id"):
        if not _is_sqlite():
            op.drop_constraint(
                "fk_pipeline_runs_strategic_plan_id", "pipeline_runs", type_="foreignkey"
            )
        op.drop_index("ix_pipeline_runs_strategic_plan_id", "pipeline_runs")
        op.drop_column("pipeline_runs", "strategic_plan_id")
