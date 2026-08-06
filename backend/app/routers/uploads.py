import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.db.models import SessionNoteFile, Upload, User
from app.deps import get_current_user
from app.services.diff import compute_diff
from app.services.finalize import finalize_upload
from app.services.uploads import void_upload
from app.storage import resolve_stored_path

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


class IntakeAnswersOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_insurance: str
    bcba_name_credentials_npi: str
    authorization_dates: str
    pos_schedule_vs_97153_hours: str
    hours_requesting: str


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
    # Round 57: reuses the SAME upload.intake_answers relationship Round
    # 56's prefill endpoint (GET /patients/:id/latest-intake-answers)
    # already reads -- additive field on this EXISTING, already-fetched-
    # by-the-review-page endpoint, not a new one. None for a "document"-
    # mode upload (past or present) -- that's exactly the per-upload signal
    # the frontend uses to decide "Intake Q&A" (structured_form) vs.
    # "Helping Document" (document) button behavior, since it reflects
    # what THIS upload actually was, independent of whatever the live
    # supporting_doc_mode flag currently says.
    intake_answers: IntakeAnswersOut | None


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


@router.get("/{upload_id}/file")
def get_upload_file(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    if not upload.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    # Round 58: resolve_stored_path anchors a relative stored path (every
    # row saved before this round) to the backend/ directory instead of
    # trusting the server process's own cwd -- see storage.py's docstring
    # for the real bug this fixes (a genuinely present, unpurged file
    # reported "no longer available" purely because of where the process
    # happened to be launched from).
    resolved = resolve_stored_path(upload.file_path)
    if upload.file_purged or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    return FileResponse(
        resolved,
        media_type="application/pdf",
        filename=f"upload-{upload.upload_number}.pdf",
    )


@router.get("/{upload_id}/supporting-file")
def get_upload_supporting_file(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    """Round 51 — mirrors get_upload_file above exactly, for the mandatory
    second ("supporting document") file. Same auth guard (this router's
    dependencies=[Depends(get_current_user)]), same file_purged/exists
    checks, same retention lifecycle. Display-only: served as-is for a
    reviewer to open, never parsed or fed into the pipeline.
    """
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    if not upload.supporting_document_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    resolved = resolve_stored_path(upload.supporting_document_path)
    if upload.file_purged or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    return FileResponse(
        resolved,
        media_type="application/pdf",
        filename=f"upload-{upload.upload_number}-supporting.pdf",
    )


class SessionNoteFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    original_filename: str
    created_at: datetime


class SessionNotesPageOut(BaseModel):
    """Round 57, Item 2: the session-notes page was showing filename/upload
    date only, with no indication of WHICH patient these notes belong to
    (only inferable, unreliably, from filename text). Wraps the file list
    with the patient identity this upload actually belongs to -- via
    upload.version.patient, both relationships that already exist, no new
    join/query logic invented.
    """
    patient_name: str
    patient_reference_id: str
    files: list[SessionNoteFileOut]


@router.get("/{upload_id}/session-notes", response_model=SessionNotesPageOut)
def list_session_notes(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Round 56, Item 4 -- backs the "Session Notes" new-tab page. File
    metadata is raw (filename, upload date) -- no inside/outside the TP's
    report-date-range split yet; that needs real date extraction from each
    note, which is deliberately deferred agent-side work (see
    session-notes.$uploadId.tsx's own placeholder copy). An empty `files`
    list is a normal, valid response (an old "document"-mode upload has
    none).
    """
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    return {
        "patient_name": upload.version.patient.name,
        "patient_reference_id": upload.version.patient.reference_id,
        "files": list(upload.session_note_files),
    }


@router.get("/{upload_id}/session-notes/{file_id}")
def get_session_note_file(upload_id: uuid.UUID, file_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    note = db.get(SessionNoteFile, file_id)
    if note is None or note.upload_id != upload_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session note not found")
    resolved = resolve_stored_path(note.file_path)
    if note.file_purged or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    return FileResponse(resolved, filename=note.original_filename)


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
