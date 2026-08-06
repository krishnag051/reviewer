"""Round 57: two small UI fixes, both read-only/data-display, zero real
Anthropic API calls needed or made anywhere in this file.

Item 1: GET /uploads/:id (UploadDetailOut) gained `intake_answers` --
reusing the SAME upload.intake_answers relationship Round 56's prefill
endpoint already read, additive on an EXISTING, already-fetched-by-the-
review-page route. None for a document-mode upload; populated, and
correctly SPECIFIC TO THAT UPLOAD (not some other upload's answers, and
not necessarily the patient's most recent answers), for a structured_form
upload.

Item 2: GET /uploads/:id/session-notes now wraps the file list with which
patient the upload belongs to.
"""
import io
import uuid

from pypdf import PdfWriter

from tests.conftest import ROUND56_QA_FORM_DATA, login_headers, make_patient_version_upload


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_patient_and_version(client, headers, name="Round 57 Test Patient") -> dict:
    ref = f"TP-TEST-r57-{uuid.uuid4().hex[:8]}"
    patient = client.post("/patients", json={"reference_id": ref, "name": name}, headers=headers).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
    return {"patient": patient, "version": version}


def _structured_upload(client, headers, version_id, qa_overrides=None) -> dict:
    data = {**ROUND56_QA_FORM_DATA, **(qa_overrides or {})}
    resp = client.post(
        f"/versions/{version_id}/uploads",
        data=data,
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf"), "session_notes": ("note.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --------------------------------------------------- Item 1: intake_answers


def test_upload_detail_includes_intake_answers_for_structured_form_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)
    upload = _structured_upload(client, headers, ctx["version"]["id"])

    detail = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    assert detail["intake_answers"] == ROUND56_QA_FORM_DATA


def test_upload_detail_intake_answers_null_for_document_mode_upload(client, db_session, seeded_baseline):
    upload = make_patient_version_upload(db_session, status="ready", file_path="/no/such.pdf", supporting_document_path="/no/such-supporting.pdf")
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    detail = client.get(f"/uploads/{upload.id}", headers=headers).json()
    assert detail["intake_answers"] is None


def test_intake_answers_are_specific_to_each_upload_not_shared_across_them(client, seeded_baseline):
    """The exact scenario Round 57's own verification section calls out:
    a second upload's DIFFERENT answers must not bleed into the first
    upload's own detail response (each upload keeps its own snapshot, per
    Round 56's design -- not a shared, overwritten patient-level record)."""
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers)

    upload1 = _structured_upload(client, headers, ctx["version"]["id"], {"hours_requesting": "10 hrs/week"})

    # Second upload needs its OWN version (existing-patient flow starts a
    # new draft once the current one either finalizes or -- simpler for
    # this test -- just post another upload to the SAME still-in-progress
    # version, which the backend allows for additional draft attempts).
    upload2 = _structured_upload(client, headers, ctx["version"]["id"], {"hours_requesting": "25 hrs/week"})

    detail1 = client.get(f"/uploads/{upload1['id']}", headers=headers).json()
    detail2 = client.get(f"/uploads/{upload2['id']}", headers=headers).json()

    assert detail1["intake_answers"]["hours_requesting"] == "10 hrs/week"
    assert detail2["intake_answers"]["hours_requesting"] == "25 hrs/week"


# --------------------------------------------------- Item 2: patient name


def test_session_notes_page_shows_the_correct_patient(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _create_patient_and_version(client, headers, name="Jordan Nakamura")
    upload = _structured_upload(client, headers, ctx["version"]["id"])

    page = client.get(f"/uploads/{upload['id']}/session-notes", headers=headers).json()
    assert page["patient_name"] == "Jordan Nakamura"
    assert page["patient_reference_id"] == ctx["patient"]["reference_id"]


def test_session_notes_page_patient_name_distinguishes_two_different_patients(client, seeded_baseline):
    """Not just 'a name shows up' -- the RIGHT name for THIS upload's own
    patient, not some other patient's."""
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx_a = _create_patient_and_version(client, headers, name="Patient A")
    ctx_b = _create_patient_and_version(client, headers, name="Patient B")
    upload_a = _structured_upload(client, headers, ctx_a["version"]["id"])
    upload_b = _structured_upload(client, headers, ctx_b["version"]["id"])

    page_a = client.get(f"/uploads/{upload_a['id']}/session-notes", headers=headers).json()
    page_b = client.get(f"/uploads/{upload_b['id']}/session-notes", headers=headers).json()
    assert page_a["patient_name"] == "Patient A"
    assert page_b["patient_name"] == "Patient B"
