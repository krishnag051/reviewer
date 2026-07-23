"""add stuck job timeout to app_config

Revision ID: f644de8600ea
Revises: 610ef7c09015
Create Date: 2026-07-20 19:59:57.747574

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f644de8600ea'
down_revision: Union[str, Sequence[str], None] = '610ef7c09015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_config",
        sa.Column("stuck_job_timeout_minutes", sa.Integer(), nullable=False, server_default="30"),
    )


def downgrade() -> None:
    op.drop_column("app_config", "stuck_job_timeout_minutes")
