import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(*, user_id: uuid.UUID, role: str) -> str:
    """role is embedded per the auth decision in CLAUDE.md, but it is a
    convenience claim only — authorization dependencies re-check the current
    DB row's role, never trust this claim, since it can go stale for up to
    the token's 12h lifetime if a user's role changes mid-session.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) on invalid/expired tokens —
    callers must catch that, not let it propagate as an unhandled 500."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
