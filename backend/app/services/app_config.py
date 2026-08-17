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


def set_notification_settings(
    session: Session,
    *,
    notif_from_name: str | None,
    notif_from_address: str | None,
    notif_default_cc: str | None,
    actor_user_id: uuid.UUID,
) -> AppConfig:
    """Deployment round: the "From" name/address/default-CC a correction
    email actually sends with (app/services/mailer.py::send_email reads
    these three straight off this row) had no way to be set except a
    direct DB write -- confirmed via search, no admin endpoint or seed
    default existed for them. Same pattern as set_supporting_doc_mode
    above: per-field no-op check, real audit diff, caller controls the
    transaction boundary. `None` for any of the three fields means "leave
    it unchanged" (a PATCH updating only some fields), not "clear it" --
    matching this endpoint's own PATCH semantics elsewhere in this file.
    """
    config = get_app_config(session)
    changes: dict[str, dict[str, str | None]] = {}

    if notif_from_name is not None and notif_from_name != config.notif_from_name:
        changes["notif_from_name"] = {"from": config.notif_from_name, "to": notif_from_name}
        config.notif_from_name = notif_from_name
    if notif_from_address is not None and notif_from_address != config.notif_from_address:
        changes["notif_from_address"] = {"from": config.notif_from_address, "to": notif_from_address}
        config.notif_from_address = notif_from_address
    if notif_default_cc is not None and notif_default_cc != config.notif_default_cc:
        changes["notif_default_cc"] = {"from": config.notif_default_cc, "to": notif_default_cc}
        config.notif_default_cc = notif_default_cc

    if not changes:
        return config  # no-op, same convention as set_supporting_doc_mode above

    record(
        session,
        user_id=actor_user_id,
        action="Changed notification (outbound email) settings",
        target_type="app_config",
        target_id=config.id,
        details=changes,
    )
    return config
