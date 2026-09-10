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


def _not_checkable(evidence: str) -> dict[str, Any]:
    """Distinct from _uncertain() above: "uncertain" is this module's
    existing vocabulary for "the note/TP data is genuinely ambiguous or
    incomplete" (a data-content problem). This is for a real, different
    kind of gap -- a real upstream infrastructure failure prevented this
    file's extraction from running at all, so there's no data here to be
    ambiguous ABOUT. Live incident fix (2026-08): see
    session_note_extraction.py's EXTRACTION_ERROR_KEY docstring for why
    this must never look identical to "this note states nothing"."""
    return {"result": "not_checkable", "evidence": evidence, "confidence": 0.0}


def _finding(result: str, evidence: str, confidence: float) -> dict[str, Any]:
    return {"result": result, "evidence": evidence, "confidence": confidence}


def _extraction_error(extraction: dict[str, Any] | None) -> str | None:
    """Returns the real upstream-failure message if this extraction is
    the failure-marker shape session_note_extraction.py's
    _extraction_failed_result() produces, else None (a normal, real
    extraction, whether or not it happens to be all-empty)."""
    return (extraction or {}).get("_extraction_error")


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
        # Fix Round (2026-08-27): REAL BUG FOUND AND FIXED -- this exposed
        # the literal internal field name "session_date" and Python's
        # repr() of the raw value (including a bare "None") directly in
        # reviewer-facing evidence text. Plain language now, regardless of
        # WHY the date couldn't be determined (missing vs. unparseable are
        # the same real outcome for a reviewer: no usable date).
        return _uncertain("Could not determine a session date from the session note.")
    if report_start is None or report_end is None:
        # Fix Round (2026-08-27): same class of bug as the session_date
        # case above -- !r would print a literal "None" when the TP
        # simply never stated its own report period at all. Only include
        # the raw stated text when there genuinely IS one to show.
        detail = f" (TP states {current_report_period_str!r})" if current_report_period_str else ""
        return _uncertain(f"Could not determine both ends of the TP's current-report date range{detail}.")

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

    Master Fix Round (2026-09-08) -- REAL BUG FOUND AND FIXED: this used to
    re-prefix each sub-result with `sub_results`'s own dict key (e.g.
    "assessment date: ..."), but check_field_match already embeds its own
    field_label in the evidence text it returns (e.g. "Assessment date:
    session note (...) matches..."), so the combined evidence duplicated
    the label -- "assessment date: Assessment date: session note...".
    Each sub-result's evidence is already a complete, correctly-labeled
    sentence; just join them, don't add a second label.
    """
    findings = list(sub_results.values())
    evidence = " | ".join(r["evidence"] for r in sub_results.values())
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


def check_note_detail_level_across_notes(
    session_extractions: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """Fix Round (2026-08-27): the real, session-note-content-based half of
    QA-COC-01 ("session note detailed") -- previously never checked at all
    (confirmed dead-description). Unlike QA-ACF-02/QA-ACF-08, this isn't
    tied to one specific date-matched note (COC-01's own notes name no
    such pairing) -- every uploaded, successfully-extracted note counts:
    if AT LEAST ONE reads as "detailed", that satisfies this half (a
    reviewer only needs one real, substantive session note on file, not
    every single one to individually qualify). Fails only if every
    successfully-extracted note came back "minimal". Uncertain if none
    extracted with a confident value at all.

    This is the "detailed" half ONLY -- QA-COC-01 is a compound rule (also
    checks the COC section's own provider name/title/date, from the TP
    text alone); the caller (app/rule_engine/client.py) combines this with
    that other half's own result rather than overwriting it wholesale.
    """
    ok_extractions = {fn: ext for fn, ext in session_extractions.items() if not _extraction_error(ext)}
    if not ok_extractions:
        return _uncertain("No successfully-extracted session note to check for narrative detail.")

    levels_by_file: dict[str, str | None] = {}
    for filename, extraction in ok_extractions.items():
        entry = (extraction or {}).get("note_detail_level") or {}
        levels_by_file[filename] = entry.get("value") if entry.get("confidence") != "none" else None

    if any(level == "detailed" for level in levels_by_file.values()):
        detailed_files = [fn for fn, level in levels_by_file.items() if level == "detailed"]
        return _finding(
            "pass",
            f"At least one uploaded session note reads as detailed (names real session content): {detailed_files}.",
            0.8,
        )
    if all(level == "minimal" for level in levels_by_file.values()) and levels_by_file:
        return _finding(
            "fail",
            f"Every uploaded session note only confirms contact occurred, without naming real content: "
            f"{list(levels_by_file.keys())}.",
            0.8,
        )
    return _uncertain(
        f"Could not confidently determine narrative detail level for the uploaded session note(s): "
        f"{levels_by_file}."
    )


def combine_compound_rule_result(phase1_result: dict[str, Any] | None, real_data_result: dict[str, Any]) -> dict[str, Any]:
    """Fix Round (2026-08-27): generic combine policy for a rule that's
    partly answerable from the TP alone (phase 1's own judgment call,
    reasoning blind to session-note/intake data) and partly from real
    session-note/intake data (a separate, later-computed signal) --
    QA-COC-01 is the first user of this, but it's written generic (plain
    {result, evidence, confidence} dicts in, same shape out) so any future
    compound rule can reuse it rather than each caller inventing its own
    merge policy.

    Policy, same "a real, contradicting signal wins" reasoning as every
    other override in this pipeline:
    - Either side "fail" -> combined "fail" (a confirmed problem on either
      half is a real problem; the other half being fine doesn't cancel it).
    - Both sides "pass" -> combined "pass".
    - Real-data side resolves ("pass") what phase 1 couldn't (phase 1 was
      "uncertain"/"not_checkable", genuinely blind to this half without
      session-note/intake data) -> combined uses the real-data side's own
      resolution (phase 1 had nothing to contribute past that point).
    - Real-data side itself couldn't resolve ("uncertain"/"not_checkable")
      but phase 1 confidently passed on its own (TP-only) half -> combined
      stays phase 1's own result; the real-data check simply couldn't add
      or subtract anything here.
    - Otherwise (both genuinely unresolved) -> "not_checkable" if BOTH
      sides are specifically "not_checkable" (both agree it's a real
      data/infrastructure gap, not ambiguous evidence -- collapsing this
      into "uncertain" would be a real, wrong status change, confirmed by
      a real test this round: the unmatched-rule-code fallback path
      legitimately produces "not_checkable" + "not_checkable" for a rule
      with zero real findings, and that must stay "not_checkable", not
      quietly become "uncertain"). "uncertain" otherwise (at least one
      side is genuinely ambiguous evidence, not just missing data).

    `phase1_result=None` (no draft available for some reason) is treated
    the same as phase 1 being uncertain.
    """
    p1 = phase1_result or _uncertain("No phase 1 result available.")
    evidence = f"{p1['evidence']} | {real_data_result['evidence']}"

    if p1["result"] == "fail" or real_data_result["result"] == "fail":
        confidence = max(p1.get("confidence") or 0.0, real_data_result.get("confidence") or 0.0)
        return _finding("fail", evidence, confidence)
    if p1["result"] == "pass" and real_data_result["result"] == "pass":
        confidence = min(p1.get("confidence") or 0.0, real_data_result.get("confidence") or 0.0)
        return _finding("pass", evidence, confidence)
    if p1["result"] in ("uncertain", "not_checkable") and real_data_result["result"] == "pass":
        return _finding("pass", evidence, real_data_result.get("confidence") or 0.0)
    if real_data_result["result"] in ("uncertain", "not_checkable") and p1["result"] == "pass":
        return _finding("pass", evidence, p1.get("confidence") or 0.0)
    if p1["result"] == "not_checkable" and real_data_result["result"] == "not_checkable":
        return _not_checkable(evidence)
    return _uncertain(evidence)


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

    Live incident fix (2026-08): a file whose extraction genuinely failed
    (session_note_extraction.py's EXTRACTION_ERROR_KEY sentinel -- a real
    upstream model-provider failure, retried and still not resolved) is
    handled separately from a normal extraction, for both rules below --
    see the inline comments at each point this fix touches.
    """
    def value_or_none(extraction: dict, field: str) -> str | None:
        entry = (extraction or {}).get(field) or {}
        return entry.get("value") if entry.get("confidence") != "none" else None

    ok_extractions = {fn: ext for fn, ext in session_extractions.items() if not _extraction_error(ext)}
    failed_files = {fn: _extraction_error(ext) for fn, ext in session_extractions.items() if _extraction_error(ext)}

    # QA-RPT-03: a genuinely failed file contributes a real, distinctive
    # not_checkable entry (never silently skipped, never read as "this
    # note has no date") into the SAME per-file evidence join every other
    # file already uses -- so the failure is visible in the final result's
    # own evidence text, not just in a log line.
    rpt03_by_file = {
        filename: check_date_in_current_report_period(
            value_or_none(extraction, "session_date"), tp_current_report_period,
        )
        for filename, extraction in ok_extractions.items()
    }
    for filename, error in failed_files.items():
        rpt03_by_file[filename] = _not_checkable(
            f"Extraction for this file failed due to a real upstream model-provider failure (not a "
            f"data-absence issue): {error}"
        )

    if not rpt03_by_file:
        rpt03_combined = _uncertain("No session notes were uploaded.")
    else:
        evidence = " | ".join(f"{fn}: {r['evidence']}" for fn, r in rpt03_by_file.items())
        failing_confidences = [r["confidence"] for r in rpt03_by_file.values() if r["result"] == "fail"]
        if failing_confidences:
            # A real, confirmed problem on another file takes priority
            # over "we couldn't check one file" -- it's the more
            # actionable finding.
            rpt03_combined = _finding("fail", evidence, max(failing_confidences))
        elif any(r["result"] == "not_checkable" for r in rpt03_by_file.values()):
            rpt03_combined = _not_checkable(evidence)
        elif all(r["result"] == "pass" for r in rpt03_by_file.values()):
            rpt03_combined = _finding("pass", evidence, min(r["confidence"] for r in rpt03_by_file.values()))
        else:
            rpt03_combined = _uncertain(evidence)

    # QA-ACF-02/QA-ACF-08: only match against successfully-extracted
    # files -- a failed file's own session_date is unreadable (all fields
    # are confidence="none"), so it can never spuriously "match" the TP's
    # stated Assessment Date. If no OK file matches AND at least one file
    # genuinely failed extraction, that failure might well be exactly why
    # no match was found (the matching note could be the one that failed)
    # -- say so plainly instead of the generic "no note's date matches"
    # message, which would misleadingly suggest every file was read fine
    # and none happened to match.
    _, matched_extraction = select_matching_session_note(ok_extractions, tp_assessment_date)
    if matched_extraction is None and failed_files:
        failure_note = " | ".join(f"{fn}: {err}" for fn, err in failed_files.items())
        no_match_due_to_failure = (
            f"No successfully-extracted session note's date matches the TP's stated Assessment Date "
            f"({tp_assessment_date!r}), and {len(failed_files)} file(s) could not be extracted at all "
            f"due to a real upstream failure ({failure_note}) -- the matching note may be one of those. "
            f"Flagged not_checkable rather than guessed at."
        )
        # Fix Round, Section 1 Bucket C (2026-08-27): QA-ACF-12 gets the
        # SAME treatment as ACF-02/ACF-08 in this exact branch (a real
        # upstream extraction failure on the file that might be the
        # matching one) -- same not_checkable evidence, not a silently
        # missing key the way QA-COC-01 already is in this specific
        # branch (a pre-existing gap, not introduced or touched here).
        return {
            "QA-RPT-03": rpt03_combined,
            "QA-ACF-02": _not_checkable(no_match_due_to_failure),
            "QA-ACF-08": _not_checkable(no_match_due_to_failure),
            "QA-ACF-12": _not_checkable(no_match_due_to_failure),
        }
    if matched_extraction is None:
        no_match_evidence = (
            f"No uploaded session note's own date matches the TP's stated Assessment Date "
            f"({tp_assessment_date!r}) -- cannot confirm which note backs this specific assessment."
        )
        acf02 = _uncertain(no_match_evidence)
        acf08 = _uncertain(no_match_evidence)
        # Fix Round, Section 1 Bucket C (2026-08-27): see this function's
        # own docstring -- QA-ACF-12's session-note cross-check half.
        acf12_session = _uncertain(no_match_evidence)
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
        # Fix Round, Section 1 Bucket C (2026-08-27): QA-ACF-12's own real
        # gap -- the rule's TP-only phase-1 half (fields.py::_check_ACF12)
        # only ever checked the TP's own Assessment Date against the TP's
        # own report-date range; it never cross-referenced the real
        # session note the way QA-ACF-02/QA-ACF-08 already do. Reuses
        # check_field_match (the SAME exact-match helper QA-ACF-02's own
        # date sub-check already uses) against the SAME matched note
        # ACF-02/ACF-08 use -- not a new matching mechanism. This is
        # COMPOUND with phase 1 (see combine_compound_rule_result, and
        # app/agent_client.py's _SESSION_NOTES_COMPOUND_RULE_IDS on the
        # backend side), not a replacement for the report-date-range/
        # testing-tool-date check phase 1 already does.
        session_date = value_or_none(matched_extraction, "session_date")
        acf12_session = check_field_match(session_date, tp_assessment_date, field_label="Assessment Date")

    # Fix Round (2026-08-27): QA-COC-01's "detailed" half -- checked across
    # EVERY successfully-extracted note (see check_note_detail_level_across_
    # notes's own docstring for why this one isn't date-matched to a single
    # note the way ACF-02/ACF-08 are).
    coc01_detail = check_note_detail_level_across_notes(ok_extractions)

    return {
        "QA-RPT-03": rpt03_combined, "QA-ACF-02": acf02, "QA-ACF-08": acf08, "QA-COC-01": coc01_detail,
        "QA-ACF-12": acf12_session,
    }
