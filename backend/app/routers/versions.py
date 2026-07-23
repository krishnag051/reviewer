import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.base import get_db
from app.db.models import GeneratedEmail, Patient, Upload, User, Version
from app.deps import get_current_user
from app.services.correction_email import generate_correction_email
from app.services.upload_pipeline import run_upload_pipeline
from app.services.uploads import create_upload
from app.services.versions import create_version, mark_reviewed

router = APIRouter(tags=["versions"], dependencies=[Depends(get_current_user)])


class VersionCreate(BaseModel):
    payor: str | None = None
    assessment_date: date | None = None


class VersionUpdate(BaseModel):
    reviewer_id: uuid.UUID | None = None
    assessment_date: date | None = None


class UploadOut(BaseModel):
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


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    patient_id: uuid.UUID
    version_number: int
    payor: str | None
    reviewer_id: uuid.UUID | None
    assessment_date: date | None
    status: str
    final_upload_id: uuid.UUID | None
    score: float | None
    audit_result: str | None
    finalized_at: datetime | None
    reviewed: bool
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class VersionDetailOut(VersionOut):
    uploads: list[UploadOut]


class CorrectionEmailRequest(BaseModel):
    upload_id: uuid.UUID | None = None
    routed_to: Literal["bcba", "qa", "clinical_director", "coordinator"]
    group_by: Literal["category", "page"] = "category"
    to_addr: str | None = None
    cc: str | None = None
    bcc: str | None = None


class GeneratedEmailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_id: uuid.UUID
    upload_id: uuid.UUID
    generated_by: uuid.UUID | None
    to_addr: str | None
    cc: str | None
    bcc: str | None
    subject: str
    body: str
    routed_to: str
    routed_by: uuid.UUID | None
    routed_at: datetime
    created_at: datetime


def _jsonable(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


@router.get("/patients/{patient_id}/versions", response_model=list[VersionOut])
def list_versions(patient_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Version]:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient not found")
    return list(
        db.execute(
            select(Version).where(Version.patient_id == patient_id).order_by(Version.version_number)
        ).scalars().all()
    )


@router.post("/patients/{patient_id}/versions", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
def create_version_route(
    patient_id: uuid.UUID,
    body: VersionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Version:
    version = create_version(
        db,
        patient_id,
        payor=body.payor,
        assessment_date=body.assessment_date,
        actor_user_id=current_user.id,
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient not found")
    db.refresh(version)
    return version


@router.get("/versions/{version_id}", response_model=VersionDetailOut)
def get_version(version_id: uuid.UUID, db: Session = Depends(get_db)) -> Version:
    version = db.get(Version, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    return version


@router.patch("/versions/{version_id}", response_model=VersionOut)
def update_version(
    version_id: uuid.UUID,
    body: VersionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Version:
    version = db.get(Version, version_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")

    requested = body.model_dump(exclude_unset=True)

    if "reviewer_id" in requested and requested["reviewer_id"] is not None:
        reviewer = db.get(User, requested["reviewer_id"])
        if reviewer is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reviewer_id does not exist")

    diff = {
        field: {"from": getattr(version, field), "to": new_value}
        for field, new_value in requested.items()
        if getattr(version, field) != new_value
    }
    if not diff:
        return version

    for field, change in diff.items():
        setattr(version, field, change["to"])

    audit_details = {f: {"from": _jsonable(c["from"]), "to": _jsonable(c["to"])} for f, c in diff.items()}
    record(
        db,
        user_id=current_user.id,
        action=f"Updated version {version.version_number}",
        target_type="version",
        target_id=version.id,
        details=audit_details,
    )

    db.commit()
    db.refresh(version)
    return version


@router.post("/versions/{version_id}/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def create_upload_route(
    version_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Upload:
    content = file.file.read()
    upload = create_upload(
        db,
        version_id,
        filename=file.filename or "upload.pdf",
        content=content,
        uploaded_by=current_user.id,
    )
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    db.refresh(upload)

    background_tasks.add_task(run_upload_pipeline, upload.id)

    return upload


@router.post("/versions/{version_id}/mark-reviewed", response_model=VersionOut)
def mark_reviewed_route(
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Version:
    version = mark_reviewed(db, version_id, actor_user_id=current_user.id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    db.refresh(version)
    return version


@router.post(
    "/versions/{version_id}/correction-email", response_model=GeneratedEmailOut, status_code=status.HTTP_201_CREATED
)
def generate_correction_email_route(
    version_id: uuid.UUID,
    body: CorrectionEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GeneratedEmail:
    email = generate_correction_email(
        db,
        version_id,
        upload_id=body.upload_id,
        routed_to=body.routed_to,
        group_by=body.group_by,
        to_addr=body.to_addr,
        cc=body.cc,
        bcc=body.bcc,
        actor_user_id=current_user.id,
    )
    if email is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    db.refresh(email)
    return email
