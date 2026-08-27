import logging
import uuid

from sqlalchemy import select

from app.agent_client import humanize_findings
from app.audit import record
from app.config import settings
from app.db.base import SessionLocal
from app.db.models import RuleResult, RuleSyncState, Upload
from app.rule_engine.client import run_rule_checks
from app.services.page_labels import extract_page_labels
from app.services.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


def run_upload_pipeline(upload_id: uuid.UUID) -> None:
    """Runs after POST /versions/:id/uploads returns — the upload row already
    exists with status=processing and its blob is already on disk (both
    committed by app.services.uploads.create_upload before this is called).
    Opens its own session, independent of the request's (this may run in a
    background task after the request's session has already closed).

    Steps 2-4 of the master doc's pipeline (parse, pin the snapshot, call the
    hollow rule_engine stub) are pure preparation — nothing is written to the
    DB during them. Step 5 is the one all-or-nothing transaction (gap C5):
    every rule_result plus status=ready commits together, or none of it does.
    On ANY failure — a parse error, a rule_engine error, a bad insert — we
    roll back whatever was pending, then write status=error + error_detail
    as a SEPARATE, fresh transaction. There is no path where some rule_
    results land but not others, or where status flips to ready without a
    complete result set.
    """
    session = SessionLocal()
    try:
        upload = session.get(Upload, upload_id)
        if upload is None:
            logger.error("run_upload_pipeline: upload %s not found", upload_id)
            return

        try:
            # ---- steps 2-4: preparation only, nothing persisted yet ----
            parsed_pages = parse_pdf(upload.file_path)
            low_text_pages = [p["page_number"] for p in parsed_pages if p["low_text"]]
            if low_text_pages:
                logger.warning(
                    "Upload %s: pages %s have near-zero extracted text — "
                    "flagged for OCR/vision fallback (not yet implemented)",
                    upload_id, low_text_pages,
                )

            sync_state = session.execute(select(RuleSyncState)).scalar_one()
            snapshot_id = sync_state.current_snapshot_id

            drafts = run_rule_checks(session, str(upload.id), str(snapshot_id), parsed_pages)

            # Round 70, Item 2: same parsed_pages already in hand, no second
            # PDF read -- see app/services/page_labels.py's own docstring.
            # JSONB keys must be strings; physical page numbers come back
            # from extract_page_labels as ints.
            page_label_map = {str(k): v for k, v in extract_page_labels(parsed_pages).items()}

            # Next Round, Part 2: real LLM humanize pass, now wired in.
            # ONE real call per non-empty finding (empty/N-A findings make
            # no real call at all -- see agent_client.humanize_finding's
            # own docstring), all sharing ONE call-tracker cap
            # (settings.humanize_max_calls) so a single upload can never
            # run away into an unbounded real bill.
            #
            # Humanize is a cosmetic post-process layer on top of the real
            # rule-checking results above, not part of rule-checking
            # itself. Fix Round (2026-08-27): humanize_findings itself now
            # isolates each finding's own attempt (see its own docstring
            # for the real crash this fixes) -- one bad model response
            # falls back to raw text for THAT finding only, every other
            # finding in the batch keeps its real result. This outer
            # try/except is now a last-resort net for something even more
            # catastrophic happening before/around the per-item loop
            # itself (e.g. the tracker failing to construct) -- expected
            # to fire rarely, if ever; when it does, every finding in this
            # upload falls back, same as before this round.
            finding_texts = [draft.model_finding or "" for draft in drafts]
            finding_labels = [draft.rule_id for draft in drafts]
            try:
                humanize_results = humanize_findings(
                    finding_texts, max_calls=settings.humanize_max_calls, labels=finding_labels,
                )
            except Exception:
                logger.exception(
                    "Upload %s: humanize pass failed for the WHOLE batch (not just one finding -- "
                    "this is the rare outer fallback, see upload_pipeline.py's own comment), "
                    "falling back to un-humanized text for every finding", upload_id,
                )
                humanize_results = [(text, text, {}) for text in finding_texts]

            # ---- step 5: ONE all-or-nothing transaction (gap C5) ----
            upload.rules_snapshot_id = snapshot_id
            upload.page_label_map = page_label_map
            for draft, (raw_finding, humanized_finding, _humanize_usage) in zip(drafts, humanize_results):
                session.add(RuleResult(
                    upload_id=upload.id,
                    rule_id=uuid.UUID(draft.rule_id),
                    rule_version_used=draft.rule_version_used,
                    model_status=draft.model_status,
                    # model_finding is the HUMANIZED text (what every
                    # consumer reads, unchanged from that point of view) --
                    # model_finding_raw is the pre-humanize "before",
                    # written once alongside it and never touched again,
                    # same discipline as model_finding itself.
                    model_finding=humanized_finding,
                    model_finding_raw=raw_finding,
                    model_pages=draft.model_pages,
                    model_source_quote=draft.model_source_quote,
                    final_status=draft.model_status,
                    final_finding=humanized_finding,
                    final_pages=draft.model_pages,
                ))
            upload.status = "ready"

            record(
                session,
                user_id=None,
                action=(
                    f"Upload pipeline completed: {len(drafts)} rule_results created"
                    + (f", {len(low_text_pages)} page(s) flagged for OCR fallback" if low_text_pages else "")
                ),
                target_type="upload",
                target_id=upload.id,
                details={
                    "status": {"from": "processing", "to": "ready"},
                    "rules_snapshot_id": {"from": None, "to": str(snapshot_id)},
                },
            )
            session.commit()

        except Exception as exc:
            # Roll back everything pending from the block above — partial
            # rule_result inserts, the rules_snapshot_id assignment, all of
            # it. Nothing from a failed attempt is allowed to survive.
            session.rollback()

            # rollback() expires the identity map — re-fetch upload fresh
            # rather than touch the (now stale) object from before.
            upload = session.get(Upload, upload_id)
            error_detail = str(exc)[:2000]
            upload.status = "error"
            upload.error_detail = error_detail

            record(
                session,
                user_id=None,
                action=f"Upload pipeline failed: {error_detail}",
                target_type="upload",
                target_id=upload.id,
                details={
                    "status": {"from": "processing", "to": "error"},
                    "error_detail": {"from": None, "to": error_detail},
                },
            )
            session.commit()
            logger.exception("Upload pipeline failed for upload %s", upload_id)
    finally:
        session.close()
