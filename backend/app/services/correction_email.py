import html
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import AppConfig, GeneratedEmail, Patient, Rule, RuleResult, Upload, User, Version
from app.services.mailer import Attachment, MailerNotConfigured, MailerSendFailed, send_email
from app.storage import resolve_stored_path

# Fix Round, item 3 (2026-08-12): every status a rule_result can carry,
# in the FIXED order the email body (and the frontend's own checkboxes/
# results tab bar) always uses -- Pass, Fail, Uncertain, N/A, Not
# checkable. Kept as one shared tuple so the body-builder below and the
# `statuses` validation can't silently drift out of the same order.
# MUST match frontend/src/components/tp/RuleResultCard.tsx's STATUS_LABELS
# key set exactly -- same 5 values, same meaning.
STATUS_ORDER = ("pass", "fail", "uncertain", "na", "not_checkable")
STATUS_LABELS = {"pass": "Pass", "fail": "Fail", "uncertain": "Uncertain", "na": "N/A", "not_checkable": "Not checkable"}

# Round 71's broadened set, kept as the frontend's PRE-SELECTED default
# when the escalation modal first opens (every non-Pass status) -- not a
# validation constraint anymore. This round replaces the old "always
# fail+uncertain+na+not_checkable, no Pass, no user choice" behavior with
# real category checkboxes; Pass is now a legitimate, selectable category
# too (e.g. a BCBA forwarding a fully-clean review for sign-off).
DEFAULT_STATUSES = ("fail", "uncertain", "na", "not_checkable")


def _build_body(
    patient: Patient, version: Version, upload: Upload, results_by_status: dict[str, list[RuleResult]],
    statuses: list[str], rules_by_id: dict,
) -> str:
    """Fix Round, item 3: header (identifies patient/TP/upload) + a short
    intro line + the categorized results, grouped by STATUS in
    STATUS_ORDER (never interleaved, and never in whatever order the
    checkboxes happened to be clicked) + a short closing line. Replaces
    the old rule-category/page grouping entirely -- that was a different,
    now-superseded design; every request this round is about the RESULT
    category (Pass/Fail/Uncertain/N/A/Not checkable), not the rule's own
    subject-matter category.

    An empty status bucket (checked, but zero matching results on this
    upload) gets no header at all -- a wall of "Pass (0):" headers reads
    as noise, not signal, in a real email a human has to read.
    """
    included = [s for s in STATUS_ORDER if s in statuses]
    total = sum(len(results_by_status.get(s, [])) for s in included)

    lines = [
        f"Treatment Plan Review — {patient.name} ({patient.reference_id})",
        f"Version {version.version_number}, Upload U{upload.upload_number}",
        "",
        (
            f"This email contains the {', '.join(STATUS_LABELS[s] for s in included)} result(s) from this "
            f"treatment plan's rule-check review — {total} item(s) total. The treatment plan itself is attached, "
            f"along with any supporting document, session notes, or intake Q&A on file for this upload."
        ),
        "",
    ]

    for s in included:
        items = results_by_status.get(s, [])
        if not items:
            continue
        lines.append(f"{STATUS_LABELS[s]} ({len(items)}):")
        for r in items:
            rule = rules_by_id[r.rule_id]
            lines.append(f"  [{rule.rule_code}] {rule.question_text}")
            lines.append(f"  Finding: {r.final_finding}")
            if r.final_pages:
                lines.append(f"  Reference: p.{', '.join(str(p) for p in r.final_pages)}")
        lines.append("")

    lines.append("Please review the items above and reach out with any questions.")
    lines.append("")
    lines.append("— Sent from the TP Review system")
    return "\n".join(lines)


def _finding_text(finding) -> str:
    """Same rendering `_build_body` already implicitly relies on
    (str(r.final_finding)) -- a rule_result's finding is either a plain
    string or the {page, detail} list form judge.py can produce for a
    multi-page issue. Kept as its own function so both the plain-text and
    HTML body builders render this exact shape identically, rather than
    inlining str()/escaping logic twice.
    """
    if isinstance(finding, list):
        return "; ".join(
            f"[Page {item.get('page')}] {item.get('detail')}" if isinstance(item, dict) else str(item)
            for item in finding
        )
    return str(finding)


