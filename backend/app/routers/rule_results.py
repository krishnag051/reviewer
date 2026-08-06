import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import RuleResult, User
from app.deps import get_current_user
from app.services.rule_results import override_rule_result

router = APIRouter(prefix="/rule_results", tags=["rule_results"], dependencies=[Depends(get_current_user)])

RuleResultStatus = Literal["pass", "fail", "na", "uncertain", "not_checkable"]


class RuleResultPatch(BaseModel):
    updated_at: datetime  # optimistic-lock token — the value the client's edit was based on
    final_status: RuleResultStatus | None = None
    final_finding: str | None = None
    final_pages: list[int] | None = None
    reason: str | None = None


class RuleResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    upload_id: uuid.UUID
    rule_id: uuid.UUID
    rule_version_used: int
    final_status: str
    final_finding: str
    final_pages: list[int]
    is_overridden: bool
    last_edited_by: uuid.UUID | None
    last_edited_at: datetime | None
    updated_at: datetime


@router.patch("/{rule_result_id}", response_model=RuleResultOut)
def override_rule_result_route(
    rule_result_id: uuid.UUID,
    body: RuleResultPatch,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RuleResult:
    requested = body.model_dump(exclude_unset=True)
    reason = requested.pop("reason", None)
    requested.pop("updated_at", None)

    rule_result = override_rule_result(
        db,
        rule_result_id,
        client_updated_at=body.updated_at,
        changes=requested,
        reason=reason,
        actor_user_id=current_user.id,
    )
    if rule_result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule_result not found")
    return rule_result
