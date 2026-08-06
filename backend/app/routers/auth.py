import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.deps import get_current_user
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    role: str
    credential_title: str | None
    created_at: datetime


@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenResponse:
    """form.username is the user's email — OAuth2PasswordRequestForm's field
    is always named 'username', but this system has no separate username
    concept, so email fills that slot.
    """
    user = db.execute(select(User).where(User.email == form.username)).scalar_one_or_none()
    if user is None or not user.active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")

    token = create_access_token(user_id=user.id, role=user.role)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=MeOut)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    """The frontend's source of truth for "who am I / what role am I" after
    login — reads the fresh DB row via get_current_user, not the JWT's own
    role claim, which is a convenience claim only and can go stale for up
    to the token's 12h lifetime if a role changes mid-session (see
    security.py's create_access_token docstring). Role-gated UI (Developer
    Mode) should key off THIS, not off decoding the token client-side.
    """
    return current_user
