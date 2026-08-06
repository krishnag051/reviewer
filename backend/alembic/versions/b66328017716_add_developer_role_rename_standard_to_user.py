"""add developer role, rename standard to user

Revision ID: b66328017716
Revises: ff6ae00976bd
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b66328017716'
down_revision: Union[str, Sequence[str], None] = 'ff6ae00976bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Round 41: three flat roles, no BCBA/Facilitator-specific naming —
    admin, user, developer. "standard" is renamed to "user" (same meaning,
    clearer name now that a third role exists); "developer" is new and
    gates access to the frontend's Developer Mode diagnostics screen. This
    is a pure naming/scope change to the role model, not a rethink of
    admin-provisioning: CLAUDE.md's "no public signup, admin-provisioned
    only" invariant is unchanged and still applies to all three roles.

    Postgres 10+ supports RENAME VALUE directly -- no table rewrite needed
    for the rename. ADD VALUE for "developer" follows the same
    inside-a-transaction-is-fine rule as migration ff6ae00976bd.
    """
    op.execute("ALTER TYPE user_role RENAME VALUE 'standard' TO 'user'")
    op.execute("ALTER TYPE user_role ADD VALUE 'developer'")


def downgrade() -> None:
    """Reverses the rename unconditionally (lossless, just a label).
    Refuses to reverse "developer" if anything actually uses it, same
    discipline as ff6ae00976bd's downgrade -- Postgres has no DROP VALUE,
    and silently deciding what to do with real developer-role users on a
    downgrade isn't this migration's call to make.
    """
    conn = op.get_bind()
    in_use = conn.execute("SELECT count(*) FROM users WHERE role = 'developer'").scalar()
    if in_use:
        raise RuntimeError(
            f"{in_use} user(s) have role='developer' -- cannot downgrade without "
            "either reassigning them first or accepting data loss; this migration "
            "refuses to guess which."
        )

    op.execute("ALTER TYPE user_role RENAME VALUE 'user' TO 'standard'")

    op.execute("ALTER TYPE user_role RENAME TO user_role_old")
    op.execute("CREATE TYPE user_role AS ENUM ('admin', 'standard')")
    op.execute(
        "ALTER TABLE users ALTER COLUMN role "
        "TYPE user_role USING role::text::user_role"
    )
    op.execute("DROP TYPE user_role_old")
