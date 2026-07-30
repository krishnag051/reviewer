"""Step 7 of the pipeline (Section 4): combine the deterministic and judgment
layers into one findings object, split by each rule's action_lane/action_tag.
"""

NEEDS_ACTION_RESULTS = {"fail", "uncertain"}


def _format_page_display(page) -> str | int | None:
    """A finding's `page` can be a single int, a list of 2+ ints (one
    finding whose evidence genuinely spans multiple specific pages
    together — distinct from the {page, detail} list-evidence form, which
    is the same problem recurring independently on many pages), or None.
    Renders the list case as a human-readable string for the CSV/export
    "Page" column: consecutive pages as "14-15", non-consecutive as
    "11, 14" — never silently dropping a page or picking one arbitrarily.
    """
    if page is None or isinstance(page, int):
        return page
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

        entry = {
            **layer_result,
            "category": rule["category"],
            "action_lane": rule.get("action_lane"),
            "action_tag": rule.get("action_tag"),
            "check_type": rule["check_type"],
        }
        findings[rule_id] = entry
        export_rows.extend(_explode_to_rows(rule_id, entry))

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
