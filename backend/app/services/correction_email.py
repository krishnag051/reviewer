import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record
from app.db.models import AppConfig, GeneratedEmail, Patient, Rule, RuleResult, Upload, User, Version

FAILING_STATUSES = {"fail", "uncertain"}


def _build_body(patient: Patient, version: Version, failing: list[RuleResult], rules_by_id: dict, group_by: str) -> str:
    lines = [
        f"The treatment plan for {patient.name} ({patient.reference_id}), version {version.version_number}, "
        f"has {len(failing)} item(s) that failed review or need clarification.",
        "",
    ]

    if group_by == "page":
        by_page: dict[str, list[RuleResult]] = {}
        for r in failing:
            key = ", ".join(str(p) for p in r.final_pages) if r.final_pages else "No page reference"
            by_page.setdefault(key, []).append(r)
        for page_key in sorted(by_page):
            lines.append(f"Page {page_key}:")
            for r in by_page[page_key]:
                rule = rules_by_id[r.rule_id]
                lines.append(f"  [{rule.rule_code}] {rule.question_text}")
                lines.append(f"  Finding: {r.final_finding}")
            lines.append("")
    else:  # "category"
        by_category: dict[str, list[RuleResult]] = {}
        for r in failing:
            by_category.setdefault(rules_by_id[r.rule_id].category, []).append(r)
        for category in sorted(by_category):
            lines.append(f"{category}:")
            for r in by_category[category]:
                rule = rules_by_id[r.rule_id]
                lines.append(f"  [{rule.rule_code}] {rule.question_text}")
                lines.append(f"  Finding: {r.final_finding}")
                if r.final_pages:
                    lines.append(f"  Reference: p.{', '.join(str(p) for p in r.final_pages)}")
            lines.append("")

    lines.append("Please correct the items above and re-upload an updated treatment plan for review.")
    return "\n".join(lines)


def generate_correction_email(
    session: Session,
    version_id: uuid.UUID,
    *,
    upload_id: uuid.UUID | None,
    routed_to: str,
    group_by: str,
    to_addr: str | None,
    cc: str | None,
    bcc: str | None,
    actor_user_id: uuid.UUID,
) -> GeneratedEmail | None:
    """POST /versions/:id/correction-email. Generation + persistence only —
    no SMTP/actual sending exists anywhere in this codebase; "Send Now"
    stays mock-only on the frontend, by original scope. Returns None if the
    version doesn't exist.

    Pulls failed/uncertain rule_results from the given upload_id, or the
    version's latest non-voided upload if upload_id is omitted. Raises 400
    if an explicit upload_id doesn't belong to this version, 409 if no
    upload is available to pull from at all.
    """
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

    all_results = session.execute(select(RuleResult).where(RuleResult.upload_id == upload.id)).scalars().all()
    failing = [r for r in all_results if r.final_status in FAILING_STATUSES]
    rules_by_id = {
        r.id: r
        for r in session.execute(select(Rule).where(Rule.id.in_([res.rule_id for res in failing]))).scalars().all()
    }

    subject = f"Treatment Plan Correction Needed — {patient.name} — {patient.reference_id}"
    body = _build_body(patient, version, failing, rules_by_id, group_by)

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
        },
    )
    session.commit()
    return email
