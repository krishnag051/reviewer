"""Next Round (2026-08-27), Part 2 item 2: the new, OPTIONAL "prior
Treatment Plan" upload slot -- mirrors test_supporting_document.py's own
tests for the mandatory supporting-document field, but every case here
confirms the OPTIONAL half explicitly (no previous_tp attached is a
perfectly normal, successful upload, not a 422). Zero real Anthropic API
calls -- same technique as test_supporting_document.py (structured_form
mode's own required fields are supplied so nothing 422s before reaching the
assertions that matter, and no test here reaches run_upload_pipeline at
all except via already-established helpers).
"""
import io
import uuid

from pypdf import PdfWriter

from app.db.models import Upload
from tests.conftest import ROUND56_QA_FORM_DATA, login_headers, make_patient_version_upload


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_patient_and_version(client, headers) -> dict:
    ref = f"TP-TEST-prevtp-{uuid.uuid4().hex[:8]}"
    patient = client.post("/api/patients", json={"reference_id": ref, "name": "Previous TP Test Patient"}, headers=headers).json()
    return client.post(f"/api/patients/{patient['id']}/versions", json={}, headers=headers).json()


def test_upload_succeeds_with_no_previous_tp_attached(client, db_session, seeded_baseline):
    """The core "optional" behavior: an upload with NO previous_tp file at
    all must still succeed -- this is the common case (a first-ever
    patient genuinely has no prior TP), not an edge case that happens to
    be tolerated.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/api/versions/{version['id']}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    db_session.expire_all()
    persisted = db_session.get(Upload, uuid.UUID(upload_id))
    assert persisted.previous_tp_path is None
    assert persisted.has_previous_tp is False

    detail = client.get(f"/api/uploads/{upload_id}", headers=headers).json()
    assert detail["has_previous_tp"] is False


def test_upload_succeeds_with_previous_tp_attached_and_it_persists(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version = _create_patient_and_version(client, headers)

    resp = client.post(
        f"/api/versions/{version['id']}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
            "previous_tp": ("old-tp.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    upload_id = resp.json()["id"]

    db_session.expire_all()
    persisted = db_session.get(Upload, uuid.UUID(upload_id))
    assert persisted.previous_tp_path is not None
    assert persisted.has_previous_tp is True
    # Never the same blob as the TP's own file -- separate storage key.
    assert persisted.previous_tp_path != persisted.file_path

    detail = client.get(f"/api/uploads/{upload_id}", headers=headers).json()
    assert detail["has_previous_tp"] is True


def test_get_previous_tp_file_serves_the_real_bytes(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    content = _pdf_bytes()
    path = tmp_path / "old-tp.pdf"
    path.write_bytes(content)
    upload = make_patient_version_upload(db_session, status="ready", previous_tp_path=str(path))

    resp = client.get(f"/api/uploads/{upload.id}/previous-tp-file", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == content


def test_get_previous_tp_file_requires_auth(client, db_session, tmp_path, seeded_baseline):
    path = tmp_path / "old-tp.pdf"
    path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", previous_tp_path=str(path))

    resp = client.get(f"/api/uploads/{upload.id}/previous-tp-file")
    assert resp.status_code == 401


def test_get_previous_tp_file_404s_when_never_uploaded(client, db_session, seeded_baseline):
    """No separate status/code for "never uploaded" vs. "purged" -- both
    are plain 404s, same discipline as get_upload_supporting_file."""
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    upload = make_patient_version_upload(db_session, status="ready")

    resp = client.get(f"/api/uploads/{upload.id}/previous-tp-file", headers=headers)
    assert resp.status_code == 404


def test_get_previous_tp_file_404s_when_missing_on_disk(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    upload = make_patient_version_upload(db_session, status="ready", previous_tp_path="/no/such/path.pdf")

    resp = client.get(f"/api/uploads/{upload.id}/previous-tp-file", headers=headers)
    assert resp.status_code == 404


def test_get_previous_tp_file_404s_when_file_purged(client, db_session, tmp_path, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    path = tmp_path / "old-tp.pdf"
    path.write_bytes(_pdf_bytes())
    upload = make_patient_version_upload(db_session, status="ready", previous_tp_path=str(path), file_purged=True)

    resp = client.get(f"/api/uploads/{upload.id}/previous-tp-file", headers=headers)
    assert resp.status_code == 404
