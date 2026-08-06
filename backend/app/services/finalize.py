import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import AppConfig, Patient, Rule, RuleResult, Upload, Version
from app.services.scoring import compute_score


def finalize_upload(
    session: Session,
    upload_id: uuid.UUID,
    *,
    reference_id: str | None,
    actor_user_id: uuid.UUID,
    _after_lock: Callable[[], None] | None = None,
) -> Upload | None:
    """POST /uploads/:id/finalize. Returns None if the upload doesn't exist.
    Raises HTTPException(409, detail=...) on any guard failure — nothing is
    applied when a guard fails; each guard's rollback happens before the
    raise, releasing whatever locks were held so far.

    Guards, checked in this exact order — do not reorder:
    0. upload.is_final == False already — the cheapest, most fundamental
       short-circuit. Without this, calling finalize twice on the same
       upload would re-run the entire commit each time: pushing every
       sibling's purge_after further into the future on every call
       (unbounded retention extension for something that's supposed to be a
       single irreversible action), rewriting versions.score/audit_result
       from whatever rule_results say NOW rather than what they said at the
       real finalize moment, and writing a duplicate audit entry.
    1. upload.status == "ready" (not processing, not error)
    2. upload.voided == False
    3. no OTHER non-voided upload in the same version already is_final
    4. no rule_result on this upload has final_status == "uncertain"
    5. request body's reference_id matches the upload's patient exactly —
       backend-enforced (CLAUDE.md's finalize invariant), not just a
       frontend confirmation dialog

    If all guards pass, in ONE transaction:
    - upload.is_final = True
    - every OTHER non-voided sibling upload gets
      purge_after = now() + app_config.retention_days (this upload does NOT)
    - score/audit_result computed via app.services.scoring.compute_score —
      never reinlined here
    - versions.score / versions.audit_result / versions.status="finalized" /
      versions.final_upload_id / versions.finalized_at (step 10 — the date
      reports filter on; NOT the same as versions.created_at, which is when
      the audit cycle started, not concluded)
    - one audit entry

    THERE IS NO UN-FINALIZE ENDPOINT. Do not add one here, or anywhere, even
    as a "reasonable" admin convenience — flag that request back to the user
    instead of building it (CLAUDE.md).

    Locks both the upload row and its parent version row for the duration —
    the version lock serializes concurrent finalize attempts across sibling
    uploads of the SAME version (otherwise two siblings could both read
    "no other upload is final yet" before either commits, and both finalize
    — exactly the invariant guard 3 exists to prevent). The upload-row lock
    additionally serializes against a concurrent void of this same upload,
    and (2026-07-31) against a concurrent override on this same upload's
    rule_results — `app/services/rule_results.py::override_rule_result`
    now takes the same `FOR UPDATE` lock on this upload row before checking
    `is_final`, closing a race where an override could slip through in the
    window after this function's guards pass but before its commit lands.

    `_after_lock` is a test-only hook, called right after both locks are
    acquired but before any guard check — used to force deterministic
    interleaving in concurrency tests (see
    tests/test_rule_result_overrides.py's override-vs-finalize race tests).
    """
    upload = session.execute(
        select(Upload).where(Upload.id == upload_id).with_for_update()
    ).scalar_one_or_none()
    if upload is None:
        session.rollback()
        return None

    version = session.execute(
        select(Version).where(Version.id == upload.version_id).with_for_update()
    ).scalar_one()

    if _after_lock is not None:
        _after_lock()

    # 0.
    if upload.is_final:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "already_finalized", "message": "this upload is already finalized"},
        )

    # 1.
    if upload.status != "ready":
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "not_ready",
                "message": f"upload.status is {upload.status!r}, must be 'ready' to finalize",
            },
        )

    # 2.
    if upload.voided:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "voided", "message": "a voided upload cannot be finalized"},
        )

    # 3.
    existing_final = session.execute(
        select(Upload.id).where(
            Upload.version_id == upload.version_id,
            Upload.id != upload.id,
            Upload.voided.is_(False),
            Upload.is_final.is_(True),
        )
    ).scalar_one_or_none()
    if existing_final is not None:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "sibling_already_final",
                "message": "another upload in this version is already finalized",
            },
        )

    # 4.
    rule_results = session.execute(
        select(RuleResult).where(RuleResult.upload_id == upload.id)
    ).scalars().all()
    uncertain_results = [r for r in rule_results if r.final_status == "uncertain"]
    if uncertain_results:
        rules_by_id = {
            r.id: r.rule_code
            for r in session.execute(
                select(Rule).where(Rule.id.in_([r.rule_id for r in uncertain_results]))
            ).scalars().all()
        }
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "uncertain_results_remain",
                "message": "resolve all uncertain rule results before finalizing",
                "rule_codes": sorted(rules_by_id[r.rule_id] for r in uncertain_results),
            },
        )

    # 5.
    patient = session.get(Patient, version.patient_id)
    if not reference_id or reference_id != patient.reference_id:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "reference_id_mismatch",
                "message": "reference_id must be provided and match the patient's reference_id exactly",
            },
        )

    # ---- all guards passed: one transaction ----
    upload.is_final = True

    app_config = session.execute(select(AppConfig)).scalar_one()
    now = datetime.now(timezone.utc)
    purge_after = now + timedelta(days=app_config.retention_days)
    siblings = session.execute(
        select(Upload).where(
            Upload.version_id == upload.version_id,
            Upload.id != upload.id,
            Upload.voided.is_(False),
        )
    ).scalars().all()
    for sibling in siblings:
        sibling.purge_after = purge_after

    new_score, new_audit_result = compute_score(rule_results)
    old_score = float(version.score) if version.score is not None else None
    old_audit_result = version.audit_result
    old_version_status = version.status

    version.score = new_score
    version.audit_result = new_audit_result
    version.status = "finalized"
    version.final_upload_id = upload.id
    version.finalized_at = now

    record(
        session,
        user_id=actor_user_id,
        action=f"Finalized upload {upload.upload_number} for version {version.version_number}",
        target_type="upload",
        target_id=upload.id,
        details={
            "is_final": {"from": False, "to": True},
            "version_status": {"from": old_version_status, "to": "finalized"},
            "score": {"from": old_score, "to": new_score},
            "audit_result": {"from": old_audit_result, "to": new_audit_result},
        },
    )

    session.commit()
    return upload
