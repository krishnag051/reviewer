"""create v_override_analytics view

Revision ID: bfa56f6b6f9b
Revises: 3e15a0e453a3
Create Date: 2026-07-21 17:43:26.135916

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfa56f6b6f9b'
down_revision: Union[str, Sequence[str], None] = '3e15a0e453a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CREATE_VIEW_SQL = """
CREATE VIEW v_override_analytics AS
SELECT
    r.rule_code AS rule_code,
    CASE
        WHEN rr.is_overridden THEN 'override_to_' || rr.final_status
        ELSE 'unchanged_' || rr.final_status
    END AS direction,
    COUNT(*) AS count,
    v.reviewer_id AS reviewer,
    v.payor AS payor,
    date_trunc('month', v.finalized_at) AS month
FROM rule_results rr
JOIN uploads u ON u.id = rr.upload_id
JOIN versions v ON v.id = u.version_id
JOIN rules r ON r.id = rr.rule_id
WHERE u.is_final = true
GROUP BY r.rule_code, direction, v.reviewer_id, v.payor, date_trunc('month', v.finalized_at)
"""

DROP_VIEW_SQL = "DROP VIEW v_override_analytics"


def upgrade() -> None:
    """Scoped back in step 2 (gap D2 — the model-vs-human disagreement
    dataset): v_override_analytics(rule_code, direction, count, reviewer,
    payor, month). Built now, for real, as this step's reports/trends
    endpoint needs it.

    Grain: one row per (rule_code, direction, reviewer, payor, month),
    counting how many rule_results in FINALIZED uploads landed there.
    `direction` partitions every finalized rule_result exhaustively —
    "override_to_<final_status>" if a human ever touched it
    (is_overridden=true), else "unchanged_<final_status>" — so consumers
    can derive BOTH the original override-direction-disagreement analytics
    (filter WHERE direction LIKE 'override_%') AND a plain pass-rate
    (SUM(count) WHERE direction LIKE '%_pass' / SUM(count) overall) from
    the same view, without re-deriving the rule_results/uploads/versions/
    rules join anywhere else. The reports/trends endpoint does the latter.

    Only rule_results belonging to a FINALIZED (is_final=true) upload are
    included — matches "reads finalized versions only" everywhere else in
    this step. Rows from before v.finalized_at existed (migration
    3e15a0e453a3) group under month=NULL — expected, not backfillable (see
    that migration's docstring).
    """
    op.execute(CREATE_VIEW_SQL)


def downgrade() -> None:
    op.execute(DROP_VIEW_SQL)
