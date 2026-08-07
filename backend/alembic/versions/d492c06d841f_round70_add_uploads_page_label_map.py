"""round70 add uploads.page_label_map

Revision ID: d492c06d841f
Revises: d4f8e29a6c17
Create Date: 2026-08-07 21:25:50.085008

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd492c06d841f'
down_revision: Union[str, Sequence[str], None] = 'd4f8e29a6c17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    NOTE: autogenerate also proposed dropping
    ix_session_note_files_upload_id -- that's pre-existing model/DB drift
    unrelated to this round (this migration only ever intended to add
    uploads.page_label_map), left alone rather than folded in here.
    """
    op.add_column('uploads', sa.Column('page_label_map', postgresql.JSONB(astext_type=sa.Text()), server_default='{}', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('uploads', 'page_label_map')
