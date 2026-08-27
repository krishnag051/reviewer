"""add previous_tp_path to uploads

Revision ID: fa88ba8840b9
Revises: f976c22b6506
Create Date: 2026-08-27 18:31:15.011687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa88ba8840b9'
down_revision: Union[str, Sequence[str], None] = 'f976c22b6506'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Next Round (2026-08-27), Part 2 item 2: a new, OPTIONAL upload slot
    for the patient's prior Treatment Plan document -- ma'am's ask, so
    several currently-blocked rules that need "the previous TP" as a real
    data source can be built against it in a future round. Unlike
    supporting_document_path (mandatory, FastAPI File(...) requiredness),
    this is optional -- a first-ever patient genuinely has no prior TP to
    upload. Display-only for now, same as supporting_document_path was
    when it first shipped -- not read by review_treatment_plan or any part
    of the rule-checking pipeline yet."""
    op.add_column("uploads", sa.Column("previous_tp_path", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("uploads", "previous_tp_path")