def _build_html_body(
    patient: Patient, version: Version, upload: Upload, results_by_status: dict[str, list[RuleResult]],
    statuses: list[str], rules_by_id: dict,
) -> str:
    """Deployment round: real HTML formatting for the same content
    _build_body produces -- same category headers/order, same per-rule
    Finding/Reference text, same overall structure -- styling only, no
    content change. Plain inline CSS throughout (style="..." attributes,
    no <style> block/external stylesheet) since real email clients
    (Outlook, Gmail) are notoriously inconsistent about honoring anything
    else. `<b>` for the rule ID/title per Part 1's own spec (not
    `<strong>` -- both render identically in every real client that
    matters here; `<b>` is what the task named explicitly) with a light
    `<hr>` divider after each rule entry for real visual separation,
    replacing the wall-of-text single-indent-level look the plain version
    has no way to avoid.

    Every user-controlled/model-generated string (patient name, rule
    title, finding text) is passed through html.escape() before being
    embedded -- a finding can legitimately contain '<', '>', or '&' (e.g.
    quoting document text), and this is real HTML now, not a plain-text
    body where that was never a concern.
    """
    included = [s for s in STATUS_ORDER if s in statuses]
    total = sum(len(results_by_status.get(s, [])) for s in included)

    esc_patient_name = html.escape(patient.name)
    esc_ref_id = html.escape(patient.reference_id)
    esc_status_list = html.escape(", ".join(STATUS_LABELS[s] for s in included))

    parts = [
        '<div style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; color: #1e293b; line-height: 1.5;">',
        f'<h2 style="margin: 0 0 4px 0; font-size: 18px;">Treatment Plan Review — {esc_patient_name} ({esc_ref_id})</h2>',
        f'<p style="margin: 0 0 16px 0; color: #64748b;">Version {version.version_number}, Upload U{upload.upload_number}</p>',
        (
            f'<p style="margin: 0 0 20px 0;">This email contains the {esc_status_list} result(s) from this '
            f"treatment plan's rule-check review — {total} item(s) total. The treatment plan itself is attached, "
            f"along with any supporting document, session notes, or intake Q&A on file for this upload.</p>"
        ),
    ]

    for s in included:
        items = results_by_status.get(s, [])
        if not items:
            continue
        parts.append(f'<h3 style="margin: 24px 0 12px 0; font-size: 15px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px;">{html.escape(STATUS_LABELS[s])} ({len(items)})</h3>')
        for r in items:
            rule = rules_by_id[r.rule_id]
            esc_rule_code = html.escape(rule.rule_code)
            esc_title = html.escape(rule.question_text)
            esc_finding = html.escape(_finding_text(r.final_finding))
            parts.append('<div style="margin: 0 0 14px 0;">')
            parts.append(f'<p style="margin: 0 0 4px 0;"><b>[{esc_rule_code}] {esc_title}</b></p>')
            parts.append(f'<p style="margin: 0 0 4px 0;">Finding: {esc_finding}</p>')
            if r.final_pages:
                esc_pages = html.escape(", ".join(str(p) for p in r.final_pages))
                parts.append(f'<p style="margin: 0; color: #64748b; font-size: 13px;">Reference: p.{esc_pages}</p>')
            parts.append("</div>")
            # The visual separator Part 1 explicitly asked for -- a real
            # break between one rule entry and the next, not everything
            # packed together with no breathing room.
            parts.append('<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 0 0 14px 0;">')

    parts.append('<p style="margin: 20px 0 0 0;">Please review the items above and reach out with any questions.</p>')
    parts.append('<p style="margin: 16px 0 0 0; color: #64748b;">— Sent from the TP Review system</p>')
    parts.append("</div>")
    return "\n".join(parts)


def _gather_results_by_status(
    session: Session, upload_id: uuid.UUID, statuses: list[str],
) -> tuple[dict[str, list[RuleResult]], dict]:
    """Shared by generate_correction_email (builds the plain-text body
    that gets persisted) and send_generated_email (rebuilds the HTML body
    fresh at send time, below) -- same query, same shape, factored out so
    the two can never drift into computing "the same rule results" two
    different ways.
    """
    all_results = session.execute(select(RuleResult).where(RuleResult.upload_id == upload_id)).scalars().all()
    results_by_status: dict[str, list[RuleResult]] = {}
    for r in all_results:
        if r.final_status in statuses:
            results_by_status.setdefault(r.final_status, []).append(r)
    included_results = [r for bucket in results_by_status.values() for r in bucket]
    rules_by_id = {
        r.id: r
        for r in session.execute(select(Rule).where(Rule.id.in_([res.rule_id for res in included_results]))).scalars().all()
    }
    return results_by_status, rules_by_id


