"""backfill encrypted project connector secrets

Revision ID: 016
Revises: 015
Create Date: 2026-05-11
"""

from alembic import op
import sqlalchemy as sa

from contentflow.utils.secret_crypto import backfill_plaintext_project_integration_secrets


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if _table_exists("project_integrations"):
        backfill_plaintext_project_integration_secrets(op.get_bind())


def downgrade() -> None:
    # Data backfill only. Secrets remain encrypted on downgrade.
    return None