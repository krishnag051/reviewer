import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import Upload, Version
from app.storage import save_blob


def create_upload(
    session: Session,
    version_id: uuid.UUID,
    *,
    filename: str,
    content: bytes,
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
