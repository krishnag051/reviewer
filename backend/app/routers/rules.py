import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Rule, User
from app.deps import require_admin
from app.services.rules import create_rule, edit_rule, set_rule_active

router = APIRouter(prefix="/rules", tags=["rules"], dependencies=[Depends(require_admin)])

RuleType = Literal["structural", "semantic", "cross_reference"]


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_code: str
    category: str
    question_set: str
    question_text: str
    rule_type: RuleType
    active: bool
    current_version: int


class RuleCreate(BaseModel):
    rule_code: str
    category: str
    question_set: str
    question_text: str
    rule_type: RuleType
    active: bool = True


class RuleUpdate(BaseModel):
    category: str | None = None
    question_set: str | None = None
    question_text: str | None = None
    rule_type: RuleType | None = None


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)) -> list[Rule]:
    return list(db.execute(select(Rule).order_by(Rule.rule_code)).scalars().all())


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def post_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Rule:
    existing = db.execute(select(Rule).where(Rule.rule_code == body.rule_code)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"rule_code {body.rule_code} already exists")

    rule = create_rule(db, actor_user_id=current_user.id, **body.model_dump())
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=RuleOut)
def patch_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> Rule:
    rule = edit_rule(db, rule_id, changes=body.model_dump(exclude_unset=True), actor_user_id=current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/{rule_id}/deactivate", response_model=RuleOut)
def deactivate_rule(
    rule_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(require_admin)
) -> Rule:
    rule = set_rule_active(db, rule_id, False, actor_user_id=current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    db.commit()
    db.refresh(rule)
    return rule


@router.post("/{rule_id}/reactivate", response_model=RuleOut)
def reactivate_rule(
    rule_id: uuid.UUID, db: Session = Depends(get_db), current_user: User = Depends(require_admin)
) -> Rule:
    rule = set_rule_active(db, rule_id, True, actor_user_id=current_user.id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="rule not found")
    db.commit()
    db.refresh(rule)
    return rule
