"""Step 7 of the pipeline (Section 4): combine the deterministic and judgment
layers into one findings object, split by each rule's action_lane/action_tag.
"""
import logging

logger = logging.getLogger(__name__)

NEEDS_ACTION_RESULTS = {"fail", "uncertain"}


def _format_page_display(page) -> str | int | None:
    """A finding's `page` can be a single int, a list of 2+ ints (one
    finding whose evidence genuinely spans multiple specific pages
    together — distinct from the {page, detail} list-evidence form, which
    is the same problem recurring independently on many pages), or None.
    Renders the list case as a human-readable string for the CSV/export
    "Page" column: consecutive pages as "14-15", non-consecutive as
    "11, 14" — never silently dropping a page or picking one arbitrarily.

    REAL BUG FOUND AND FIXED (2026-08-27), confirmed via a real production
    crash: `page`'s own JSON-schema shape (judge.py's FINDINGS_TOOL) is
    advisory to the model, not enforced by a runtime validator on the
    response side -- there is nothing that structurally stops the model
    from returning something other than a plain list of ints here (e.g.
    accidentally nesting {page, detail} dicts, the SEPARATE list-evidence
    form's own shape, into this field instead). `sorted(page)` on a list
    containing dicts crashes with "TypeError: '<' not supported between
    instances of 'dict' and 'dict'" -- confirmed live, real cost already
    spent (~$0.8165, a real tie-break round on 20 disagreeing rules)
    before this crash discarded every one of those real results along
    with everything else in the same review. A malformed page value is
    now treated as "not page-specific" (None) -- exactly what None
    already means elsewhere in this same field -- rather than crashing
    the whole review over one rule's malformed field.
    """
    if page is None or isinstance(page, int):
        return page
    if not isinstance(page, list) or not all(isinstance(p, int) for p in page):
        logger.warning(
            "merge._format_page_display: malformed page value %r (expected int, list[int], or "
            "None) -- treating as not-page-specific (None) rather than crashing.",
            page,
        )
        return None
    pages = sorted(page)
    if len(pages) == 1:
        return pages[0]
    is_consecutive = all(b - a == 1 for a, b in zip(pages, pages[1:]))
    if is_consecutive:
        return f"{pages[0]}-{pages[-1]}"
    return ", ".join(str(p) for p in pages)


def _explode_to_rows(rule_id: str, entry: dict) -> list[dict]:
    """One export row per page-level entry when `evidence` is the
    {page, detail} list form; a single row (unchanged) when it's a plain
    string. A reviewer reading the export sees one row per real page-level
    issue, never a summary sentence with page numbers buried inside it.
    """
    base = {
        "rule_id": rule_id,
        "category": entry["category"],
        "result": entry["result"],
        "confidence": entry["confidence"],
        "action_lane": entry["action_lane"],
        "action_tag": entry["action_tag"],
    }
    if isinstance(entry["evidence"], list):
        return [
            {**base, "page": item["page"], "detail": item["detail"]}
            for item in entry["evidence"]
        ]
    return [{**base, "page": _format_page_display(entry["page"]), "detail": entry["evidence"]}]


def merge_findings(rules: list[dict], det_results: dict[str, dict], judgment_results: dict[str, dict]) -> dict:
    """Returns:
    {
        "findings": {rule_id: {result, evidence, page, confidence, category,
                                action_lane, action_tag, check_type}},
        "export_rows": [{rule_id, category, result, page, detail, confidence,
                          action_lane, action_tag}, ...],  # one row per
                          page-level entry when evidence is multi-page,
                          one row per rule_id otherwise — this is what the
                          report/export table should render, not `findings`.
        "bcba_fix": [rule_id, ...],       # active, needs-action, action_lane == "BCBA-fix"
        "facilitator_assign": [rule_id, ...],  # active, needs-action, action_lane == "Facilitator-assign"
    }
    """
    findings = {}
    export_rows = []
    bcba_fix = []
    facilitator_assign = []

    for rule in rules:
        if not rule["active"]:
            continue
        rule_id = rule["rule_id"]
        layer_result = det_results.get(rule_id) if rule["check_type"] == "deterministic" else judgment_results.get(rule_id)
        if layer_result is None:
            continue

        # REAL BUG FOUND AND FIXED (2026-08-27), confirmed via a real
        # production crash: this loop runs once for EVERY rule in a
        # single document review, and used to have no isolation at all --
        # one rule's entry/export-row build throwing (the malformed-page
        # TypeError _format_page_display now handles above, or any future
        # different bug) crashed straight out of merge_findings, which
        # discarded every OTHER rule's real, already-computed, already-
        # paid-for finding in the same review along with it (confirmed
        # real cost lost: ~$0.8165, a genuine tie-break round on 20
        # disagreeing rules). Same principle as the humanize-batch
        # isolation fix from a prior round: one rule's own resolution
        # failing must land ONLY that rule on a safe, clearly-marked
        # fallback, never take the rest of the review down with it.
        try:
            entry = {
                **layer_result,
                "category": rule["category"],
                "action_lane": rule.get("action_lane"),
                "action_tag": rule.get("action_tag"),
                "check_type": rule["check_type"],
            }
            rows = _explode_to_rows(rule_id, entry)
        except Exception as exc:
            logger.exception(
                "merge_findings: building the export entry for %s failed -- falling back to an "
                "'uncertain, resolution failed' finding for THIS rule only; every other rule's "
                "real result in this same review is unaffected.",
                rule_id,
            )
            entry = {
                "result": "uncertain",
                "evidence": (
                    f"This rule's own result could not be safely finalized due to an internal "
                    f"error ({type(exc).__name__}) -- flagged uncertain rather than silently "
                    f"dropped or guessed at."
                ),
                "page": None,
                "confidence": 0.0,
                "category": rule["category"],
                "action_lane": rule.get("action_lane"),
                "action_tag": rule.get("action_tag"),
                "check_type": rule["check_type"],
            }
            # Deliberately NOT calling _explode_to_rows here -- if THAT
            # function (or _format_page_display) is itself what just
            # failed, calling it again with the fallback entry could fail
            # the exact same way and escape this except block entirely,
            # defeating the whole point of this fallback. Every value
            # below is a plain literal this code just built itself, so
            # this row can never fail to construct.
            rows = [{
                "rule_id": rule_id,
                "category": entry["category"],
                "result": entry["result"],
                "confidence": entry["confidence"],
                "action_lane": entry["action_lane"],
                "action_tag": entry["action_tag"],
                "page": None,
                "detail": entry["evidence"],
            }]

        findings[rule_id] = entry
        export_rows.extend(rows)

        if entry["result"] in NEEDS_ACTION_RESULTS:
            if rule.get("action_lane") == "BCBA-fix":
                bcba_fix.append(rule_id)
            elif rule.get("action_lane") == "Facilitator-assign":
                facilitator_assign.append(rule_id)

    return {
        "findings": findings,
        "export_rows": export_rows,
        "bcba_fix": bcba_fix,
        "facilitator_assign": facilitator_assign,
    }
