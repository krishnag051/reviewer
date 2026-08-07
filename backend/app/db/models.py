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
    and_,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from app.db.base import Base

# --- Native Postgres enum types (per §2: "Enums are Postgres enums") ---
user_role_enum = Enum("admin", "user", "developer", name="user_role")
version_status_enum = Enum("in_progress", "finalized", name="version_status")
audit_result_enum = Enum("pass", "fail", name="audit_result")
upload_status_enum = Enum("processing", "ready", "error", name="upload_status")
rule_type_enum = Enum("structural", "semantic", "cross_reference", name="rule_type")
rule_result_status_enum = Enum("pass", "fail", "na", "uncertain", "not_checkable", name="rule_result_status")
# Round 50: metadata only, same as every other Rule column -- see
# app/rule_engine/client.py's docstring. NULL means "applies to every
# payor" (mirrors the old mock's "ALL" sentinel).
rule_payor_enum = Enum(
    "Aetna", "Anthem", "Cigna", "Emblem", "Empire", "Healthfirst", "Molina",
    "MVP", "Straight Medicaid", "New York Medicaid",
    name="rule_payor",
)
# Round 56: which upload path is active. "document" is Rounds 51-55's
# free-form supporting document + AI extraction (kept fully intact, just
# dormant by default). "structured_form" is the new 5-question form +
# multi-file session notes upload. Switchable from Developer Mode/admin
# settings (see app/services/app_config.py) -- this is a live config
# value, not a deploy-time constant.
supporting_doc_mode_enum = Enum("document", "structured_form", name="supporting_doc_mode")


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
    # Round 53: explicit order_by -- without it, Postgres/SQLAlchemy give no
    # ordering guarantee for this collection at all. The frontend's "which
    # draft attempt is currently being reviewed" logic
    # (plans.$refId.index.tsx: `uploads[uploads.length - 1]` when the
    # version isn't finalized yet) silently depended on this happening to
    # come back in insertion order -- a real bug, not a hypothetical one,
    # since a wrong pick here means overriding or finalizing the wrong
    # draft. upload_number is system-assigned/sequential/never-reused
    # (CLAUDE.md invariant), so ascending by it is the correct, deterministic
    # "oldest to newest" order this relationship's consumers already assume.
    uploads: Mapped[list["Upload"]] = relationship(
        back_populates="version", foreign_keys="Upload.version_id", order_by="Upload.upload_number"
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
    # Round 51: the mandatory "supporting document" -- a second, required
    # file at every upload creation point (app/services/uploads.py::
    # create_upload enforces "required" at the application layer, same
    # two-phase insert-then-set-path pattern as file_path above, which is
    # why this is nullable at the schema level too). Shares file_path's
    # exact retention lifecycle (same file_purged flag, same purge_after,
    # same never-purged-while-is_final protection) -- see
    # app/services/retention.py. Display-only for now (GET /uploads/:id/
    # supporting-file) -- no parsing/extraction/pipeline consumption yet,
    # deliberately deferred to a future round.
    supporting_document_path: Mapped[str | None] = mapped_column(Text)
    file_purged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    purge_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rules_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rule_snapshots.id", ondelete="RESTRICT"))
    # Round 70, Item 2: {physical_page_number (as a string key, JSON's own
    # object-key rule) -> printed page label found in that page's own text},
    # computed once at upload-processing time by
    # app/services/page_labels.py::extract_page_labels, from the SAME parsed
    # text run_upload_pipeline already produces (no second PDF read). A page
    # with no confidently-detected printed label is simply absent from this
    # map -- never defaulted to str(physical_index) -- so "not a key here"
    # always means "couldn't find one," not "found one that matches."
    # Display/cross-check only: page-jump navigation always targets the
    # physical index already stored in model_pages/final_pages (see that
    # module's own docstring for why no translation step is needed there).
    page_label_map: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(upload_status_enum, nullable=False, server_default="processing")
    error_detail: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    version: Mapped["Version"] = relationship(back_populates="uploads", foreign_keys=[version_id])
    # Round 53: explicit order_by -- GET /uploads/:id serializes this
    # relationship directly into the reviewer's rule checklist
    # (plans.$refId.index.tsx's `results`/`filteredResults`), which renders
    # rows in exactly this order with no re-sort of its own. created_at ties
    # (the pipeline writes every pinned rule's result in one batch) are
    # broken by id for full determinism -- without both, the checklist's
    # row order was unspecified DB row order, not a designed ordering.
    rule_results: Mapped[list["RuleResult"]] = relationship(
        back_populates="upload", order_by="RuleResult.created_at, RuleResult.id"
    )
    # Round 56: 1:1 detail row, populated only when this upload was created
    # under supporting_doc_mode="structured_form". None for every "document"
    # -mode upload (past and future, while that mode stays active for a
    # given upload) -- never both on the same upload.
    intake_answers: Mapped["UploadIntakeAnswers | None"] = relationship(back_populates="upload", uselist=False)
    # Round 56: one-to-many, unlike supporting_document_path's single column
    # -- multiple session-note files per upload. Explicit order_by for the
    # same reason Round 53 added one to uploads/rule_results above: an
    # unordered list rendered directly in the "Session Notes" page would be
    # unspecified DB row order, not a designed one.
    session_note_files: Mapped[list["SessionNoteFile"]] = relationship(
        back_populates="upload", order_by="SessionNoteFile.created_at, SessionNoteFile.id"
    )


class UploadIntakeAnswers(Base):
    """Round 56: the 5 structured Q&A answers, replacing the old free-form
    supporting document + AI extraction for new uploads (that path stays
    fully intact behind app_config.supporting_doc_mode="document" -- see
    SupportingDocMode). Plain text, typed by the reviewer, no AI extraction
    involved. One row per upload (a snapshot of what was answered at THAT
    submission, not a live-editable patient-level record) -- the "editable
    across versions" requirement is a frontend prefill behavior (show the
    previous upload's answers as the new form's starting values), not a
    shared mutable row, matching this codebase's audit/historical-accuracy
    convention (each upload's own facts-at-the-time never change after the
    fact, even if a later upload's answers differ).
    """

    __tablename__ = "upload_intake_answers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    upload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    client_insurance: Mapped[str] = mapped_column(Text, nullable=False)
    bcba_name_credentials_npi: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_dates: Mapped[str] = mapped_column(Text, nullable=False)
    pos_schedule_vs_97153_hours: Mapped[str] = mapped_column(Text, nullable=False)
    hours_requesting: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    upload: Mapped["Upload"] = relationship(back_populates="intake_answers")


class SessionNoteFile(Base):
    """Round 56: multi-file session notes upload, required alongside the
    structured Q&A form (same mandatory pattern the old supporting document
    had). Retained permanently like the TP's own file -- purge lifecycle is
    entirely the PARENT upload's (file_purged/purge_after/is_final); this
    table has its own file_purged flag only so retention.py can mark each
    blob's deletion individually/idempotently, not because it expires on a
    different schedule. Display-only: never parsed, never fed into any
    pipeline (real date-range extraction is deliberately deferred agent-side
    work, see the "Session Notes" page's own placeholder UI).
    """

    __tablename__ = "session_note_files"

    id: Mapped[uuid.UUID] = _uuid_pk()
    upload_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("uploads.id", ondelete="RESTRICT"), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_purged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    upload: Mapped["Upload"] = relationship(back_populates="session_note_files")


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[uuid.UUID] = _uuid_pk()
    rule_code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    question_set: Mapped[str] = mapped_column(Text, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_type: Mapped[str] = mapped_column(rule_type_enum, nullable=False)
    payor: Mapped[str | None] = mapped_column(rule_payor_enum)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    # Round 56: metadata only, same convention as the payor column above
    # (Round 50) -- zero comparison logic lives here or anywhere in this
    # backend. session_notes_only=true means this rule's real check can
    # only ever be resolved from session notes, never the TP text alone
    # (the actual agent-side wiring to enforce that is a deliberately
    # deferred future round). tp_section names where in the TP this check
    # anchors (e.g. "Assessment of Current Functioning") for that future
    # work's benefit -- independent of `category` above, which is this
    # rule's own checklist grouping and may or may not be the same string.
    session_notes_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tp_section: Mapped[str | None] = mapped_column(Text)
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
    payor: Mapped[str | None] = mapped_column(rule_payor_enum)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Round 56: mirrored from Rule, same as every other versioned metadata
    # field -- see Rule.session_notes_only/tp_section above.
    session_notes_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tp_section: Mapped[str | None] = mapped_column(Text)
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

    # Round 70: display-only relationships, viewonly (this file's own
    # invariant comment above already says model_status/model_finding/
    # model_pages are written once and never updated -- these two
    # relationships exist purely so the API layer can attach a real
    # question_text/category/rule_code to a rule_result without a second
    # round-trip; they never get assigned to or used for a write).
    #
    # `rule` gives the CURRENT/live rule row (for rule_code, which is
    # immutable and never versioned). `version_history` joins on BOTH
    # rule_id AND rule_version_used to get the question_text/category as
    # they read AT THE VERSION actually pinned for this result -- not
    # whatever the rule's text has since been edited to. This matters: a
    # rule's question_text can be edited after this result was created
    # (see app/services/rules.py::edit_rule), and an already-finalized
    # upload's displayed question must stay the one actually reviewed
    # against, not silently drift to newer wording.
    rule: Mapped["Rule"] = relationship(viewonly=True)
    version_history: Mapped["RuleVersionHistory"] = relationship(
        "RuleVersionHistory",
        primaryjoin=(
            "and_(RuleResult.rule_id == foreign(RuleVersionHistory.rule_id), "
            "RuleResult.rule_version_used == foreign(RuleVersionHistory.version))"
        ),
        viewonly=True,
        uselist=False,
    )

    @property
    def question_text(self) -> str:
        # Falls back to the live rule's text only if no history row exists
        # for this exact version (shouldn't happen post gap-A3/create_rule's
        # own v1-row guarantee, but a fallback beats a 500 on old/odd data).
        return self.version_history.question_text if self.version_history else self.rule.question_text

    @property
    def category(self) -> str:
        return self.version_history.category if self.version_history else self.rule.category

    @property
    def rule_code(self) -> str:
        return self.rule.rule_code


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
    # Round 56: feature flag, live-switchable (Developer Mode/admin settings
    # -- see app/services/app_config.py and app/routers/admin.py), not a
    # deploy-time constant. "document" = Rounds 51-55's free-form supporting
    # document + AI extraction, kept fully intact and testable. "structured_
    # form" (the new default for every row) = the 5-question form + session
    # notes upload this round adds. Read once per upload creation, at
    # request time -- switching it never rewrites past uploads' own data.
    supporting_doc_mode: Mapped[str] = mapped_column(
        supporting_doc_mode_enum, nullable=False, server_default="structured_form"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
