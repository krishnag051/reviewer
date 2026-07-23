from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import RuleSnapshot, RuleSyncState
from app.services.rule_snapshots import (
    compute_content_fingerprint,
    compute_content_hash,
    rule_content_payload,
    rule_ids_and_versions_payload,
)


def run_sync_tick(session: Session) -> None:
    """The one recurring rule timer (architecture doc §1.8a / gap D5).

    Locks the rule_sync_state singleton row for the duration (SELECT ... FOR
    UPDATE) so an overlapping call — a second process, a retried scheduler
    firing — blocks until this one commits, rather than racing to publish
    two snapshots or double-reset the counters.

    - pending_change_count == 0: no-op. Don't touch anything, not even the
      timestamps — nothing happened, there is nothing to record.
    - candidate content fingerprint == current snapshot's content fingerprint
      (an edit that reverted to identical rule wording): don't publish a
      duplicate snapshot, but DO reset pending_change_count and the
      timestamps — the window still elapsed, even though the ruleset ended
      up unchanged. Audited as an explicit no-op tick, not silently dropped.
      Compared on content_fingerprint (actual rule wording), NOT content_hash
      ({rule_id, version} pairs) — current_version increments monotonically
      and never reverts, so a reverted-content rule always has a *different*
      content_hash from before, even though nothing meaningfully changed;
      content_fingerprint is what actually detects "is this a no-op."
    - otherwise: publish the new snapshot, repoint current_snapshot_id,
      reset counters, audit.
    """
    sync_state = session.execute(select(RuleSyncState).with_for_update()).scalar_one_or_none()
    if sync_state is None:
        raise RuntimeError("rule_sync_state singleton is missing — bootstrap_snapshot_zero was never run")

    if sync_state.pending_change_count == 0:
        session.rollback()  # release the row lock; nothing to do
        return

    # Deterministic by construction — see rule_ids_and_versions_payload's /
    # rule_content_payload's docstrings. Two calls against the same
    # active-rule state always produce the same hash/fingerprint, regardless
    # of when or how many times this runs.
    payload = rule_ids_and_versions_payload(session)
    candidate_hash = compute_content_hash(payload)
    content_payload = rule_content_payload(session)
    candidate_fingerprint = compute_content_fingerprint(content_payload)

    current_snapshot = session.get(RuleSnapshot, sync_state.current_snapshot_id)
    now = datetime.now(timezone.utc)
    next_sync_at = now + timedelta(minutes=sync_state.sync_interval_minutes)
    old_pending_count = sync_state.pending_change_count  # captured before any mutation below

    if current_snapshot is not None and candidate_fingerprint == current_snapshot.content_fingerprint:
        sync_state.pending_change_count = 0
        sync_state.last_synced_at = now
        sync_state.next_sync_at = next_sync_at
        record(
            session,
            user_id=None,
            action="Sync tick: no-op (candidate snapshot identical to current)",
            target_type="rule_sync_state",
            target_id=sync_state.id,
            details={"pending_change_count": {"from": old_pending_count, "to": 0}},
        )
        session.commit()
        return

    new_snapshot = RuleSnapshot(
        rule_ids_and_versions=payload,
        content_hash=candidate_hash,
        content_fingerprint=candidate_fingerprint,
    )
    session.add(new_snapshot)
    session.flush()  # assigns new_snapshot.id

    old_snapshot_id = sync_state.current_snapshot_id
    sync_state.current_snapshot_id = new_snapshot.id
    sync_state.pending_change_count = 0
    sync_state.last_synced_at = now
    sync_state.next_sync_at = next_sync_at

    record(
        session,
        user_id=None,
        action="Sync tick: published new rule snapshot",
        target_type="rule_snapshot",
        target_id=new_snapshot.id,
        details={"current_snapshot_id": {"from": str(old_snapshot_id), "to": str(new_snapshot.id)}},
    )
    session.commit()
