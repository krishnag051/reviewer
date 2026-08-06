"""Backend-only test/dummy-data cleanup — 2026-07-30.

Deliberately NOT an API endpoint and NOT reachable from the frontend at
all — this is a maintenance script run directly against the database by
whoever needs to clean up dev/test churn, never something the application
exposes through its own UI or router. Real product deletes stay banned
(CLAUDE.md: "No hard deletes, except PDF blobs past their retention
window") — this script sits entirely outside that boundary, the same way
`scripts/seed.py` does: it's tooling that operates on the database
directly, not a feature of the running application.

Targets patients by a reference_id LIKE pattern — defaults to `TP-TEST-%`,
which matches exactly what the test suite's own fixtures generate
(`f"TP-TEST-{uuid.uuid4().hex[:8]}"` — see tests/*.py's `_create_patient`/
`_ready_upload` helpers) — so a default run only ever touches data the test
suite itself created, never anything a real seeded/demo patient would
plausibly be named. Pass --pattern to target something else explicitly.

Dry-run by default: lists exactly what would be deleted and does nothing
until --yes is also passed.

Deletes, in FK-safe order: rule_result_edits -> rule_results -> uploads
(+ their on-disk PDF blobs, via app.storage.delete_blob) -> versions ->
patients. audit_log rows referencing these ids are intentionally left
alone, not scrubbed — audit history is meant to be permanent regardless of
whether the entity it describes still exists; deleting audit rows here
would just be a second, smaller hard-delete problem layered on top of the
first.

Run from backend/:
    .venv/Scripts/python.exe scripts/purge_test_data.py                  # dry run, default pattern
    .venv/Scripts/python.exe scripts/purge_test_data.py --yes            # actually delete, default pattern
    .venv/Scripts/python.exe scripts/purge_test_data.py --pattern "TP-DEMO-%" --yes
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Patient, RuleResult, RuleResultEdit, Upload, Version
from app.storage import delete_blob


def find_matching_patients(session, pattern: str) -> list[Patient]:
    return list(session.execute(select(Patient).where(Patient.reference_id.like(pattern))).scalars().all())


def purge(session, patients: list[Patient], *, dry_run: bool) -> dict[str, int]:
    counts = {"patients": 0, "versions": 0, "uploads": 0, "rule_results": 0, "rule_result_edits": 0, "blobs": 0}

    for patient in patients:
        versions = list(session.execute(select(Version).where(Version.patient_id == patient.id)).scalars().all())
        for version in versions:
            uploads = list(session.execute(select(Upload).where(Upload.version_id == version.id)).scalars().all())
            for upload in uploads:
                rule_results = list(session.execute(select(RuleResult).where(RuleResult.upload_id == upload.id)).scalars().all())
                for rr in rule_results:
                    edits = list(session.execute(select(RuleResultEdit).where(RuleResultEdit.rule_result_id == rr.id)).scalars().all())
                    counts["rule_result_edits"] += len(edits)
                    if not dry_run:
                        for edit in edits:
                            session.delete(edit)
                counts["rule_results"] += len(rule_results)
                if not dry_run:
                    for rr in rule_results:
                        session.delete(rr)

                if upload.file_path and not upload.file_purged:
                    counts["blobs"] += 1
                    if not dry_run:
                        delete_blob(upload.file_path)
                # Round 51: the mandatory second (supporting document) file
                # shares file_path's exact retention/purge lifecycle -- same
                # file_purged flag -- so it's cleaned up here alongside it.
                if upload.supporting_document_path and not upload.file_purged:
                    counts["blobs"] += 1
                    if not dry_run:
                        delete_blob(upload.supporting_document_path)
            counts["uploads"] += len(uploads)
            if not dry_run:
                # version.final_upload_id points at one of these uploads --
                # must be cleared before the upload rows can be deleted
                # (FK is RESTRICT, use_alter).
                version.final_upload_id = None
                session.flush()
                for upload in uploads:
                    session.delete(upload)
        counts["versions"] += len(versions)
        if not dry_run:
            for version in versions:
                session.delete(version)
        counts["patients"] += 1
        if not dry_run:
            session.delete(patient)

    if not dry_run:
        session.commit()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pattern", default="TP-TEST-%", help="SQL LIKE pattern on patients.reference_id (default: TP-TEST-%%, matching the test suite's own fixtures)")
    parser.add_argument("--yes", action="store_true", help="actually delete — omit for a dry run")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        patients = find_matching_patients(session, args.pattern)
        if not patients:
            print(f"No patients match reference_id LIKE {args.pattern!r}. Nothing to do.")
            return

        print(f"{'Would delete' if not args.yes else 'Deleting'} {len(patients)} patient(s) matching {args.pattern!r}:")
        for p in patients:
            print(f"  {p.reference_id}  ({p.name})")

        counts = purge(session, patients, dry_run=not args.yes)
        print()
        print(("Dry run — would delete:" if not args.yes else "Deleted:"))
        for key, value in counts.items():
            print(f"  {key}: {value}")
        if not args.yes:
            print("\nRe-run with --yes to actually delete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
