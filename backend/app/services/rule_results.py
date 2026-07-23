import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import RuleResult, RuleResultEdit, Upload, Version
from app.optimistic_lock import check_not_stale
from app.services.scoring import compute_score

MUTABLE_FIELDS = {"final_status", "final_finding", "final_pages"}


def override_rule_result(
    session: Session,
    rule_result_id: uuid.UUID,
    *,
    client_updated_at: datetime,
    changes: dict,
    reason: str | None,
    actor_user_id: uuid.UUID,
    _after_lock: Callable[[], None] | None = None,
) -> RuleResult | None:
    """PATCH /rule_results/:id. `changes` is whatever subset of
    {final_status, final_finding, final_pages} the caller's request body
    actually included (any subset, independently — never require all three).
    Returns None if the rule_result doesn't exist.

    Order matters here, per the tp-review-invariants skill file — do not
    reorder:
    1. Optimistic lock check FIRST. The row is fetched via
       SELECT ... FOR UPDATE, not a plain read — this is what makes the
       staleness check race-free under genuine concurrent requests, not just
       best-effort. Two overlapping PATCHes on the SAME row serialize on this
       lock; the second one only proceeds after the first commits, so it
       always re-reads the row's *post*-first-edit updated_at before
       comparing — a lost update is structurally impossible, not just
       unlikely.
    2-3. Diff computed BEFORE any mutation. Empty diff -> true no-op: no
       history row, no audit entry, no downstream recompute (same no-op
       discipline as the rules-PATCH fix from step 4 — don't reintroduce
       that class of bug here).
    4. is_overridden / last_edited_by / last_edited_at set only on a real diff.
    5. rule_result_edits row — changed fields only, plus reason if given.
    6. Audit entry for the override itself.
    7. CRITICAL (gap A2): if the parent upload is already finalized,
       recompute the version's score/audit_result in THIS SAME transaction
       via app.services.scoring.compute_score (never inline the formula
       here), and audit that recompute as a second, separate entry. This is
       not optional, not deferred, not batched — a stale score on an
       already-finalized, already-reviewed version is the single worst bug
       this system could ship.

    All of the above is one transaction: it either all commits, or (on any
    exception) all rolls back via the caller's session lifecycle.
    """
    rule_result = session.execute(
        select(RuleResult).where(RuleResult.id == rule_result_id).with_for_update()
    ).scalar_one_or_none()
    if rule_result is None:
        session.rollback()
        return None

    if _after_lock is not None:
        _after_lock()

    # 1. Optimistic lock check FIRST — before computing or applying anything.
    check_not_stale(rule_result.updated_at, client_updated_at)

    # 2-3. Diff computed before any mutation.
    diff = {
        field: {"from": getattr(rule_result, field), "to": new_value}
        for field, new_value in changes.items()
        if field in MUTABLE_FIELDS and getattr(rule_result, field) != new_value
    }
    if not diff:
        session.rollback()  # release the row lock; nothing to do
        return rule_result

    # 4. Apply the diff + override flags.
    for field, change in diff.items():
        setattr(rule_result, field, change["to"])
    rule_result.is_overridden = True
    rule_result.last_edited_by = actor_user_id
    rule_result.last_edited_at = datetime.now(timezone.utc)
    session.flush()

    # 5. rule_result_edits row.
    session.add(
        RuleResultEdit(
            rule_result_id=rule_result.id,
            edited_by=actor_user_id,
            changes=diff,
            reason=reason,
        )
    )

    # 6. Audit entry for the override itself.
    record(
        session,
        user_id=actor_user_id,
        action=f"Overrode rule result {rule_result.id}",
        target_type="rule_result",
        target_id=rule_result.id,
        details=diff,
    )

    # 7. CRITICAL (gap A2) — recompute synchronously if already finalized.
    upload = session.get(Upload, rule_result.upload_id)
    if upload.is_final:
        version = session.get(Version, upload.version_id)
        all_results = session.execute(
            select(RuleResult).where(RuleResult.upload_id == upload.id)
        ).scalars().all()
        new_score, new_audit_result = compute_score(all_results)

        old_score = float(version.score) if version.score is not None else None
        old_audit_result = version.audit_result
        version.score = new_score
        version.audit_result = new_audit_result

        record(
            session,
            user_id=actor_user_id,
            action=f"Recomputed score for version {version.version_number} after override on a finalized upload",
            target_type="version",
            target_id=version.id,
            details={
                "score": {"from": old_score, "to": new_score},
                "audit_result": {"from": old_audit_result, "to": new_audit_result},
            },
        )

    session.commit()
    return rule_result
