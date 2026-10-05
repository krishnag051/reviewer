"""consolidate New York Medicaid into Straight Medicaid

Revision ID: 9f3c6a1d7e52
Revises: fa88ba8840b9
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9f3c6a1d7e52'
down_revision: Union[str, Sequence[str], None] = 'fa88ba8840b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix Round 15 (2026-10-05): real business confirmation that "New
    York Medicaid" was never a distinct payor — it's the same thing as
    "Straight Medicaid". Three things, in order:

    1. Data-migrate the two free-text `payor` columns (patients.payor,
       versions.payor — both plain Text, not the enum below) so historical
       records stay consistent with the new, single canonical name. Prints
       the real affected row count for each table rather than guessing or
       silently assuming zero.
    2. Rebuild the `rule_payor` enum (used only by rules.payor and
       rule_version_history.payor — metadata describing which payor a RULE
       applies to, never a document's own detected payor) without "New York
       Medicaid". Confirmed via direct inspection before writing this
       migration that no `rules`/`rule_version_history` row has ever used
       "New York Medicaid" as its own applies_to_payor value — SM-01/SM-02
       are already scoped to "Straight Medicaid" directly — so this is a
       pure type-shrink, not a data migration. Postgres has no DROP VALUE
       for enums (same constraint ff6ae00976bd's downgrade already
       documents) — rebuild via rename-old/create-new/cast/drop-old.
    """
    conn = op.get_bind()

    patients_updated = conn.execute(
        "UPDATE patients SET payor = 'Straight Medicaid' WHERE payor = 'New York Medicaid'"
    ).rowcount
    versions_updated = conn.execute(
        "UPDATE versions SET payor = 'Straight Medicaid' WHERE payor = 'New York Medicaid'"
    ).rowcount
    print(
        f"[migration 9f3c6a1d7e52] 'New York Medicaid' -> 'Straight Medicaid' data migration: "
        f"{patients_updated} patients row(s), {versions_updated} versions row(s) updated."
    )

    op.execute("ALTER TYPE rule_payor RENAME TO rule_payor_old")
    op.execute(
        "CREATE TYPE rule_payor AS ENUM ("
        "'Aetna', 'Anthem', 'Cigna', 'Emblem', 'Empire', 'Healthfirst', 'Molina', "
        "'MVP', 'Straight Medicaid'"
        ")"
    )
    op.execute(
        "ALTER TABLE rules ALTER COLUMN payor "
        "TYPE rule_payor USING payor::text::rule_payor"
    )
    op.execute(
        "ALTER TABLE rule_version_history ALTER COLUMN payor "
        "TYPE rule_payor USING payor::text::rule_payor"
    )
    op.execute("DROP TYPE rule_payor_old")


def downgrade() -> None:
    """Restores the enum's old value. Does NOT un-migrate patients.payor/
    versions.payor data — once a record's payor is relabeled "Straight
    Medicaid" there is no way to tell, after the fact, which of those rows
    used to say "New York Medicaid" vs. always having genuinely been
    "Straight Medicaid"; re-splitting them would be a guess, not a real
    reversal, so this intentionally only restores the TYPE, not the data.
    """
    op.execute("ALTER TYPE rule_payor RENAME TO rule_payor_new")
    op.execute(
        "CREATE TYPE rule_payor AS ENUM ("
        "'Aetna', 'Anthem', 'Cigna', 'Emblem', 'Empire', 'Healthfirst', 'Molina', "
        "'MVP', 'Straight Medicaid', 'New York Medicaid'"
        ")"
    )
    op.execute(
        "ALTER TABLE rules ALTER COLUMN payor "
        "TYPE rule_payor USING payor::text::rule_payor"
    )
    op.execute(
        "ALTER TABLE rule_version_history ALTER COLUMN payor "
        "TYPE rule_payor USING payor::text::rule_payor"
    )
    op.execute("DROP TYPE rule_payor_new")
