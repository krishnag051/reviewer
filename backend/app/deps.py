import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = db.get(User, uuid.UUID(sub))
    if user is None or not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # Checks the freshly-loaded DB row's role, NOT the JWT's embedded role
    # claim. A demoted admin's still-valid token must lose admin access
    # immediately on the next request, not silently keep it for up to the
    # remaining 12h of the token's life.
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


def require_developer(current_user: User = Depends(get_current_user)) -> User:
    # Same freshly-loaded-row discipline as require_admin. Gates the Round 49
    # dev-only simulated-completion route -- a real BCBA/reviewer account is
    # never provisioned with the `developer` role (scripts/seed.py seeds none;
    # it's created only via POST /admin/users), so this is never reachable
    # from the normal review workflow, only for whoever's doing dev/
    # diagnostics work and was deliberately given that role.
    if current_user.role != "developer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Developer role required")
    return current_user
