"""add not_checkable rule_result_status value

Revision ID: ff6ae00976bd
Revises: bfa56f6b6f9b
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ff6ae00976bd'
down_revision: Union[str, Sequence[str], None] = 'bfa56f6b6f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Wiring the real rule-checking agent (agent-making) in means its own
    result vocabulary — pass/fail/uncertain/not_applicable/not_checkable —
    has to be representable without collapsing anything. `not_applicable`
    already maps onto this backend's existing `"na"` value, but
    `not_checkable` (an answer genuinely couldn't be determined — payor
    detection failing for a payor-specific rule, a deterministic checker
    not finding the text pattern it needed in this document, or a rule
    with no checker implemented at all — a genuinely different case from
    `"na"`, which means applicability WAS determined and the rule just
    doesn't apply) had no home here at all. Per app/rule_engine/contract.py
    and agent-making/INTEGRATION_PLAN.md's explicit decision: add it as its
    own value rather than folding it into `"na"`.

    Postgres 12+ allows ADD VALUE inside a transaction as long as the new
    value isn't used by the same transaction — safe here.
    """
    op.execute("ALTER TYPE rule_result_status ADD VALUE 'not_checkable'")


def downgrade() -> None:
    """Postgres has no DROP VALUE for enums — the only safe way back is to
    confirm nothing actually used the value, then rebuild the type without
    it. Raises rather than silently destroying any real `not_checkable`
    rows if this is ever run against data that has them.
    """
    conn = op.get_bind()
    in_use = conn.execute(
        "SELECT count(*) FROM rule_results "
        "WHERE model_status = 'not_checkable' OR final_status = 'not_checkable'"
    ).scalar()
    if in_use:
        raise RuntimeError(
            f"{in_use} rule_results row(s) use 'not_checkable' — cannot downgrade "
            "without either migrating that data first or accepting data loss; "
            "this migration refuses to guess which."
        )

    op.execute("ALTER TYPE rule_result_status RENAME TO rule_result_status_old")
    op.execute("CREATE TYPE rule_result_status AS ENUM ('pass', 'fail', 'na', 'uncertain')")
    op.execute(
        "ALTER TABLE rule_results ALTER COLUMN model_status "
        "TYPE rule_result_status USING model_status::text::rule_result_status"
    )
    op.execute(
        "ALTER TABLE rule_results ALTER COLUMN final_status "
        "TYPE rule_result_status USING final_status::text::rule_result_status"
    )
    op.execute("DROP TYPE rule_result_status_old")
