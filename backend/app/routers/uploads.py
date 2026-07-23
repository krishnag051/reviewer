import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import Upload, User
from app.deps import get_current_user
from app.services.diff import compute_diff
from app.services.finalize import finalize_upload
from app.services.uploads import void_upload

router = APIRouter(prefix="/uploads", tags=["uploads"], dependencies=[Depends(get_current_user)])


class RuleResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    rule_id: uuid.UUID
    rule_version_used: int
    final_status: str
    final_finding: str
    final_pages: list[int]
    is_overridden: bool
    updated_at: datetime


class UploadDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_id: uuid.UUID
    upload_number: int
    is_final: bool
    voided: bool
    status: str
    error_detail: str | None
    rules_snapshot_id: uuid.UUID | None
    created_at: datetime
    rule_results: list[RuleResultOut]


class FinalizeBody(BaseModel):
    reference_id: str


class VoidBody(BaseModel):
    reason: str


class DiffEntryOut(BaseModel):
    rule_id: uuid.UUID
    rule_code: str
    this_status: str | None
    against_status: str | None
    was_overridden_previously: bool


class DiffOut(BaseModel):
    upload_id: uuid.UUID
    against_upload_id: uuid.UUID
    fixed: list[DiffEntryOut]
    newly_broken: list[DiffEntryOut]
    still_failing: list[DiffEntryOut]
    unchanged_pass: list[DiffEntryOut]
    other: list[DiffEntryOut]
    rules_changed: list[DiffEntryOut]


@router.get("/{upload_id}", response_model=UploadDetailOut)
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> Upload:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    return upload


@router.post("/{upload_id}/finalize", response_model=UploadDetailOut)
def finalize_upload_route(
    upload_id: uuid.UUID,
    body: FinalizeBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Upload:
    upload = finalize_upload(
        db, upload_id, reference_id=body.reference_id, actor_user_id=current_user.id
    )
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    db.refresh(upload)
    return upload


@router.post("/{upload_id}/void", response_model=UploadDetailOut)
def void_upload_route(
    upload_id: uuid.UUID,
    body: VoidBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Upload:
    upload = void_upload(db, upload_id, reason=body.reason, actor_user_id=current_user.id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    db.refresh(upload)
    return upload


@router.get("/{upload_id}/diff", response_model=DiffOut)
def diff_uploads_route(
    upload_id: uuid.UUID,
    against: uuid.UUID,
    db: Session = Depends(get_db),
) -> dict:
    result = compute_diff(db, upload_id, against)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    return result
