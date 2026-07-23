import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import RuleSyncState
from app.services.retention import run_retention_sweep
from app.services.rule_sync import run_sync_tick
from app.services.stuck_jobs import run_stuck_job_sweep

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_MINUTES = 30  # used only if rule_sync_state hasn't been seeded yet
STUCK_JOB_SWEEP_INTERVAL_MINUTES = 10
RETENTION_SWEEP_HOUR_UTC = 3  # once daily, off-peak


def _current_sync_interval_minutes() -> int:
    session = SessionLocal()
    try:
        sync_state = session.execute(select(RuleSyncState)).scalar_one_or_none()
        return sync_state.sync_interval_minutes if sync_state else DEFAULT_SYNC_INTERVAL_MINUTES
    finally:
        session.close()


def _sync_tick_job() -> None:
    session = SessionLocal()
    try:
        run_sync_tick(session)
    except Exception:
        logger.exception("Sync tick failed")
        session.rollback()
    finally:
        session.close()


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")

    # max_instances=1 on every job: if a run is still in flight when the next
    # firing comes due, the scheduler skips that firing rather than starting
    # a second overlapping run in the same process. coalesce=True means a
    # backlog of missed firings (e.g. process was asleep) collapses into a
    # single catch-up run instead of firing once per missed interval.
    scheduler.add_job(
        _sync_tick_job,
        trigger=IntervalTrigger(minutes=_current_sync_interval_minutes()),
        id="rule_sync_tick",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_retention_sweep,
        trigger="cron",
        hour=RETENTION_SWEEP_HOUR_UTC,
        id="retention_sweep",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        run_stuck_job_sweep,
        trigger=IntervalTrigger(minutes=STUCK_JOB_SWEEP_INTERVAL_MINUTES),
        id="stuck_job_sweep",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    return scheduler
