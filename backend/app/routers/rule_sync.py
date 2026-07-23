from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import RuleSyncState, User
from app.deps import get_current_user

router = APIRouter(prefix="/rule-sync", tags=["rule-sync"])


class RuleSyncStatus(BaseModel):
    pending_change_count: int
    next_sync_at: datetime | None


@router.get("/status", response_model=RuleSyncStatus)
def get_rule_sync_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # any authenticated user — powers the frontend banner
) -> RuleSyncStatus:
    sync_state = db.execute(select(RuleSyncState)).scalar_one_or_none()
    if sync_state is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="rule sync not yet bootstrapped"
        )
    return RuleSyncStatus(
        pending_change_count=sync_state.pending_change_count,
        next_sync_at=sync_state.next_sync_at,
    )
