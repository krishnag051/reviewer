"""Round 56: structured intake Q&A + multi-file session notes upload,
behind the supporting_doc_mode feature flag. Zero real Anthropic API calls
-- every test here either never reaches the pipeline (garbage TP bytes
guarantee parse_pdf fails before review_treatment_plan, same technique
test_upload_file_and_wiring.py established) or checks a route that never
touches the pipeline at all (app-config, latest-intake-answers,
session-notes listing/serving).
"""
import io
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.models import SessionNoteFile, Upload, UploadIntakeAnswers
from tests.conftest import login_headers, make_patient_version_upload, unique_rule_code

VALID_QA = {
    "client_insurance": "Aetna",
    "bcba_name_credentials_npi": "Jane Smith, BCBA-D — NPI 1234567890",
    "authorization_dates": "01/15/2026 – 07/15/2026",
    "pos_schedule_vs_97153_hours": "Home, Mon-Fri 5-8pm, 15 hrs/week",
    "hours_requesting": "15 hrs/week",
}


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_patient_and_version(client, headers) -> dict:
    ref = f"TP-TEST-r56-{uuid.uuid4().hex[:8]}"
    patient = client.post("/patients", json={"reference_id": ref, "name": "Round 56 Test Patient"}, headers=headers).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
    return {"patient": patient, "version": version}


def _restore_mode(client, headers, mode: str) -> None:
    client.patch("/admin/app-config", json={"supporting_doc_mode": mode}, headers=headers)


# --------------------------------------------------------- app-config flag


