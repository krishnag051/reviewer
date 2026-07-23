import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Rule, RuleResult, Upload

FAILING_STATUSES = {"fail", "uncertain"}


def compute_diff(
    session: Session,
    upload_id: uuid.UUID,
    against_upload_id: uuid.UUID,
) -> dict | None:
    """GET /uploads/:id/diff?against=:otherUploadId. Returns None if either
    upload doesn't exist (caller maps to 404). Raises HTTPException(400) if
    the two uploads aren't comparable.

    Matches rule_results by rule_id across both uploads and compares
    final_status (never model_status — human corrections are what the diff
    must reflect). Buckets, exactly as specified in the master doc §6:
    - fixed: fail/uncertain on `against`, pass on `upload`
    - newly_broken: pass on `against`, fail/uncertain on `upload`
    - still_failing: fail/uncertain on both
    - unchanged_pass: pass on both
    - rules_changed: the rule is present in one upload's results but not the
      other's (snapshot drift between the two uploads) — surfaced
      separately, never silently dropped

    `other` is not in the master doc's named list, but is needed for the
    same "never silently drop a rule" reason `rules_changed` exists: a
    combination not covered above (currently: anything involving "na" on
    either side, since the hollow rule_engine stub returns "na" for every
    rule until overridden — na doesn't fit "fixed/broken/failing/passing" on
    either side of a comparison). Every rule_id present in either upload
    lands in exactly one bucket; nothing is ever dropped.

    was_overridden_previously is set on every entry that has a rule_result
    on the `against` side: true if THAT rule_result had is_overridden=true —
    context only, never applied to `upload`'s own final_status.
    """
    upload = session.get(Upload, upload_id)
    against = session.get(Upload, against_upload_id)
    if upload is None or against is None:
        return None

    if upload.version_id != against.version_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "different_version", "message": "both uploads must belong to the same version"},
        )
    if upload.voided or against.voided:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "voided_upload", "message": "neither upload may be voided"},
        )

    this_results = {
        r.rule_id: r
        for r in session.execute(select(RuleResult).where(RuleResult.upload_id == upload_id)).scalars().all()
    }
    against_results = {
        r.rule_id: r
        for r in session.execute(select(RuleResult).where(RuleResult.upload_id == against_upload_id)).scalars().all()
    }
    rule_ids = set(this_results) | set(against_results)
    rule_codes = {
        r.id: r.rule_code
        for r in session.execute(select(Rule).where(Rule.id.in_(rule_ids))).scalars().all()
    }

    buckets: dict[str, list[dict]] = {
        "fixed": [], "newly_broken": [], "still_failing": [], "unchanged_pass": [], "other": [], "rules_changed": [],
    }

    for rule_id in rule_ids:
        this_r = this_results.get(rule_id)
        against_r = against_results.get(rule_id)
        entry = {
            "rule_id": rule_id,
            "rule_code": rule_codes.get(rule_id, "?"),
            "this_status": this_r.final_status if this_r else None,
            "against_status": against_r.final_status if against_r else None,
            "was_overridden_previously": bool(against_r is not None and against_r.is_overridden),
        }

        if this_r is None or against_r is None:
            buckets["rules_changed"].append(entry)
            continue

        t, a = this_r.final_status, against_r.final_status
        if a in FAILING_STATUSES and t == "pass":
            buckets["fixed"].append(entry)
        elif a == "pass" and t in FAILING_STATUSES:
            buckets["newly_broken"].append(entry)
        elif a in FAILING_STATUSES and t in FAILING_STATUSES:
            buckets["still_failing"].append(entry)
        elif a == "pass" and t == "pass":
            buckets["unchanged_pass"].append(entry)
        else:
            buckets["other"].append(entry)

    return {
        "upload_id": upload_id,
        "against_upload_id": against_upload_id,
        **buckets,
    }
