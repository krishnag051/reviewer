import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.config import settings
from app.db.base import get_db
from app.db.models import GeneratedEmail, Patient, Upload, User, Version
from app.deps import get_current_user, require_developer
from app.services.app_config import get_app_config
from app.services.correction_email import generate_correction_email
from app.services.simulated_pipeline import simulate_upload_completion
from app.services.upload_pipeline import run_upload_pipeline
from app.services.uploads import create_upload, get_latest_intake_answers
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


def _missing_field_422(field: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[{"loc": ["body", field], "msg": "field required", "type": "missing"}],
    )


@router.post("/versions/{version_id}/uploads", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def create_upload_route(
    version_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    # Round 51: the mandatory second ("supporting document") file --
    # required ONLY under supporting_doc_mode="document" (Round 56 made
    # this Optional at the schema level so the structured_form-mode
    # request shape below doesn't need to send a dummy file; requiredness
    # for "document" mode is now enforced in the body below instead of via
    # `File(...)`'s own automatic 422). Never fed into the pipeline —
    # display-only (GET /uploads/:id/supporting-file); parsing/extraction
    # is a deliberately deferred future round, independent of which mode
    # is active.
    supporting_document: UploadFile | None = File(None),
    # Round 56: the structured_form-mode alternative -- 5 plain-text
    # answers + 1+ session-note files, required ONLY under
    # supporting_doc_mode="structured_form". Kept as exactly these 5 named
    # fields (no generic dict) so a malformed/renamed field 422s clearly
    # rather than silently vanishing into an unrecognized key.
    client_insurance: str | None = Form(None),
    bcba_name_credentials_npi: str | None = Form(None),
    authorization_dates: str | None = Form(None),
    pos_schedule_vs_97153_hours: str | None = Form(None),
    hours_requesting: str | None = Form(None),
    session_notes: list[UploadFile] = File([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Upload:
    mode = get_app_config(db).supporting_doc_mode

    supporting_document_filename: str | None = None
    supporting_document_content: bytes | None = None
    intake_answers: dict[str, str] | None = None
    session_note_tuples: list[tuple[str, bytes]] | None = None

    if mode == "document":
        if supporting_document is None:
            raise _missing_field_422("supporting_document")
        supporting_document_filename = supporting_document.filename or "supporting-document.pdf"
        supporting_document_content = supporting_document.file.read()
    else:  # "structured_form"
        qa_fields = {
            "client_insurance": client_insurance,
            "bcba_name_credentials_npi": bcba_name_credentials_npi,
            "authorization_dates": authorization_dates,
            "pos_schedule_vs_97153_hours": pos_schedule_vs_97153_hours,
            "hours_requesting": hours_requesting,
        }
        for field_name, value in qa_fields.items():
            if value is None or not value.strip():
                raise _missing_field_422(field_name)
        if not session_notes:
            raise _missing_field_422("session_notes")
        intake_answers = qa_fields
        session_note_tuples = [(f.filename or "session-note.pdf", f.file.read()) for f in session_notes]

    content = file.file.read()
    upload = create_upload(
        db,
        version_id,
        filename=file.filename or "upload.pdf",
        content=content,
        supporting_document_filename=supporting_document_filename,
        supporting_document_content=supporting_document_content,
        intake_answers=intake_answers,
        session_notes=session_note_tuples,
        uploaded_by=current_user.id,
    )
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    db.refresh(upload)

    background_tasks.add_task(run_upload_pipeline, upload.id)

    return upload


class LatestIntakeAnswersOut(BaseModel):
    client_insurance: str
    bcba_name_credentials_npi: str
    authorization_dates: str
    pos_schedule_vs_97153_hours: str
    hours_requesting: str


@router.get("/patients/{patient_id}/latest-intake-answers", response_model=LatestIntakeAnswersOut | None)
def get_latest_intake_answers_route(patient_id: uuid.UUID, db: Session = Depends(get_db)) -> object | None:
    """Round 56, Item 2's "editable across versions" -- the structured Q&A
    form's prefill source. Returns null (not 404) when this patient has no
    prior structured-mode upload yet -- that's the ordinary "first
    submission" case, not an error.
    """
    return get_latest_intake_answers(db, patient_id)


@router.post("/versions/{version_id}/uploads/simulate", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
def create_simulated_upload_route(
    version_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_developer),
) -> Upload:
    """Dev-only (Round 49) -- creates a real Upload row via the same
    create_upload service the real route uses (real blob storage, real
    sequential upload_number, real audit entry), but the background task is
    app.services.simulated_pipeline.simulate_upload_completion instead of
    the real run_upload_pipeline -- never calls review_treatment_plan, never
    reaches the real Anthropic API, by construction (that module has no
    import path to app.rule_engine.client at all).

    Double-gated, both required: `require_developer` (a real BCBA/reviewer
    account is never provisioned with the developer role) AND
    `settings.allow_simulated_completion` (off by default in every
    environment; someone has to deliberately set
    ALLOW_SIMULATED_COMPLETION=true). Neither condition is reachable from
    the normal login flow a real reviewer uses.
    """
    if not settings.allow_simulated_completion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="simulated completion is disabled (set ALLOW_SIMULATED_COMPLETION=true to enable this dev-only route)",
        )

    content = file.file.read()
    # Round 51: create_upload now requires a second (supporting document)
    # file -- this dev-only route stays single-file in its own request
    # shape (unchanged UX for the "Simulate completion" checkbox) and
    # supplies a synthetic placeholder for the shared service call instead
    # of asking a developer to pick a second file for a simulated run.
    upload = create_upload(
        db,
        version_id,
        filename=file.filename or "simulated.pdf",
        content=content,
        supporting_document_filename="simulated-supporting-document.pdf",
        supporting_document_content=b"%PDF-1.4\n(SIMULATED supporting document -- dev-only, not a real file)\n%%EOF",
        uploaded_by=current_user.id,
    )
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="version not found")
    db.refresh(upload)

    background_tasks.add_task(simulate_upload_completion, upload.id)

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
