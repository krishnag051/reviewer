"""add payor to rules

Revision ID: a1c9e4f2b7d3
Revises: b66328017716
Create Date: 2026-08-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1c9e4f2b7d3'
down_revision: Union[str, Sequence[str], None] = 'b66328017716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same 10 payor values already used everywhere else in the app (patients.payor,
# upload.tsx's PAYORS select, the old mock Rules Studio) -- Round 50's own
# instructions said "9 payors" but the actual, already-established list (see
# frontend/src/lib/tp-mock.ts) has always had 10; using the real existing list
# rather than silently matching a miscounted instruction.
rule_payor_enum = postgresql.ENUM(
    "Aetna", "Anthem", "Cigna", "Emblem", "Empire", "Healthfirst", "Molina",
    "MVP", "Straight Medicaid", "New York Medicaid",
    name="rule_payor",
)


def upgrade() -> None:
    """Round 50: Rules Studio's payor-scoping tabs are real UI, but the
    backend Rule row had no payor concept at all before this -- payor
    applicability only ever existed in agent-making's own rules.json, which
    the backend doesn't read or store. Nullable: NULL means "applies to
    every payor" (mirrors the old mock's "ALL" sentinel), so all 120
    existing rules default to universal until an admin sets one specifically.
    This is metadata only, same as every other Rule column -- see client.py's
    docstring: nothing here ever reaches the real rule-checking agent.
    """
    rule_payor_enum.create(op.get_bind(), checkfirst=False)
    op.add_column("rules", sa.Column("payor", rule_payor_enum, nullable=True))
    op.add_column("rule_version_history", sa.Column("payor", rule_payor_enum, nullable=True))


def downgrade() -> None:
    op.drop_column("rule_version_history", "payor")
    op.drop_column("rules", "payor")
    rule_payor_enum.drop(op.get_bind(), checkfirst=False)
