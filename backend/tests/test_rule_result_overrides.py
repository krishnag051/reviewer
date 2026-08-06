"""Step 7 regression coverage: the override endpoint (PATCH /rule_results/:id),
rule_result_edits, and the draft-only override guard (2026-07-30 —
overrides are rejected once the parent upload is finalized; this replaced
an earlier, now-wrong "recompute score on override" behavior — gap A2 is
now "override-after-finalize must be blocked", not "must recompute").
"""
import io
import threading
import uuid

import pytest
from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import AuditLog, Patient, Rule, RuleResult, RuleSyncState, Upload, Version
from app.services.finalize import finalize_upload
from app.services.rule_results import override_rule_result
from tests.conftest import ROUND56_QA_FORM_DATA, login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _different_status(current: str) -> str:
    """Any valid final_status value guaranteed different from `current` —
    used wherever a test needs to force a REAL diff. Since the pipeline is
    now real (2026-07-30), a freshly-created rule_result's starting status
    is whatever the agent honestly returned, not a fixed "na" default —
    tests can no longer assume any particular starting value.
    """
    for candidate in ("pass", "fail", "uncertain", "na", "not_checkable"):
        if candidate != current:
            return candidate
    raise AssertionError(f"no different status available from {current!r}")  # unreachable


def _resolve_all_uncertain(client, headers, detail: dict) -> dict:
    """The real rule-checking agent can honestly return "uncertain" for
    some rules against this fixture's content-free blank-page PDF —
    finalize's uncertain-results guard would then block whichever test
    happens to draw one, even though none of the finalize-adjacent tests
    below are testing that specific guard. Resolves every uncertain result
    to "na" (a safe, generic resolution, not asserting a real answer) right
    after upload creation.
    """
    for rr in detail["rule_results"]:
        if rr["final_status"] == "uncertain":
            client.patch(
                f"/rule_results/{rr['id']}",
                json={"updated_at": rr["updated_at"], "final_status": "na"},
                headers=headers,
            )
    return client.get(f"/uploads/{detail['id']}", headers=headers).json()


def _ready_upload(client, headers) -> dict:
    """Creates patient -> version -> upload and lets the real pipeline run
    (via the background task, synchronously complete under TestClient,
    calling the real rule-checking agent — 2026-07-30, previously the
    hollow stub) — returns the upload detail body incl. its real
    rule_results, whatever the agent honestly returned for this fixture's
    blank-page PDF (any "uncertain" ones pre-resolved to "na" — see
    _resolve_all_uncertain — since most tests below finalize and aren't
    testing that specific guard).
    """
    ref = f"TP-TEST-{uuid.uuid4().hex[:8]}"
    patient = client.post(
        "/patients", json={"reference_id": ref, "name": "Test Patient"}, headers=headers
    ).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
    upload = client.post(
        f"/versions/{version['id']}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    ).json()
    detail = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    assert detail["status"] == "ready", detail
    detail = _resolve_all_uncertain(client, headers, detail)
    return {"patient": patient, "version": version, "upload": detail}


def _override(client, headers, rule_result: dict, **fields) -> "client response":
    body = {"updated_at": rule_result["updated_at"], **fields}
    return client.patch(f"/rule_results/{rule_result['id']}", json=body, headers=headers)


# --------------------------------------------------------------- partial overrides

def test_override_status_only(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]
    original_status = rr["final_status"]
    target = _different_status(original_status)

    resp = _override(client, headers, rr, final_status=target)
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_status"] == target
    assert body["final_finding"] == rr["final_finding"]  # untouched
    assert body["final_pages"] == rr["final_pages"]  # untouched
    assert body["is_overridden"] is True

    edit = db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalar_one()
    assert set(edit.changes.keys()) == {"final_status"}
    assert edit.changes["final_status"] == {"from": original_status, "to": target}


def test_override_finding_only(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][1]

    resp = _override(client, headers, rr, final_finding="Corrected finding text")
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_finding"] == "Corrected finding text"
    assert body["final_status"] == rr["final_status"]

    edit = db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalar_one()
    assert set(edit.changes.keys()) == {"final_finding"}


def test_override_pages_only(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][2]

    resp = _override(client, headers, rr, final_pages=[3, 4])
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_pages"] == [3, 4]
    assert body["final_status"] == rr["final_status"]

    edit = db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalar_one()
    assert set(edit.changes.keys()) == {"final_pages"}


def test_override_combination_of_fields(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][3]
    target = _different_status(rr["final_status"])

    resp = _override(
        client, headers, rr,
        final_status=target, final_finding="Missing signature", reason="Reviewer caught this manually",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_status"] == target
    assert body["final_finding"] == "Missing signature"

    edit = db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalar_one()
    assert set(edit.changes.keys()) == {"final_status", "final_finding"}
    assert edit.reason == "Reviewer caught this manually"


# --------------------------------------------------------------- status transitions

def test_every_status_transition_direction(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    results = ctx["upload"]["rule_results"]

    # na -> pass, na -> fail, na -> uncertain (independent rows, all start na)
    for i, target in enumerate(["pass", "fail", "uncertain"]):
        resp = _override(client, headers, results[4 + i], final_status=target)
        assert resp.status_code == 200
        assert resp.json()["final_status"] == target

    # uncertain -> anything: chain transitions on ONE row, refetching updated_at each time
    rr = results[7]
    resp = _override(client, headers, rr, final_status="uncertain")
    assert resp.status_code == 200
    rr = resp.json()

    for target in ["pass", "fail", "na", "uncertain"]:
        resp = _override(client, headers, rr, final_status=target)
        assert resp.status_code == 200, resp.text
        assert resp.json()["final_status"] == target
        rr = resp.json()


# --------------------------------------------------------------------- no-op

def test_no_op_patch_does_nothing(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][8]

    edits_before = len(db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalars().all())
    audit_before = len(db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "rule_result", AuditLog.target_id == uuid.UUID(rr["id"]))
    ).scalars().all())

    # Resend the exact same values already on the row.
    resp = _override(
        client, headers, rr,
        final_status=rr["final_status"], final_finding=rr["final_finding"], final_pages=rr["final_pages"],
    )
    assert resp.status_code == 200
    assert resp.json()["is_overridden"] is False
    assert resp.json()["updated_at"] == rr["updated_at"], "no-op must not bump updated_at either"

    db_session.expire_all()
    edits_after = len(db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalars().all())
    audit_after = len(db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "rule_result", AuditLog.target_id == uuid.UUID(rr["id"]))
    ).scalars().all())
    assert edits_after == edits_before, "no-op PATCH must not write a rule_result_edits row"
    assert audit_after == audit_before, "no-op PATCH must not write an audit entry"


