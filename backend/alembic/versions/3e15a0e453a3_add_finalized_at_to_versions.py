"""add finalized_at to versions

Revision ID: 3e15a0e453a3
Revises: 1c62c73b8fb4
Create Date: 2026-07-21 17:43:04.207261

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3e15a0e453a3'
down_revision: Union[str, Sequence[str], None] = '1c62c73b8fb4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Step 10 (reports) needs a real "when was this TP concluded" date to
    filter by (This week / Last 30 days / etc.) — versions.created_at is
    when the audit CYCLE STARTED, not when it concluded, and would
    misrepresent any version that took a while to review. Nullable: never
    set for a non-finalized version, and not backfillable for any version
    finalized before this migration (the exact original finalize moment
    isn't recorded anywhere else). Set going forward by
    app/services/finalize.py, in the same transaction as everything else
    finalize already writes.
    """
    op.add_column("versions", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("versions", "finalized_at")
