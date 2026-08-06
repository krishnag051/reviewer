"""Round 42 verification-only helper — NOT part of the real product seed.

Creates one TP-TEST-round42-pdf-demo patient with two versions (one
finalized, one still an in-progress draft), each with a real Upload row
(status="ready", a real on-disk PDF at the real configured
upload_storage_dir) and a couple of real RuleResult rows referencing real,
already-seeded Rule ids.

This exists ONLY so Round 42's real click-through verification of the new
PDF pane (GET /uploads/:id/file) has a real "ready" upload to look at for
both a draft and a finalized version, WITHOUT ever calling the real
rule-checking agent to produce one — inserts rows directly, exactly the
same pattern backend/tests/conftest.py's make_patient_version_upload helper
already uses, just against the dev database instead of the disposable test
database. Zero real Anthropic API calls.

Matches the TP-TEST- reference_id convention scripts/purge_test_data.py
already knows how to clean up — run that script (dry-run first) when this
demo data is no longer needed.

Run from backend/:
    .venv/Scripts/python.exe scripts/seed_round42_pdf_demo.py
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Patient, Rule, RuleResult, Upload, User, Version
from app.storage import save_blob, save_supporting_blob

REFERENCE_ID = "TP-TEST-round42-pdf-demo"


def _pdf_bytes(label: str) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = __import__("io").BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _make_ready_upload(session, version_id, upload_number: int, rules: list[Rule], uploaded_by) -> Upload:
    upload = Upload(
        version_id=version_id,
        upload_number=upload_number,
        status="ready",
        uploaded_by=uploaded_by,
    )
    session.add(upload)
    session.flush()

    upload.file_path = save_blob(upload.id, f"round42-demo-{upload_number}.pdf", _pdf_bytes(f"upload {upload_number}"))
    # Round 51: mandatory second file -- backfilled here too so this demo
    # upload's "Helping Document" button has something real to open.
    upload.supporting_document_path = save_supporting_blob(
        upload.id, f"round42-demo-{upload_number}-supporting.pdf", _pdf_bytes(f"supporting {upload_number}")
    )

    for i, rule in enumerate(rules):
        final_status = "pass" if i % 2 == 0 else "fail"
        session.add(RuleResult(
            upload_id=upload.id,
            rule_id=rule.id,
            rule_version_used=1,
            model_status=final_status,
            model_finding=f"Round 42 demo finding for {rule.rule_code} (upload {upload_number}).",
            model_pages=[1],
            final_status=final_status,
            final_finding=f"Round 42 demo finding for {rule.rule_code} (upload {upload_number}).",
            final_pages=[1],
        ))

    return upload


def main() -> None:
    session = SessionLocal()
    try:
        existing = session.execute(select(Patient).where(Patient.reference_id == REFERENCE_ID)).scalar_one_or_none()
        if existing is not None:
            print(f"{REFERENCE_ID} already exists (patient id {existing.id}) — nothing to do.")
            return

        admin = session.execute(select(User).where(User.email == "m.chen@brightpath-aba.com")).scalar_one()
        rules = list(session.execute(select(Rule).where(Rule.active.is_(True)).limit(4)).scalars().all())
        assert rules, "no active rules found — run scripts/seed.py first"

        patient = Patient(reference_id=REFERENCE_ID, name="Round42 PDF Demo Patient", payor="Aetna")
        session.add(patient)
        session.flush()

        v1 = Version(
            patient_id=patient.id, version_number=1, status="finalized",
            score=50.0, audit_result="fail", finalized_at=datetime.now(timezone.utc), reviewed=False,
        )
        session.add(v1)
        session.flush()
        u1 = _make_ready_upload(session, v1.id, 1, rules, admin.id)
        session.flush()
        v1.final_upload_id = u1.id
        u1.is_final = True

        v2 = Version(patient_id=patient.id, version_number=2, status="in_progress")
        session.add(v2)
        session.flush()
        _make_ready_upload(session, v2.id, 1, rules, admin.id)

        session.commit()
        print(f"Created {REFERENCE_ID}: finalized v1 (upload ready) + in-progress v2 draft (upload ready).")
    finally:
        session.close()


if __name__ == "__main__":
    main()
