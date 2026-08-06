"""add supporting_document_path to uploads

Revision ID: c3e7b1a94f56
Revises: a1c9e4f2b7d3
Create Date: 2026-08-02 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3e7b1a94f56'
down_revision: Union[str, Sequence[str], None] = 'a1c9e4f2b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Round 51: the mandatory "supporting document" -- a second, required
    file at every real upload creation point going forward. Nullable at the
    schema level (same reason file_path itself is nullable: the row is
    inserted first to get an id for the blob filename, the path is set
    right after, all within one transaction -- by the time any client sees
    the row, both paths are already populated for a real upload). Required-
    ness is enforced at the application layer (app/services/uploads.py::
    create_upload / the router), not a NOT NULL constraint, so this stays a
    pure additive column -- zero effect on any existing row.
    """
    op.add_column("uploads", sa.Column("supporting_document_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "supporting_document_path")
