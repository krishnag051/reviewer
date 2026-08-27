import uuid
from datetime import datetime, timezone
from typing import Literal

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
    active: bool
    deactivated_at: datetime | None


class PatientListItem(BaseModel):
    id: uuid.UUID
    reference_id: str
    name: str
    payor: str | None
    latest_version_number: int | None
    score: float | None
    audit_result: str | None
    reviewed: bool | None
    active: bool


@router.get("", response_model=list[PatientListItem])
def list_patients(
    status_filter: Literal["active", "archived", "all"] = "active",
    db: Session = Depends(get_db),
) -> list[PatientListItem]:
    """Part 6, Fix Round: defaults to active-only, matching every existing
    caller's own expectation of "the patient list" unchanged -- a deactivated
    patient genuinely stops showing up here by default, without needing a
    query param anyone has to remember to pass. `status_filter=archived` is
    the dedicated view for deactivated patients; `all` is available for
    anything that genuinely needs both (not currently used by the frontend,
    kept for completeness/future use)."""
    query = select(Patient).order_by(Patient.reference_id)
    if status_filter == "active":
        query = query.where(Patient.active.is_(True))
    elif status_filter == "archived":
        query = query.where(Patient.active.is_(False))
    patients = db.execute(query).scalars().all()
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
                active=patient.active,
            )
        )
    return items


@router.post("/{patient_id}/deactivate", response_model=PatientOut)
def deactivate_patient(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Patient:
    """Part 6, Fix Round: reversible archive, same access level as finalize
    (any authenticated user -- no extra role gate beyond being logged in,
    matching every other mutating endpoint on this router). Never a hard
    delete -- flips `active`, same convention as uploads.voided."""
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient not found")
    if not patient.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="patient is already deactivated")

    patient.active = False
    patient.deactivated_by = current_user.id
    patient.deactivated_at = datetime.now(timezone.utc)

    record(
        db,
        user_id=current_user.id,
        action=f"Deactivated patient {patient.reference_id}",
        target_type="patient",
        target_id=patient.id,
        details={"active": {"from": True, "to": False}},
    )

    db.commit()
    db.refresh(patient)
    return patient


@router.post("/{patient_id}/reactivate", response_model=PatientOut)
def reactivate_patient(
    patient_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Patient:
    """The reverse of deactivate -- the whole point of this being a flag,
    not a delete, is that this is always possible."""
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="patient not found")
    if patient.active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="patient is already active")

    patient.active = True
    patient.deactivated_by = None
    patient.deactivated_at = None

    record(
        db,
        user_id=current_user.id,
        action=f"Reactivated patient {patient.reference_id}",
        target_type="patient",
        target_id=patient.id,
        details={"active": {"from": False, "to": True}},
    )

    db.commit()
    db.refresh(patient)
    return patient


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
