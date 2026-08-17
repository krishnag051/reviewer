"""Round 86: proves the real-filename wiring end-to-end through the actual
running system -- create_upload -> Upload.original_filename ->
run_rule_checks -> agent_client.review_treatment_plan -> agent-making's real
QA-PPI-03 checker. Marked @pytest.mark.real_api because it lets the real
pipeline run (same convention as test_rule_result_overrides.py's own
_ready_upload real-pipeline test) -- confirmed to route through OpenRouter's
already-sanctioned free tier, not real Anthropic, since this environment's
backend/.env has no ANTHROPIC_API_KEY configured (agent-making's own
provider resolution defaults to OpenRouter whenever neither an explicit
model_override nor AGENT_LLM_PROVIDER=anthropic is set -- confirmed neither
is set anywhere in this environment before this test was written).
"""
import io
import uuid

import fitz
import pytest

from tests.conftest import ROUND56_QA_FORM_DATA, login_headers


def _pdf_with_text(text: str) -> bytes:
    """A real, single-page PDF with real embedded text -- unlike this
    suite's usual blank-page fixture, QA-PPI-03 (a deterministic text-
    pattern checker) needs real extractable text to have anything to find."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    buf = io.BytesIO(doc.tobytes())
    doc.close()
    return buf.getvalue()


def _ppi03_finding(client, headers, upload: dict) -> dict:
    detail = client.get(f"/api/uploads/{upload['id']}", headers=headers).json()
    assert detail["status"] == "ready", detail
    for rr in detail["rule_results"]:
        if rr["rule_code"] == "QA-PPI-03":
            return rr
    raise AssertionError("QA-PPI-03 not found in rule_results -- rule set drift?")


def _upload_tp(client, headers, version_id: str, tp_filename: str, tp_text: str) -> dict:
    return client.post(
        f"/api/versions/{version_id}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": (tp_filename, _pdf_with_text(tp_text), "application/pdf"),
            "supporting_document": ("supporting.pdf", _pdf_with_text("supporting doc"), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_with_text("session note"), "application/pdf"),
        },
        headers=headers,
    ).json()


def _new_patient_and_version(client, headers) -> str:
    ref = f"TP-R86-{uuid.uuid4().hex[:8]}"
    patient = client.post("/api/patients", json={"reference_id": ref, "name": "Round 86 Test"}, headers=headers).json()
    version = client.post(f"/api/patients/{patient['id']}/versions", json={}, headers=headers).json()
    return version["id"]


@pytest.mark.real_api
def test_real_upload_with_mismatched_filename_reports_uncertain(client, db_session, seeded_baseline):
    """THE real-evidence requirement: upload a real file whose document
    text names one patient and whose FILENAME names a close-but-different
    one -- confirms QA-PPI-03 now reports the mismatch as 'uncertain' with
    real evidence naming both the document's name and the actual uploaded
    filename, through the real create_upload -> run_rule_checks ->
    review_treatment_plan chain -- not the pre-Round-86 fallback (which
    would never see a real filename at all and would just report 'pass').
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version_id = _new_patient_and_version(client, headers)

    upload = _upload_tp(
        client, headers, version_id,
        tp_filename="Zohran Hossain TP.pdf",
        tp_text="Patient Name: Zohan Hossain Patient DOB: 01/01/2020 Patient Insurance: Medicaid\n",
    )
    finding = _ppi03_finding(client, headers, upload)

    assert finding["final_status"] == "uncertain", finding
    assert "Zohan" in finding["final_finding"] and "Zohran" in finding["final_finding"], finding


@pytest.mark.real_api
def test_real_upload_with_exact_match_filename_still_passes_cleanly(client, db_session, seeded_baseline):
    """No false positive: an exact-match filename must still pass, using
    the real upload path -- not the fallback, a REAL filename that happens
    to match."""
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version_id = _new_patient_and_version(client, headers)

    upload = _upload_tp(
        client, headers, version_id,
        tp_filename="Zohran Hossain TP.pdf",
        tp_text="Patient Name: Zohran Hossain Patient DOB: 01/01/2020 Patient Insurance: Medicaid\n",
    )
    finding = _ppi03_finding(client, headers, upload)
    assert finding["final_status"] == "pass", finding


@pytest.mark.real_api
def test_real_upload_with_innocuous_filename_variation_still_passes_cleanly(client, db_session, seeded_baseline):
    """No false positive on a real but innocuous filename difference (a
    date/version suffix) -- through the real upload path."""
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    version_id = _new_patient_and_version(client, headers)

    upload = _upload_tp(
        client, headers, version_id,
        tp_filename="Zohran_Hossain_2026-08-11_v2.pdf",
        tp_text="Patient Name: Zohran Hossain Patient DOB: 01/01/2020 Patient Insurance: Medicaid\n",
    )
    finding = _ppi03_finding(client, headers, upload)
    assert finding["final_status"] == "pass", finding
