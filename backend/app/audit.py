import uuid

from sqlalchemy.orm import Session

from app.db.models import AuditLog


def record(
    session: Session,
    *,
    user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID,
    details: dict,
) -> AuditLog:
    """The single shared audit-write helper — every mutating service calls this,
    inside its own transaction, never a separate commit. user_id=None only for
    scheduled/system jobs (sync tick, retention, seeding), never for a
    user-initiated action.
    """
    entry = AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    )
    session.add(entry)
    session.flush()
    return entry
