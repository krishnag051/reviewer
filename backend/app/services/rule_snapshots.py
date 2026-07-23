import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import Rule, RuleSnapshot, RuleSyncState


def rule_ids_and_versions_payload(session: Session) -> list[dict]:
    """The exact payload a rule_snapshot freezes. Deterministic by
    construction, which matters because two independent computations of this
    (Snapshot 0 bootstrap here, a sync-tick candidate elsewhere) must produce
    byte-identical output for identical rule state, or content-hash
    comparison is meaningless:
      - `ORDER BY rule_code` (a unique, never-reused column) fixes row order
        regardless of insertion order or how Postgres happens to scan the
        table.
      - Only active rules are included — a deactivated rule must vanish from
        the payload, not linger with stale data.
    """
    rows = session.execute(
        select(Rule.id, Rule.current_version).where(Rule.active.is_(True)).order_by(Rule.rule_code)
    ).all()
    return [{"rule_id": str(rule_id), "version": version} for rule_id, version in rows]


def compute_content_hash(rule_ids_and_versions: list[dict]) -> str:
    canonical = json.dumps(rule_ids_and_versions, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def rule_content_payload(session: Session) -> list[dict]:
    """The defining content of each active rule — question_text, category,
    question_set, rule_type, active — used ONLY for the sync tick's
    no-op-on-revert check (see compute_content_fingerprint). Deliberately
    separate from rule_ids_and_versions_payload: current_version increments
    monotonically and never reverts, so a rule edited then reverted to its
    original wording has different {rule_id, version} pairs but identical
    content — this payload is what lets that be detected as a true no-op.
    Same `ORDER BY rule_code` / active-only discipline as the version payload,
    for the same determinism reasons.
    """
    rows = session.execute(
        select(
            Rule.id, Rule.question_text, Rule.category, Rule.question_set, Rule.rule_type, Rule.active
        ).where(Rule.active.is_(True)).order_by(Rule.rule_code)
    ).all()
    return [
        {
            "rule_id": str(rule_id),
            "question_text": question_text,
            "category": category,
            "question_set": question_set,
            "rule_type": rule_type,
            "active": active,
        }
        for rule_id, question_text, category, question_set, rule_type, active in rows
    ]


def compute_content_fingerprint(rule_content_payload_value: list[dict]) -> str:
    canonical = json.dumps(rule_content_payload_value, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def bootstrap_snapshot_zero(
    session: Session, *, sync_interval_minutes: int = 30
) -> RuleSyncState:
    """Gap A4: a fresh system must never have an upload dereference a null
    current_snapshot_id. Publishes Snapshot 0 from whatever active rules
    exist right now — even zero — and initializes the rule_sync_state
    singleton. No-op if rule_sync_state already has a row; never runs twice.
    Does not commit — caller controls the transaction boundary.
    """
    existing = session.execute(select(RuleSyncState)).scalar_one_or_none()
    if existing is not None:
        return existing

    payload = rule_ids_and_versions_payload(session)
    content_payload = rule_content_payload(session)
    snapshot = RuleSnapshot(
        rule_ids_and_versions=payload,
        content_hash=compute_content_hash(payload),
        content_fingerprint=compute_content_fingerprint(content_payload),
    )
    session.add(snapshot)
    session.flush()  # assigns snapshot.id

    now = datetime.now(timezone.utc)
    sync_state = RuleSyncState(
        current_snapshot_id=snapshot.id,
        last_synced_at=now,
        next_sync_at=now + timedelta(minutes=sync_interval_minutes),
        sync_interval_minutes=sync_interval_minutes,
        pending_change_count=0,
    )
    session.add(sync_state)
    session.flush()

    record(
        session,
        user_id=None,
        action="Published Snapshot 0 (bootstrap)",
        target_type="system",
        target_id=snapshot.id,
        details={"rule_count": {"from": None, "to": len(payload)}},
    )

    return sync_state
