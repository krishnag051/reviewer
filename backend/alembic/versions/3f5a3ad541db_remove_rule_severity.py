"""remove rule severity

Revision ID: 3f5a3ad541db
Revises: 266ab3f91800
Create Date: 2026-07-21 16:21:20.211019

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3f5a3ad541db'
down_revision: Union[str, Sequence[str], None] = '266ab3f91800'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

rule_severity_enum = postgresql.ENUM("normal", "critical", name="rule_severity")


def upgrade() -> None:
    """Every rule is mandatory — no severity tier at all (user decision,
    2026-07-21; see CLAUDE.md's "Pending policy defaults", now decided).
    Drops rules.severity and rule_version_history.severity, then the
    rule_severity enum type itself — columns must go first, the type can't
    be dropped while any column still references it.
    """
    op.drop_column("rules", "severity")
    op.drop_column("rule_version_history", "severity")
    rule_severity_enum.drop(op.get_bind(), checkfirst=False)


def downgrade() -> None:
    rule_severity_enum.create(op.get_bind(), checkfirst=False)
    # Data is not recoverable — every row gets the same placeholder severity,
    # same convention as any other structural-only downgrade in this project.
    op.add_column(
        "rules",
        sa.Column("severity", rule_severity_enum, nullable=False, server_default="normal"),
    )
    op.add_column(
        "rule_version_history",
        sa.Column("severity", rule_severity_enum, nullable=False, server_default="normal"),
    )
