"""add model_finding_raw to rule_results

Revision ID: f976c22b6506
Revises: e0bfb4144de2
Create Date: 2026-08-27 17:31:40.944941

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f976c22b6506'
down_revision: Union[str, Sequence[str], None] = 'e0bfb4144de2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Next Round, Part 2: preserves the pre-humanize text alongside
    model_finding (now the humanized text) -- nullable, no backfill for
    existing rows (their model_finding was never humanized to begin
    with, so there's no real "pre" text to invent for them)."""
    op.add_column("rule_results", sa.Column("model_finding_raw", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rule_results", "model_finding_raw")
