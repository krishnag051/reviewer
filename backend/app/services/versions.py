import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import Patient, Version


def create_version(
    session: Session,
    patient_id: uuid.UUID,
    *,
    payor: str | None,
    assessment_date: date | None,
    actor_user_id: uuid.UUID,
    _after_lock: Callable[[], None] | None = None,
) -> Version | None:
    """Locks the parent patient row for the duration of this transaction so
    concurrent version creates for the SAME patient serialize on
    version_number assignment, instead of both reading the same "next
    number" and racing to insert it (the UNIQUE(patient_id, version_number)
    constraint is a backstop here, not the only protection — a losing
    request under real concurrency should never surface as a 500). Returns
    None if the patient doesn't exist. `_after_lock` is a test-only hook,
    invoked right after the lock is acquired — production callers never
    pass it.
    """
    patient = session.execute(
        select(Patient).where(Patient.id == patient_id).with_for_update()
    ).scalar_one_or_none()
    if patient is None:
        session.rollback()
        return None

    if _after_lock is not None:
        _after_lock()

    next_number = (
        session.execute(
            select(func.max(Version.version_number)).where(Version.patient_id == patient_id)
        ).scalar()
        or 0
    ) + 1

    version = Version(
        patient_id=patient_id,
        version_number=next_number,
        payor=payor,
        assessment_date=assessment_date,
    )
    session.add(version)
    session.flush()  # assigns version.id

    record(
        session,
        user_id=actor_user_id,
        action=f"Created version {next_number} for patient {patient.reference_id}",
        target_type="version",
        target_id=version.id,
        details={"version_number": {"from": None, "to": next_number}},
    )
    session.commit()
    return version


def mark_reviewed(
    session: Session,
    version_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID,
) -> Version | None:
    """POST /versions/:id/mark-reviewed. Guard: the version must already be
    finalized — 409 otherwise. Independent of audit_result: a version with
    audit_result=fail can still be marked reviewed, since human sign-off is
    not the same thing as passing. Returns None if the version doesn't exist.
    """
    version = session.execute(
        select(Version).where(Version.id == version_id).with_for_update()
    ).scalar_one_or_none()
    if version is None:
        session.rollback()
        return None

    if version.status != "finalized":
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_finalized", "message": "finalize an upload first"},
        )

    version.reviewed = True
    version.reviewed_by = actor_user_id
    version.reviewed_at = datetime.now(timezone.utc)

    record(
        session,
        user_id=actor_user_id,
        action=f"Marked version {version.version_number} as reviewed",
        target_type="version",
        target_id=version.id,
        details={"reviewed": {"from": False, "to": True}},
    )
    session.commit()
    return version
