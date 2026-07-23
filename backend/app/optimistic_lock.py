from datetime import datetime

from fastapi import HTTPException, status


def check_not_stale(current_updated_at: datetime, client_updated_at: datetime) -> None:
    """Optimistic-lock guard, shared by every PATCH endpoint whose body carries
    the row's updated_at token. Call this FIRST, before applying any field —
    on mismatch, raise 409 and apply nothing; the caller refreshes and retries.
    Never skip this to "save a round trip" — the whole point is rejecting a
    stale edit before it touches the row.
    """
    if current_updated_at != client_updated_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "stale_update",
                "message": "This record changed since you loaded it. Refresh and try again.",
                "current_updated_at": current_updated_at.isoformat(),
            },
        )
