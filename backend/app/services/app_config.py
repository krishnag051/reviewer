"""Round 56: app_config is a singleton row (see AppConfig's own docstring) --
these helpers assume seed.py's bootstrap already created it, same assumption
app/services/rules.py's increment_pending_change_count makes about
rule_sync_state.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import AppConfig

SupportingDocMode = str  # "document" | "structured_form" -- see supporting_doc_mode_enum


def get_app_config(session: Session) -> AppConfig:
    config = session.execute(select(AppConfig)).scalar_one_or_none()
    if config is None:
        raise RuntimeError("app_config singleton is missing -- scripts/seed.py was never run")
    return config


def set_supporting_doc_mode(
    session: Session, mode: SupportingDocMode, *, actor_user_id: uuid.UUID,
) -> AppConfig:
    """Live-switchable feature flag (Developer Mode/admin settings) --
    controls which upload path new uploads take from this point forward.
    Does not touch any existing upload's already-stored data either way.
    Does not commit -- caller controls the transaction boundary, same
    convention as every other mutating service in this codebase.
    """
    config = get_app_config(session)
    old_mode = config.supporting_doc_mode
    if old_mode == mode:
        return config  # no-op, matches set_rule_active's already-in-state convention

    config.supporting_doc_mode = mode
    record(
        session,
        user_id=actor_user_id,
        action=f"Changed supporting_doc_mode from {old_mode} to {mode}",
        target_type="app_config",
        target_id=config.id,
        details={"supporting_doc_mode": {"from": old_mode, "to": mode}},
    )
    return config
