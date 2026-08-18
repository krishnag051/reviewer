import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.base import get_db
from app.db.models import User
from app.deps import get_current_user, require_admin
from app.security import hash_password
from app.services.app_config import get_app_config, set_notification_settings, set_supporting_doc_mode

# Admin-provisioned accounts only -- CLAUDE.md's Auth invariant ("No public
# signup route. Users are created only via POST /admin/users") is unchanged
# by Round 41's role rework; this router is that route, finally built (it
# was described in CLAUDE.md before this round but never actually existed).
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])

# Round 56: GET/PATCH app-config need to be reachable by developer accounts
# too (the round's own ask: "switchable from Developer Mode / admin
# settings"), unlike every other route in this router -- so these two
# declare their OWN dependency instead of relying on the router-level
# require_admin above.
config_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])


def _require_admin_or_developer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in ("admin", "developer"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin or developer role required")
    return current_user

UserRole = Literal["admin", "user", "developer"]


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: UserRole
    credential_title: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    credential_title: str | None
    active: bool
    created_at: datetime


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> User:
    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"email {body.email} already exists")

    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        credential_title=body.credential_title,
        active=True,
    )
    db.add(user)
    db.flush()  # assigns user.id

    record(
        db,
        user_id=current_user.id,
        action=f"Created user {body.email} (role={body.role})",
        target_type="user",
        target_id=user.id,
        details={
            "email": {"from": None, "to": body.email},
            "role": {"from": None, "to": body.role},
        },
    )

    db.commit()
    db.refresh(user)
    return user


# --------------------------------------------------------------- app-config

SupportingDocMode = Literal["document", "structured_form"]


class AppConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    supporting_doc_mode: SupportingDocMode
    retention_days: int
    # Deployment round: the real "From" name/address/default-CC a
    # correction email actually sends with -- previously NULL with no way
    # to set them except a direct DB write. Surfaced here so Admin
    # Settings can show/edit the real values, not hide them.
    notif_from_name: str | None
    notif_from_address: str | None
    notif_default_cc: str | None
    # Deployment round, Part 2: a real, pre-existing column with no other
    # reader in this codebase yet -- see set_notification_settings' own
    # docstring. Surfaced so the "Require manual review before sending"
    # toggle has a real value to load/persist, even though flipping it
    # doesn't yet gate any actual send behavior.
    auto_send: bool


class SupportingDocModeUpdate(BaseModel):
    supporting_doc_mode: SupportingDocMode


class NotificationSettingsUpdate(BaseModel):
    # None means "leave unchanged" for that one field -- a PATCH, not a
    # full replace; matches this file's own existing PATCH semantics.
    notif_from_name: str | None = None
    notif_from_address: str | None = None
    notif_default_cc: str | None = None
    auto_send: bool | None = None


@config_router.get("/app-config", response_model=AppConfigOut)
def get_app_config_route(db: Session = Depends(get_db)) -> object:
    """Readable by any authenticated role -- same relaxation Rules Studio's
    GET already has (Round 50), matching the pre-existing convention of
    "anyone can see config, only admin/developer can change it".
    """
    return get_app_config(db)


@config_router.patch("/app-config", response_model=AppConfigOut)
def update_supporting_doc_mode_route(
    body: SupportingDocModeUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin_or_developer),
) -> object:
    config = set_supporting_doc_mode(db, body.supporting_doc_mode, actor_user_id=current_user.id)
    db.commit()
    db.refresh(config)
    return config


@config_router.patch("/app-config/notifications", response_model=AppConfigOut)
def update_notification_settings_route(
    body: NotificationSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin_or_developer),
) -> object:
    """Deployment round: the real "From" name/address/default-CC a
    correction email sends with -- see set_notification_settings' own
    docstring for why this didn't exist before. Separate sub-path from the
    existing /app-config PATCH (which only ever handled supporting_doc_mode)
    rather than overloading that route's single-purpose body shape.
    """
    config = set_notification_settings(
        db,
        notif_from_name=body.notif_from_name,
        notif_from_address=body.notif_from_address,
        notif_default_cc=body.notif_default_cc,
        auto_send=body.auto_send,
        actor_user_id=current_user.id,
    )
    db.commit()
    db.refresh(config)
    return config
