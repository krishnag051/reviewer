"""Step 9 regression coverage: GET /uploads/:id/diff and
POST /versions/:id/correction-email (generation + persistence, no sending).
"""
import io
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.models import AuditLog, GeneratedEmail
from tests.conftest import login_headers


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
        files={"file": ("tp.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()
    detail = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    assert detail["status"] == "ready", detail
    return {"patient": patient, "version_id": version_id, "upload": detail}


def _override(client, headers, rr: dict, **fields):
    return client.patch(
        f"/rule_results/{rr['id']}", json={"updated_at": rr["updated_at"], **fields}, headers=headers
    )


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
        json={"routed_to": "bcba", "group_by": "category"},
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
        json={"routed_to": "qa"},
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
        json={"routed_to": "clinical_director", "upload_id": ctx1["upload"]["id"]},
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
        json={"routed_to": "coordinator", "upload_id": ctx2["upload"]["id"]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_upload"


def test_generate_correction_email_group_by_page(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]
    _override(client, headers, rr, final_status="fail", final_pages=[3])

    resp = client.post(
        f"/versions/{ctx['version_id']}/correction-email",
        json={"routed_to": "bcba", "group_by": "page"},
        headers=headers,
    )
    assert resp.status_code == 201
    assert "Page 3:" in resp.json()["body"]


def test_no_send_capability_exists(client):
    """Generation + persistence only — no actual email-sending endpoint or
    capability exists anywhere in this backend. Checks actual usage
    (import statements, dependency list), not a bare-word substring scan —
    the service's own docstring explains that no SMTP is used, which would
    otherwise trip a naive "is the word 'smtp' anywhere in this file" check.
    """
    schema = client.app.openapi()
    for path in schema["paths"]:
        assert "/send" not in path.lower()

    import re

    import app.services.correction_email as mod
    source = open(mod.__file__, encoding="utf-8").read()
    for forbidden_import in (r"\bimport smtplib\b", r"\bsendgrid\b", r"\bboto3\b", r"\bses\.send", r"\.sendmail\("):
        assert re.search(forbidden_import, source) is None, f"found {forbidden_import!r} in {mod.__file__}"

    pyproject = open("pyproject.toml", encoding="utf-8").read().lower()
    for forbidden_dep in ("sendgrid", "boto3", "mailgun", "postmark"):
        assert forbidden_dep not in pyproject
