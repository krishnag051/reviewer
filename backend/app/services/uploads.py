import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import SessionNoteFile, Upload, UploadIntakeAnswers, Version
from app.storage import save_blob, save_session_note_blob, save_supporting_blob


def create_upload(
    session: Session,
    version_id: uuid.UUID,
    *,
    filename: str,
    content: bytes,
    supporting_document_filename: str | None = None,
    supporting_document_content: bytes | None = None,
    # Round 56: the structured_form-mode alternative to the two params
    # above. `intake_answers` is the 5 plain-text Q&A answers (dict keyed by
    # UploadIntakeAnswers' own column names); `session_notes` is a list of
    # (filename, content) tuples, one per uploaded file. The router decides
    # which of these two shapes to populate based on the live
    # app_config.supporting_doc_mode and validates required-ness BEFORE
    # calling this function — this function itself just persists whatever
    # it's given, it doesn't re-check mode or requiredness.
    intake_answers: dict[str, str] | None = None,
    session_notes: list[tuple[str, bytes]] | None = None,
    uploaded_by: uuid.UUID,
    _after_lock: Callable[[], None] | None = None,
) -> Upload | None:
    """Locks the parent version row for the duration of this transaction so
    concurrent uploads against the SAME version serialize on upload_number
    assignment, instead of both reading the same "next number" and racing to
    insert it (the UNIQUE(version_id, upload_number) constraint is a
    backstop here, not the only protection). Returns None if the version
    doesn't exist. `_after_lock` is a test-only hook, invoked right after
    the lock is acquired — production callers never pass it.

    Round 51: `supporting_document_filename`/`_content`, when given, are
    stored via save_supporting_blob, a separate function from save_blob so
    the two files' on-disk paths can never collide. Round 56 widened both
    to Optional since a structured_form-mode upload supplies
    intake_answers/session_notes instead — the router guarantees exactly
    the pair matching the live mode is populated before this is ever
    called.
    """
    version = session.execute(
        select(Version).where(Version.id == version_id).with_for_update()
    ).scalar_one_or_none()
    if version is None:
        session.rollback()
        return None

    if _after_lock is not None:
        _after_lock()

    next_number = (
        session.execute(
            select(func.max(Upload.upload_number)).where(Upload.version_id == version_id)
        ).scalar()
        or 0
    ) + 1

    upload = Upload(
        version_id=version_id,
        upload_number=next_number,
        status="processing",
        uploaded_by=uploaded_by,
    )
    session.add(upload)
    session.flush()  # assigns upload.id

    upload.file_path = save_blob(upload.id, filename, content)

    if supporting_document_filename is not None:
        upload.supporting_document_path = save_supporting_blob(
            upload.id, supporting_document_filename, supporting_document_content
        )

    if intake_answers is not None:
        session.add(UploadIntakeAnswers(upload_id=upload.id, **intake_answers))

    if session_notes:
        for note_filename, note_content in session_notes:
            path = save_session_note_blob(upload.id, note_filename, note_content)
            session.add(SessionNoteFile(upload_id=upload.id, file_path=path, original_filename=note_filename))

    record(
        session,
        user_id=uploaded_by,
        action=f"Uploaded document {next_number} for version {version.version_number}",
        target_type="upload",
        target_id=upload.id,
        details={
            "upload_number": {"from": None, "to": next_number},
            "status": {"from": None, "to": "processing"},
        },
    )
    session.commit()
    return upload


def get_latest_intake_answers(session: Session, patient_id: uuid.UUID) -> UploadIntakeAnswers | None:
    """Round 56: "editable across versions" (Item 2) -- the structured Q&A
    form prefills from whatever the most recent upload for this patient
    (across every version, draft or finalized) answered, so a later
    submission never forces blank re-entry. Purely a read for the
    frontend's own prefill; does not copy/mutate anything server-side --
    each upload still gets its own UploadIntakeAnswers row at submission
    time (see create_upload above), a fresh snapshot, not a shared one.
    """
    return session.execute(
        select(UploadIntakeAnswers)
        .join(Upload, Upload.id == UploadIntakeAnswers.upload_id)
        .join(Version, Version.id == Upload.version_id)
        .where(Version.patient_id == patient_id)
        .order_by(UploadIntakeAnswers.created_at.desc(), UploadIntakeAnswers.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def void_upload(
    session: Session,
    upload_id: uuid.UUID,
    *,
    reason: str,
    actor_user_id: uuid.UUID,
) -> Upload | None:
    """POST /uploads/:id/void. Only allowed if is_final == False. Sets
    voided=True/voided_by/voided_at/voided_reason, and purge_after=now()
    immediately — voided uploads are purge-eligible right away, not waiting
    for a sibling finalize event. Requires a non-blank reason (not optional
    — this is what makes the mistake/disagreement data useful later, per the
    gap analysis). Returns None if the upload doesn't exist.
    """
    upload = session.execute(
        select(Upload).where(Upload.id == upload_id).with_for_update()
    ).scalar_one_or_none()
    if upload is None:
        session.rollback()
        return None

    if not reason or not reason.strip():
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "reason_required", "message": "a reason is required to void an upload"},
        )

    if upload.is_final:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_final", "message": "a finalized upload cannot be voided"},
        )

    old_voided = upload.voided
    now = datetime.now(timezone.utc)
    upload.voided = True
    upload.voided_by = actor_user_id
    upload.voided_at = now
    upload.voided_reason = reason
    upload.purge_after = now

    record(
        session,
        user_id=actor_user_id,
        action=f"Voided upload {upload.upload_number}: {reason}",
        target_type="upload",
        target_id=upload.id,
        details={
            "voided": {"from": old_voided, "to": True},
            "voided_reason": {"from": None, "to": reason},
            "purge_after": {"from": None, "to": now.isoformat()},
        },
    )
    session.commit()
    return upload
