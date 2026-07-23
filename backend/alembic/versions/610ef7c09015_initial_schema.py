"""initial schema

Revision ID: 610ef7c09015
Revises:
Create Date: 2026-07-20 19:26:34.384320

Full §2 schema from TP_Review_Master_Build_Document.md. Table creation order
is dependency order; versions.final_upload_id -> uploads.id is added as a
separate ALTER after both tables exist, since versions and uploads reference
each other (versions.final_upload_id -> uploads.id, uploads.version_id ->
versions.id).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '610ef7c09015'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- Native Postgres enum types — created once, referenced with create_type=False
# on every column so CREATE TYPE isn't attempted a second time in this script. ---
user_role = postgresql.ENUM("admin", "standard", name="user_role")
version_status = postgresql.ENUM("in_progress", "finalized", name="version_status")
audit_result = postgresql.ENUM("pass", "fail", name="audit_result")
upload_status = postgresql.ENUM("processing", "ready", "error", name="upload_status")
rule_severity = postgresql.ENUM("normal", "critical", name="rule_severity")
rule_type = postgresql.ENUM("structural", "semantic", "cross_reference", name="rule_type")
rule_result_status = postgresql.ENUM("pass", "fail", "na", "uncertain", name="rule_result_status")

ALL_ENUMS = [user_role, version_status, audit_result, upload_status, rule_severity, rule_type, rule_result_status]


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("region", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", postgresql.ENUM("admin", "standard", name="user_role", create_type=False), nullable=False),
        sa.Column("credential_title", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("reference_id", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("payor", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # patients.reference_id is permanent per CLAUDE.md — enforced here with a DB
    # trigger (not app-layer-only) so it holds even if a future code path forgets
    # to guard it.
    op.execute("""
        CREATE FUNCTION enforce_patients_reference_id_immutable() RETURNS trigger AS $$
        BEGIN
            IF NEW.reference_id IS DISTINCT FROM OLD.reference_id THEN
                RAISE EXCEPTION 'patients.reference_id is immutable and cannot be changed (patient id=%)', OLD.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER trg_patients_reference_id_immutable
        BEFORE UPDATE ON patients
        FOR EACH ROW
        EXECUTE FUNCTION enforce_patients_reference_id_immutable();
    """)

    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_code", sa.Text(), nullable=False, unique=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("question_set", sa.Text(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("severity", postgresql.ENUM("normal", "critical", name="rule_severity", create_type=False), nullable=False),
        sa.Column("rule_type", postgresql.ENUM("structural", "semantic", "cross_reference", name="rule_type", create_type=False), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "rule_version_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("question_set", sa.Text(), nullable=False),
        sa.Column("severity", postgresql.ENUM("normal", "critical", name="rule_severity", create_type=False), nullable=False),
        sa.Column("rule_type", postgresql.ENUM("structural", "semantic", "cross_reference", name="rule_type", create_type=False), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("rule_id", "version", name="uq_rule_version_history_rule_version"),
    )

    op.create_table(
        "rule_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_ids_and_versions", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "rule_sync_state",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("current_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rule_snapshots.id", ondelete="RESTRICT")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("next_sync_at", sa.DateTime(timezone=True)),
        sa.Column("sync_interval_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("pending_change_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("payor", sa.Text()),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assessment_date", sa.Date()),
        sa.Column("status", postgresql.ENUM("in_progress", "finalized", name="version_status", create_type=False), nullable=False, server_default="in_progress"),
        # final_upload_id -> uploads.id FK added after "uploads" exists (circular dependency)
        sa.Column("final_upload_id", postgresql.UUID(as_uuid=True)),
        sa.Column("score", sa.Numeric()),
        sa.Column("audit_result", postgresql.ENUM("pass", "fail", name="audit_result", create_type=False)),
        sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("patient_id", "version_number", name="uq_version_patient_number"),
    )

    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("upload_number", sa.Integer(), nullable=False),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("voided", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("voided_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("voided_at", sa.DateTime(timezone=True)),
        sa.Column("voided_reason", sa.Text()),
        sa.Column("file_path", sa.Text()),
        sa.Column("file_purged", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.Column("rules_snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rule_snapshots.id", ondelete="RESTRICT")),
        sa.Column("status", postgresql.ENUM("processing", "ready", "error", name="upload_status", create_type=False), nullable=False, server_default="processing"),
        sa.Column("error_detail", sa.Text()),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("version_id", "upload_number", name="uq_upload_version_number"),
    )

    op.create_foreign_key(
        "fk_versions_final_upload_id",
        "versions",
        "uploads",
        ["final_upload_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "rule_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_version_used", sa.Integer(), nullable=False),
        sa.Column("model_status", postgresql.ENUM("pass", "fail", "na", "uncertain", name="rule_result_status", create_type=False), nullable=False),
        sa.Column("model_finding", sa.Text(), nullable=False),
        sa.Column("model_pages", postgresql.ARRAY(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("model_source_quote", sa.Text()),
        sa.Column("final_status", postgresql.ENUM("pass", "fail", "na", "uncertain", name="rule_result_status", create_type=False), nullable=False),
        sa.Column("final_finding", sa.Text(), nullable=False),
        sa.Column("final_pages", postgresql.ARRAY(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("is_overridden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_edited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_edited_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("upload_id", "rule_id", name="uq_rule_results_upload_rule"),
    )

    op.create_table(
        "rule_result_edits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("rule_results.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("edited_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "generated_emails",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("upload_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("to_addr", sa.Text()),
        sa.Column("cc", sa.Text()),
        sa.Column("bcc", sa.Text()),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "app_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("notif_from_name", sa.Text()),
        sa.Column("notif_from_address", sa.Text()),
        sa.Column("notif_default_cc", sa.Text()),
        sa.Column("auto_send", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("integration_state", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_config")
    op.drop_table("audit_log")
    op.drop_table("generated_emails")
    op.drop_table("rule_result_edits")
    op.drop_table("rule_results")
    op.drop_constraint("fk_versions_final_upload_id", "versions", type_="foreignkey")
    op.drop_table("uploads")
    op.drop_table("versions")
    op.drop_table("rule_sync_state")
    op.drop_table("rule_snapshots")
    op.drop_table("rule_version_history")
    op.drop_table("rules")

    op.execute("DROP TRIGGER IF EXISTS trg_patients_reference_id_immutable ON patients;")
    op.execute("DROP FUNCTION IF EXISTS enforce_patients_reference_id_immutable();")
    op.drop_table("patients")
    op.drop_table("users")
    op.drop_table("organizations")

    bind = op.get_bind()
    for enum in ALL_ENUMS:
        enum.drop(bind, checkfirst=True)
