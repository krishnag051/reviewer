"""Step 6 regression coverage: patients/versions/uploads routes, sequential
number assignment (including under real concurrency), and the upload
pipeline (success producing one real rule_result per pinned rule via the
now-real rule_engine wiring to agent-making — 2026-07-30, previously the
hollow stub's "na"/"agent not yet implemented" for everything; failure
leaving nothing partial). The success-path test below makes a real, billed
call to the rule-checking agent — this file's fixture PDF is a genuinely
blank page, so exact result values aren't asserted (they're whatever the
agent honestly returns for a document with no extractable content), only
the structural guarantees the pipeline itself is responsible for.
"""
import io
import threading
import uuid

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.models import AuditLog, Patient, RuleResult, RuleSnapshot, Version
from app.services.uploads import create_upload
from app.services.versions import create_version
from tests.conftest import ROUND56_QA_FORM_DATA, login_headers, unique_rule_code


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_patient(client, headers, reference_id: str | None = None) -> dict:
    resp = client.post(
        "/patients",
        json={
            "reference_id": reference_id or f"TP-TEST-{uuid.uuid4().hex[:8]}",
            "name": "Test Patient",
            "payor": "Aetna",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_version(client, headers, patient_id: str) -> dict:
    resp = client.post(f"/patients/{patient_id}/versions", json={}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_upload(client, headers, version_id: str, content: bytes = None, filename: str = "tp.pdf") -> dict:
    content = content if content is not None else _pdf_bytes()
    resp = client.post(
        f"/versions/{version_id}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": (filename, content, "application/pdf"),
            # Round 51's mandatory second file -- always sent as a real, valid
            # PDF here regardless of `content` (which some callers deliberately
            # set to garbage to test the TP's own parse-failure path); the
            # supporting document is never parsed, so it never needs to be.
            "supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- patients

def test_create_patient(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ref = f"TP-TEST-{uuid.uuid4().hex[:8]}"
    body = _create_patient(client, headers, reference_id=ref)
    assert body["reference_id"] == ref
    assert body["name"] == "Test Patient"

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "patient", AuditLog.target_id == uuid.UUID(body["id"]))
    ).scalar_one()
    assert audit_row.details["reference_id"]["to"] == ref


def test_create_patient_duplicate_reference_id_409(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    ref = f"TP-TEST-{uuid.uuid4().hex[:8]}"
    _create_patient(client, headers, reference_id=ref)

    resp = client.post("/patients", json={"reference_id": ref, "name": "Someone Else"}, headers=headers)
    assert resp.status_code == 409


def test_patch_patient_name_only(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)

    resp = client.patch(f"/patients/{patient['id']}", json={"name": "Corrected Name"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Corrected Name"
    assert resp.json()["reference_id"] == patient["reference_id"]

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "patient", AuditLog.target_id == uuid.UUID(patient["id"]))
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details["name"] == {"from": "Test Patient", "to": "Corrected Name"}


def test_patch_patient_rejects_reference_id_change(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)

    resp = client.patch(
        f"/patients/{patient['id']}",
        json={"name": "New Name", "reference_id": "TP-SOMETHING-ELSE"},
        headers=headers,
    )
    assert resp.status_code == 400

    db_session.expire_all()
    row = db_session.get(Patient, uuid.UUID(patient["id"]))
    assert row.reference_id == patient["reference_id"], "reference_id must be untouched by a rejected PATCH"
    assert row.name == "Test Patient", "name must also be untouched — the whole PATCH is rejected, not partially applied"


def test_patch_patient_echoing_same_reference_id_is_allowed(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)

    resp = client.patch(
        f"/patients/{patient['id']}",
        json={"name": "New Name", "reference_id": patient["reference_id"]},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_list_patients_includes_latest_version_fields(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    _create_version(client, headers, patient["id"])
    v2 = _create_version(client, headers, patient["id"])

    resp = client.get("/patients", headers=headers)
    assert resp.status_code == 200
    item = next(p for p in resp.json() if p["id"] == patient["id"])
    assert item["latest_version_number"] == v2["version_number"] == 2
    assert item["score"] is None
    assert item["audit_result"] is None
    assert item["reviewed"] is False


# ---------------------------------------------------------------- versions

def test_create_version_sequential_numbering(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)

    v1 = _create_version(client, headers, patient["id"])
    v2 = _create_version(client, headers, patient["id"])
    assert v1["version_number"] == 1
    assert v2["version_number"] == 2

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == uuid.UUID(v1["id"]))
    ).scalar_one()
    assert audit_row.details["version_number"] == {"from": None, "to": 1}


def test_concurrent_version_creation_no_duplicate_numbers(db_session, engine, seeded_baseline):
    """Bypasses HTTP — calls the locked service function directly from two
    threads, each with its own session, to genuinely exercise the row lock
    rather than just trusting the UNIQUE constraint as a backstop.
    """
    from sqlalchemy.orm import sessionmaker

    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    patient = Patient(reference_id=f"TP-CONC-{uuid.uuid4().hex[:8]}", name="Concurrency Test Patient")
    db_session.add(patient)
    db_session.commit()
    patient_id = patient.id

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    lock_acquired = threading.Event()

    def _worker(delay_after_lock: bool):
        session = Session()
        try:
            def _after_lock():
                if delay_after_lock:
                    lock_acquired.set()
                    import time
                    time.sleep(0.2)
                else:
                    lock_acquired.wait(timeout=2)

            version = create_version(
                session, patient_id, payor=None, assessment_date=None, actor_user_id=admin_id, _after_lock=_after_lock
            )
            results.append(version.version_number)
        except Exception as exc:  # pragma: no cover - failure path surfaced via `errors`
            errors.append(exc)
        finally:
            session.close()

    t1 = threading.Thread(target=_worker, args=(True,))
    t2 = threading.Thread(target=_worker, args=(False,))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"concurrent version creation raised: {errors}"
    assert sorted(results) == [1, 2], f"expected exactly one 1 and one 2, got {results}"

    db_session.expire_all()
    versions = db_session.execute(
        select(Version).where(Version.patient_id == patient_id)
    ).scalars().all()
    assert sorted(v.version_number for v in versions) == [1, 2]


def test_get_version_detail_includes_uploads(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])
    upload = _create_upload(client, headers, version["id"])

    resp = client.get(f"/versions/{version['id']}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["uploads"]) == 1
    assert body["uploads"][0]["id"] == upload["id"]


def test_patch_version_reviewer_and_assessment_date(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    reviewer_id = seeded_baseline["s.patel@brightpath-aba.com"]
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])

    resp = client.patch(
        f"/versions/{version['id']}",
        json={"reviewer_id": str(reviewer_id), "assessment_date": "2026-01-15"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reviewer_id"] == str(reviewer_id)
    assert body["assessment_date"] == "2026-01-15"

    audit_row = db_session.execute(
        select(AuditLog).where(AuditLog.target_type == "version", AuditLog.target_id == uuid.UUID(version["id"]))
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details["reviewer_id"]["to"] == str(reviewer_id)
    assert audit_row.details["assessment_date"]["to"] == "2026-01-15"


# ----------------------------------------------------------------- uploads

def test_create_upload_sequential_numbering(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])

    u1 = _create_upload(client, headers, version["id"])
    u2 = _create_upload(client, headers, version["id"])
    assert u1["upload_number"] == 1
    assert u2["upload_number"] == 2

    # Two audit rows target this upload (creation + the pipeline's own
    # "completed" entry) — filter to the creation one specifically.
    audit_row = db_session.execute(
        select(AuditLog).where(
            AuditLog.target_type == "upload",
            AuditLog.target_id == uuid.UUID(u1["id"]),
            AuditLog.action.like("Uploaded document%"),
        )
    ).scalar_one()
    assert audit_row.details["upload_number"] == {"from": None, "to": 1}


def test_concurrent_upload_creation_no_duplicate_numbers(db_session, engine, seeded_baseline):
    from sqlalchemy.orm import sessionmaker

    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    patient = Patient(reference_id=f"TP-CONC-{uuid.uuid4().hex[:8]}", name="Concurrency Test Patient")
    db_session.add(patient)
    db_session.flush()
    version = Version(patient_id=patient.id, version_number=1)
    db_session.add(version)
    db_session.commit()
    version_id = version.id

    Session = sessionmaker(bind=engine)
    results = []
    errors = []
    lock_acquired = threading.Event()
    pdf_content = _pdf_bytes()

    def _worker(delay_after_lock: bool):
        session = Session()
        try:
            def _after_lock():
                if delay_after_lock:
                    lock_acquired.set()
                    import time
                    time.sleep(0.2)
                else:
                    lock_acquired.wait(timeout=2)

            upload = create_upload(
                session, version_id, filename="tp.pdf", content=pdf_content,
                supporting_document_filename="supporting.pdf", supporting_document_content=pdf_content,
                uploaded_by=admin_id, _after_lock=_after_lock,
            )
            results.append(upload.upload_number)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)
        finally:
            session.close()

    t1 = threading.Thread(target=_worker, args=(True,))
    t2 = threading.Thread(target=_worker, args=(False,))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"concurrent upload creation raised: {errors}"
    assert sorted(results) == [1, 2], f"expected exactly one 1 and one 2, got {results}"


def test_pipeline_success_produces_one_real_result_per_pinned_rule(client, db_session, seeded_baseline):
    """Real, billed call to the rule-checking agent (agent-making via
    app/rule_engine/client.py) — not mocked. Asserts the structural
    guarantees the PIPELINE is responsible for (one result per pinned rule,
    a real status/finding, nothing pre-overridden) — not specific status
    values, since this fixture's blank-page PDF has no real content for
    the agent to judge and its actual answers are honest, not scripted.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])
    upload = _create_upload(client, headers, version["id"])

    resp = client.get(f"/uploads/{upload['id']}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready", body
    assert body["rules_snapshot_id"] is not None

    # Compare against the rule count actually pinned in THIS upload's
    # snapshot — not "however many active rules exist in the DB right now".
    # Other test files share this same DB and create their own rules
    # concurrently, so the live active-rule count is not a stable baseline;
    # the snapshot pinned at pipeline time is exactly what the pipeline is
    # supposed to have used.
    snapshot = db_session.get(RuleSnapshot, uuid.UUID(body["rules_snapshot_id"]))
    assert len(body["rule_results"]) == len(snapshot.rule_ids_and_versions)
    valid_statuses = {"pass", "fail", "na", "uncertain", "not_checkable"}
    assert all(r["final_status"] in valid_statuses for r in body["rule_results"])
    assert all(r["final_finding"] for r in body["rule_results"]), "every result needs a real, non-empty finding"
    assert all(r["is_overridden"] is False for r in body["rule_results"])


def test_pipeline_failure_leaves_nothing_partial_status_error(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])
    upload = _create_upload(client, headers, version["id"], content=b"not a pdf at all, just garbage bytes", filename="garbage.pdf")

    resp = client.get(f"/uploads/{upload['id']}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error", body
    assert body["error_detail"] is not None
    assert body["rules_snapshot_id"] is None, "a failed pipeline must never pin a snapshot"
    assert body["rule_results"] == [], "a failed pipeline must leave zero rule_results — nothing partial"

    db_session.expire_all()
    persisted = db_session.execute(
        select(RuleResult).where(RuleResult.upload_id == uuid.UUID(upload["id"]))
    ).scalars().all()
    assert persisted == []


def test_uploading_sibling_upload_does_not_touch_other_uploads(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers)
    version = _create_version(client, headers, patient["id"])

    u1 = _create_upload(client, headers, version["id"])
    resp1_before = client.get(f"/uploads/{u1['id']}", headers=headers).json()
    assert resp1_before["status"] == "ready"
    u1_result_ids = sorted(r["id"] for r in resp1_before["rule_results"])

    u2 = _create_upload(client, headers, version["id"])
    resp2 = client.get(f"/uploads/{u2['id']}", headers=headers).json()
    assert resp2["status"] == "ready"

    resp1_after = client.get(f"/uploads/{u1['id']}", headers=headers).json()
    assert resp1_after["status"] == "ready"
    assert sorted(r["id"] for r in resp1_after["rule_results"]) == u1_result_ids
    assert resp1_after["rules_snapshot_id"] == resp1_before["rules_snapshot_id"]
