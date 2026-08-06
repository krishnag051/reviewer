"""Round 43 verification-only helper — NOT part of the real product seed.

Creates ONE fresh in-progress draft version (a real Upload, status="ready",
with two real RuleResult rows -- one "fail", one "pass", referencing real
already-seeded Rule ids) for a patient identified by `--ref-id`. Inserts
rows directly (same technique as seed_round42_pdf_demo.py / conftest.py's
make_patient_version_upload) -- zero real Anthropic API calls, no pipeline
run at all.

Takes `--ref-id` (required, not defaulted) rather than a fixed reference_id
like Round 42's PDF demo script: this data gets FINALIZED by the Round 43
frontend click-through test, and finalize is irreversible (CLAUDE.md) --
reusing one fixed patient across repeated test runs would only work once.
The caller (see src/test/lifecycle.test.tsx's Stage 3 describe block) is
expected to generate a fresh, unique ref id per run and pass it through via
the ROUND43_DEMO_REF_ID env var, matching what this script created.

Run from backend/:
    .venv/Scripts/python.exe scripts/seed_round43_override_demo.py --ref-id TP-TEST-round43-abc123
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfWriter
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Patient, Rule, RuleResult, Upload, User, Version
from app.storage import save_blob, save_supporting_blob


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = __import__("io").BytesIO()
    writer.write(buf)
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref-id", required=True)
    parser.add_argument("--name", default="Round43 Override Demo Patient")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        existing = session.execute(select(Patient).where(Patient.reference_id == args.ref_id)).scalar_one_or_none()
        if existing is not None:
            print(f"{args.ref_id} already exists (patient id {existing.id}) — refusing to create a duplicate.")
            sys.exit(1)

        admin = session.execute(select(User).where(User.email == "m.chen@brightpath-aba.com")).scalar_one()
        rules = list(session.execute(select(Rule).where(Rule.active.is_(True)).limit(2)).scalars().all())
        assert len(rules) >= 2, "need at least 2 active rules — run scripts/seed.py first"

        patient = Patient(reference_id=args.ref_id, name=args.name, payor="Aetna")
        session.add(patient)
        session.flush()

        version = Version(patient_id=patient.id, version_number=1, status="in_progress")
        session.add(version)
        session.flush()

        upload = Upload(version_id=version.id, upload_number=1, status="ready", uploaded_by=admin.id)
        session.add(upload)
        session.flush()
        upload.file_path = save_blob(upload.id, "round43-override-demo.pdf", _pdf_bytes())
        upload.supporting_document_path = save_supporting_blob(upload.id, "round43-override-demo-supporting.pdf", _pdf_bytes())

        rr_fail = RuleResult(
            upload_id=upload.id, rule_id=rules[0].id, rule_version_used=1,
            model_status="fail", model_finding="Round 43 demo finding (fail, awaiting override).", model_pages=[1],
            final_status="fail", final_finding="Round 43 demo finding (fail, awaiting override).", final_pages=[1],
        )
        rr_pass = RuleResult(
            upload_id=upload.id, rule_id=rules[1].id, rule_version_used=1,
            model_status="pass", model_finding="Round 43 demo finding (pass).", model_pages=[1],
            final_status="pass", final_finding="Round 43 demo finding (pass).", final_pages=[1],
        )
        session.add_all([rr_fail, rr_pass])
        session.commit()

        print(f"Created {args.ref_id}: in-progress v1 draft, ready upload, 1 fail + 1 pass rule_result.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
