import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.base import get_db
from app.db.models import Patient, User, Version
from app.deps import get_current_user

router = APIRouter(prefix="/patients", tags=["patients"], dependencies=[Depends(get_current_user)])


class PatientCreate(BaseModel):
    reference_id: str
    name: str
    payor: str | None = None


class PatientUpdate(BaseModel):
    name: str | None = None
    # Accepted only so it can be checked-and-rejected if it differs from the
    # current value — reference_id is immutable. Echoing the same value back
    # is tolerated (common "resend the whole object" client pattern).
    reference_id: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reference_id: str
    name: str
    payor: str | None
    created_at: datetime


class PatientListItem(BaseModel):
    id: uuid.UUID
    reference_id: str
    name: str
    payor: str | None
    latest_version_number: int | None
    score: float | None
    audit_result: str | None
    reviewed: bool | None


@router.get("", response_model=list[PatientListItem])
def list_patients(db: Session = Depends(get_db)) -> list[PatientListItem]:
    patients = db.execute(select(Patient).order_by(Patient.reference_id)).scalars().all()
    items = []
    for patient in patients:
        latest = db.execute(
            select(Version)
            .where(Version.patient_id == patient.id)
            .order_by(Version.version_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        items.append(
            PatientListItem(
                id=patient.id,
                reference_id=patient.reference_id,
                name=patient.name,
                payor=patient.payor,
                latest_version_number=latest.version_number if latest else None,
                score=float(latest.score) if latest is not None and latest.score is not None else None,
                audit_result=latest.audit_result if latest else None,
                reviewed=latest.reviewed if latest else None,
            )
        )
    return items


@router.post("", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    body: PatientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Patient:
    existing = db.execute(select(Patient).where(Patient.reference_id == body.reference_id)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"reference_id {body.reference_id} already exists"
        )

    patient = Patient(reference_id=body.reference_id, name=body.name, payor=body.payor)
    db.add(patient)
    db.flush()  # assigns patient.id

    record(
        db,
        user_id=current_user.id,
        action=f"Created patient {body.reference_id}",
        target_type="patient",
        target_id=patient.id,
        details={
            "reference_id": {"from": None, "to": body.reference_id},
            "name": {"from": None, "to": body.name},
        },
    )

    db.commit()
    db.refresh(patient)
    return patient


@router.patch("/{patient_id}", response_model=PatientOut)
def update_patient(
    patient_id: uuid.UUID,
    body: PatientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient not found")

    requested = body.model_dump(exclude_unset=True)

    # reference_id is immutable — reject a genuine change attempt in the
    # handler (backstop: the DB trigger blocks it too, if this were ever
    # bypassed). Echoing the unchanged value back is not a "change".
    if "reference_id" in requested and requested["reference_id"] != patient.reference_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="reference_id is immutable and cannot be changed",
        )
    requested.pop("reference_id", None)

    diff = {
        field: {"from": getattr(patient, field), "to": new_value}
        for field, new_value in requested.items()
        if getattr(patient, field) != new_value
    }
    if not diff:
        return patient

    for field, change in diff.items():
        setattr(patient, field, change["to"])

    record(
        db,
        user_id=current_user.id,
        action=f"Updated patient {patient.reference_id}",
        target_type="patient",
        target_id=patient.id,
        details=diff,
    )

    db.commit()
    db.refresh(patient)
    return patient