def generate_correction_email(
    session: Session,
    version_id: uuid.UUID,
    *,
    upload_id: uuid.UUID | None,
    routed_to: str,
    statuses: list[str],
    to_addr: str | None,
    cc: str | None,
    bcc: str | None,
    actor_user_id: uuid.UUID,
) -> GeneratedEmail | None:
    """POST /versions/:id/correction-email. Builds and persists a
    GeneratedEmail row from this upload's CURRENT (live, as-of-this-call)
    rule_results -- reads `final_status`/`final_finding`, which already
    reflect any human override made before this call, never `model_*`.
    Does not send anything by itself; see send_generated_email below --
    callers that want "reflects overrides at send time" must call this
    function again immediately before sending, not reuse an old row.

    `statuses`: which result categories to include, e.g. ["fail",
    "uncertain"]. Must be non-empty and every value must be one of
    STATUS_ORDER -- 400 otherwise. Order in the input list doesn't matter;
    the body always renders in STATUS_ORDER regardless.

    Returns None if the version doesn't exist.
    """
    if not statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "no_statuses_selected", "message": "At least one result category must be selected."},
        )
    unknown = [s for s in statuses if s not in STATUS_ORDER]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "unknown_status", "message": f"Unknown status value(s): {unknown}"},
        )

    version = session.get(Version, version_id)
    if version is None:
        return None

    if upload_id is not None:
        upload = session.get(Upload, upload_id)
        if upload is None or upload.version_id != version_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "invalid_upload", "message": "upload_id must belong to this version"},
            )
    else:
        upload = session.execute(
            select(Upload)
            .where(Upload.version_id == version_id, Upload.voided.is_(False))
            .order_by(Upload.upload_number.desc())
            .limit(1)
        ).scalar_one_or_none()
        if upload is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "no_upload_available",
                    "message": "this version has no non-voided upload to generate a correction email from",
                },
            )

    patient = session.get(Patient, version.patient_id)

    results_by_status, rules_by_id = _gather_results_by_status(session, upload.id, statuses)

    subject = f"Treatment Plan Review — {patient.name} ({patient.reference_id}) — v{version.version_number} U{upload.upload_number}"
    body = _build_body(patient, version, upload, results_by_status, statuses, rules_by_id)

    resolved_to = to_addr
    if resolved_to is None and version.reviewer_id is not None:
        reviewer = session.get(User, version.reviewer_id)
        resolved_to = reviewer.email if reviewer is not None else None

    resolved_cc = cc
    if resolved_cc is None:
        app_config = session.execute(select(AppConfig)).scalar_one()
        resolved_cc = app_config.notif_default_cc

    now = datetime.now(timezone.utc)
    email = GeneratedEmail(
        version_id=version_id,
        upload_id=upload.id,
        generated_by=actor_user_id,
        to_addr=resolved_to,
        cc=resolved_cc,
        bcc=bcc,
        subject=subject,
        body=body,
        routed_to=routed_to,
        routed_by=actor_user_id,
        routed_at=now,
        statuses=list(statuses),
    )
    session.add(email)
    session.flush()  # assigns email.id

    record(
        session,
        user_id=actor_user_id,
        action=f"Generated correction email for version {version.version_number}, routed to {routed_to}",
        target_type="version",
        target_id=version.id,
        details={
            "generated_email_id": {"from": None, "to": str(email.id)},
            "routed_to": {"from": None, "to": routed_to},
            "statuses": {"from": None, "to": list(statuses)},
        },
    )
    session.commit()
    return email


