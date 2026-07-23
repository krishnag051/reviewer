"""Step 8 regression coverage: finalize guards + effects, void, mark-reviewed.
Finalize is irreversible by design — there is no un-finalize endpoint
anywhere in this system (see the dedicated test at the bottom).
"""
import io
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.models import AppConfig, AuditLog, Upload, Version
from tests.conftest import login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _ready_upload(client, headers) -> dict:
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


def _finalize(client, headers, upload_id: str, reference_id: str):
    return client.post(
        f"/uploads/{upload_id}/finalize", json={"reference_id": reference_id}, headers=headers
    )


# ------------------------------------------------------------- finalize guards

def test_finalize_rejects_processing_upload(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    upload_row = db_session.get(Upload, uuid.UUID(ctx["upload"]["id"]))
    upload_row.status = "processing"
    db_session.commit()

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_ready"


def test_finalize_rejects_voided_upload(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = client.post(
        f"/uploads/{ctx['upload']['id']}/void", json={"reason": "wrong patient"}, headers=headers
    )
    assert resp.status_code == 200

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "voided"


def test_finalize_rejects_existing_final_sibling(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    # A second upload for the SAME version.
    upload2 = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()
    detail2 = client.get(f"/uploads/{upload2['id']}", headers=headers).json()
    assert detail2["status"] == "ready"

    resp2 = _finalize(client, headers, upload2["id"], ctx["patient"]["reference_id"])
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["error"] == "sibling_already_final"


def test_finalize_rejects_uncertain_remaining(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]

    resp = client.patch(
        f"/rule_results/{rr['id']}",
        json={"updated_at": rr["updated_at"], "final_status": "uncertain"},
        headers=headers,
    )
    assert resp.status_code == 200

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["error"] == "uncertain_results_remain"
    assert isinstance(detail["rule_codes"], list) and len(detail["rule_codes"]) == 1


def test_finalize_rejects_reference_id_mismatch(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = _finalize(client, headers, ctx["upload"]["id"], "TP-WRONG-REFERENCE")
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "reference_id_mismatch"


def test_finalize_rejects_missing_reference_id(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = client.post(f"/uploads/{ctx['upload']['id']}/finalize", json={}, headers=headers)
    assert resp.status_code in (409, 422)  # 422 if pydantic rejects a missing required field outright


def test_finalize_rejects_already_finalized_upload_and_changes_nothing(client, db_session, seeded_baseline):
    """Guard 0. Calling finalize twice on the SAME upload must not re-run the
    commit — no repeated purge_after extension on siblings, no rewritten
    score/audit_result, no duplicate audit entry.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    sibling = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()

    resp1 = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp1.status_code == 200

    db_session.expire_all()
    version_after_first = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    sibling_after_first = db_session.get(Upload, uuid.UUID(sibling["id"]))
    score_after_first = version_after_first.score
    audit_result_after_first = version_after_first.audit_result
    purge_after_first = sibling_after_first.purge_after
    finalize_audit_count_after_first = len(db_session.execute(
        select(AuditLog).where(
            AuditLog.target_type == "upload",
            AuditLog.target_id == uuid.UUID(ctx["upload"]["id"]),
            AuditLog.action.like("Finalized upload%"),
        )
    ).scalars().all())
    assert finalize_audit_count_after_first == 1

    resp2 = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp2.status_code == 409
    assert resp2.json()["detail"]["error"] == "already_finalized"

    db_session.expire_all()
    version_after_second = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    sibling_after_second = db_session.get(Upload, uuid.UUID(sibling["id"]))
    assert version_after_second.score == score_after_first
    assert version_after_second.audit_result == audit_result_after_first
    assert sibling_after_second.purge_after == purge_after_first, (
        "a second finalize call must not push the sibling's purge_after further out"
    )

    finalize_audit_count_after_second = len(db_session.execute(
        select(AuditLog).where(
            AuditLog.target_type == "upload",
            AuditLog.target_id == uuid.UUID(ctx["upload"]["id"]),
            AuditLog.action.like("Finalized upload%"),
        )
    ).scalars().all())
    assert finalize_audit_count_after_second == 1, "no duplicate finalize audit entry"


# ----------------------------------------------------------- successful finalize

def test_finalize_success_sets_purge_after_on_siblings_not_self(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    # Second, non-final sibling upload for the same version.
    upload2 = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200
    assert resp.json()["is_final"] is True

    db_session.expire_all()
    finalized = db_session.get(Upload, uuid.UUID(ctx["upload"]["id"]))
    sibling = db_session.get(Upload, uuid.UUID(upload2["id"]))
    app_config = db_session.execute(select(AppConfig)).scalar_one()

    assert finalized.purge_after is None, "the finalized upload itself must NOT get a purge_after"
    assert sibling.purge_after is not None
    expected_days = app_config.retention_days
    delta = sibling.purge_after - finalized.created_at
    assert abs(delta.days - expected_days) <= 1


def test_finalize_success_computes_score_via_scoring_module(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    results = ctx["upload"]["rule_results"]

    # Override 2 to pass, 1 to fail before finalizing -> score = 2/3 * 100.
    for rr in results[:2]:
        client.patch(
            f"/rule_results/{rr['id']}",
            json={"updated_at": rr["updated_at"], "final_status": "pass"},
            headers=headers,
        )
    client.patch(
        f"/rule_results/{results[2]['id']}",
        json={"updated_at": results[2]["updated_at"], "final_status": "fail"},
        headers=headers,
    )

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    db_session.expire_all()
    version = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version.status == "finalized"
    assert version.final_upload_id == uuid.UUID(ctx["upload"]["id"])
    assert version.audit_result == "fail"  # not 100%
    assert abs(float(version.score) - (2 / 3 * 100)) < 0.001

    audit_rows = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "upload", AuditLog.target_id == uuid.UUID(ctx["upload"]["id"]))
    ).scalars().all()
    assert any("Finalized upload" in a.action for a in audit_rows)


# --------------------------------------------------------------------- void

def test_void_rejected_on_already_final_upload(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    resp = client.post(f"/uploads/{ctx['upload']['id']}/void", json={"reason": "changed my mind"}, headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "already_final"


def test_void_requires_reason(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = client.post(f"/uploads/{ctx['upload']['id']}/void", json={}, headers=headers)
    assert resp.status_code in (400, 422)

    resp = client.post(f"/uploads/{ctx['upload']['id']}/void", json={"reason": "   "}, headers=headers)
    assert resp.status_code == 400


def test_void_sets_purge_after_immediately(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = client.post(
        f"/uploads/{ctx['upload']['id']}/void", json={"reason": "wrong file uploaded"}, headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["voided"] is True

    db_session.expire_all()
    upload = db_session.get(Upload, uuid.UUID(ctx["upload"]["id"]))
    assert upload.voided is True
    assert upload.voided_reason == "wrong file uploaded"
    assert upload.purge_after is not None
    from datetime import datetime, timezone
    assert (datetime.now(timezone.utc) - upload.purge_after).total_seconds() < 10

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "upload", AuditLog.target_id == upload.id)
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert "Voided upload" in audit_row.action
    assert audit_row.details["voided"] == {"from": False, "to": True}


def test_voided_upload_excluded_from_finalize_sibling_check(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    # Void the first upload, then finalize a second — must NOT be blocked by
    # the (voided) first even if it were somehow marked final beforehand.
    resp = client.post(f"/uploads/{ctx['upload']['id']}/void", json={"reason": "duplicate upload"}, headers=headers)
    assert resp.status_code == 200

    upload2 = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()
    detail2 = client.get(f"/uploads/{upload2['id']}", headers=headers).json()
    assert detail2["status"] == "ready"

    resp2 = _finalize(client, headers, upload2["id"], ctx["patient"]["reference_id"])
    assert resp2.status_code == 200


def test_voided_siblings_purge_after_not_extended_by_finalize(client, db_session, seeded_baseline):
    """A voided sibling is already purge-eligible immediately (purge_after
    set to the void moment). A later finalize on another upload in the same
    version must not touch it — not extend it out to
    now() + retention_days like a non-voided sibling, and not reset it.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    upload2 = client.post(
        f"/versions/{ctx['version']['id']}/uploads",
        files={"file": ("tp2.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    ).json()
    void_resp = client.post(f"/uploads/{upload2['id']}/void", json={"reason": "wrong file"}, headers=headers)
    assert void_resp.status_code == 200

    db_session.expire_all()
    voided_upload_row = db_session.get(Upload, uuid.UUID(upload2["id"]))
    purge_after_before_finalize = voided_upload_row.purge_after
    assert purge_after_before_finalize is not None

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    db_session.expire_all()
    voided_upload_row = db_session.get(Upload, uuid.UUID(upload2["id"]))
    assert voided_upload_row.purge_after == purge_after_before_finalize, (
        "finalize must not touch an already-voided sibling's purge_after at all"
    )


# -------------------------------------------------------------- mark-reviewed

def test_mark_reviewed_rejected_before_finalize(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = client.post(f"/versions/{ctx['version']['id']}/mark-reviewed", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "not_finalized"


def test_mark_reviewed_succeeds_after_finalize(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    resp = client.post(f"/versions/{ctx['version']['id']}/mark-reviewed", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["reviewed"] is True
    assert body["reviewed_by"] is not None
    assert body["reviewed_at"] is not None

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == uuid.UUID(ctx["version"]["id"]))
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert "reviewed" in audit_row.action.lower()
    assert audit_row.details["reviewed"] == {"from": False, "to": True}


def test_mark_reviewed_succeeds_independent_of_audit_result(client, db_session, seeded_baseline):
    """A version with audit_result=fail can still be marked reviewed — human
    sign-off is not the same as passing.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ctx = _ready_upload(client, headers)
    rr = ctx["upload"]["rule_results"][0]

    client.patch(
        f"/rule_results/{rr['id']}",
        json={"updated_at": rr["updated_at"], "final_status": "fail"},
        headers=headers,
    )

    resp = _finalize(client, headers, ctx["upload"]["id"], ctx["patient"]["reference_id"])
    assert resp.status_code == 200

    db_session.expire_all()
    version = db_session.get(Version, uuid.UUID(ctx["version"]["id"]))
    assert version.audit_result == "fail"

    resp = client.post(f"/versions/{ctx['version']['id']}/mark-reviewed", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["reviewed"] is True


# ------------------------------------------------------------- no un-finalize

def test_no_un_finalize_route_exists(client):
    schema = client.app.openapi()
    paths = schema["paths"]
    for path in paths:
        assert "unfinalize" not in path.replace("-", "").replace("_", "").lower()
        assert "un-finalize" not in path

    # A guess at plausible route shapes, all must 404/405 — not silently work.
    fake_id = str(uuid.uuid4())
    for method, path in [
        ("post", f"/uploads/{fake_id}/unfinalize"),
        ("post", f"/uploads/{fake_id}/un-finalize"),
        ("delete", f"/uploads/{fake_id}/finalize"),
        ("post", f"/uploads/{fake_id}/finalize/undo"),
    ]:
        resp = getattr(client, method)(path)
        assert resp.status_code in (404, 405)


def test_no_hard_delete_code_path_exists():
    """CLAUDE.md: "No hard deletes, except PDF blobs past their retention
    window. Everything else is a flag." Sweeps every router and service
    module for a raw SQLAlchemy `.delete(` call or a literal `DELETE FROM`
    statement — the only legitimate delete in this codebase is the
    filesystem blob removal in app/storage.py::delete_blob (a PDF file, not
    a DB row), which this sweep explicitly excludes.
    """
    import re
    from pathlib import Path

    import app.routers
    import app.services

    forbidden = re.compile(r"\.delete\(|DELETE\s+FROM", re.IGNORECASE)

    checked = 0
    for package in (app.routers, app.services):
        package_dir = Path(package.__file__).parent
        for py_file in package_dir.glob("*.py"):
            if py_file.stem == "__init__":
                continue
            source = py_file.read_text(encoding="utf-8")
            checked += 1
            for lineno, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if forbidden.search(line):
                    assert False, (
                        f"found a hard-delete-shaped statement in {py_file.name}:{lineno}: {line.strip()!r} "
                        "— everything except PDF blobs past retention must be a flag, never DELETE"
                    )
    assert checked > 10, "sweep should have scanned every router/service module — checked too few files"
