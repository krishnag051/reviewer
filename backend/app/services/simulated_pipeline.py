"""Dev-only stand-in for app/services/upload_pipeline.py (Round 49).

Lets a `developer`-role user test the U1/U2/V1/V2/finalize lifecycle
mechanics repeatedly without waiting on or paying for the real agent.

STRUCTURAL SAFETY: this module has NO import of app.rule_engine.client,
review_treatment_plan, or anything in agent-making -- grep this file, there
is nothing here that could reach the real Anthropic API even if the gating
in app/routers/versions.py were ever misconfigured. Every synthetic
RuleResult this produces is labeled "SIMULATED" in its own finding text, so
it can never be mistaken for a real agent result once persisted. Verified
by tests/test_simulated_pipeline_never_touches_real_api.py, which runs this
under the test suite's normal review_treatment_plan-blocking guardrail
(tests/conftest.py::_block_real_api_calls) and confirms the upload still
reaches status="ready" -- if this module ever called the real seam, that
guardrail would turn it into status="error" instead.
"""
import logging
import time
import uuid

from sqlalchemy import select

from app.audit import record
from app.db.base import SessionLocal
from app.db.models import Rule, RuleResult, RuleSnapshot, RuleSyncState, Upload

logger = logging.getLogger(__name__)

# Deliberately excludes "uncertain" -- finalize (real guard AND the
# frontend's own disable condition) blocks while any uncertain result
# remains, and the whole point of this dev-only path is fast, frictionless
# U/V/finalize lifecycle testing. A real upload can and does produce
# uncertain results; this synthetic one never does, by design.
SIMULATED_STATUSES = ["pass", "fail", "na", "not_checkable"]
SIMULATED_FINDING_PREFIX = "SIMULATED — not a real agent result."


def simulate_upload_completion(upload_id: uuid.UUID) -> None:
    """Waits ~5s (long enough to see a real "processing" state in the UI,
    short enough to actually be useful for repeated lifecycle testing),
    then marks the upload ready with one clearly-labeled synthetic
    RuleResult per rule pinned in the current snapshot -- same snapshot-
    pinning discipline as the real pipeline (upload_pipeline.py), so a
    simulated upload's rules_snapshot_id is just as real and auditable as
    any other upload's, only the FINDINGS are fake.
    """
    time.sleep(5)
    session = SessionLocal()
    try:
        upload = session.get(Upload, upload_id)
        if upload is None:
            logger.error("simulate_upload_completion: upload %s not found", upload_id)
            return

        sync_state = session.execute(select(RuleSyncState)).scalar_one()
        snapshot_id = sync_state.current_snapshot_id
        snapshot = session.get(RuleSnapshot, snapshot_id)

        backend_rule_ids = [uuid.UUID(entry["rule_id"]) for entry in snapshot.rule_ids_and_versions]
        rules_by_id = {
            r.id: r for r in session.execute(select(Rule).where(Rule.id.in_(backend_rule_ids))).scalars().all()
        }

        upload.rules_snapshot_id = snapshot_id
        for i, entry in enumerate(snapshot.rule_ids_and_versions):
            rule_id = uuid.UUID(entry["rule_id"])
            rule = rules_by_id.get(rule_id)
            status_value = SIMULATED_STATUSES[i % len(SIMULATED_STATUSES)]
            finding = f"{SIMULATED_FINDING_PREFIX} Dev lifecycle-testing placeholder for rule {rule.rule_code if rule else rule_id} (#{i + 1})."
            session.add(RuleResult(
                upload_id=upload.id,
                rule_id=rule_id,
                rule_version_used=entry["version"],
                model_status=status_value,
                model_finding=finding,
                model_pages=[],
                final_status=status_value,
                final_finding=finding,
                final_pages=[],
            ))
        upload.status = "ready"

        record(
            session,
            user_id=None,
            action=(
                f"SIMULATED upload completion (dev-only, not a real agent run): "
                f"{len(snapshot.rule_ids_and_versions)} synthetic rule_results created"
            ),
            target_type="upload",
            target_id=upload.id,
            details={
                "status": {"from": "processing", "to": "ready"},
                "simulated": {"from": None, "to": True},
                "rules_snapshot_id": {"from": None, "to": str(snapshot_id)},
            },
        )
        session.commit()

    except Exception as exc:
        session.rollback()
        upload = session.get(Upload, upload_id)
        error_detail = f"SIMULATED pipeline error (dev-only path): {exc}"[:2000]
        upload.status = "error"
        upload.error_detail = error_detail
        record(
            session,
            user_id=None,
            action=f"SIMULATED upload completion failed: {error_detail}",
            target_type="upload",
            target_id=upload.id,
            details={"status": {"from": "processing", "to": "error"}, "error_detail": {"from": None, "to": error_detail}},
        )
        session.commit()
        logger.exception("simulate_upload_completion failed for upload %s", upload_id)
    finally:
        session.close()
