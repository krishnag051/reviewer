"""add real-send fields to generated_emails

Revision ID: 6039b6cd941b
Revises: 340f79d7115f
Create Date: 2026-08-12 23:39:58.158505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6039b6cd941b'
down_revision: Union[str, Sequence[str], None] = '340f79d7115f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix Round, item 3 (2026-08-12) -- real "Escalate to BCBA" sending.
    `statuses` (which result categories a draft's body covers) defaults to
    '[]' for every pre-existing row -- accurate for them: nothing about
    what they cover was ever tracked before this, and none of them were
    ever actually sent (sent_at/send_error both null, matching "never
    attempted" for old rows too)."""
    op.add_column(
        "generated_emails",
        sa.Column("statuses", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )
    op.add_column("generated_emails", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("generated_emails", sa.Column("send_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("generated_emails", "send_error")
    op.drop_column("generated_emails", "sent_at")
    op.drop_column("generated_emails", "statuses")
