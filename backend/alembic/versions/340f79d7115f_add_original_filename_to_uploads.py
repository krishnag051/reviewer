"""add original_filename to uploads

Revision ID: 340f79d7115f
Revises: d492c06d841f
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '340f79d7115f'
down_revision: Union[str, Sequence[str], None] = 'd492c06d841f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Round 86: the client-supplied filename a TP was actually uploaded
    under (e.g. "Zohran Hossain TP.pdf") -- captured before save_blob
    renames the file to its internal storage key, which deliberately
    discards the original name. Same purpose SessionNoteFile.
    original_filename already serves for session-note files; the TP's own
    upload row never had an equivalent column until now. Nullable, same
    reason file_path is nullable (the row is inserted first, this is set
    right after within the same transaction) and so an upload row created
    before this migration doesn't need a backfill. Purely additive -- no
    change to how the file itself is stored or how collisions are avoided.
    """
    op.add_column("uploads", sa.Column("original_filename", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "original_filename")
