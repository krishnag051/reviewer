"""Step 5 regression coverage: sync tick, retention sweep, stuck-job sweep,
GET /rule-sync/status.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import AuditLog, Rule, RuleResult, RuleSnapshot, RuleSyncState, Upload
from app.services.retention import run_retention_sweep
from app.services.rule_sync import run_sync_tick
from app.services.rules import create_rule, edit_rule
from app.services.stuck_jobs import run_stuck_job_sweep
from tests.conftest import login_headers, make_patient_version_upload, unique_rule_code


def _make_rule(session, actor_id, question_text: str) -> Rule:
    """Calls the real create_rule service — not a reimplementation — so this
    test exercises (and stays in sync with) the actual creation path,
    including its pending_change_count increment.
    """
    rule = create_rule(
        session,
        rule_code=unique_rule_code(),
        category="Patient Info",
        question_set="Treatment Plan",
        question_text=question_text,
        rule_type="structural",
        actor_user_id=actor_id,
    )
    session.commit()
    return rule


def _edit_rule(session, rule: Rule, new_question_text: str, actor_id):
    """Calls the real edit_rule service — not a reimplementation — so this
    test exercises (and stays in sync with) the actual PATCH /rules/:id
    path, including its history-versioning order and pending_change_count
    increment.
    """
    updated = edit_rule(session, rule.id, changes={"question_text": new_question_text}, actor_user_id=actor_id)
    session.commit()
    return updated


def test_sync_tick_publishes_new_snapshot_on_real_change(db_session, seeded_baseline):
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    rule = _make_rule(db_session, admin_id, "Sync tick test — original")

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    snapshot_before_id = sync_state.current_snapshot_id

    _edit_rule(db_session, rule, "Sync tick test — genuinely changed", admin_id)

    run_sync_tick(db_session)

    db_session.expire_all()
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == 0
    assert sync_state.current_snapshot_id != snapshot_before_id, "expected a new snapshot to be published"

    new_snapshot = db_session.get(RuleSnapshot, sync_state.current_snapshot_id)
    assert new_snapshot is not None
    rule_ids_in_snapshot = {entry["rule_id"] for entry in new_snapshot.rule_ids_and_versions}
    assert str(rule.id) in rule_ids_in_snapshot

    audit_row = db_session.execute(
        select(AuditLog)
        .where(AuditLog.target_type == "rule_snapshot", AuditLog.target_id == new_snapshot.id)
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.action == "Sync tick: published new rule snapshot"


def test_published_rule_snapshot_never_changes_after_a_later_edit(db_session, seeded_baseline):
    """CLAUDE.md: "Published rule_snapshots never change once created." Once
    a snapshot is published, a LATER rule edit (and the sync tick that
    publishes a newer snapshot for it) must not retroactively alter the
    earlier snapshot's own rule_ids_and_versions/content_hash/
    content_fingerprint — old uploads must stay interpretable against the
    exact wording they were checked with, forever.
    """
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    rule = _make_rule(db_session, admin_id, "Immutable snapshot test — v1 wording")

    run_sync_tick(db_session)  # publish a snapshot that includes this rule at v1
    db_session.expire_all()

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    first_snapshot = db_session.get(RuleSnapshot, sync_state.current_snapshot_id)
    first_snapshot_id = first_snapshot.id
    first_payload_snapshot = list(first_snapshot.rule_ids_and_versions)
    first_content_hash = first_snapshot.content_hash
    first_content_fingerprint = first_snapshot.content_fingerprint

    # Edit the SAME rule again and publish a second snapshot.
    _edit_rule(db_session, rule, "Immutable snapshot test — v2 wording, genuinely different", admin_id)
    run_sync_tick(db_session)
    db_session.expire_all()

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.current_snapshot_id != first_snapshot_id, "expected a second, newer snapshot"

    # The FIRST snapshot's own row must be completely untouched.
    first_snapshot_reloaded = db_session.get(RuleSnapshot, first_snapshot_id)
    assert first_snapshot_reloaded.rule_ids_and_versions == first_payload_snapshot
    assert first_snapshot_reloaded.content_hash == first_content_hash
    assert first_snapshot_reloaded.content_fingerprint == first_content_fingerprint
    # Specifically: it must still reference the rule at v1, not v2.
    entry = next(e for e in first_snapshot_reloaded.rule_ids_and_versions if e["rule_id"] == str(rule.id))
    assert entry["version"] == 1


def test_sync_tick_no_op_on_revert_resets_counters_with_correct_from_value(db_session, seeded_baseline):
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    original_text = "Sync tick revert test — original"
    rule = _make_rule(db_session, admin_id, original_text)

    # Let this rule's creation settle into the published snapshot before the
    # edit/revert sequence, so "revert" means "back to what's published."
    run_sync_tick(db_session)
    db_session.expire_all()

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    snapshot_before_id = sync_state.current_snapshot_id

    _edit_rule(db_session, rule, "Sync tick revert test — temporarily changed", admin_id)
    _edit_rule(db_session, rule, original_text, admin_id)  # revert — content matches the published snapshot again

    db_session.expire_all()
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == 2, "expected two edits to have incremented pending_change_count by 2"

    snapshot_count_before = len(db_session.execute(select(RuleSnapshot)).scalars().all())

    run_sync_tick(db_session)

    db_session.expire_all()
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == 0
    assert sync_state.current_snapshot_id == snapshot_before_id, "no-op tick must not repoint current_snapshot_id"

    snapshot_count_after = len(db_session.execute(select(RuleSnapshot)).scalars().all())
    assert snapshot_count_after == snapshot_count_before, "no-op tick must not insert a new snapshot row"

    audit_row = db_session.execute(
        select(AuditLog)
        .where(AuditLog.target_type == "rule_sync_state")
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.action == "Sync tick: no-op (candidate snapshot identical to current)"
    # Regression assertion for the bug caught while building this: "from"
    # must be the real prior count (2), not 0 (which is what reading the
    # field AFTER mutating it would produce).
    assert audit_row.details["pending_change_count"]["from"] == 2
    assert audit_row.details["pending_change_count"]["to"] == 0


def test_retention_sweep_purges_past_due_non_final_upload(db_session, tmp_path):
    blob = tmp_path / "fake.pdf"
    blob.write_text("fake pdf content")

    upload = make_patient_version_upload(
        db_session,
        status="ready",
        is_final=False,
        file_purged=False,
        purge_after=datetime.now(timezone.utc) - timedelta(days=1),
        file_path=str(blob),
    )

    run_retention_sweep()

    db_session.expire_all()
    refreshed = db_session.get(Upload, upload.id)
    assert refreshed.file_purged is True
    assert not blob.exists()

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "upload", AuditLog.target_id == upload.id)
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details["file_purged"] == {"from": False, "to": True}


def test_retention_sweep_leaves_upload_with_no_purge_after_untouched(db_session):
    upload = make_patient_version_upload(
        db_session, status="ready", is_final=False, file_purged=False, purge_after=None
    )

    run_retention_sweep()

    db_session.expire_all()
    refreshed = db_session.get(Upload, upload.id)
    assert refreshed.file_purged is False


def test_retention_sweep_leaves_file_purged_false_on_delete_failure(db_session, monkeypatch, tmp_path):
    blob = tmp_path / "fake2.pdf"
    blob.write_text("fake pdf content")

    upload = make_patient_version_upload(
        db_session,
        status="ready",
        is_final=False,
        file_purged=False,
        purge_after=datetime.now(timezone.utc) - timedelta(days=1),
        file_path=str(blob),
    )

    def _boom(file_path):
        raise OSError("simulated storage failure")

    monkeypatch.setattr("app.services.retention.delete_blob", _boom)

    run_retention_sweep()

    db_session.expire_all()
    refreshed = db_session.get(Upload, upload.id)
    assert refreshed.file_purged is False, "must not mark file_purged=True when the delete failed"
    assert blob.exists(), "the blob itself must be untouched on a simulated failure"


def test_stuck_job_sweep_marks_old_processing_upload_as_error(db_session):
    old_created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    upload = make_patient_version_upload(db_session, status="processing", created_at=old_created_at)

    run_stuck_job_sweep()

    db_session.expire_all()
    refreshed = db_session.get(Upload, upload.id)
    assert refreshed.status == "error"
    assert refreshed.error_detail == "pipeline timeout"

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "upload", AuditLog.target_id == upload.id)
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details["status"] == {"from": "processing", "to": "error"}

    rule_results = db_session.execute(select(RuleResult).where(RuleResult.upload_id == upload.id)).scalars().all()
    assert rule_results == [], "no rule_results should exist for a stuck upload — pipeline never finished"


def test_stuck_job_sweep_leaves_recent_processing_upload_untouched(db_session):
    upload = make_patient_version_upload(db_session, status="processing")  # created_at ~= now

    run_stuck_job_sweep()

    db_session.expire_all()
    refreshed = db_session.get(Upload, upload.id)
    assert refreshed.status == "processing"


def test_rule_sync_status_endpoint_returns_correct_shape(client, db_session, seeded_baseline):
    headers = login_headers(client, "s.patel@brightpath-aba.com")
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()

    resp = client.get("/rule-sync/status", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"pending_change_count", "next_sync_at"}
    assert body["pending_change_count"] == sync_state.pending_change_count
