"""add active/deactivated fields to patients

Revision ID: e0bfb4144de2
Revises: 6039b6cd941b
Create Date: 2026-08-27 15:17:43.531136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0bfb4144de2'
down_revision: Union[str, Sequence[str], None] = '6039b6cd941b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Part 6, Fix Round (2026-08-27): deactivate/archive a TP, reversibly --
    no hard delete, matches this project's own standing convention (voided
    uploads, not deleted rows). `active` defaults true so every existing
    patient stays exactly where it already was -- nothing is deactivated by
    this migration itself."""
    op.add_column("patients", sa.Column("active", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("patients", sa.Column("deactivated_by", sa.UUID(), nullable=True))
    op.add_column("patients", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_patients_deactivated_by_users", "patients", "users", ["deactivated_by"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_patients_deactivated_by_users", "patients", type_="foreignkey")
    op.drop_column("patients", "deactivated_at")
    op.drop_column("patients", "deactivated_by")
    op.drop_column("patients", "active")