# ------------------------------------------------------------- optimistic lock

def test_optimistic_lock_stale_updated_at_409(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][9]

    resp = client.patch(
        f"/rule_results/{rr['id']}",
        json={"updated_at": "2020-01-01T00:00:00+00:00", "final_status": _different_status(rr["final_status"])},
        headers=headers,
    )
    assert resp.status_code == 409

    # Confirm nothing was applied — still whatever the agent originally said.
    fresh = client.get(f"/uploads/{ctx['upload']['id']}", headers=headers).json()
    fresh_rr = next(r for r in fresh["rule_results"] if r["id"] == rr["id"])
    assert fresh_rr["final_status"] == rr["final_status"]
    assert fresh_rr["is_overridden"] is False


def test_optimistic_lock_matching_updated_at_succeeds(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][10]

    resp = _override(client, headers, rr, final_status="pass")
    assert resp.status_code == 200


# --------------------------------------------------------- score recompute (gap A2)

def test_override_on_non_final_upload_does_not_touch_version_score(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][11]

    resp = _override(client, headers, rr, final_status="pass")
    assert resp.status_code == 200

    db_session.expire_all()
    version = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version.score is None
    assert version.audit_result is None


def test_override_on_final_upload_is_rejected_409(client, db_session, seeded_baseline):
    """2026-07-30, corrected: overrides are draft-only. An earlier version of
    this test asserted the OPPOSITE (override-on-finalized recomputes the
    version's score) — that behavior is gone. Finalizing locks the document;
    no further overrides, no score changes, nothing.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    results = ctx["upload"]["rule_results"]

    finalize_resp = client.post(
        f"/uploads/{ctx['upload']['id']}/finalize",
        json={"reference_id": ctx["patient"]["reference_id"]},
        headers=headers,
    )
    assert finalize_resp.status_code == 200, finalize_resp.text

    db_session.expire_all()
    version_before = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    score_before = version_before.score
    audit_result_before = version_before.audit_result

    resp = _override(client, headers, results[0], final_status="pass")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "upload_already_finalized"

    # Nothing changed: not the rule_result, not the version's score.
    db_session.expire_all()
    fresh = client.get(f"/uploads/{ctx['upload']['id']}", headers=headers).json()
    fresh_rr = next(r for r in fresh["rule_results"] if r["id"] == results[0]["id"])
    assert fresh_rr["final_status"] == results[0]["final_status"]
    assert fresh_rr["is_overridden"] is False

    version_after = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version_after.score == score_before
    assert version_after.audit_result == audit_result_before

    # No score-recompute audit entry was written — only whatever finalize
    # itself already wrote.
    audit_rows = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == version_after.id)
    ).scalars().all()
    assert not any("Recomputed score" in row.action for row in audit_rows)


# ------------------------------------------------------------ real concurrency
#
# Round 44/45: this test's own _ready_upload() call makes ONE real
# review_treatment_plan call (agent-making's self-consistency pair -- ~2
# real Anthropic API calls, same as test_live_smoke.py's single upload).
# Marked @pytest.mark.real_api so it isn't structurally blocked by
# conftest.py's autouse guardrail, and its real calls count against that
# same conftest.py's session-wide MAX_REAL_API_CALLS_PER_SESSION ceiling --
# never run this test (or add this marker to another one) without the
# user's explicit, per-instance approval first, same as any other real call.


@pytest.mark.real_api
def test_concurrent_overrides_same_rule_result_prevents_lost_update(client, db_session, engine, seeded_baseline):
    """Two threads PATCH the SAME rule_result with the SAME (soon-to-be-stale)
    updated_at, racing on genuinely overlapping DB transactions (forced via
    the `_after_lock` hook, same pattern as step 6's concurrency tests).
    Exactly one must succeed; the other must see a 409, having reread the
    row's post-first-edit updated_at under the FOR UPDATE lock — not a lost
    update where the second silently overwrites the first.
    """
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][12]
    original_updated_at = rr["updated_at"]
    # Both targets must be real diffs from the original (whatever the agent
    # honestly returned) -- if either target happened to equal the
    # original, that thread's override would be a true no-op and never
    # bump updated_at, breaking the race this test is built to force.
    remaining = [s for s in ("pass", "fail", "uncertain", "na", "not_checkable") if s != rr["final_status"]]
    target_1, target_2 = remaining[0], remaining[1]

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    lock_acquired = threading.Event()

    def _worker(target_status: str, delay_after_lock: bool):
        session = Session()
        try:
            def _after_lock():
                if delay_after_lock:
                    lock_acquired.set()
                    import time
                    time.sleep(0.2)
                else:
                    lock_acquired.wait(timeout=2)

            from datetime import datetime as dt
            result = override_rule_result(
                session,
                uuid.UUID(rr["id"]),
                client_updated_at=dt.fromisoformat(original_updated_at),
                changes={"final_status": target_status},
                reason=None,
                actor_user_id=admin_id,
                _after_lock=_after_lock,
            )
            results.append(("ok", target_status))
        except Exception as exc:
            errors.append(exc)
        finally:
            session.close()

    t1 = threading.Thread(target=_worker, args=(target_1, True))
    t2 = threading.Thread(target=_worker, args=(target_2, False))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(results) == 1, f"exactly one override should succeed, got {results}"
    assert len(errors) == 1, f"exactly one override should be rejected as stale, got {len(errors)} errors: {errors}"

    from fastapi import HTTPException
    assert isinstance(errors[0], HTTPException)
    assert errors[0].status_code == 409

    db_session.expire_all()
    fresh = client.get(f"/uploads/{ctx['upload']['id']}", headers=headers).json()
    fresh_rr = next(r for r in fresh["rule_results"] if r["id"] == rr["id"])
    # Whichever one won, the row reflects exactly that one edit — not both,
    # not neither, and not silently overwritten by the loser.
    assert fresh_rr["final_status"] == results[0][1]


# --------------------------------------------------- override vs. finalize race (2026-07-31)
#
# Direct ORM construction, NOT _ready_upload -- these tests only need SOME
# upload + rule_result to exist to prove the locking fix, not real agent
# content, and must not make real Anthropic API calls (standing rule).

def _direct_ready_upload_with_one_rule_result(db_session, seeded_baseline):
    """Builds patient -> version -> upload (status=ready) -> one rule_result,
    entirely via direct inserts against the real DB connection the test's
    other assertions also use (so everything is visible without needing a
    separate session/commit round-trip) -- bypasses create_upload/
    run_upload_pipeline and therefore the real rule-checking agent
    entirely. Returns (patient, upload, rule_result).
    """
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
    db_session.refresh(patient)
    db_session.refresh(upload)
    db_session.refresh(rule_result)
    return patient, upload, rule_result


def test_finalize_wins_race_override_blocks_then_sees_finalized_and_is_rejected(
    db_session, engine, seeded_baseline,
):
    """Finalize acquires the Upload row lock first and holds it briefly
    (via finalize_upload's `_after_lock` hook) before committing. A
    concurrent override attempt on the SAME upload must genuinely BLOCK on
    that lock (not read a stale "not yet finalized" snapshot) and, once
    finalize has committed, correctly see is_final=True and reject with
    409 -- proving the fix: before 2026-07-31, override only did a plain
    read/refresh of Upload, which could miss finalize's in-flight,
    not-yet-committed change.
    """
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    patient, upload, rule_result = _direct_ready_upload_with_one_rule_result(db_session, seeded_baseline)
    original_updated_at = rule_result.updated_at

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    finalize_lock_acquired = threading.Event()

    def _finalize_worker():
        session = Session()
        try:
            def _after_lock():
                finalize_lock_acquired.set()
                import time
                time.sleep(0.3)

            result = finalize_upload(
                session, upload.id,
                reference_id=patient.reference_id, actor_user_id=admin_id,
                _after_lock=_after_lock,
            )
            results.append(("finalize", result is not None))
        except Exception as exc:
            errors.append(("finalize", exc))
        finally:
            session.close()

    def _override_worker():
        finalize_lock_acquired.wait(timeout=2)
        session = Session()
        try:
            from datetime import datetime as dt
            result = override_rule_result(
                session, rule_result.id,
                client_updated_at=original_updated_at,
                changes={"final_status": "pass"},
                reason=None, actor_user_id=admin_id,
            )
            results.append(("override", result))
        except Exception as exc:
            errors.append(("override", exc))
        finally:
            session.close()

    t1 = threading.Thread(target=_finalize_worker)
    t2 = threading.Thread(target=_override_worker)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not any(name == "finalize" for name, _ in errors), f"finalize should succeed cleanly: {errors}"
    assert ("finalize", True) in results, f"finalize should have completed: {results}"

    from fastapi import HTTPException
    override_errors = [exc for name, exc in errors if name == "override"]
    assert len(override_errors) == 1, f"override should have been rejected exactly once: errors={errors} results={results}"
    assert isinstance(override_errors[0], HTTPException)
    assert override_errors[0].status_code == 409
    assert override_errors[0].detail["error"] == "upload_already_finalized"

    # No torn state: the rule_result was never touched by the rejected override.
    db_session.expire_all()
    fresh_rr = db_session.get(RuleResult, rule_result.id)
    assert fresh_rr.final_status == "na"
    assert fresh_rr.is_overridden is False
    fresh_upload = db_session.get(Upload, upload.id)
    assert fresh_upload.is_final is True


def test_override_wins_race_finalize_blocks_then_succeeds_normally(db_session, engine, seeded_baseline):
    """Override acquires the Upload row lock first and holds it briefly
    (via override_rule_result's `_after_lock` hook) before committing. A
    concurrent finalize attempt on the SAME upload must genuinely BLOCK on
    that lock, then -- once override has committed -- proceed normally and
    finalize successfully (the override target is "pass", so it doesn't
    leave anything "uncertain" for finalize's own guard to trip on). No
    torn state either way: the override's edit is fully applied AND
    finalize sees it and finalizes cleanly.
    """
    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    patient, upload, rule_result = _direct_ready_upload_with_one_rule_result(db_session, seeded_baseline)
    original_updated_at = rule_result.updated_at

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    override_lock_acquired = threading.Event()

    def _override_worker():
        session = Session()
        try:
            def _after_lock():
                override_lock_acquired.set()
                import time
                time.sleep(0.3)

            result = override_rule_result(
                session, rule_result.id,
                client_updated_at=original_updated_at,
                changes={"final_status": "pass"},
                reason=None, actor_user_id=admin_id,
                _after_lock=_after_lock,
            )
            # Capture the value while the object is still attached to its
            # (about-to-close) session -- reading it later from another
            # thread after `finally: session.close()` runs would raise
            # DetachedInstanceError (attributes expire on commit by
            # default and need a live session to reload).
            results.append(("override", result is not None and result.is_overridden))
        except Exception as exc:
            errors.append(("override", exc))
        finally:
            session.close()

    def _finalize_worker():
        override_lock_acquired.wait(timeout=2)
        session = Session()
        try:
            result = finalize_upload(
                session, upload.id,
                reference_id=patient.reference_id, actor_user_id=admin_id,
            )
            results.append(("finalize", result is not None))
        except Exception as exc:
            errors.append(("finalize", exc))
        finally:
            session.close()

    t1 = threading.Thread(target=_override_worker)
    t2 = threading.Thread(target=_finalize_worker)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert errors == [], f"neither call should error in this ordering: {errors}"
    assert ("finalize", True) in results, f"finalize should have completed: {results}"
    assert ("override", True) in results, f"override should have succeeded and been a real diff: {results}"

    # No torn state: the override landed AND finalize saw it and completed.
    db_session.expire_all()
    fresh_rr = db_session.get(RuleResult, rule_result.id)
    assert fresh_rr.final_status == "pass"
    assert fresh_rr.is_overridden is True
    fresh_upload = db_session.get(Upload, upload.id)
    assert fresh_upload.is_final is True
    fresh_version = db_session.get(Version, upload.version_id)
    assert fresh_version.status == "finalized"
    assert fresh_version.audit_result == "pass"  # 1 pass, 0 fail -> 100%
