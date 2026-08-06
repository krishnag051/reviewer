import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import Rule, RuleSyncState, RuleVersionHistory


def increment_pending_change_count(session: Session) -> None:
    """For edit/deactivate/reactivate — callers where rule_sync_state must
    already exist (any edit necessarily happens well after initial bootstrap).
    """
    sync_state = session.execute(select(RuleSyncState)).scalar_one_or_none()
    if sync_state is None:
        # Should be impossible post gap-A4 bootstrap — fail loudly rather than
        # silently drop the "new uploads should see this change" signal.
        raise RuntimeError("rule_sync_state singleton is missing — bootstrap_snapshot_zero was never run")
    sync_state.pending_change_count += 1


def _increment_pending_change_count_if_bootstrapped(session: Session) -> None:
    """For create_rule only. Unlike edits, rule creation legitimately happens
    during initial seeding, before bootstrap_snapshot_zero has ever run (the
    dev seed script creates all 24 rules first, then bootstraps Snapshot 0
    from whatever rules exist — see scripts/seed.py:main). In that pre-
    bootstrap window there's nothing to count against yet: Snapshot 0 will
    capture this rule directly, from live DB state, the moment it's computed.
    Post-bootstrap, this behaves identically to increment_pending_change_count.
    """
    sync_state = session.execute(select(RuleSyncState)).scalar_one_or_none()
    if sync_state is not None:
        sync_state.pending_change_count += 1


def create_rule(
    session: Session,
    *,
    rule_code: str,
    category: str,
    question_set: str,
    question_text: str,
    rule_type: str,
    payor: str | None = None,
    active: bool = True,
    # Round 56: metadata-only, same convention as payor above -- see
    # Rule.session_notes_only/tp_section's own docstring in db/models.py.
    session_notes_only: bool = False,
    tp_section: str | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> Rule:
    """Creates a rule and writes its rule_version_history v1 row in the same
    transaction (gap A3 — every {rule_id, version} a snapshot can reference
    must have a history row, from the moment the rule is created, not just
    on later edits). Does not commit — caller controls the transaction
    boundary, same as every other mutating service in this codebase.
    """
    rule = Rule(
        rule_code=rule_code,
        category=category,
        question_set=question_set,
        question_text=question_text,
        rule_type=rule_type,
        payor=payor,
        active=active,
        session_notes_only=session_notes_only,
        tp_section=tp_section,
        current_version=1,
        updated_by=actor_user_id,
    )
    session.add(rule)
    session.flush()  # assigns rule.id

    session.add(
        RuleVersionHistory(
            rule_id=rule.id,
            version=1,
            question_text=question_text,
            category=category,
            question_set=question_set,
            rule_type=rule_type,
            payor=payor,
            active=active,
            session_notes_only=session_notes_only,
            tp_section=tp_section,
            changed_by=actor_user_id,
        )
    )

    # A new rule is a rule-set change like any other — it waits for the next
    # sync tick to actually become part of a published snapshot, same as edits.
    _increment_pending_change_count_if_bootstrapped(session)

    record(
        session,
        user_id=actor_user_id,
        action=f"Created rule {rule_code}",
        target_type="rule",
        target_id=rule.id,
        details={
            "rule_code": {"from": None, "to": rule_code},
            "category": {"from": None, "to": category},
            "question_set": {"from": None, "to": question_set},
            "question_text": {"from": None, "to": question_text},
            "rule_type": {"from": None, "to": rule_type},
            "payor": {"from": None, "to": payor},
            "active": {"from": None, "to": active},
            "session_notes_only": {"from": None, "to": session_notes_only},
            "tp_section": {"from": None, "to": tp_section},
        },
    )

    return rule


def _post_change_history_row(rule: Rule, actor_user_id: uuid.UUID | None) -> RuleVersionHistory:
    """Snapshot of the rule's state as of its NEW current_version, written the
    moment that version becomes live — not deferred to the next edit. Must be
    built (and added/flushed) AFTER the setattr()s and the current_version
    bump, so it captures the POST-change content under the version number
    that content actually corresponds to.
    """
    return RuleVersionHistory(
        rule_id=rule.id,
        version=rule.current_version,
        question_text=rule.question_text,
        category=rule.category,
        question_set=rule.question_set,
        rule_type=rule.rule_type,
        payor=rule.payor,
        active=rule.active,
        session_notes_only=rule.session_notes_only,
        tp_section=rule.tp_section,
        changed_by=actor_user_id,
    )


def edit_rule(
    session: Session,
    rule_id: uuid.UUID,
    *,
    changes: dict,
    actor_user_id: uuid.UUID,
) -> Rule | None:
    """PATCH /rules/:id. `changes` is whatever subset of {category,
    question_set, question_text, rule_type, payor} the request included. Returns
    None if the rule doesn't exist. Does not commit — caller controls the
    transaction boundary (matches create_rule's convention).

    Order matters, per the tp-review-invariants skill file — do not reorder:
    1. diff computed BEFORE any mutation. Empty diff -> true no-op: no
       history row, no version bump, no pending_change_count increment, no
       audit entry.
    2. apply the diff + bump current_version.
    3. history row of the POST-change state, at the NEW version number.
    4. bump rule_sync_state.pending_change_count.
    5. audit entry (from the diff captured before any mutation).
    """
    rule = session.get(Rule, rule_id)
    if rule is None:
        return None

    diff = {
        field: {"from": getattr(rule, field), "to": new_value}
        for field, new_value in changes.items()
        if getattr(rule, field) != new_value
    }
    if not diff:
        return rule

    for field, change in diff.items():
        setattr(rule, field, change["to"])
    rule.current_version += 1
    rule.updated_by = actor_user_id
    session.flush()

    session.add(_post_change_history_row(rule, actor_user_id))
    session.flush()

    increment_pending_change_count(session)

    record(
        session,
        user_id=actor_user_id,
        action=f"Edited rule {rule.rule_code}",
        target_type="rule",
        target_id=rule.id,
        details=diff,
    )
    return rule


def set_rule_active(
    session: Session,
    rule_id: uuid.UUID,
    active: bool,
    *,
    actor_user_id: uuid.UUID,
) -> Rule | None:
    """POST /rules/:id/deactivate or /reactivate. Returns None if the rule
    doesn't exist. Does not commit — caller controls the transaction
    boundary (matches create_rule's convention).
    """
    rule = session.get(Rule, rule_id)
    if rule is None:
        return None
    if rule.active == active:
        return rule  # already in the requested state — no-op, nothing to write

    old_active = rule.active
    rule.active = active
    rule.current_version += 1
    rule.updated_by = actor_user_id
    session.flush()

    session.add(_post_change_history_row(rule, actor_user_id))
    session.flush()

    increment_pending_change_count(session)

    record(
        session,
        user_id=actor_user_id,
        action=f"{'Deactivated' if not active else 'Reactivated'} rule {rule.rule_code}",
        target_type="rule",
        target_id=rule.id,
        details={"active": {"from": old_active, "to": active}},
    )
    return rule
