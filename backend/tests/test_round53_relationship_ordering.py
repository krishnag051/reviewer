"""Round 53: confirms two ORM relationships that previously had no explicit
order_by now return a deterministic order regardless of insertion order --
not just that they happen to look right today (the exact hazard this round's
audit was asked to check for).

Version.uploads feeds plans.$refId.index.tsx's `uploads[uploads.length - 1]`
fallback for "which draft attempt is currently being reviewed" when a
version isn't finalized yet -- an unordered collection here means picking
the WRONG draft to override/finalize, a real correctness bug for a
healthcare-compliance tool, not just a cosmetic one.

Upload.rule_results feeds the reviewer's rule checklist
(plans.$refId.index.tsx's `results`/`filteredResults`, rendered with no
re-sort of its own) -- an unordered collection here means the checklist's
row order changes across reloads with no functional bug, but still violates
"explicit, not implicit DB order."

Both tests insert rows in the REVERSE of the expected final order, so a
passing assertion only holds if the relationship's own order_by is doing
the work -- not because Postgres happened to return rows in insertion order,
which is the exact false confidence this round's task description warned
about ("even if it happens to look correct in casual testing").

Zero real Anthropic API calls -- pure ORM/DB test, no pipeline involved.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models import Patient, Rule, RuleResult, RuleSyncState, Upload, Version


def _make_version(session) -> Version:
    patient = Patient(reference_id=f"TP-TEST-order-{uuid.uuid4().hex[:8]}", name="Ordering Test Patient")
    session.add(patient)
    session.flush()
    version = Version(patient_id=patient.id, version_number=1, status="in_progress")
    session.add(version)
    session.flush()
    return version


def test_version_uploads_relationship_orders_by_upload_number_not_insertion_order(db_session, seeded_baseline):
    version = _make_version(db_session)
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()

    # Inserted in the REVERSE of upload_number order.
    upload_3 = Upload(version_id=version.id, upload_number=3, rules_snapshot_id=sync_state.current_snapshot_id)
    upload_1 = Upload(version_id=version.id, upload_number=1, rules_snapshot_id=sync_state.current_snapshot_id)
    upload_2 = Upload(version_id=version.id, upload_number=2, rules_snapshot_id=sync_state.current_snapshot_id)
    db_session.add_all([upload_3, upload_1, upload_2])
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.get(Version, version.id)
    assert [u.upload_number for u in reloaded.uploads] == [1, 2, 3], (
        "Version.uploads must be explicitly ordered ascending by upload_number -- "
        "this is what plans.$refId.index.tsx's `uploads[uploads.length - 1]` fallback "
        "relies on to pick the current (latest) draft attempt."
    )


def test_upload_rule_results_relationship_orders_by_created_at_then_id(db_session, seeded_baseline):
    version = _make_version(db_session)
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    upload = Upload(version_id=version.id, upload_number=1, rules_snapshot_id=sync_state.current_snapshot_id)
    db_session.add(upload)
    db_session.flush()

    rules = db_session.execute(select(Rule).limit(3)).scalars().all()
    assert len(rules) == 3, "seeded_baseline must provide at least 3 real rules for this test"

    base = datetime.now(timezone.utc)
    # Inserted with explicit, out-of-order created_at timestamps -- oldest last.
    results = [
        RuleResult(
            upload_id=upload.id, rule_id=rules[2].id, rule_version_used=1,
            model_status="pass", model_finding="f", final_status="pass", final_finding="f",
            created_at=base + timedelta(seconds=20),
        ),
        RuleResult(
            upload_id=upload.id, rule_id=rules[0].id, rule_version_used=1,
            model_status="pass", model_finding="f", final_status="pass", final_finding="f",
            created_at=base,
        ),
        RuleResult(
            upload_id=upload.id, rule_id=rules[1].id, rule_version_used=1,
            model_status="pass", model_finding="f", final_status="pass", final_finding="f",
            created_at=base + timedelta(seconds=10),
        ),
    ]
    db_session.add_all(results)
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.get(Upload, upload.id)
    assert [r.rule_id for r in reloaded.rule_results] == [rules[0].id, rules[1].id, rules[2].id], (
        "Upload.rule_results must be explicitly ordered by created_at (then id as a "
        "tiebreaker) -- this is what the reviewer's rule checklist renders directly, "
        "with no re-sort of its own on the frontend."
    )
