"""Step 7 regression coverage: the override endpoint (PATCH /rule_results/:id),
rule_result_edits, and score-recompute-on-final (gap A2).
"""
import io
import threading
import uuid

from pypdf import PdfWriter
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models import AuditLog, RuleResultEdit, Version
from app.services.rule_results import override_rule_result
from tests.conftest import login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _ready_upload(client, headers) -> dict:
    """Creates patient -> version -> upload and lets the real pipeline run
    (via the background task, synchronously complete under TestClient),
    returning the upload detail body incl. its 24 "na" rule_results.
    """
    ref = f"TP-TEST-{uuid.uuid4().hex[:8]}"
    patient = client.post(
        "/patients", json={"reference_id": ref, "name": "Test Patient"}, headers=headers
    ).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
    upload = client.post(
        f"/versions/{version['id']}/uploads",
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()
    detail = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    assert detail["status"] == "ready", detail
    return {"patient": patient, "version": version, "upload": detail}


def _override(client, headers, rule_result: dict, **fields) -> "client response":
    body = {"updated_at": rule_result["updated_at"], **fields}
    return client.patch(f"/rule_results/{rule_result['id']}", json=body, headers=headers)


# --------------------------------------------------------------- partial overrides

def test_override_status_only(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]

    resp = _override(client, headers, rr, final_status="pass")
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_status"] == "pass"
    assert body["final_finding"] == rr["final_finding"]  # untouched
    assert body["final_pages"] == rr["final_pages"]  # untouched
    assert body["is_overridden"] is True

    edit = db_session.execute(
        select(RuleResultEdit).where(RuleResultEdit.rule_result_id == uuid.UUID(rr["id"]))
    ).scalar_one()
    assert set(edit.changes.keys()) == {"final_status"}
    assert edit.changes["final_status"] == {"from": "na", "to": "pass"}


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

    resp = _override(
        client, headers, rr,
        final_status="fail", final_finding="Missing signature", reason="Reviewer caught this manually",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final_status"] == "fail"
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
        json={"updated_at": "2020-01-01T00:00:00+00:00", "final_status": "pass"},
        headers=headers,
    )
    assert resp.status_code == 409

    # Confirm nothing was applied.
    fresh = client.get(f"/uploads/{ctx['upload']['id']}", headers=headers).json()
    fresh_rr = next(r for r in fresh["rule_results"] if r["id"] == rr["id"])
    assert fresh_rr["final_status"] == "na"
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


def test_override_on_final_upload_recomputes_score_and_audits_it(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    results = ctx["upload"]["rule_results"]

    # Finalize via the real endpoint (step 8) — no more direct-DB bypass now
    # that it exists. All rule_results are still "na" at this point, which
    # satisfies finalize's uncertain-results guard fine.
    finalize_resp = client.post(
        f"/uploads/{ctx['upload']['id']}/finalize",
        json={"reference_id": ctx["patient"]["reference_id"]},
        headers=headers,
    )
    assert finalize_resp.status_code == 200, finalize_resp.text

    # Override one result to "pass" and one to "fail" so the score is determinate.
    resp1 = _override(client, headers, results[0], final_status="pass")
    assert resp1.status_code == 200

    db_session.expire_all()
    version = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version.audit_result == "pass", "1 pass, 0 fail -> 100%"
    assert float(version.score) == 100.0

    # One "version"-targeted audit row already exists from create_version's
    # own "Created version..." entry — the score-recompute is the SECOND.
    audit_rows = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == version.id)
        .order_by(AuditLog.created_at)
    ).scalars().all()
    assert len(audit_rows) == 2
    assert audit_rows[1].details["score"]["to"] == 100.0
    assert audit_rows[1].details["audit_result"] == {"from": None, "to": "pass"}

    # Second override, to "fail" this time — score must recompute again, inline.
    rr2 = next(r for r in results if r["id"] != results[0]["id"])
    resp2 = _override(client, headers, rr2, final_status="fail")
    assert resp2.status_code == 200

    db_session.expire_all()
    version = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version.audit_result == "fail", "1 pass, 1 fail -> 50%, not 100%"
    assert float(version.score) == 50.0

    audit_rows = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == version.id)
        .order_by(AuditLog.created_at)
    ).scalars().all()
    assert len(audit_rows) == 3, "each override on a finalized upload gets its own score-recompute audit entry"
    assert audit_rows[2].details["score"] == {"from": 100.0, "to": 50.0}
    assert audit_rows[2].details["audit_result"] == {"from": "pass", "to": "fail"}


# ------------------------------------------------------------ real concurrency

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

    t1 = threading.Thread(target=_worker, args=("pass", True))
    t2 = threading.Thread(target=_worker, args=("fail", False))
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
