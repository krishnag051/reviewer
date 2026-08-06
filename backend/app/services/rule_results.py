import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import RuleResult, RuleResultEdit, Upload
from app.optimistic_lock import check_not_stale

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
    0. CRITICAL, checked before anything else including the RuleResult
       lock: overrides are draft-only (2026-07-30, corrected — this is the
       final answer). If the parent upload is already finalized, raise
       HTTPException(409) and touch nothing. The real workflow is: the
       agent flags each rule, a human reviewer corrects whatever's wrong
       while the upload is still in progress, and finalizing locks the
       document forever — no further overrides after that point.

       (2026-07-31, fixed) This check takes its own `SELECT ... FOR UPDATE`
       lock on the *Upload* row — a plain read/refresh isn't enough. Under
       READ COMMITTED, a concurrent `finalize_upload` call that's already
       past its own guards (holding the Upload row's lock, `is_final` set
       in memory, not yet committed) wouldn't be visible to a plain read
       here; an override could slip through in the window between
       finalize's guards passing and its commit landing. Taking the SAME
       `FOR UPDATE` lock on Upload means this call now genuinely blocks
       until any in-flight finalize on this upload commits or rolls back,
       then reads the real, post-commit value of `is_final` — not a stale
       snapshot. Locked in this order — Upload, then RuleResult — to match
       `finalize_upload`'s own lock ordering (Upload, then Version); a
       consistent lock order across the two code paths is what actually
       prevents a lock-ordering deadlock between concurrent override/
       finalize calls on the same upload. Because the Upload lock is held
       continuously from here through commit, there's no need for a
       second is_final re-check later — nothing can flip it out from under
       us once we hold it.
    1. Optimistic lock check. The RuleResult row is fetched via
       SELECT ... FOR UPDATE too, not a plain read — this is what makes
       the staleness check race-free under genuine concurrent requests,
       not just best-effort. Two overlapping PATCHes on the SAME row
       serialize on this lock; the second one only proceeds after the
       first commits, so it always re-reads the row's *post*-first-edit
       updated_at before comparing — a lost update is structurally
       impossible, not just unlikely.
    2-3. Diff computed BEFORE any mutation. Empty diff -> true no-op: no
       history row, no audit entry (same no-op discipline as the
       rules-PATCH fix from step 4 — don't reintroduce that class of bug
       here).
    4. is_overridden / last_edited_by / last_edited_at set only on a real diff.
    5. rule_result_edits row — changed fields only, plus reason if given.
    6. Audit entry for the override itself.

    There is no score-recompute step: a draft's parent version has no
    `score`/`audit_result` yet (those stay null until finalize sets them
    together, once), and a finalized upload can no longer be overridden at
    all per step 0 — so there is nothing left to recompute here.
    `app/services/scoring.py::compute_score` is called from exactly one
    place now, `finalize.py`.

    All of the above is one transaction: it either all commits, or (on any
    exception) all rolls back via the caller's session lifecycle.
    """
    # 0. Draft-only guard. Look up which upload this rule_result belongs to
    # (upload_id never changes once a rule_result exists, so an unlocked
    # lookup is fine here), then lock THAT Upload row FOR UPDATE before
    # checking is_final. See the docstring above for why a lock is required
    # here, not just a read.
    #
    # 2026-08-01 fix: this used to be `session.get(RuleResult, rule_result_id)`
    # -- an unlocked read of the FULL mapped RuleResult object, which
    # populates SQLAlchemy's identity map with that row's attributes
    # (including updated_at) BEFORE the FOR UPDATE lock below is acquired.
    # The later locked `select(RuleResult)...with_for_update()` genuinely
    # serializes at the database level, but SQLAlchemy hands back the
    # ALREADY-IDENTITY-MAPPED object rather than refreshing its attributes
    # from the fresh, lock-protected row -- so step 1's staleness check below
    # was comparing against a stale in-memory updated_at, not the real value
    # the lock just protected. Two concurrent overrides could both pass the
    # check and both "succeed," a genuine lost update (confirmed reproducing
    # 3/3 via tests/test_round45_concurrent_override_diagnostic.py). Selecting
    # only the scalar `upload_id` column here -- never touching the mapped
    # RuleResult object at all -- means the locked select() below is the
    # FIRST time this row enters the identity map, so it's populated from
    # the fresh, lock-protected data, not a stale pre-lock snapshot.
    upload_id = session.execute(
        select(RuleResult.upload_id).where(RuleResult.id == rule_result_id)
    ).scalar_one_or_none()
    if upload_id is None:
        return None

    upload = session.execute(
        select(Upload).where(Upload.id == upload_id).with_for_update()
    ).scalar_one()
    if upload.is_final:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "upload_already_finalized",
                "message": "this upload is finalized; overrides are draft-only",
            },
        )

    rule_result = session.execute(
        select(RuleResult).where(RuleResult.id == rule_result_id).with_for_update()
    ).scalar_one_or_none()
    if rule_result is None:
        session.rollback()
        return None

    if _after_lock is not None:
        _after_lock()

    # 1. Optimistic lock check.
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

    session.commit()
    return rule_result
