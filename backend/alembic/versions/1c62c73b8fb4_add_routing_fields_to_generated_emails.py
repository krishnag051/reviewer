"""add routing fields to generated emails

Revision ID: 1c62c73b8fb4
Revises: 3f5a3ad541db
Create Date: 2026-07-21 17:22:27.519844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '1c62c73b8fb4'
down_revision: Union[str, Sequence[str], None] = '3f5a3ad541db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Step 9 routing decision (user decision, 2026-07-21): every generated
    correction email records where it was routed — to the BCBA to fix, or to
    QA/Clinical Director/Coordinator with system-suggested language.

    routed_to is a plain text column, NOT a Postgres enum — the set of valid
    destinations may still evolve, and a text column doesn't need a
    migration to add a new one later (application-level validation via a
    Pydantic Literal is enough for now). routed_by follows the same
    nullable + ON DELETE SET NULL convention as every other *_by column in
    this schema (uploaded_by, voided_by, reviewed_by, generated_by, ...).
    routed_to/routed_at are NOT NULL — both are always set together, at
    generation time, same as subject/body already are on this table.
    generated_emails has never been written to (no route existed before
    this step), so there's no existing-row backfill concern.
    """
    op.add_column("generated_emails", sa.Column("routed_to", sa.Text(), nullable=False))
    op.add_column(
        "generated_emails",
        sa.Column(
            "routed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "generated_emails", sa.Column("routed_at", sa.DateTime(timezone=True), nullable=False)
    )


def downgrade() -> None:
    op.drop_column("generated_emails", "routed_at")
    op.drop_column("generated_emails", "routed_by")
    op.drop_column("generated_emails", "routed_to")
