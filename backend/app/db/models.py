import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# --- Native Postgres enum types (per §2: "Enums are Postgres enums") ---
user_role_enum = Enum("admin", "standard", name="user_role")
version_status_enum = Enum("in_progress", "finalized", name="version_status")
audit_result_enum = Enum("pass", "fail", name="audit_result")
upload_status_enum = Enum("processing", "ready", "error", name="upload_status")
rule_type_enum = Enum("structural", "semantic", "cross_reference", name="rule_type")
rule_result_status_enum = Enum("pass", "fail", "na", "uncertain", name="rule_result_status")


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False)
    credential_title: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = _uuid_pk()
    reference_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    payor: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list["Version"]] = relationship(back_populates="patient")


class Version(Base):
    __tablename__ = "versions"
    __table_args__ = (UniqueConstraint("patient_id", "version_number", name="uq_version_patient_number"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    patient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    payor: Mapped[str | None] = mapped_column(Text)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assessment_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(version_status_enum, nullable=False, server_default="in_progress")
    final_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("uploads.id", use_alter=True, name="fk_versions_final_upload_id", ondelete="RESTRICT")
    )
    score: Mapped[float | None] = mapped_column(Numeric)
    audit_result: Mapped[str | None] = mapped_column(audit_result_enum)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    patient: Mapped["Patient"] = relationship(back_populates="versions")
    uploads: Mapped[list["Upload"]] = relationship(
        back_populates="version", foreign_keys="Upload.version_id"
    )


class Upload(Base):
    __tablename__ = "uploads"
    __table_args__ = (UniqueConstraint("version_id", "upload_number", name="uq_upload_version_number"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("versions.id", ondelete="RESTRICT"), nullable=False)
    upload_number: Mapped[int] = mapped_column(Integer, nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    voided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    voided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_reason: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    file_purged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rule_snapshots.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(upload_status_enum, nullable=False, server_default="processing")
    error_detail: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped["Version"] = relationship(back_populates="uploads", foreign_keys=[version_id])
    rule_results: Mapped[list["RuleResult"]] = relationship(back_populates="upload")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question_set: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(rule_type_enum, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleVersionHistory(Base):
    __tablename__ = "rule_version_history"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_rule_version_history_rule_version"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question_set: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(rule_type_enum, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleSnapshot(Base):
    __tablename__ = "rule_snapshots"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_ids_and_versions: Mapped[list] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RuleSyncState(Base):
    __tablename__ = "rule_sync_state"

    id: Mapped[uuid.UUID] = _uuid_pk()
    current_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rule_snapshots.id", ondelete="RESTRICT"))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    pending_change_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class RuleResult(Base):
    __tablename__ = "rule_results"
    __table_args__ = (UniqueConstraint("upload_id", "rule_id", name="uq_rule_results_upload_rule"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False)
    rule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False)
    rule_version_used: Mapped[int] = mapped_column(Integer, nullable=False)

    # model layer — written once by the pipeline, never updated afterward
    model_status: Mapped[str] = mapped_column(rule_result_status_enum, nullable=False)
    model_finding: Mapped[str] = mapped_column(Text, nullable=False)
    model_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, server_default="{}")
    model_source_quote: Mapped[str | None] = mapped_column(Text)

    # final layer — the human-ownable truth
    final_status: Mapped[str] = mapped_column(rule_result_status_enum, nullable=False)
    final_finding: Mapped[str] = mapped_column(Text, nullable=False)
    final_pages: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False, server_default="{}")
    is_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_edited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    upload: Mapped["Upload"] = relationship(back_populates="rule_results")


class RuleResultEdit(Base):
    __tablename__ = "rule_result_edits"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rule_results.id", ondelete="RESTRICT"), nullable=False)
    edited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GeneratedEmail(Base):
    __tablename__ = "generated_emails"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("versions.id", ondelete="RESTRICT"), nullable=False)
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    to_addr: Mapped[str | None] = mapped_column(Text)
    cc: Mapped[str | None] = mapped_column(Text)
    bcc: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    routed_to: Mapped[str] = mapped_column(Text, nullable=False)
    routed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    routed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # null = system job
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppConfig(Base):
    """Singleton row — one and only one record ever exists."""

    __tablename__ = "app_config"

    id: Mapped[uuid.UUID] = _uuid_pk()
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    stuck_job_timeout_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    notif_from_name: Mapped[str | None] = mapped_column(Text)
    notif_from_address: Mapped[str | None] = mapped_column(Text)
    notif_default_cc: Mapped[str | None] = mapped_column(Text)
    auto_send: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    integration_state: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
