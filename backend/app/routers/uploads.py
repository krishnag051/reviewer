import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.agent_client import SessionNoteExtraction, extract_session_note
from app.config import settings
from app.db.base import get_db
from app.db.models import SessionNoteFile, Upload, User
from app.deps import get_current_user
from app.services.diff import compute_diff
from app.services.finalize import finalize_upload
from app.services.rule_ordering import sort_rule_results
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
    # Round 70: real, human-readable content the results panel needs to
    # match the Brellium reference pattern -- a plain-English question,
    # its category, and the stable rule code (never a bare rule_id UUID).
    # Sourced from RuleResult.question_text/category/rule_code (see that
    # model's own docstring) -- version-pinned to rule_version_used, not
    # whatever the rule's text has since been edited to.
    question_text: str
    category: str
    rule_code: str
    # The model layer's own original finding/pages, alongside final_* --
    # lets the UI show "the AI's original answer" distinctly from a
    # human's override, instead of only ever showing whichever one won.
    # Never written to from this API; PATCH /rule_results/:id still only
    # ever touches final_status/final_finding/final_pages (see CLAUDE.md's
    # model-layer-immutable invariant).
    model_status: str
    model_finding: str
    model_pages: list[int]
    # Next Round, Part 2: the pre-humanize "raw" text, alongside
    # model_finding (now the humanized text) -- display-only, same as the
    # other model_* fields above; never written to from this API. None
    # for any rule_result created before this round's migration (no real
    # "pre" text exists for those -- see the migration's own docstring).
    model_finding_raw: str | None = None


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
    # Round 70, Item 2: {"physical_page_number": "printed_label"} for pages
    # where a printed label was actually found -- see
    # app/services/page_labels.py. Frontend cross-checks/displays with
    # this; page-jump navigation itself still targets the physical page
    # number already in final_pages/model_pages, not a translated value.
    page_label_map: dict[str, str]
    # Next Round (2026-08-27), Part 2 item 2: whether THIS upload has a
    # prior-TP file attached -- optional on every upload, so the frontend
    # needs a real presence flag (unlike supporting_document_path, always
    # present under "document" mode). Never the raw path itself.
    has_previous_tp: bool
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


def _to_upload_detail_out(upload: Upload) -> UploadDetailOut:
    """Next Round, Part 3: the ONE place every route below builds its
    UploadDetailOut response, so the fixed rule-list order (this TP's own
    payor-specific rules, then Template, then the fixed 20-category order
    -- see app/services/rule_ordering.py) is applied identically on every
    endpoint that can hand back an upload's rule_results, not just GET.
    `model_validate` first (from_attributes, picks up every field as-is,
    including rule_results in the relationship's own created_at order),
    then override rule_results with the real sorted order.
    """
    detail = UploadDetailOut.model_validate(upload)
    payor = upload.version.payor if upload.version else None
    sorted_results = sort_rule_results(upload.rule_results, payor)
    detail.rule_results = [RuleResultOut.model_validate(rr) for rr in sorted_results]
    return detail


@router.get("/{upload_id}", response_model=UploadDetailOut)
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> UploadDetailOut:
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    return _to_upload_detail_out(upload)


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


@router.get("/{upload_id}/previous-tp-file")
def get_upload_previous_tp_file(upload_id: uuid.UUID, db: Session = Depends(get_db)) -> FileResponse:
    """Next Round (2026-08-27), Part 2 item 2 -- mirrors
    get_upload_supporting_file above exactly, for the new OPTIONAL prior-TP
    slot. Same auth guard, same file_purged/exists checks, same retention
    lifecycle. 404 (not a different status) when this upload simply never
    had a previous TP attached -- same as any other "file no longer
    available" case, so the frontend doesn't need a separate code path to
    distinguish "never uploaded" from "purged."
    """
    upload = db.get(Upload, upload_id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    if not upload.previous_tp_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    resolved = resolve_stored_path(upload.previous_tp_path)
    if upload.file_purged or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    return FileResponse(
        resolved,
        media_type="application/pdf",
        filename=f"upload-{upload.upload_number}-previous-tp.pdf",
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


@router.get("/{upload_id}/session-notes/{file_id}/extraction", response_model=SessionNoteExtraction)
def get_session_note_extraction(upload_id: uuid.UUID, file_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionNoteExtraction:
    """Round 79, Item 2 -- real extracted fields (session_date/session_
    location/clinician_telehealth_location/patient_telehealth_location/
    assessment_activity) for one session-note file, straight from
    agent-making's real Round 59 extraction step via
    app.agent_client.extract_session_note. Deliberately still the free
    OpenRouter tier (model_override="openrouter"), matching every other
    session-notes-related real call site in this backend (see
    app/rule_engine/client.py's own comment on this) -- never real
    Anthropic for this display-only feature. Cached by agent-making's own
    content hash, so re-viewing an already-extracted file costs nothing.
    """
    note = db.get(SessionNoteFile, file_id)
    if note is None or note.upload_id != upload_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session note not found")
    resolved = resolve_stored_path(note.file_path)
    if note.file_purged or not resolved.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="file no longer available")
    return extract_session_note(
        str(resolved), model_override="openrouter", max_calls=settings.session_notes_max_calls,
    )


@router.post("/{upload_id}/finalize", response_model=UploadDetailOut)
def finalize_upload_route(
    upload_id: uuid.UUID,
    body: FinalizeBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadDetailOut:
    upload = finalize_upload(
        db, upload_id, reference_id=body.reference_id, actor_user_id=current_user.id
    )
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    db.refresh(upload)
    return _to_upload_detail_out(upload)


@router.post("/{upload_id}/void", response_model=UploadDetailOut)
def void_upload_route(
    upload_id: uuid.UUID,
    body: VoidBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadDetailOut:
    upload = void_upload(db, upload_id, reason=body.reason, actor_user_id=current_user.id)
    if upload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="upload not found")
    db.refresh(upload)
    return _to_upload_detail_out(upload)


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
