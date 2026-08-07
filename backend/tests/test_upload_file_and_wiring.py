"""Round 42: (1) GET /uploads/{id}/file — serving the stored PDF blob for the
real PDF pane, and (2) Stage 2 upload-creation wiring verified WITHOUT any
real Anthropic API call.

Zero real Anthropic API calls in this file:
- test_get_upload_file_* build the Upload row directly via
  make_patient_version_upload (no pipeline run at all — same helper step 5's
  job tests use to avoid a real pipeline run).
- test_create_upload_route_reaches_real_pipeline_wiring_with_mocked_agent_call
  monkeypatches app.rule_engine.client.review_treatment_plan itself (the
  exact seam client.py imports agent-making's real function into) so
  POST /versions/{id}/uploads exercises its real HTTP route, real
  create_upload service, real background task, real parse_pdf, and real
  run_rule_checks translation logic end to end — but the one call that
  would hit the network never reaches agent-making's real implementation.
"""
import io
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.agent_client import ReviewResult, UsageInfo
from app.db.models import Upload
from tests.conftest import ROUND56_QA_FORM_DATA, login_headers, make_patient_version_upload


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --------------------------------------------------------- GET .../file


def test_get_upload_file_serves_the_real_pdf_bytes(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    content = _pdf_bytes()
    pdf_path = tmp_path / "stored.pdf"
    pdf_path.write_bytes(content)

    upload = make_patient_version_upload(db_session, status="ready", file_path=str(pdf_path))

    resp = client.get(f"/uploads/{upload.id}/file", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == content


def test_get_upload_file_requires_auth(client, db_session, tmp_path, seeded_baseline):
    pdf_path = tmp_path / "stored.pdf"
    pdf_path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", file_path=str(pdf_path))

    resp = client.get(f"/uploads/{upload.id}/file")
    assert resp.status_code == 401


def test_get_upload_file_404s_when_purged(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    pdf_path = tmp_path / "stored.pdf"
    pdf_path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", file_path=str(pdf_path), file_purged=True)

    resp = client.get(f"/uploads/{upload.id}/file", headers=headers)
    assert resp.status_code == 404


def test_get_upload_file_404s_when_missing_on_disk(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    upload = make_patient_version_upload(db_session, status="ready", file_path="/no/such/path/on/disk.pdf")

    resp = client.get(f"/uploads/{upload.id}/file", headers=headers)
    assert resp.status_code == 404


def test_get_upload_file_404s_for_unknown_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.get(f"/uploads/{uuid.uuid4()}/file", headers=headers)
    assert resp.status_code == 404


# ------------------------------------------ Stage 2 wiring, agent mocked


def test_create_upload_route_reaches_real_pipeline_wiring_with_mocked_agent_call(
    client, db_session, monkeypatch, seeded_baseline,
):
    """Proves the real HTTP route -> create_upload -> background task ->
    run_upload_pipeline -> run_rule_checks wiring is correct end to end,
    without ever calling agent-making's real review_treatment_plan (and
    therefore without any real Anthropic API call). The mocked seam
    returns a "complete" ReviewResult with zero findings -- exercising the
    real _drafts_from_review_result fallback path (every pinned rule comes
    back "not_checkable"), which is exactly the real code path a genuine
    agent response with unmatched rule_codes would also hit.

    Round 67: this upload's fixture attaches a `session_notes` file (a
    real requirement of the structured-form upload shape, not because this
    test is ABOUT session notes) -- since Round 67 wired
    app.rule_engine.client.review_session_notes into run_rule_checks for
    ANY upload with session-note files attached, that real seam is ALSO
    mocked here (to `[]`, "no session notes found anything") so this
    test's own "every pinned rule comes back not_checkable" assertion
    stays true to what it's actually testing (the general wiring, not
    session-notes-specific behavior) -- see
    test_round67_session_notes_wiring.py for the real, dedicated
    session-notes proof.
    """
    def _fake_review_treatment_plan(
        pdf_path, *, supporting_doc_path=None, payor_override=None, plan_type_override=None, max_calls=None,
    ):
        assert pdf_path, "wiring must pass the upload's real file_path through"
        # Round 66: app.rule_engine.client.review_treatment_plan is now
        # app.agent_client.review_treatment_plan under the hood, returning
        # the typed ReviewResult contract, not a raw dict.
        return ReviewResult(
            schema_version="1.0",
            status="complete",
            detected_payor=None,
            detected_plan_type=None,
            supporting_doc_extraction=None,
            results=[],
            bcba_fix_rule_ids=[],
            facilitator_assign_rule_ids=[],
            counts_by_result={},
            usage=UsageInfo(api_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0),
            error=None,
        )

    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan", _fake_review_treatment_plan,
    )
    monkeypatch.setattr("app.rule_engine.client.review_session_notes", lambda *a, **k: [])

    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient_resp = client.post(
        "/patients",
        json={"reference_id": f"TP-TEST-{uuid.uuid4().hex[:8]}", "name": "Wiring Test Patient", "payor": "Aetna"},
        headers=headers,
    )
    assert patient_resp.status_code == 201, patient_resp.text
    patient = patient_resp.json()

    version_resp = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers)
    assert version_resp.status_code == 201, version_resp.text
    version = version_resp.json()

    upload_resp = client.post(
        f"/versions/{version['id']}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert upload_resp.status_code == 201, upload_resp.text
    upload_out = upload_resp.json()

    detail_resp = client.get(f"/uploads/{upload_out['id']}", headers=headers)
    assert detail_resp.status_code == 200
    body = detail_resp.json()
    assert body["status"] == "ready", body
    assert body["rules_snapshot_id"] is not None
    assert len(body["rule_results"]) > 0, "every pinned rule should have produced a rule_result row"
    assert all(r["final_status"] == "not_checkable" for r in body["rule_results"])

    db_session.expire_all()
    persisted = db_session.get(Upload, uuid.UUID(upload_out["id"]))
    assert persisted.status == "ready"
    assert persisted.file_path is not None
