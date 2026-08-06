"""Round 56: structured intake Q&A, session notes, supporting_doc_mode flag, rule flagging

Revision ID: d4f8e29a6c17
Revises: c3e7b1a94f56
Create Date: 2026-08-05 00:00:00.000000

Round 56 (frontend/backend wiring only -- no agent-making changes):
- app_config.supporting_doc_mode: feature flag ("document" | "structured_form")
  controlling which upload path (Round 51-55's free-form doc + AI extraction,
  still fully intact, vs. the new structured 5-question form + session notes)
  is active. Defaults to "structured_form" for every row going forward.
- upload_intake_answers: one row per upload, the 5 structured Q&A answers
  (plain text, no AI extraction). 1:1 with uploads, same "insert upload row
  first, attach detail row after" pattern as file_path.
- session_note_files: one-to-many per upload (multi-file, unlike the single
  supporting_document_path column it's replacing for this purpose). Shares
  file_path's exact retention lifecycle via the PARENT upload's
  file_purged/purge_after/is_final -- no independent expiry logic, same
  convention supporting_document_path already established.
- rules.session_notes_only / rules.tp_section (+ mirrored on
  rule_version_history, same pattern as the payor column): metadata-only
  flags, zero comparison logic. Marks the 3 rule_ids whose real check can
  only ever be resolved from session notes, never the TP text alone.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4f8e29a6c17'
down_revision: Union[str, Sequence[str], None] = 'c3e7b1a94f56'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

supporting_doc_mode_enum = postgresql.ENUM("document", "structured_form", name="supporting_doc_mode")


def upgrade() -> None:
    supporting_doc_mode_enum.create(op.get_bind())
    op.add_column(
        "app_config",
        sa.Column("supporting_doc_mode", supporting_doc_mode_enum, nullable=False, server_default="structured_form"),
    )

    op.create_table(
        "upload_intake_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False, unique=True),
        sa.Column("client_insurance", sa.Text(), nullable=False),
        sa.Column("bcba_name_credentials_npi", sa.Text(), nullable=False),
        sa.Column("authorization_dates", sa.Text(), nullable=False),
        sa.Column("pos_schedule_vs_97153_hours", sa.Text(), nullable=False),
        sa.Column("hours_requesting", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "session_note_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("file_purged", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_session_note_files_upload_id", "session_note_files", ["upload_id"])

    op.add_column("rules", sa.Column("session_notes_only", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("rules", sa.Column("tp_section", sa.Text(), nullable=True))
    op.add_column("rule_version_history", sa.Column("session_notes_only", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("rule_version_history", sa.Column("tp_section", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("rule_version_history", "tp_section")
    op.drop_column("rule_version_history", "session_notes_only")
    op.drop_column("rules", "tp_section")
    op.drop_column("rules", "session_notes_only")
    op.drop_index("ix_session_note_files_upload_id", table_name="session_note_files")
    op.drop_table("session_note_files")
    op.drop_table("upload_intake_answers")
    op.drop_column("app_config", "supporting_doc_mode")
    supporting_doc_mode_enum.drop(op.get_bind())