def _gather_attachments(upload: Upload) -> list[Attachment]:
    """Fix Round, item 3: always attaches the treatment plan itself; ALSO
    attaches the supporting document, every session-note file, and a
    plain-text rendering of the intake Q&A -- each ONLY if that document
    type actually exists for this upload. Skips silently (no error, no
    partial-attachment warning) for whichever types weren't uploaded --
    never blocks sending over a missing optional document. Also skips
    silently (doesn't raise) if a file's real bytes are no longer on disk
    (purged past retention, or a genuinely missing blob) -- an attachment
    that can't be read is exactly like one that was never uploaded, from
    this function's point of view; the calling send still proceeds.
    """
    attachments: list[Attachment] = []

    def _try_add(stored_path: str | None, filename: str) -> None:
        if not stored_path:
            return
        path = resolve_stored_path(stored_path)
        if not path.exists():
            return
        attachments.append(Attachment(filename=filename, content=path.read_bytes(), mime_type="application/pdf"))

    _try_add(upload.file_path, upload.original_filename or f"treatment-plan-U{upload.upload_number}.pdf")
    _try_add(upload.supporting_document_path, f"supporting-document-U{upload.upload_number}.pdf")

    for note in upload.session_note_files:
        _try_add(note.file_path, note.original_filename)

    if upload.intake_answers is not None:
        ia = upload.intake_answers
        text_lines = [
            f"Intake Q&A — Upload U{upload.upload_number}",
            "",
            f"Client insurance: {ia.client_insurance}",
            f"BCBA name/credentials/NPI: {ia.bcba_name_credentials_npi}",
            f"Authorization dates: {ia.authorization_dates}",
            f"POS/schedule vs. 97153 hours: {ia.pos_schedule_vs_97153_hours}",
            f"Hours requesting: {ia.hours_requesting}",
        ]
        attachments.append(Attachment(
            filename=f"intake-qa-U{upload.upload_number}.txt",
            content="\n".join(text_lines).encode("utf-8"),
            mime_type="text/plain",
        ))

    return attachments


def send_generated_email(session: Session, email_id: uuid.UUID, *, actor_user_id: uuid.UUID) -> GeneratedEmail | None:
    """POST /versions/:id/correction-email/:email_id/send. Sends the
    ALREADY-GENERATED row's exact subject/body/recipients -- the freshness
    guarantee ("reflects overrides at the moment of sending") comes from
    the caller always calling generate_correction_email again, immediately
    before this, rather than reusing a stale row from when a modal first
    opened; this function itself just sends whatever row it's given.

    Attachments are gathered HERE, at send time, not at generate time --
    always current for this upload (there's no realistic scenario where a
    document attached to an upload changes between generate and send, but
    this keeps the two concerns cleanly separated regardless).

    Deployment round: the real HTML body (bold rule ID/title + a visual
    divider per entry, see _build_html_body's own docstring) is ALSO built
    fresh here, at send time -- same reasoning as attachments above, and
    the only option that didn't need a schema migration: GeneratedEmail's
    persisted `body` column stays exactly what it always was (the plain-
    text version, unchanged, still the real fallback for a plain-text-only
    mail client), and the HTML alternative is derived from the SAME
    `email.upload_id` + `email.statuses` this row already persists,
    through the exact same _gather_results_by_status query
    generate_correction_email itself uses -- never a second, differently-
    computed picture of "what results are in this email."

    Returns None if the email row doesn't exist. Raises HTTPException(422)
    if there's no recipient. On a real SMTP failure, persists send_error
    on the row (so the failure is visible in the audit trail/UI) and
    re-raises as HTTPException(502) -- never silently marks a failed send
    as sent.
    """
    email = session.get(GeneratedEmail, email_id)
    if email is None:
        return None

    if not email.to_addr:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "no_recipient", "message": "No \"To\" address set for this email."},
        )

    upload = session.get(Upload, email.upload_id)
    version = session.get(Version, email.version_id)
    patient = session.get(Patient, version.patient_id)
    attachments = _gather_attachments(upload)

    results_by_status, rules_by_id = _gather_results_by_status(session, email.upload_id, email.statuses)
    html_body = _build_html_body(patient, version, upload, results_by_status, email.statuses, rules_by_id)

    app_config = session.execute(select(AppConfig)).scalar_one()

    try:
        send_email(
            to_addr=email.to_addr,
            cc=email.cc,
            bcc=email.bcc,
            subject=email.subject,
            body=email.body,
            html_body=html_body,
            from_addr=app_config.notif_from_address,
            from_name=app_config.notif_from_name,
            attachments=attachments,
        )
    except (MailerNotConfigured, MailerSendFailed) as exc:
        email.send_error = str(exc)
        record(
            session,
            user_id=actor_user_id,
            action=f"Failed to send correction email for {patient.name} ({patient.reference_id})",
            target_type="generated_email",
            target_id=email.id,
            details={"send_error": {"from": None, "to": str(exc)}},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "send_failed", "message": str(exc)},
        ) from exc

    email.sent_at = datetime.now(timezone.utc)
    email.send_error = None
    record(
        session,
        user_id=actor_user_id,
        action=f"Sent correction email for {patient.name} ({patient.reference_id}) to {email.to_addr}",
        target_type="generated_email",
        target_id=email.id,
        details={
            "sent_at": {"from": None, "to": email.sent_at.isoformat()},
            "attachment_count": {"from": None, "to": len(attachments)},
        },
    )
    session.commit()
    return email
