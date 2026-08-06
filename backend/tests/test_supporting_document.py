"""Round 51: the mandatory second ("supporting document") file, required at
real upload creation, retained permanently like the TP's own file, served
via its own real endpoint. Zero real Anthropic API calls -- garbage TP-file
bytes guarantee parse_pdf fails before ever reaching review_treatment_plan
(same technique test_upload_file_and_wiring.py already established), and
the missing-field tests never even reach create_upload.
"""
import io
import uuid

from pypdf import PdfWriter

from app.db.models import Upload
from tests.conftest import login_headers, make_patient_version_upload


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_patient_and_version(client, headers) -> dict:
    ref = f"TP-TEST-supdoc-{uuid.uuid4().hex[:8]}"
    patient = client.post("/patients", json={"reference_id": ref, "name": "Supporting Doc Test Patient"}, headers=headers).json()
    return client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()


def test_upload_rejected_when_supporting_document_missing(client, seeded_baseline, document_mode):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/versions/{version['id']}/uploads",
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any(err.get("loc", [])[-1] == "supporting_document" for err in detail)


def test_upload_rejected_when_tp_file_missing_but_supporting_document_present(client, seeded_baseline, document_mode):
    """The requirement is symmetric -- both files are mandatory, not just the
    new one at the expense of the original.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/versions/{version['id']}/uploads",
        files={"supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert any(err.get("loc", [])[-1] == "file" for err in detail)


def test_upload_succeeds_with_both_files_and_both_persist(client, db_session, seeded_baseline, document_mode):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/versions/{version['id']}/uploads",
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("helping.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    db_session.expire_all()
    persisted = db_session.get(Upload, uuid.UUID(upload_id))
    assert persisted.file_path is not None
    assert persisted.supporting_document_path is not None
    assert persisted.file_path != persisted.supporting_document_path


def test_get_supporting_file_serves_the_real_bytes(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    content = _pdf_bytes()
    path = tmp_path / "supporting.pdf"
    path.write_bytes(content)
    upload = make_patient_version_upload(db_session, status="ready", supporting_document_path=str(path))

    resp = client.get(f"/uploads/{upload.id}/supporting-file", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == content


def test_get_supporting_file_requires_auth(client, db_session, tmp_path, seeded_baseline):
    path = tmp_path / "supporting.pdf"
    path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", supporting_document_path=str(path))

    resp = client.get(f"/uploads/{upload.id}/supporting-file")
    assert resp.status_code == 401


def test_get_supporting_file_404s_when_missing_on_disk(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    upload = make_patient_version_upload(db_session, status="ready", supporting_document_path="/no/such/path.pdf")

    resp = client.get(f"/uploads/{upload.id}/supporting-file", headers=headers)
    assert resp.status_code == 404


def test_get_supporting_file_404s_when_file_purged(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    path = tmp_path / "supporting.pdf"
    path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", supporting_document_path=str(path), file_purged=True)

    resp = client.get(f"/uploads/{upload.id}/supporting-file", headers=headers)
    assert resp.status_code == 404


def test_run_rule_checks_forwards_supporting_document_path_to_review_treatment_plan(
    client, db_session, monkeypatch, seeded_baseline, document_mode,
):
    """Round 53: confirms app/rule_engine/client.py's run_rule_checks actually
    forwards upload.supporting_document_path into review_treatment_plan's
    supporting_doc_path kwarg -- not just that the column is populated (that
    was Round 51's test above), but that the value actually reaches the
    pipeline call site. Mocks the exact seam client.py imports agent-making's
    real function into, so zero real Anthropic API calls are made.
    """
    seen_kwargs = {}

    def _fake_review_treatment_plan(pdf_path, *, supporting_doc_path=None, payor_override=None, plan_type_override=None, max_calls=None):
        seen_kwargs["pdf_path"] = pdf_path
        seen_kwargs["supporting_doc_path"] = supporting_doc_path
        return {
            "schema_version": 1, "status": "complete", "detected_payor": None, "detected_plan_type": None,
            "findings": [], "summary": {}, "usage": {"calls": 0}, "error": None,
        }

    monkeypatch.setattr("app.rule_engine.client.review_treatment_plan", _fake_review_treatment_plan)

    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    upload_resp = client.post(
        f"/versions/{version['id']}/uploads",
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("helping.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert upload_resp.status_code == 201, upload_resp.text
    upload_id = upload_resp.json()["id"]

    db_session.expire_all()
    persisted = db_session.get(Upload, uuid.UUID(upload_id))

    assert seen_kwargs["pdf_path"] == persisted.file_path
    assert seen_kwargs["supporting_doc_path"] == persisted.supporting_document_path
    assert seen_kwargs["supporting_doc_path"] is not None, "the mandatory second file's path must actually be forwarded"


def test_upload_rejected_for_existing_patient_flow_missing_supporting_document(client, seeded_baseline, document_mode):
    """Same requirement applies identically to the existing-patient (a
    second/third upload against the SAME version) flow -- not just the
    first upload on a brand-new patient.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    first = client.post(
        f"/versions/{version['id']}/uploads",
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("helping.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    second = client.post(
        f"/versions/{version['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert second.status_code == 422, second.text
