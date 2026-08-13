"""Step 9 regression coverage: GET /uploads/:id/diff and
POST /versions/:id/correction-email (generation + persistence, no sending).
"""
import io
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.models import (
    AuditLog, GeneratedEmail, Patient, Rule, RuleResult, RuleSyncState, SessionNoteFile, Upload,
    UploadIntakeAnswers, Version,
)
from tests.conftest import ROUND56_QA_FORM_DATA, login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _ready_upload(client, headers, version_id: str | None = None, patient=None) -> dict:
    if version_id is None:
        ref = f"TP-TEST-{uuid.uuid4().hex[:8]}"
        patient = client.post(
            "/patients", json={"reference_id": ref, "name": "Test Patient"}, headers=headers
        ).json()
        version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
        version_id = version["id"]
    upload = client.post(
        f"/versions/{version_id}/uploads",
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
    return {"patient": patient, "version_id": version_id, "upload": detail}


def _override(client, headers, rr: dict, **fields):
    return client.patch(
        f"/rule_results/{rr['id']}", json={"updated_at": rr["updated_at"], **fields}, headers=headers
    )


# Fix Round, item 3 (2026-08-12): every new test below is about the real-
# send / statuses-filtering feature itself, not the pre-existing rule-
# checking pipeline -- so, same discipline as
# test_rule_result_overrides.py's own `_direct_ready_upload_with_one_rule_
# result` (see that function's own docstring), these build patient ->
# version -> upload -> rule_results DIRECTLY via ORM, bypassing
# create_upload/run_upload_pipeline and the real rule-checking agent
# entirely. NOTE: `_ready_upload` above (the pre-existing helper this
# file's OLDER tests use) is currently broken for an unrelated, PRE-
# EXISTING reason -- confirmed via `git stash` that it fails identically
# with every Fix Round change reverted: the real-API-blocking guardrail
# (tests/conftest.py::_block_real_api_calls) correctly blocks
# run_upload_pipeline's real call, and upload_pipeline.py's own except
# clause turns that into upload.status="error", so _ready_upload's own
# `assert detail["status"] == "ready"` fails every time it's used,
# independent of anything in this round. Out of scope to fix here --
# flagged, not silently routed around.
def _direct_ready_upload(
    db_session, seeded_baseline, tmp_path, *,
    statuses: dict[str, str] | None = None,
    with_attachments: bool = False,
) -> dict:
    """`statuses`: {marker_text: final_status} -- one real rule_result per
    entry, each with a distinguishable marker string in its finding text
    so a test can assert exactly which ones ended up in an email body.
    `with_attachments`: when True, writes real small PDF/text files to
    disk and points file_path/supporting_document_path/session note/
    intake answers at them, so _gather_attachments has real bytes to
    read -- exactly mirroring what a real upload's row shapes look like.
    """
    statuses = statuses or {}
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
    if with_attachments:
        tp_path = tmp_path / "tp.pdf"
        tp_path.write_bytes(_pdf_bytes())
        upload.file_path = str(tp_path)
        upload.original_filename = "Real Treatment Plan.pdf"
        supporting_path = tmp_path / "supporting.pdf"
        supporting_path.write_bytes(_pdf_bytes())
        upload.supporting_document_path = str(supporting_path)
    db_session.add(upload)
    db_session.flush()

    if with_attachments:
        note_path = tmp_path / "session-note.pdf"
        note_path.write_bytes(_pdf_bytes())
        db_session.add(SessionNoteFile(
            upload_id=upload.id, file_path=str(note_path), original_filename="Session Note 1.pdf",
        ))
        db_session.add(UploadIntakeAnswers(
            upload_id=upload.id, client_insurance="Aetna", bcba_name_credentials_npi="J. Smith, BCBA, 123",
            authorization_dates="1/1/26-3/1/26", pos_schedule_vs_97153_hours="Home, 10hr/wk",
            hours_requesting="10 hrs/wk 97153",
        ))

    rules = db_session.execute(select(Rule)).scalars().all()
    for i, (marker, final_status) in enumerate(statuses.items()):
        db_session.add(RuleResult(
            upload_id=upload.id, rule_id=rules[i].id, rule_version_used=1,
            model_status=final_status, model_finding=marker, model_pages=[],
            final_status=final_status, final_finding=marker, final_pages=[],
        ))
    db_session.commit()
    db_session.refresh(patient)
    db_session.refresh(version)
    db_session.refresh(upload)
    return {"patient": patient, "version": version, "upload": upload}


# ------------------------------------------------------------------- diff

def test_diff_buckets_fixed_newly_broken_still_failing_unchanged(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    results1 = ctx1["upload"]["rule_results"]

    # Set up upload 1 (the "against" upload): distinct final_status per row.
    r_fail_becomes_pass = results1[0]
    r_pass_stays_pass = results1[1]
    r_pass_becomes_fail = results1[2]
    r_fail_stays_fail = results1[3]

    _override(client, headers, r_fail_becomes_pass, final_status="fail")
    _override(client, headers, r_pass_stays_pass, final_status="pass")
    _override(client, headers, r_pass_becomes_fail, final_status="pass")
    _override(client, headers, r_fail_stays_fail, final_status="uncertain")

    # Upload 2, same version — override the SAME rule_ids to the "after" state.
    ctx2 = _ready_upload(client, headers, version_id=ctx1["version_id"])
    results2 = {r["rule_id"]: r for r in ctx2["upload"]["rule_results"]}

    _override(client, headers, results2[r_fail_becomes_pass["rule_id"]], final_status="pass")
    _override(client, headers, results2[r_pass_stays_pass["rule_id"]], final_status="pass")
    _override(client, headers, results2[r_pass_becomes_fail["rule_id"]], final_status="fail")
    _override(client, headers, results2[r_fail_stays_fail["rule_id"]], final_status="fail")

    resp = client.get(
        f"/uploads/{ctx2['upload']['id']}/diff", params={"against": ctx1["upload"]["id"]}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()

    fixed_ids = {e["rule_id"] for e in body["fixed"]}
    newly_broken_ids = {e["rule_id"] for e in body["newly_broken"]}
    still_failing_ids = {e["rule_id"] for e in body["still_failing"]}
    unchanged_pass_ids = {e["rule_id"] for e in body["unchanged_pass"]}

    assert r_fail_becomes_pass["rule_id"] in fixed_ids
    assert r_pass_becomes_fail["rule_id"] in newly_broken_ids
    assert r_fail_stays_fail["rule_id"] in still_failing_ids
    assert r_pass_stays_pass["rule_id"] in unchanged_pass_ids


def test_diff_rules_changed_bucket_for_snapshot_drift(client, db_session, seeded_baseline):
    """Simulates snapshot drift by deleting one rule_result from the
    'against' upload's set — that rule_id then only exists on 'this' side.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    ctx2 = _ready_upload(client, headers, version_id=ctx1["version_id"])

    from app.db.models import RuleResult
    victim_rule_id = uuid.UUID(ctx1["upload"]["rule_results"][0]["rule_id"])
    victim = db_session.execute(
        select(RuleResult).where(
            RuleResult.upload_id == uuid.UUID(ctx1["upload"]["id"]), RuleResult.rule_id == victim_rule_id
        )
    ).scalar_one()
    db_session.delete(victim)
    db_session.commit()

    resp = client.get(
        f"/uploads/{ctx2['upload']['id']}/diff", params={"against": ctx1["upload"]["id"]}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    rules_changed_ids = {e["rule_id"] for e in body["rules_changed"]}
    assert str(victim_rule_id) in rules_changed_ids
    entry = next(e for e in body["rules_changed"] if e["rule_id"] == str(victim_rule_id))
    assert entry["against_status"] is None
    assert entry["this_status"] is not None


def test_diff_was_overridden_previously(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    rr1 = ctx1["upload"]["rule_results"][0]
    _override(client, headers, rr1, final_status="pass")  # sets is_overridden=True on upload 1's row

    ctx2 = _ready_upload(client, headers, version_id=ctx1["version_id"])
    rr2 = next(r for r in ctx2["upload"]["rule_results"] if r["rule_id"] == rr1["rule_id"])
    # Leave rr2 untouched (is_overridden=False on THIS upload).

    resp = client.get(
        f"/uploads/{ctx2['upload']['id']}/diff", params={"against": ctx1["upload"]["id"]}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    all_entries = (
        body["fixed"] + body["newly_broken"] + body["still_failing"] + body["unchanged_pass"] + body["other"]
    )
    entry = next(e for e in all_entries if e["rule_id"] == rr1["rule_id"])
    assert entry["was_overridden_previously"] is True


def test_diff_rejects_uploads_from_different_versions(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    ctx2 = _ready_upload(client, headers)  # different patient/version entirely

    resp = client.get(
        f"/uploads/{ctx1['upload']['id']}/diff", params={"against": ctx2["upload"]["id"]}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "different_version"


def test_diff_rejects_when_either_upload_voided(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    ctx2 = _ready_upload(client, headers, version_id=ctx1["version_id"])

    client.post(f"/uploads/{ctx1['upload']['id']}/void", json={"reason": "test void"}, headers=headers)

    resp = client.get(
        f"/uploads/{ctx2['upload']['id']}/diff", params={"against": ctx1["upload"]["id"]}, headers=headers
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "voided_upload"


# ---------------------------------------------------------- correction email

def test_generate_correction_email_persists_with_routing(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]
    _override(client, headers, rr, final_status="fail", final_finding="Missing BCBA signature")

    resp = client.post(
        f"/versions/{ctx['version_id']}/correction-email",
        json={"routed_to": "bcba", "statuses": ["fail"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["routed_to"] == "bcba"
    assert body["routed_by"] is not None
    assert body["routed_at"] is not None
    assert ctx["patient"]["reference_id"] in body["subject"]
    assert "Missing BCBA signature" in body["body"]

    row = db_session.get(GeneratedEmail, uuid.UUID(body["id"]))
    assert row is not None
    assert row.routed_to == "bcba"
    assert row.version_id == uuid.UUID(ctx["version_id"])
    assert row.upload_id == uuid.UUID(ctx["upload"]["id"])

    audit_rows = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == uuid.UUID(ctx["version_id"]))
    ).scalars().all()
    assert any("Generated correction email" in a.action for a in audit_rows)


def test_generate_correction_email_defaults_to_latest_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    ctx2 = _ready_upload(client, headers, version_id=ctx1["version_id"])

    resp = client.post(
        f"/versions/{ctx1['version_id']}/correction-email",
        json={"routed_to": "qa", "statuses": ["pass", "fail", "uncertain", "na", "not_checkable"]},
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["upload_id"] == ctx2["upload"]["id"], "should default to the latest (highest-numbered) upload"


def test_generate_correction_email_explicit_upload_id(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    _ready_upload(client, headers, version_id=ctx1["version_id"])

    resp = client.post(
        f"/versions/{ctx1['version_id']}/correction-email",
        json={
            "routed_to": "clinical_director", "upload_id": ctx1["upload"]["id"],
            "statuses": ["pass", "fail", "uncertain", "na", "not_checkable"],
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["upload_id"] == ctx1["upload"]["id"]


def test_generate_correction_email_rejects_upload_from_other_version(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx1 = _ready_upload(client, headers)
    ctx2 = _ready_upload(client, headers)  # different version entirely

    resp = client.post(
        f"/versions/{ctx1['version_id']}/correction-email",
        json={"routed_to": "coordinator", "upload_id": ctx2["upload"]["id"], "statuses": ["fail"]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_upload"


def test_generate_correction_email_requires_at_least_one_status(client, db_session, seeded_baseline, tmp_path):
    ctx = _direct_ready_upload(db_session, seeded_baseline, tmp_path)
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.post(
        f"/versions/{ctx['version'].id}/correction-email",
        json={"routed_to": "bcba", "statuses": []},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "no_statuses_selected"


def test_generate_correction_email_only_includes_checked_statuses_in_fixed_order(
    client, db_session, seeded_baseline, tmp_path,
):
    """Fix Round, item 3: body groups by STATUS in the fixed Pass, Fail,
    Uncertain, N/A, Not checkable order -- never interleaved, and never
    includes a status that wasn't checked, regardless of what real results
    exist on the upload."""
    ctx = _direct_ready_upload(db_session, seeded_baseline, tmp_path, statuses={
        "FAIL-MARKER-ONE": "fail",
        "UNCERTAIN-MARKER-TWO": "uncertain",
        "NA-MARKER-THREE": "na",
    })
    headers = login_headers(client, "m.chen@brightpath-aba.com")

    resp = client.post(
        f"/versions/{ctx['version'].id}/correction-email",
        json={"routed_to": "bcba", "statuses": ["fail", "na"]},  # deliberately NOT uncertain
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()["body"]
    assert "FAIL-MARKER-ONE" in body
    assert "NA-MARKER-THREE" in body
    assert "UNCERTAIN-MARKER-TWO" not in body  # not checked -- must not leak in
    # Fail's header must appear before N/A's, matching STATUS_ORDER.
    assert body.index("Fail (") < body.index("N/A (")
    assert resp.json()["statuses"] == ["fail", "na"]


def test_generate_correction_email_header_identifies_patient_tp_upload(
    client, db_session, seeded_baseline, tmp_path,
):
    """The email's own header line must identify patient/version/upload --
    per this round's explicit request, not just a raw results dump."""
    ctx = _direct_ready_upload(db_session, seeded_baseline, tmp_path, statuses={"X": "fail"})
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    resp = client.post(
        f"/versions/{ctx['version'].id}/correction-email",
        json={"routed_to": "bcba", "statuses": ["fail"]},
        headers=headers,
    )
    body = resp.json()["body"]
    assert ctx["patient"].name in body
    assert ctx["patient"].reference_id in body
    assert f"Version {ctx['version'].version_number}" in body
    assert f"U{ctx['upload'].upload_number}" in body
    assert "Please review" in body  # closing line present


# --------------------------------------------------------------- real send

def test_send_endpoint_exists_and_uses_real_smtplib(client):
    """Fix Round, item 3 (2026-08-12): REPLACES the old, now-obsolete
    test_no_send_capability_exists -- this system now has a real send path,
    by explicit request. Confirms the endpoint exists and that the mailer
    module genuinely uses stdlib smtplib (not a mock/fake), rather than
    just trusting a docstring."""
    schema = client.app.openapi()
    assert any("/send" in path.lower() for path in schema["paths"]), "no /send endpoint found"

    import re

    import app.services.mailer as mod
    source = open(mod.__file__, encoding="utf-8").read()
    assert re.search(r"\bimport smtplib\b", source), "mailer.py should use stdlib smtplib"
    assert re.search(r"\.send_message\(", source), "mailer.py should call smtplib's real send API"


def test_send_without_smtp_configured_fails_clearly_not_silently(
    client, db_session, seeded_baseline, tmp_path, monkeypatch,
):
    """No real network call happens in this test (settings.smtp_host is
    unset in the test environment by default) -- confirms that missing
    config produces a clear 502 with a real error message, never a
    silent "success" for a message that was never actually sent."""
    from app.config import settings
    monkeypatch.setattr(settings, "smtp_host", None)

    ctx = _direct_ready_upload(db_session, seeded_baseline, tmp_path, statuses={"X": "pass"})
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    gen = client.post(
        f"/versions/{ctx['version'].id}/correction-email",
        json={"routed_to": "bcba", "statuses": ["pass"], "to_addr": "bcba@example.com"},
        headers=headers,
    ).json()

    resp = client.post(
        f"/versions/{ctx['version'].id}/correction-email/{gen['id']}/send",
        headers=headers,
    )
    assert resp.status_code == 502
    assert resp.json()["detail"]["error"] == "send_failed"
    assert "smtp" in resp.json()["detail"]["message"].lower()

    db_session.expire_all()
    row = db_session.get(GeneratedEmail, uuid.UUID(gen["id"]))
    assert row.send_error is not None
    assert row.sent_at is None


def test_send_without_recipient_returns_422(client, db_session, seeded_baseline, tmp_path):
    ctx = _direct_ready_upload(db_session, seeded_baseline, tmp_path, statuses={"X": "pass"})
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    gen = client.post(
        f"/versions/{ctx['version'].id}/correction-email",
        json={"routed_to": "bcba", "statuses": ["pass"], "to_addr": ""},
        headers=headers,
    ).json()
    resp = client.post(
        f"/versions/{ctx['version'].id}/correction-email/{gen['id']}/send",
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "no_recipient"


def test_send_success_attaches_tp_supporting_doc_session_note_and_intake_qa(
    client, db_session, seeded_baseline, tmp_path, monkeypatch,
):
    """Fix Round, item 3 -- real end-to-end send verification against a
    LOCAL SMTP debug server (real smtplib client, real socket, real bytes
    on the wire -- only the destination is local, not mocked). Confirms:
    real send succeeds, sent_at is set, and all 4 attachment types this
    round requires (TP, supporting doc, session note, intake Q&A) arrive
    -- each auto-attached with no manual step, none skipped since all 4
    exist on this upload.
    """
    import asyncore
    import smtpd
    import threading

    received = {}

    class _CapturingServer(smtpd.SMTPServer):
        def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
            received["mailfrom"] = mailfrom
            received["rcpttos"] = rcpttos
            received["data"] = data

    server = _CapturingServer(("127.0.0.1", 0), None, decode_data=True)
    port = server.socket.getsockname()[1]
    thread = threading.Thread(target=asyncore.loop, kwargs={"timeout": 0.2}, daemon=True)
    thread.start()

    from app.config import settings
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", port)
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_username", None)
    monkeypatch.setattr(settings, "smtp_password", None)

    try:
        ctx = _direct_ready_upload(
            db_session, seeded_baseline, tmp_path, statuses={"REAL-SEND-MARKER": "fail"}, with_attachments=True,
        )
        headers = login_headers(client, "m.chen@brightpath-aba.com")
        gen = client.post(
            f"/versions/{ctx['version'].id}/correction-email",
            json={"routed_to": "bcba", "statuses": ["fail"], "to_addr": "bcba@example.com"},
            headers=headers,
        ).json()

        resp = client.post(
            f"/versions/{ctx['version'].id}/correction-email/{gen['id']}/send",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["sent_at"] is not None
        assert resp.json()["send_error"] is None

        import time
        for _ in range(50):
            if received:
                break
            time.sleep(0.1)
    finally:
        server.close()

    assert received, "local SMTP debug server never received the message"
    assert received["rcpttos"] == ["bcba@example.com"]
    raw = received["data"]
    assert "REAL-SEND-MARKER" in raw  # body text, not base64-encoded

    # Attachment content is base64 (email.message's default transfer
    # encoding) -- filenames appear in plain Content-Disposition headers,
    # but each attachment's own BYTES must be parsed/decoded to verify,
    # not string-searched in the raw wire form.
    from email import message_from_string
    parsed = message_from_string(raw)
    attachments = {
        part.get_filename(): part.get_payload(decode=True)
        for part in parsed.walk() if part.get_filename()
    }
    assert set(attachments) == {
        "Real Treatment Plan.pdf", "supporting-document-U1.pdf", "Session Note 1.pdf", "intake-qa-U1.txt",
    }
    assert b"Aetna" in attachments["intake-qa-U1.txt"]

    db_session.expire_all()
    row = db_session.get(GeneratedEmail, uuid.UUID(gen["id"]))
    assert row.sent_at is not None
    assert row.send_error is None
