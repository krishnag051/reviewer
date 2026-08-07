"""Round 59, Step 2: plain deterministic Python (zero model calls) that
compares a session note's Step-1 extraction (session_note_extraction.py)
against the TP's own data, for exactly the 3 rules Round 56 already
flagged as session-notes-only, metadata-only (rules.session_notes_only=
True, tp_section="Assessment of Current Functioning"):

- QA-RPT-03 -- the session date must fall within the TP's stated CURRENT
  REPORT date range ("Date of Current Report"), inclusive of both stated
  dates. Round 63, item 1 fix: this was previously (wrongly) compared
  against "Authorization Dates Requested" instead -- a different date
  range that also appears on every TP (the FUTURE period being requested,
  not the period the report itself covers). QA-RPT-03's own rule
  description in rules.json is unambiguous about which one is correct:
  "Dates of current report match 97151 session notes." A session note
  genuinely falling inside the authorization period but outside the
  report's own covered dates is not what this rule is asking about, and
  the previous wiring would have silently passed/failed it against the
  wrong window for every patient, not just Yisroel Leibowitz -- this was a
  general logic error, not something specific to his document.
- QA-ACF-02 -- three sub-checks bundled into ONE rule (it's a single rule
  in rules.json, not three -- see Round 56's own flagging notes): the
  session's assessment date, the clinician's location, and the patient's
  location must each match what the TP's own "Assessment of Current
  Functioning" section states. All three must match for an overall pass;
  any mismatch is an overall fail; missing data on either side is
  uncertain, not a guessed pass or fail.
- QA-ACF-08 -- the session's assessment-activity checkbox must match the
  assessment tool/activity the TP's own ACF section names.

Same technique already proven for QA-PPI-05 (fields.py) -- a plain,
independently-testable Python comparison, no LLM involved in this step at
all. The TP-side "Assessment of Current Functioning" values
(tp_assessment_date/tp_pos/tp_patient_location/tp_assessment_tool) are
accepted as plain arguments here rather than parsed from a real TP
document by this module -- that TP-side extraction is a separate, already-
existing concern (fields.py's own checkers already read a TP's raw text
for related ACF facts, e.g. QA-ACF-01's presence check, and
fields.py::_find_labeled_date_range already extracts "Date of Current
Report" for several other checkers -- app.py's caller uses that same
helper for this comparison too, rather than re-implementing date-range
extraction here). This module is built to work generically against
whatever those values turn out to be, from any patient's TP.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y")

_RANGE_SEPARATORS = re.compile(r"\s*(?:–|-|—|to)\s*")


def parse_date_flexible(date_str: str | None) -> date | None:
    """Returns None (not a guess) when the string doesn't contain enough
    information to know a real calendar date -- e.g. "7/29" with no year
    is genuinely ambiguous, not "probably this year." Callers turn a None
    into an "uncertain" comparison result, never a silent skip.
    """
    if not date_str or not date_str.strip():
        return None
    candidate = date_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


def parse_date_range(range_str: str | None) -> tuple[date | None, date | None]:
    """Splits a single free-text field like "08/17/2026 – 02/17/2027"
    (exactly the shape UploadIntakeAnswers.authorization_dates stores,
    per Round 56's structured Q&A form -- one text field, not two) into
    (start, end). Either side is None if it can't be confidently parsed.
    """
    if not range_str:
        return None, None
    parts = _RANGE_SEPARATORS.split(range_str.strip(), maxsplit=1)
    if len(parts) != 2:
        return parse_date_flexible(range_str), None
    return parse_date_flexible(parts[0]), parse_date_flexible(parts[1])


def _uncertain(evidence: str) -> dict[str, Any]:
    return {"result": "uncertain", "evidence": evidence, "confidence": 0.0}


def _finding(result: str, evidence: str, confidence: float) -> dict[str, Any]:
    return {"result": result, "evidence": evidence, "confidence": confidence}


def check_date_in_current_report_period(
    session_date_str: str | None, current_report_period_str: str | None,
) -> dict[str, Any]:
    """QA-RPT-03: session date must fall within [report_start, report_end]
    -- the TP's "Date of Current Report" range, i.e. the period the report
    ITSELF covers -- inclusive of both endpoints.

    Round 63, item 1: renamed from check_date_in_authorization_period,
    which compared against the wrong range ("Authorization Dates
    Requested," the future period being asked for). The two ranges are
    genuinely different fields on every TP; QA-RPT-03's own description
    ("Dates of current report match 97151 session notes") only ever meant
    this one. Callers must now pass the TP's "Date of Current Report"
    range here, not its authorization period.
    """
    session_date = parse_date_flexible(session_date_str)
    report_start, report_end = parse_date_range(current_report_period_str)

    if session_date is None:
        return _uncertain(
            f"Could not determine a specific calendar date from the session note's session_date "
            f"({session_date_str!r})."
        )
    if report_start is None or report_end is None:
        return _uncertain(
            f"Could not determine both ends of the TP's current-report date range from "
            f"{current_report_period_str!r}."
        )

    if report_start <= session_date <= report_end:
        return _finding(
            "pass",
            f"Session date {session_date_str} falls within the current-report date range "
            f"{report_start.isoformat()} to {report_end.isoformat()} (inclusive).",
            0.9,
        )
    return _finding(
        "fail",
        f"Session date {session_date_str} falls OUTSIDE the current-report date range "
        f"{report_start.isoformat()} to {report_end.isoformat()}.",
        0.9,
    )


def _values_match(a: str | None, b: str | None) -> bool:
    """Case/whitespace-insensitive equality -- not fuzzy matching. "Home"
    vs "home" is a match; "Home" vs "Office" is not. Deliberately simple:
    this is the same kind of plain-string comparison QA-PPI-05's
    deterministic checker already uses for NPI/License agreement.
    """
    if a is None or b is None:
        return False
    return a.strip().casefold() == b.strip().casefold()


def check_field_match(
    session_value: str | None, tp_value: str | None, *, field_label: str,
) -> dict[str, Any]:
    """One sub-check of QA-ACF-02 (assessment-date, clinician-location, or
    patient-location): does the session note's stated value match the
    TP's own stated value for the same fact, via exact (case/whitespace-
    insensitive) equality.

    Round 65, item 1: this is NO LONGER used for QA-ACF-08 -- see
    check_tool_mentioned below. QA-ACF-08's real-world shape (a session's
    assessment-activity field is often several checked boxes joined
    together, e.g. 'Direct observation...; Treatment plan development;
    VB-MAPP') means the TP's stated tool name is frequently a genuine
    SUBSTRING of the session's value rather than its entire exact value --
    an exact-match check would never fire there even though the tool
    genuinely is documented. QA-ACF-02's three sub-checks (date/clinician-
    location/patient-location) are each single, atomic facts where exact
    equality is still the right comparison -- unchanged here.
    """
    if session_value is None and tp_value is None:
        return _uncertain(f"{field_label}: neither the session note nor the TP states this.")
    if session_value is None:
        return _uncertain(f"{field_label}: the session note doesn't state this (TP states {tp_value!r}).")
    if tp_value is None:
        return _uncertain(f"{field_label}: the TP doesn't state this (session note states {session_value!r}).")
    if _values_match(session_value, tp_value):
        return _finding("pass", f"{field_label}: session note ({session_value!r}) matches the TP ({tp_value!r}).", 0.85)
    return _finding(
        "fail", f"{field_label}: session note ({session_value!r}) does NOT match the TP ({tp_value!r}).", 0.85
    )


def check_tool_mentioned(
    session_activity: str | None, tp_tool: str | None, *, field_label: str,
) -> dict[str, Any]:
    """QA-ACF-08's real comparison (Round 65, item 1 fix): the TP's stated
    assessment tool must appear as a genuine SUBSTRING somewhere in the
    session note's assessment-activity text, not match it exactly.

    Root cause this replaces: the session's assessment_activity field is
    often several checked boxes joined together by
    session_note_extraction.py (e.g. 'Direct observation/treatment of
    patient to inform treatment goals; Treatment plan development;
    VB-MAPP'), so an exact-equality check (check_field_match) would fail
    even when the TP's tool name is plainly documented as one of the
    checked items. Case/whitespace-insensitive substring containment --
    still not fuzzy matching: the TP's tool name must appear as a literal
    run of characters within the session's text, nothing looser than that.
    """
    if session_activity is None and tp_tool is None:
        return _uncertain(f"{field_label}: neither the session note nor the TP states this.")
    if session_activity is None:
        return _uncertain(f"{field_label}: the session note doesn't state this (TP states {tp_tool!r}).")
    if tp_tool is None:
        return _uncertain(f"{field_label}: the TP doesn't state this (session note states {session_activity!r}).")
    if tp_tool.strip().casefold() in session_activity.strip().casefold():
        return _finding(
            "pass",
            f"{field_label}: the TP's stated tool ({tp_tool!r}) is present within the session note's "
            f"assessment activity ({session_activity!r}).",
            0.85,
        )
    return _finding(
        "fail",
        f"{field_label}: the TP's stated tool ({tp_tool!r}) does NOT appear anywhere within the session "
        f"note's assessment activity ({session_activity!r}).",
        0.85,
    )


def _combine_acf02_subchecks(sub_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """QA-ACF-02 is ONE rule in rules.json covering three underlying facts
    at once (see this module's docstring) -- combines the 3 sub-check
    results into one overall finding. All 3 pass -> pass. Any fail ->
    fail (the rule failed if ANY of the three facts disagree). Otherwise
    (some uncertain, none failing) -> uncertain.
    """
    findings = list(sub_results.values())
    evidence = " | ".join(f"{label}: {r['evidence']}" for label, r in sub_results.items())
    if all(f["result"] == "pass" for f in findings):
        return _finding("pass", evidence, min(f["confidence"] for f in findings))
    failing = [f for f in findings if f["result"] == "fail"]
    if failing:
        return _finding("fail", evidence, max(f["confidence"] for f in failing))
    return _uncertain(evidence)


def compare_session_note_to_tp(
    session_extraction: dict[str, dict[str, Any]],
    *,
    tp_current_report_period: str | None,
    tp_assessment_date: str | None = None,
    tp_pos: str | None = None,
    tp_patient_location: str | None = None,
    tp_assessment_tool: str | None = None,
) -> dict[str, dict[str, Any]]:
    """The top-level entry point a future caller (agent-side pipeline
    orchestration, once wired in a later round) uses: takes Step 1's
    normalized extraction dict (session_note_extraction.py's own output
    shape -- {field: {value, confidence, source_quote}}) plus whatever the
    TP's own "Assessment of Current Functioning" section states, and
    returns exactly the 3 flagged rule_ids' findings, same {result,
    evidence, confidence} shape every other checker in this pipeline uses.

    `tp_current_report_period` (Round 63, item 1 -- renamed from
    tp_authorization_period, which was the wrong field entirely) must be
    the TP's "Date of Current Report" range, not its "Authorization Dates
    Requested" range -- see check_date_in_current_report_period's own
    docstring for why these are different fields.

    A "none"-confidence session-note field is treated as if the session
    note doesn't state that fact at all (matches this pipeline's existing
    convention: "none" means genuinely absent, not authoritative).
    """
    def value_or_none(field: str) -> str | None:
        entry = session_extraction.get(field) or {}
        return entry.get("value") if entry.get("confidence") != "none" else None

    session_date = value_or_none("session_date")
    patient_loc = value_or_none("patient_telehealth_location")
    assessment_activity = value_or_none("assessment_activity")
    session_location = value_or_none("session_location")

    # Round 65, item 2a fix: the TP's ACF section has exactly ONE location
    # field on the provider/clinician side -- "Provider Location During
    # Assessment" (tp_pos here) -- which states the overall modality/
    # location of the assessment (e.g. "Telehealth"), the SAME kind of
    # fact as the session note's own "Session Location" field. It has NO
    # counterpart to clinician_telehealth_location, which is a FINER
    # sub-detail that only exists for a telehealth session (specifically
    # where the clinician was physically sitting during it, e.g.
    # "Clinician's Home") -- comparing tp_pos against that sub-detail was
    # comparing two different granularities of the same visit, and could
    # fail even when the modality/location genuinely matched. The correct
    # like-for-like pairing is tp_pos vs. session_location, always -- not
    # clinician_telehealth_location, with or without a fallback.
    #
    # patient_telehealth_location keeps its own fallback to
    # session_location (unchanged) -- the round's fix is scoped to the
    # clinician-location sub-check specifically, since the TP's
    # "Patient Location during Assessment" field is a different fact this
    # sub-check already pairs correctly.
    clinician_loc = session_location
    if patient_loc is None:
        patient_loc = session_location

    acf02_subchecks = {
        "assessment date": check_field_match(session_date, tp_assessment_date, field_label="Assessment date"),
        "clinician location": check_field_match(clinician_loc, tp_pos, field_label="Clinician location/POS"),
        "patient location": check_field_match(patient_loc, tp_patient_location, field_label="Patient location"),
    }

    return {
        "QA-RPT-03": check_date_in_current_report_period(session_date, tp_current_report_period),
        "QA-ACF-02": _combine_acf02_subchecks(acf02_subchecks),
        "QA-ACF-08": check_tool_mentioned(assessment_activity, tp_assessment_tool, field_label="Assessment type/tool"),
    }


def select_matching_session_note(
    session_extractions: dict[str, dict[str, dict[str, Any]]],
    tp_assessment_date: str | None,
) -> tuple[str | None, dict[str, dict[str, Any]] | None]:
    """Round 65, item 2b: QA-ACF-02/QA-ACF-08 are specifically about
    validating the ONE session note that backs the TP's stated Assessment
    Date -- not every uploaded note regardless of date. A patient can have
    multiple real session notes on file for entirely different visits
    (e.g. an assessment-type session vs. a treatment-plan-development
    session two days later); only the one whose own session_date matches
    the TP's stated Assessment Date is the note this rule is actually
    asking about.

    General mechanism, not a hardcoded date or "pick the first file":
    parses the TP's Assessment Date and every candidate note's own
    session_date as real calendar dates (via parse_date_flexible, so
    different string formats for the same date still match) and returns
    the first note whose date matches.

    Returns (filename, extraction) for the match, or (None, None) if the
    TP's own assessment date can't be parsed, or if no uploaded note's
    date matches it -- never guesses by falling back to an unrelated note
    (e.g. "just use the first one").
    """
    tp_date = parse_date_flexible(tp_assessment_date)
    if tp_date is None:
        return None, None
    for filename, extraction in session_extractions.items():
        entry = (extraction or {}).get("session_date") or {}
        if entry.get("confidence") == "none":
            continue
        note_date = parse_date_flexible(entry.get("value"))
        if note_date is not None and note_date == tp_date:
            return filename, extraction
    return None, None


def compare_session_notes_to_tp(
    session_extractions: dict[str, dict[str, dict[str, Any]]],
    *,
    tp_current_report_period: str | None,
    tp_assessment_date: str | None = None,
    tp_pos: str | None = None,
    tp_patient_location: str | None = None,
    tp_assessment_tool: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Round 65, item 2b: the top-level entry point for potentially
    MULTIPLE uploaded session notes for a single TP (a real caller,
    e.g. app.py, should use this instead of calling
    compare_session_note_to_tp per file when more than one note is
    uploaded).

    QA-RPT-03 is checked against EVERY uploaded note independently --
    each session's own date must fall within the report window on its own
    merits, regardless of which note backs the stated assessment -- and
    combined into one finding (pass only if every note is in range, fail
    if any is out of range, each note's own result named in the evidence).

    QA-ACF-02/QA-ACF-08 are computed ONLY against the note
    select_matching_session_note() finds -- reusing
    compare_session_note_to_tp's own logic for that one note, not
    duplicating it. If no uploaded note's date matches the TP's stated
    Assessment Date, both come back uncertain, explicitly saying so,
    rather than being run against some unrelated note.
    """
    def value_or_none(extraction: dict, field: str) -> str | None:
        entry = (extraction or {}).get(field) or {}
        return entry.get("value") if entry.get("confidence") != "none" else None

    rpt03_by_file = {
        filename: check_date_in_current_report_period(
            value_or_none(extraction, "session_date"), tp_current_report_period,
        )
        for filename, extraction in session_extractions.items()
    }

    if not rpt03_by_file:
        rpt03_combined = _uncertain("No session notes were uploaded.")
    else:
        evidence = " | ".join(f"{fn}: {r['evidence']}" for fn, r in rpt03_by_file.items())
        if all(r["result"] == "pass" for r in rpt03_by_file.values()):
            rpt03_combined = _finding("pass", evidence, min(r["confidence"] for r in rpt03_by_file.values()))
        else:
            failing_confidences = [r["confidence"] for r in rpt03_by_file.values() if r["result"] == "fail"]
            if failing_confidences:
                rpt03_combined = _finding("fail", evidence, max(failing_confidences))
            else:
                rpt03_combined = _uncertain(evidence)

    _, matched_extraction = select_matching_session_note(session_extractions, tp_assessment_date)
    if matched_extraction is None:
        no_match_evidence = (
            f"No uploaded session note's own date matches the TP's stated Assessment Date "
            f"({tp_assessment_date!r}) -- cannot confirm which note backs this specific assessment."
        )
        acf02 = _uncertain(no_match_evidence)
        acf08 = _uncertain(no_match_evidence)
    else:
        matched_result = compare_session_note_to_tp(
            matched_extraction,
            tp_current_report_period=tp_current_report_period,
            tp_assessment_date=tp_assessment_date,
            tp_pos=tp_pos,
            tp_patient_location=tp_patient_location,
            tp_assessment_tool=tp_assessment_tool,
        )
        acf02 = matched_result["QA-ACF-02"]
        acf08 = matched_result["QA-ACF-08"]

    return {"QA-RPT-03": rpt03_combined, "QA-ACF-02": acf02, "QA-ACF-08": acf08}