def test_app_config_defaults_to_structured_form(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.get("/admin/app-config", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["supporting_doc_mode"] == "structured_form"


def test_app_config_readable_by_any_authenticated_role(client, seeded_baseline):
    headers = login_headers(client, "s.patel@brightpath-aba.com")  # role: user
    resp = client.get("/admin/app-config", headers=headers)
    assert resp.status_code == 200, resp.text


def test_app_config_patch_rejected_for_plain_user_role(client, seeded_baseline):
    headers = login_headers(client, "s.patel@brightpath-aba.com")  # role: user
    resp = client.patch("/admin/app-config", json={"supporting_doc_mode": "document"}, headers=headers)
    assert resp.status_code == 403


def test_app_config_patch_allowed_for_admin_and_persists(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    try:
        resp = client.patch("/admin/app-config", json={"supporting_doc_mode": "document"}, headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["supporting_doc_mode"] == "document"
        assert client.get("/admin/app-config", headers=headers).json()["supporting_doc_mode"] == "document"
    finally:
        _restore_mode(client, headers, "structured_form")


# --------------------------------------------- structured_form mode uploads


def test_structured_form_upload_rejects_missing_qa_field(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    incomplete = {k: v for k, v in VALID_QA.items() if k != "hours_requesting"}
    resp = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=incomplete,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf"), "session_notes": ("note.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert any(e.get("loc", [])[-1] == "hours_requesting" for e in resp.json()["detail"])


def test_structured_form_upload_rejects_missing_session_notes(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    resp = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=VALID_QA,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert any(e.get("loc", [])[-1] == "session_notes" for e in resp.json()["detail"])


def test_structured_form_upload_succeeds_and_persists_answers_and_notes(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=VALID_QA,
        files=[
            ("file", ("tp.pdf", _pdf_bytes(), "application/pdf")),
            ("session_notes", ("note1.pdf", _pdf_bytes(), "application/pdf")),
            ("session_notes", ("note2.pdf", _pdf_bytes(), "application/pdf")),
        ],
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    upload_id = uuid.UUID(resp.json()["id"])

    db_session.expire_all()
    answers = db_session.execute(select(UploadIntakeAnswers).where(UploadIntakeAnswers.upload_id == upload_id)).scalar_one()
    assert answers.client_insurance == VALID_QA["client_insurance"]
    assert answers.hours_requesting == VALID_QA["hours_requesting"]

    notes = list(db_session.execute(select(SessionNoteFile).where(SessionNoteFile.upload_id == upload_id)).scalars().all())
    assert {n.original_filename for n in notes} == {"note1.pdf", "note2.pdf"}
    upload = db_session.get(Upload, upload_id)
    assert upload.supporting_document_path is None, "structured_form mode must not populate the old document column"


def test_document_mode_still_works_unchanged_when_switched_back(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    try:
        client.patch("/admin/app-config", json={"supporting_doc_mode": "document"}, headers=headers)
        ctx = _create_patient_and_version(client, headers)

        # Missing supporting_document -> 422, same as pre-Round-56 behavior.
        missing_resp = client.post(
            f"/versions/{ctx['version']['id']}/uploads",
            files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf")},
            headers=headers,
        )
        assert missing_resp.status_code == 422, missing_resp.text
        assert any(e.get("loc", [])[-1] == "supporting_document" for e in missing_resp.json()["detail"])

        ok_resp = client.post(
            f"/versions/{ctx['version']['id']}/uploads",
            files={
                "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
                "supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf"),
            },
            headers=headers,
        )
        assert ok_resp.status_code == 201, ok_resp.text
        upload_id = uuid.UUID(ok_resp.json()["id"])
        db_session.expire_all()
        upload = db_session.get(Upload, upload_id)
        assert upload.supporting_document_path is not None
        answers = db_session.execute(select(UploadIntakeAnswers).where(UploadIntakeAnswers.upload_id == upload_id)).scalar_one_or_none()
        assert answers is None, "document mode must not create an intake_answers row"
    finally:
        _restore_mode(client, headers, "structured_form")


# ------------------------------------------------------- latest intake answers


def test_latest_intake_answers_null_before_any_structured_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    resp = client.get(f"/patients/{ctx['patient']['id']}/latest-intake-answers", headers=headers)
    assert resp.status_code == 200
    assert resp.json() is None


def test_latest_intake_answers_prefill_from_previous_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=VALID_QA,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf"), "session_notes": ("note.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    resp = client.get(f"/patients/{ctx['patient']['id']}/latest-intake-answers", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == VALID_QA


# ----------------------------------------------------------- session notes


def test_session_notes_list_and_serve(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    content = _pdf_bytes()
    upload_resp = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=VALID_QA,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf"), "session_notes": ("note.pdf", content, "application/pdf")},
        headers=headers,
    )
    upload_id = upload_resp.json()["id"]

    list_resp = client.get(f"/uploads/{upload_id}/session-notes", headers=headers)
    assert list_resp.status_code == 200
    page = list_resp.json()
    # Round 57, Item 2: the page's response now wraps the file list with
    # which patient this upload belongs to.
    assert page["patient_name"] == ctx["patient"]["name"]
    assert page["patient_reference_id"] == ctx["patient"]["reference_id"]
    notes = page["files"]
    assert len(notes) == 1
    assert notes[0]["original_filename"] == "note.pdf"

    file_resp = client.get(f"/uploads/{upload_id}/session-notes/{notes[0]['id']}", headers=headers)
    assert file_resp.status_code == 200
    assert file_resp.content == content


def test_session_notes_list_empty_for_document_mode_upload(client, db_session, seeded_baseline):
    upload = make_patient_version_upload(db_session, status="ready", file_path="/no/such.pdf", supporting_document_path="/no/such-supporting.pdf")
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.get(f"/uploads/{upload.id}/session-notes", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["files"] == []
    assert body["patient_name"] == "Test Patient"  # make_patient_version_upload's fixed patient name


def test_session_note_file_404s_when_upload_id_does_not_match(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    upload_resp = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        data=VALID_QA,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf"), "session_notes": ("note.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    upload_id = upload_resp.json()["id"]
    note_id = client.get(f"/uploads/{upload_id}/session-notes", headers=headers).json()["files"][0]["id"]

    other_upload = make_patient_version_upload(db_session, status="ready")
    resp = client.get(f"/uploads/{other_upload.id}/session-notes/{note_id}", headers=headers)
    assert resp.status_code == 404


def test_session_notes_requires_auth(client, seeded_baseline):
    resp = client.get(f"/uploads/{uuid.uuid4()}/session-notes")
    assert resp.status_code == 401


# ----------------------------------------------------------- rule flagging


def test_rules_response_includes_session_notes_only_and_tp_section_fields(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.get("/rules", headers=headers)
    assert resp.status_code == 200
    rules_by_code = {r["rule_code"]: r for r in resp.json()}
    for code in ("QA-RPT-03", "QA-ACF-02", "QA-ACF-08"):
        assert code in rules_by_code, f"{code} missing from seeded rules -- run scripts/seed.py"

    # These are flagged by scripts/seed_round56_session_notes_only_rules.py
    # against the DEV database -- the test database is freshly migrated and
    # seeded independently (seeded_baseline), so it starts with the schema
    # default (false/null) for every rule, including these 3. This test
    # verifies the FIELDS are present and correctly typed/round-tripped
    # through the API, not that the one-time dev-data flagging script ran
    # against this disposable test DB too.
    for code in ("QA-RPT-03", "QA-ACF-02", "QA-ACF-08"):
        assert rules_by_code[code]["session_notes_only"] is False
        assert rules_by_code[code]["tp_section"] is None


def _create_test_rule(client, headers) -> dict:
    """A fresh, disposable rule -- NOT one of the 120 real seeded rules.
    Deliberately not mutating a real rule (e.g. QA-ACF-02) here: edit_rule
    permanently bumps current_version and adds a rule_version_history row
    with no way to undo that (versioning is append-only by design, per
    CLAUDE.md) -- doing that to a shared, session-scoped seeded rule would
    permanently change state other tests in this same session assume is
    pristine (e.g. test_seed.py's "every rule has exactly one history row
    at version 1" invariant check)."""
    resp = client.post(
        "/rules",
        json={
            "rule_code": unique_rule_code("R-TEST-r56"), "category": "Test", "question_set": "Test",
            "question_text": "Disposable test rule for Round 56 flagging coverage.", "rule_type": "structural",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_rule_update_can_set_session_notes_only_and_tp_section(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    target = _create_test_rule(client, headers)

    resp = client.patch(
        f"/rules/{target['id']}",
        json={"session_notes_only": True, "tp_section": "Assessment of Current Functioning"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["session_notes_only"] is True
    assert body["tp_section"] == "Assessment of Current Functioning"
    assert body["current_version"] == target["current_version"] + 1


def test_rule_update_rejected_for_non_admin(client, seeded_baseline):
    admin_headers = login_headers(client, "m.chen@brightpath-aba.com")
    target = _create_test_rule(client, admin_headers)

    user_headers = login_headers(client, "s.patel@brightpath-aba.com")
    resp = client.patch(f"/rules/{target['id']}", json={"session_notes_only": True}, headers=user_headers)
    assert resp.status_code == 403
