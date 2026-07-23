import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.audit import record
from app.db.base import SessionLocal
from app.db.models import AppConfig, Upload

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MINUTES = 30  # used only if app_config hasn't been seeded yet


def run_stuck_job_sweep() -> None:
    """Periodic job. Uploads stuck in `processing` past the configured
    timeout are marked `error`. rule_results are never touched here — the
    upload pipeline (step 6) writes them all-or-nothing at the end of a run,
    so a stuck upload has none to clean up.
    """
    session = SessionLocal()
    try:
        config = session.execute(select(AppConfig)).scalar_one_or_none()
        timeout_minutes = config.stuck_job_timeout_minutes if config else DEFAULT_TIMEOUT_MINUTES
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

        candidate_ids = list(
            session.execute(
                select(Upload.id).where(
                    Upload.status == "processing",
                    Upload.created_at < cutoff,
                )
            ).scalars()
        )
    finally:
        session.close()

    for upload_id in candidate_ids:
        _mark_stuck_one(upload_id)


def _mark_stuck_one(upload_id: uuid.UUID) -> None:
    session = SessionLocal()
    try:
        upload = session.execute(
            select(Upload).where(Upload.id == upload_id).with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if upload is None:
            return

        if upload.status != "processing":
            session.rollback()  # pipeline finished (or already swept) since the outer query ran
            return

        upload.status = "error"
        upload.error_detail = "pipeline timeout"
        record(
            session,
            user_id=None,
            action=f"Marked upload {upload_id} as error (pipeline timeout)",
            target_type="upload",
            target_id=upload.id,
            details={"status": {"from": "processing", "to": "error"}},
        )
        session.commit()
    finally:
        session.close()
