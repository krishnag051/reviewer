"""add content fingerprint to rule snapshots

Revision ID: 266ab3f91800
Revises: f644de8600ea
Create Date: 2026-07-21 16:12:46.936281

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '266ab3f91800'
down_revision: Union[str, Sequence[str], None] = 'f644de8600ea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adds rule_snapshots.content_fingerprint — a hash of each active rule's
    defining content fields (question_text, category, question_set,
    rule_type, active), separate from the existing content_hash (which
    fingerprints {rule_id, version} pairs and stays exactly as-is for
    resolving historical wording via rule_version_history).

    The sync tick's no-op-on-revert check needs content_fingerprint, not
    content_hash: current_version increments monotonically and never reverts,
    so two snapshots can have identical rule *content* while still differing
    in {rule_id, version} pairs. content_hash can never detect that; this
    column can.

    Backfilled to '' for any snapshot that predates this column — that never
    equals a real computed fingerprint, so the very next sync tick after this
    migration will always publish rather than incorrectly no-op. Safe,
    conservative default; not a real backfill since the pre-migration
    snapshots' rule wording at the time isn't reconstructable here.
    """
    op.add_column(
        "rule_snapshots",
        sa.Column("content_fingerprint", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("rule_snapshots", "content_fingerprint")
