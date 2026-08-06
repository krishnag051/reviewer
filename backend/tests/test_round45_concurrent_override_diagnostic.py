"""Round 45 diagnostic -- zero real Anthropic API calls.

tests/test_rule_result_overrides.py::test_concurrent_overrides_same_rule_result_prevents_lost_update
failed for real this round (both threads' overrides succeeded; exactly one
was supposed to be rejected 409 stale_update). That test's own real API
call already spent this session's approved budget, and the new ceiling
correctly refuses to let it run again without fresh explicit approval --
so this reproduces the SAME two-thread race against a directly-inserted
rule_result (same pattern as test_rule_result_overrides.py's own
_direct_ready_upload_with_one_rule_result, used by its override-vs-finalize
race tests) instead of a real pipeline-created one, to tell apart:

(a) a genuine regression in the FOR UPDATE locking itself (this test would
    also show a lost update), vs
(b) something specific to that one real run's timing/environment (this
    test would correctly show exactly one rejection, like it's presumed to
    have before credit ran out).
"""
import threading
import uuid
from datetime import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import Patient, Rule, RuleResult, RuleSyncState, Upload, Version
from app.services.rule_results import override_rule_result


def _direct_ready_upload_with_one_rule_result(db_session):
    patient = Patient(reference_id=f"TP-TEST-{uuid.uuid4().hex[:8]}", name="Test Patient")
    db_session.add(patient)
    db_session.flush()

    version = Version(patient_id=patient.id, version_number=1, status="in_progress")
    db_session.add(version)
    db_session.flush()

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    upload = Upload(
        version_id=version.id, upload_number=1, status="ready",
        rules_snapshot_id=sync_state.current_snapshot_id,
    )
    db_session.add(upload)
    db_session.flush()

    rule = db_session.execute(select(Rule)).scalars().first()
    rule_result = RuleResult(
        upload_id=upload.id, rule_id=rule.id, rule_version_used=1,
        model_status="na", model_finding="seed", model_pages=[],
        final_status="na", final_finding="seed", final_pages=[],
    )
    db_session.add(rule_result)
    db_session.commit()
    db_session.refresh(rule_result)
    return patient, upload, rule_result


def test_concurrent_overrides_same_rule_result_prevents_lost_update_direct_insert(
    db_session, engine, seeded_baseline,
):
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    patient, upload, rule_result = _direct_ready_upload_with_one_rule_result(db_session)
    original_updated_at = rule_result.updated_at
    target_1, target_2 = "pass", "fail"

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    lock_acquired = threading.Event()

    def _worker(target_status: str, delay_after_lock: bool):
        import time as time_mod
        session = Session()
        try:
            def _after_lock():
                print(f"[{target_status}] after_lock reached at {time_mod.time():.3f}, delay={delay_after_lock}")
                if delay_after_lock:
                    lock_acquired.set()
                    time_mod.sleep(0.2)
                else:
                    waited = lock_acquired.wait(timeout=2)
                    print(f"[{target_status}] wait() returned {waited}")

            result = override_rule_result(
                session,
                rule_result.id,
                client_updated_at=original_updated_at,
                changes={"final_status": target_status},
                reason=None,
                actor_user_id=admin_id,
                _after_lock=_after_lock,
            )
            print(f"[{target_status}] succeeded, resulting updated_at={result.updated_at}")
            results.append(("ok", target_status))
        except Exception as exc:
            print(f"[{target_status}] raised {type(exc).__name__}: {exc}")
            errors.append(exc)
        finally:
            session.close()

    print(f"original_updated_at = {original_updated_at}")

    t1 = threading.Thread(target=_worker, args=(target_1, True))
    t2 = threading.Thread(target=_worker, args=(target_2, False))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    print(f"\nROUND 45 DIAGNOSTIC -- results={results} errors={[type(e).__name__ for e in errors]}")

    assert len(results) == 1, f"exactly one override should succeed, got {results}"
    assert len(errors) == 1, f"exactly one override should be rejected as stale, got {len(errors)} errors: {errors}"
