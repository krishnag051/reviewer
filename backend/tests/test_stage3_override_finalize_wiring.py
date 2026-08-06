"""Round 43, Stage 3: real click-through-equivalent proof that the frontend's
new override/finalize wiring reaches the exact routes/service functions
Round 40 built and race-tested (`app/services/rule_results.py::override_rule_result`,
`app/services/finalize.py::finalize_upload`) -- not a separate or duplicate
code path.

Zero real Anthropic API calls: the upload/rule_results here are built
directly via make_patient_version_upload + a manual RuleResult insert (same
technique as Round 42's test_upload_file_and_wiring.py), never through the
real pipeline.
"""
import uuid

from sqlalchemy import select

from app.db.models import RuleResult, Upload, Version
from tests.conftest import login_headers, make_patient_version_upload


def _add_rule_result(session, upload, rule, status: str = "fail") -> RuleResult:
    rr = RuleResult(
        upload_id=upload.id,
        rule_id=rule.id,
        rule_version_used=1,
        model_status=status,
        model_finding=f"Stage 3 wiring test finding ({status}).",
        model_pages=[1],
        final_status=status,
        final_finding=f"Stage 3 wiring test finding ({status}).",
        final_pages=[1],
    )
    session.add(rr)
    session.commit()
    session.refresh(rr)
    return rr


def _some_active_rules(session, count: int):
    from app.db.models import Rule

    return list(session.execute(select(Rule).where(Rule.active.is_(True)).limit(count)).scalars().all())


def test_override_then_finalize_then_override_409_via_the_real_hardened_routes(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rules = _some_active_rules(db_session, 2)
    assert len(rules) == 2

    upload = make_patient_version_upload(db_session, status="ready")
    rr_fail = _add_rule_result(db_session, upload, rules[0], status="fail")
    rr_pass = _add_rule_result(db_session, upload, rules[1], status="pass")

    version = db_session.get(Version, upload.version_id)
    from app.db.models import Patient
    patient = db_session.get(Patient, version.patient_id)

    # --- 1. real override on a real draft, through the real PATCH route ---
    get_resp = client.get(f"/uploads/{upload.id}", headers=headers)
    assert get_resp.status_code == 200
    live = next(r for r in get_resp.json()["rule_results"] if r["id"] == str(rr_fail.id))
    assert live["final_status"] == "fail"

    override_resp = client.patch(
        f"/rule_results/{rr_fail.id}",
        json={"updated_at": live["updated_at"], "final_status": "pass"},
        headers=headers,
    )
    assert override_resp.status_code == 200, override_resp.text
    overridden = override_resp.json()
    assert overridden["final_status"] == "pass"
    assert overridden["is_overridden"] is True

    db_session.expire_all()
    persisted = db_session.get(RuleResult, rr_fail.id)
    assert persisted.final_status == "pass"
    assert persisted.model_status == "fail", "model_status is written once by the pipeline and never touched by override"
    assert persisted.is_overridden is True

    # --- 2. real finalize, through the real POST .../finalize route ---
    finalize_resp = client.post(
        f"/uploads/{upload.id}/finalize",
        json={"reference_id": patient.reference_id},
        headers=headers,
    )
    assert finalize_resp.status_code == 200, finalize_resp.text
    finalized = finalize_resp.json()
    assert finalized["is_final"] is True

    db_session.expire_all()
    persisted_version = db_session.get(Version, version.id)
    assert persisted_version.status == "finalized"
    # score = pass/(pass+fail) with both rule_results now "pass" (rr_fail was
    # overridden to pass, rr_pass was already pass) -- proves finalize's
    # compute_score read the FINAL layer (post-override), not the model layer.
    assert float(persisted_version.score) == 100.0
    assert persisted_version.audit_result == "pass"
    assert persisted_version.final_upload_id == upload.id

    # --- 3. override-after-finalize is rejected for real, 409, nothing applied ---
    get_resp_2 = client.get(f"/uploads/{upload.id}", headers=headers)
    live_2 = next(r for r in get_resp_2.json()["rule_results"] if r["id"] == str(rr_pass.id))

    blocked_resp = client.patch(
        f"/rule_results/{rr_pass.id}",
        json={"updated_at": live_2["updated_at"], "final_status": "fail"},
        headers=headers,
    )
    assert blocked_resp.status_code == 409, blocked_resp.text
    body = blocked_resp.json()
    assert body["detail"]["error"] == "upload_already_finalized"
    assert "message" in body["detail"] and body["detail"]["message"]

    db_session.expire_all()
    still_pass = db_session.get(RuleResult, rr_pass.id)
    assert still_pass.final_status == "pass", "the rejected override must not have touched the row"

    # Version's score/audit_result must be exactly what finalize computed --
    # untouched by the rejected override attempt (nothing left to recompute
    # after finalize, per the locked invariant).
    db_session.expire_all()
    persisted_version_after = db_session.get(Version, version.id)
    assert float(persisted_version_after.score) == 100.0
    assert persisted_version_after.audit_result == "pass"


def test_finalize_blocked_while_uncertain_result_remains(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rules = _some_active_rules(db_session, 1)
    upload = make_patient_version_upload(db_session, status="ready")
    _add_rule_result(db_session, upload, rules[0], status="uncertain")

    version = db_session.get(Version, upload.version_id)
    from app.db.models import Patient
    patient = db_session.get(Patient, version.patient_id)

    resp = client.post(
        f"/uploads/{upload.id}/finalize",
        json={"reference_id": patient.reference_id},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "uncertain_results_remain"

    db_session.expire_all()
    persisted_upload = db_session.get(Upload, upload.id)
    assert persisted_upload.is_final is False


def test_finalize_rejects_reference_id_mismatch(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rules = _some_active_rules(db_session, 1)
    upload = make_patient_version_upload(db_session, status="ready")
    _add_rule_result(db_session, upload, rules[0], status="pass")

    resp = client.post(
        f"/uploads/{upload.id}/finalize",
        json={"reference_id": f"WRONG-{uuid.uuid4().hex[:8]}"},
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "reference_id_mismatch"

    db_session.expire_all()
    persisted_upload = db_session.get(Upload, upload.id)
    assert persisted_upload.is_final is False
