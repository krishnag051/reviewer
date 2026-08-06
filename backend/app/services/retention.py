import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.audit import record
from app.db.base import SessionLocal
from app.db.models import Upload
from app.storage import delete_blob

logger = logging.getLogger(__name__)


def run_retention_sweep() -> None:
    """Daily job. Finds uploads whose retention window has passed and whose
    blob hasn't been purged yet. Delete the blob FIRST; only flip
    file_purged=True on confirmed success — never mark-then-delete. A
    failure here leaves the row untouched, eligible again on tomorrow's run.
    """
    session = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        candidate_ids = list(
            session.execute(
                select(Upload.id).where(
                    Upload.purge_after < now,
                    Upload.file_purged.is_(False),
                    Upload.is_final.is_(False),
                )
            ).scalars()
        )
    finally:
        session.close()

    for upload_id in candidate_ids:
        _purge_one(upload_id)


def _purge_one(upload_id: uuid.UUID) -> None:
    session = SessionLocal()
    try:
        # skip_locked: if another running job (or process) is already on this
        # row, don't wait for it — just skip it this run, pick it up next time.
        upload = session.execute(
            select(Upload).where(Upload.id == upload_id).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if upload is None:
            return

        # Re-check eligibility under the lock — state may have moved since
        # the outer query ran (e.g. finalized in the meantime).
        now = datetime.now(timezone.utc)
        if upload.file_purged or upload.is_final or upload.purge_after is None or upload.purge_after >= now:
            session.rollback()
            return

        if upload.file_path:
            try:
                delete_blob(upload.file_path)
            except Exception:
                logger.exception("Failed to purge blob for upload %s — will retry next run", upload_id)
                session.rollback()
                return

        # Round 51: the supporting document follows the exact same
        # retention lifecycle as the TP's own file -- same purge_after,
        # same file_purged flag (not a separate one), same "never purged
        # while is_final" protection above. No independent expiry logic.
        if upload.supporting_document_path:
            try:
                delete_blob(upload.supporting_document_path)
            except Exception:
                logger.exception("Failed to purge supporting-document blob for upload %s — will retry next run", upload_id)
                session.rollback()
                return

        # Round 56: session-note files follow the exact same lifecycle too
        # -- the PARENT upload's file_purged/purge_after/is_final, not any
        # expiry of their own. Each file gets its own file_purged flip so a
        # failure partway through (blob 2 of 3 fails to delete) leaves an
        # accurate per-file record and retries only what's actually left,
        # instead of a single all-or-nothing flag across every file.
        for note in upload.session_note_files:
            if note.file_purged:
                continue
            try:
                delete_blob(note.file_path)
            except Exception:
                logger.exception(
                    "Failed to purge session-note blob %s for upload %s — will retry next run", note.id, upload_id
                )
                session.rollback()
                return
            note.file_purged = True

        upload.file_purged = True
        record(
            session,
            user_id=None,
            action=f"Purged blob for upload {upload_id} (retention window elapsed)",
            target_type="upload",
            target_id=upload.id,
            details={"file_purged": {"from": False, "to": True}},
        )
        session.commit()
    finally:
        session.close()
