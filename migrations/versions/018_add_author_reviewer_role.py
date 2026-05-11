"""add author reviewer role

Revision ID: 018
Revises: 017
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "018"
down_revision = "017"
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
    if _table_exists("authors") and not _column_exists("authors", "reviewer_role"):
        op.add_column("authors", sa.Column("reviewer_role", sa.String(), server_default="", nullable=False))

    if _table_exists("authors") and _column_exists("authors", "reviewer_role") and _column_exists("authors", "is_medical_reviewer"):
        bind = op.get_bind()
        authors = sa.table(
            "authors",
            sa.column("id", sa.Integer()),
            sa.column("is_medical_reviewer", sa.Boolean()),
            sa.column("reviewer_role", sa.String()),
        )
        bind.execute(
            sa.update(authors)
            .where(authors.c.is_medical_reviewer.is_(True))
            .where(sa.or_(authors.c.reviewer_role.is_(None), authors.c.reviewer_role == ""))
            .values(reviewer_role="medical")
        )


def downgrade() -> None:
    if _table_exists("authors") and _column_exists("authors", "reviewer_role"):
        op.drop_column("authors", "reviewer_role")