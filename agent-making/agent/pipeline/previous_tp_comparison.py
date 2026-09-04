"""Previous TP round -- REAL comparison logic for QA-MAST-01, QA-MAST-02,
QA-RPT-05 (previous-auth-end half), QA-ACF-04, and QA-PROB-04.

Ground truth for this round: Ms. Yachnes's real worked answers for two real
patients (Mihad Ali and Jacob F/"JF") -- see this round's own report for the
full detail; NOTHING from either real document (names, dates, goal text,
scores) is hardcoded anywhere in this file or its tests, per this round's
own explicit instruction. Those worked examples shaped the LOGIC below, not
literal reference data baked into the system.

Structural mirror of pipeline/session_note_comparison.py: a pure-Python
`compare_previous_tp_to_tp()` entry point returning
`{rule_id: {result, evidence, confidence}}`, EXCEPT that two of these five
comparisons can each make real, narrow model calls -- unlike
session_note_comparison.py, which is 100% deterministic Python:
QA-ACF-04's score extraction (boxed field -> vision on a rendered
milestone-grid image, via model_provider.py::call_tool_json_with_images ->
narrative-text fallback, via call_tool_json, in that order) and
QA-PROB-04's near-identical semantic read (call_tool_json). Every real-call
path is used ONLY when a cheaper check can't answer -- see each function's
own docstring.

Fix Round (Previous TP: 3 Real Bugs, Jacob F) fixed 3 real bugs found by
running this module against a real previous+current TP pair (Jacob
Freund) and checking results against both real PDFs and Ms. Yachnes's own
confirmed real answer: Bug 1 (QA-MAST-01 compared against the wrong date
field -- "Authorization Dates Requested" instead of "Date of Current
Report"), Bug 2 (QA-ACF-04 had no way to read a score that lives in an
embedded image, not text -- now has real vision), Bug 3 (QA-PROB-04
compared the wrong text span -- the fixed rubric template instead of the
patient-specific "As evidenced by:" findings). See each function's own
docstring for the full detail.

Compound-combine policy: QA-MAST-01/QA-MAST-02 are treated as PURE
OVERRIDES (same shape as QA-RPT-03/QA-ACF-02/QA-ACF-08 in
session_note_comparison.py) -- their existing TP-only phase-1 answer (per
their own rules.json notes) is always not_checkable/a blind guess absent
previous-TP data, so there's nothing meaningful to combine; when a previous
TP exists, this module's own answer simply becomes the final one.
QA-RPT-05/QA-ACF-04/QA-PROB-04 are COMPOUND (same shape as
QA-COC-01/QA-ACF-12) -- each has a real, meaningful TP-only phase-1 half
(RPT-05's existing 26-week-default checker; ACF-04/PROB-04's existing
judgment-layer attempt), combined with this module's own previous-TP-derived
half via combine_compound_rule_result. The actual combine call happens at
the backend layer (app/agent_client.py::review_previous_tp), same split of
responsibility session-notes already uses -- this module only ever returns
its OWN half of each compound rule's answer, never touches phase1 itself.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .fields import _extract_evidenced_by_blocks, _normalize_goal_text
from .model_provider import CallTracker, call_tool_json, call_tool_json_with_images


def _finding(result: str, evidence: str, confidence: float) -> dict[str, Any]:
    return {"result": result, "evidence": evidence, "confidence": confidence}


def _not_checkable(evidence: str) -> dict[str, Any]:
    return _finding("not_checkable", evidence, 0.0)


def _parse_date(date_str: str | None) -> datetime | None:
    """Every date this module reads comes from _find_labeled_date_range or
    _extract_mastered_goals_with_dates, both of which only ever hand back
    raw "MM/DD/YYYY"-shaped strings (or None) -- no parsing/validation was
    done at extraction time (see each function's own docstring). This is
    that parsing step, centralized so every comparison below fails the
    same, safe way (None, never a guess/exception) on a malformed date
    rather than each comparison reimplementing its own try/except.
    """
    if not date_str:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# --- QA-MAST-01 -------------------------------------------------------------


def _compare_mast01(current_fields: dict, previous_fields: dict) -> dict[str, Any]:
    """Each CURRENT TP mastered goal's own Date Mastered must fall within
    the elapsed-authorization WINDOW spanning from the PREVIOUS TP's own
    "Date of Current Report" START through the CURRENT TP's own "Date of
    Current Report" END.

    Fix Round (Previous TP, U3 re-run), Bug 1 -- REAL BUG FOUND AND FIXED,
    confirmed against the real Jacob Freund pair: the prior round's fix
    (comparing every current-TP mastered goal against ONLY the previous
    TP's own narrow ~2-week report window) regressed hard on this real
    document -- Jacob's real "Mastered Goals:" section is a genuine
    CUMULATIVE list (58 real entries, dated 02/12/2026 through
    08/10/2026, confirmed by direct extraction -- not a scoping/regex bug:
    the section-boundary extraction correctly bounds to the ONE real
    "Mastered Goals:" section on this document, ending cleanly at "Goals
    in Progress:"; there is no second, narrower "this period only" list
    hiding elsewhere in this document to redirect to, disproving that
    hypothesis directly). Comparing an 8-month cumulative spread against a
    single 2-week window from an old document was always going to fail
    almost everything in it.

    CONFIRMED FIX: the real min/max dates on Jacob's current TP (02/12 and
    08/10/2026) line up almost exactly with the previous TP's own report
    START (02/10/2026) and the CURRENT TP's own report END (08/21/2026) --
    i.e. the real, intended window is the full elapsed span BETWEEN the
    two documents' own report periods, not the previous document's report
    window alone. This still matches the original Mihad Ali motivating
    example (goals dated within a single narrow window naturally still
    fall inside a WIDER one -- widening the window only ever admits MORE
    valid dates, never fewer, so a genuinely out-of-window date, e.g.
    mastered before program start or after the current report was even
    written, is still caught).
    """
    current_goals = current_fields.get("mastered_goals") or []
    if not current_goals:
        return _not_checkable("No 'Mastered Goals:' entries found on the current TP to check.")

    prev_range = previous_fields.get("report_date_range")
    current_range = current_fields.get("report_date_range")
    if not prev_range or not current_range:
        return _not_checkable(
            "Could not find a 'Date of Current Report' range on both the previous and current TP to "
            "check mastered-goal dates against."
        )
    range_start = _parse_date(prev_range[0])
    range_end = _parse_date(current_range[1])
    if not range_start or not range_end:
        return _not_checkable(
            f"Previous TP's report start ({prev_range[0]!r}) or current TP's report end "
            f"({current_range[1]!r}) could not be parsed as real dates."
        )

    out_of_range = []
    checked_any = False
    for g in current_goals:
        d = _parse_date(g.get("date_mastered"))
        if d is None:
            continue
        checked_any = True
        if not (range_start <= d <= range_end):
            out_of_range.append((g.get("name", "").strip(), g["date_mastered"]))

    if not checked_any:
        return _not_checkable(
            "No mastered goal on the current TP has a parseable Date Mastered value to check."
        )
    window_desc = f"{prev_range[0]} (previous TP's report start) to {current_range[1]} (current TP's report end)"
    if out_of_range:
        detail = "; ".join(f"{name!r} (Date Mastered {dm})" for name, dm in out_of_range)
        return _finding(
            "fail",
            (
                f"{len(out_of_range)} mastered goal(s) on the current TP have a Date Mastered outside "
                f"the elapsed-authorization window ({window_desc}): {detail}."
            ),
            0.75,
        )
    return _finding(
        "pass",
        (
            f"Every mastered goal on the current TP with a parseable Date Mastered falls within the "
            f"elapsed-authorization window ({window_desc})."
        ),
        0.75,
    )


# --- QA-MAST-02 -------------------------------------------------------------


def _compare_mast02(current_fields: dict, previous_fields: dict) -> dict[str, Any]:
    """Same exact-after-normalization duplicate-detection shape QA-GIP-05
    already uses (fields.py::_normalize_goal_text + dict/set membership,
    NOT fuzzy matching) -- reused verbatim, just comparing across two
    DOCUMENTS' Mastered Goals lists instead of one document's Mastered vs.
    active-goal sections. Ms. Yachnes's own stated rule (this round's
    brief): "If it appears in one TP, it should NOT appear in the other."
    """
    current_goals = current_fields.get("mastered_goals") or []
    previous_goals = previous_fields.get("mastered_goals") or []
    if not current_goals or not previous_goals:
        return _not_checkable(
            "Could not find a 'Mastered Goals:' list with named entries on both the current and "
            "previous TP to compare."
        )

    previous_by_norm: dict[str, str] = {}
    for g in previous_goals:
        name = (g.get("name") or "").strip()
        if name:
            previous_by_norm.setdefault(_normalize_goal_text(name), name)

    duplicates = []
    for g in current_goals:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        norm = _normalize_goal_text(name)
        if norm in previous_by_norm:
            duplicates.append(name)

    if duplicates:
        detail = "; ".join(repr(d) for d in duplicates)
        return _finding(
            "fail",
            (
                f"{len(duplicates)} mastered goal(s) appear on BOTH the current and previous TP's "
                f"Mastered Goals list: {detail}."
            ),
            0.75,
        )
    return _finding(
        "pass",
        "No mastered goal name (formatting-normalized) appears on both the current and previous TP's "
        "Mastered Goals list.",
        0.75,
    )


# --- QA-RPT-05 (previous-auth-end half only) ---------------------------------


def _compare_rpt05_previous_auth_end(current_fields: dict, previous_fields: dict) -> dict[str, Any]:
    """The SECOND half of QA-RPT-05's own two-part description -- the
    existing fields.py::_check_RPT05 only ever computes the 26-week-
    default-window half from the CURRENT TP alone (see its own docstring,
    explicitly out of scope for that function). This is the "previous auth
    end" half: current TP's Authorization Dates Requested START must be
    exactly the day after the previous TP's Authorization Dates Requested
    END. Matches Ms. Yachnes's real Mihad Ali (adjacent, 8/5 -> 8/6 =
    pass) and Jacob F (gap, 9/2 -> 10/16 = fail) examples.

    This function's own result gets COMBINED with _check_RPT05's existing
    result via combine_compound_rule_result at the backend layer (both
    halves must hold for an overall pass) -- this function never sees or
    touches _check_RPT05's own answer.
    """
    current_range = current_fields.get("auth_dates_requested")
    previous_range = previous_fields.get("auth_dates_requested")
    if not current_range or not previous_range:
        return _not_checkable(
            "Could not find 'Authorization Dates Requested' on both the current and previous TP to "
            "check for a gap/overlap at the boundary."
        )
    current_start = _parse_date(current_range[0])
    previous_end = _parse_date(previous_range[1])
    if not current_start or not previous_end:
        return _not_checkable(
            f"Current TP auth start ({current_range[0]!r}) or previous TP auth end "
            f"({previous_range[1]!r}) could not be parsed as a real date."
        )

    gap_days = (current_start - previous_end).days - 1  # 0 = directly adjacent (no gap)
    if gap_days == 0:
        return _finding(
            "pass",
            (
                f"Current TP's requested auth start ({current_range[0]}) is exactly the day after the "
                f"previous TP's requested auth end ({previous_range[1]}) -- no gap."
            ),
            0.8,
        )
    if gap_days > 0:
        return _finding(
            "fail",
            (
                f"Current TP's requested auth start ({current_range[0]}) is {gap_days} day(s) after the "
                f"previous TP's requested auth end ({previous_range[1]}) -- a gap in coverage."
            ),
            0.8,
        )
    return _finding(
        "fail",
        (
            f"Current TP's requested auth start ({current_range[0]}) overlaps the previous TP's "
            f"requested auth end ({previous_range[1]}) by {-gap_days} day(s)."
        ),
        0.8,
    )


# --- QA-ACF-04 ---------------------------------------------------------------


_ACF04_SCORE_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {
            "type": "boolean",
            "description": "true only if a specific numeric score for this assessment tool is stated in the text, "
                            "even in plain narrative sentences (not just a boxed/labeled field).",
        },
        "score": {
            "type": ["number", "null"],
            "description": "The numeric score value if found, else null.",
        },
    },
    "required": ["found", "score"],
}


_ACF04_VISION_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {
            "type": "boolean",
            "description": "true only if a specific numeric score for the MOST RECENT completed test row is "
                            "visible in the rendered image(s).",
        },
        "score": {
            "type": ["number", "null"],
            "description": "The numeric score value for the most recent completed test row, if found, else null.",
        },
        "score_date": {
            "type": ["string", "null"],
            "description": "The date shown next to that score in the grid's own key/legend table, if visible "
                            "(e.g. 'Aug-26'), else null. Used to double-check the model picked the right row, "
                            "not a blank or earlier one.",
        },
    },
    "required": ["found", "score"],
}


def _extract_acf_score_vision(
    milestone_grid_images: dict[int, bytes], assessment_tool: str | None, *, tracker: CallTracker,
    model_override: str | None,
) -> tuple[float | None, str | None]:
    """Fix Round (Previous TP: 3 Real Bugs, Jacob F), Bug 2 -- REAL
    CAPABILITY GAP FOUND AND FIXED, confirmed against real documents: the
    score genuinely isn't in extractable text at all on some documents --
    Jacob Freund's real current TP literally states "Below you will find
    the milestone grid" immediately before an embedded image containing
    the VB-MAPP/ABLLS-style score grid. Neither the boxed/structured
    extractor NOR the old narrative-text judgment fallback below can see
    an image -- this is the real, vision-based fix, via
    model_provider.py::call_tool_json_with_images (call_tool_json itself
    has no way to attach an image -- confirmed, see that function's own
    docstring). ONLY called when `milestone_grid_images` is non-empty --
    this is a real, billed Anthropic call (vision requires the
    "anthropic" provider explicitly), made only when there's an actual
    image to look at.

    U3 re-run round -- REAL BUG FOUND AND FIXED (still not working):
    confirmed via direct visual inspection of both real Jacob Freund
    documents that the grid's own "Key" table lists MULTIPLE historical
    test rows (1st/2nd/3rd/4th test, each with its own Score + Date), not
    one single score -- the earlier prompt just asked for "the score",
    which is genuinely ambiguous on a real grid shaped like this. Now
    explicitly instructs the model to identify the MOST RECENT test row
    that actually has both a score AND a date filled in (the blank/black
    "4th test" row on both real documents must never be picked), and
    returns the matching date alongside the score so a human reviewer (or
    a future round) can spot-check which row was actually read, rather
    than trusting a bare number with no traceability.
    """
    tool_label = assessment_tool or "the assessment/testing tool used in this document"
    prompt = (
        f"Look at the rendered treatment-plan page image(s) below, which contain a milestone/scoring grid "
        f"for {tool_label}. The grid's own 'Key' table lists multiple historical test rows (1st test, 2nd "
        f"test, 3rd test, 4th test), each with its own Score and Date column -- NOT one single score. Find "
        f"the MOST RECENT row that has BOTH a score AND a date actually filled in (skip any row left blank "
        f"-- a blank row is not a real, completed test). Report that row's own numeric score (not a "
        f"subscale count, not a page number) and its own date. If every row is genuinely blank, or the key "
        f"table itself isn't visible, say not found."
    )
    result = call_tool_json_with_images(
        prompt_text=prompt,
        images=milestone_grid_images,
        tool_name="report_milestone_grid_score",
        tool_description="Report the most recent completed test's numeric score and date, visible in a "
                          "rendered milestone grid image.",
        input_schema=_ACF04_VISION_SCORE_SCHEMA,
        tracker=tracker,
        model_override=model_override,
        call_reason="acf04_vision_score",
    )
    if result.get("found") and result.get("score") is not None:
        try:
            return float(result["score"]), result.get("score_date")
        except (TypeError, ValueError):
            return None, None
    return None, None


def _extract_acf_score_narrative(
    full_text: str, assessment_tool: str | None, *, tracker: CallTracker, model_override: str | None,
) -> float | None:
    """Judgment-layer fallback for QA-ACF-04's real, flagged extraction gap
    (Ms. Yachnes, an earlier round's brief): "The system should also check
    for times that the BCBA writes the score out and it is not in a 'box'
    ..." -- e.g. "Zyaan scored a 53 on the ABLLS-R" in flowing prose, which
    no reliable regex can distinguish from every OTHER number in a TP (page
    numbers, hours, ages, CPT codes). This is the TEXT-only fallback --
    used only when BOTH the boxed extractor AND the vision extractor above
    found nothing (no milestone-grid image on this document at all, and no
    boxed field either) -- a real, narrow, single-purpose call via
    model_provider.py::call_tool_json (the same primitive
    session_note_extraction.py already uses for this exact "one structured
    JSON answer, not a full rule batch" shape), not judge.py's full-batch
    machinery.
    """
    tool_label = assessment_tool or "the assessment/testing tool used in this document"
    prompt = (
        "Read the following treatment plan text. Find whether it states a specific NUMERIC score for "
        f"{tool_label}, anywhere in the text -- including plain narrative sentences, not only a boxed or "
        "labeled 'Score:' field. If multiple numbers are near the tool's name, only report one if it is "
        "unambiguously THIS tool's own overall/total score (not a subscale, not a date, not a page "
        "number, not an hours/CPT value). If genuinely absent or ambiguous, say not found.\n\n"
        f"--- DOCUMENT TEXT ---\n{full_text[:12000]}"
    )
    result = call_tool_json(
        prompt_text=prompt,
        tool_name="report_acf_score",
        tool_description="Report whether a numeric assessment-tool score was found in narrative text, and its value.",
        input_schema=_ACF04_SCORE_TOOL_SCHEMA,
        tracker=tracker,
        model_override=model_override,
        call_reason="acf04_narrative_score",
    )
    if result.get("found") and result.get("score") is not None:
        try:
            return float(result["score"])
        except (TypeError, ValueError):
            return None
    return None


def _get_acf_score(
    fields: dict, *, tracker: CallTracker, model_override: str | None,
) -> tuple[float | None, str | None]:
    """Boxed extraction first (free, deterministic); then vision (if this
    document has a milestone-grid image); then the narrative-text judgment
    fallback last (in case a document has neither a box nor a grid image,
    just prose). Returns (score, method) where method is "boxed",
    "vision (milestone grid, dated <score_date>)" (the date included for
    real traceability -- U3 re-run round's own fix, so a reviewer can spot-
    check which of the grid's multiple historical rows was actually read),
    or "narrative (judgment)", for evidence text."""
    boxed = fields.get("acf_score_boxed")
    if boxed is not None:
        return boxed, "boxed"
    assessment_tool = (fields.get("acf_fields") or {}).get("assessment_tool")
    grid_images = fields.get("milestone_grid_images") or {}
    if grid_images:
        vision_score, score_date = _extract_acf_score_vision(
            grid_images, assessment_tool, tracker=tracker, model_override=model_override,
        )
        if vision_score is not None:
            method = f"vision (milestone grid, dated {score_date})" if score_date else "vision (milestone grid)"
            return vision_score, method
    narrative = _extract_acf_score_narrative(
        fields.get("full_text", ""), assessment_tool, tracker=tracker, model_override=model_override,
    )
    if narrative is not None:
        return narrative, "narrative (judgment)"
    return None, None


def _compare_acf04(
    current_fields: dict, previous_fields: dict, *, tracker: CallTracker, model_override: str | None,
) -> dict[str, Any]:
    """FAIL (real Director-tag trigger, per this rule's own rules.json
    action_tag) if the current TP's assessment score for a tool is LOWER
    than the previous TP's score for the same tool -- matches Ms. Yachnes's
    real Mihad Ali (55 -> 53, fail) and Jacob F (higher, pass) examples.

    This function is ONLY ever called with a real previous TP (see
    app/agent_client.py::review_previous_tp's own early-return when
    `previous_tp_path` is None) -- so a not_checkable result here NEVER
    means "no previous TP to compare" (Fix Round, Bug 2's smaller fix: the
    combined evidence text used to read "No prior TP version exists to
    compare | ..." even when a real previous TP genuinely was uploaded and
    used correctly by MAST-01/RPT-05 in the same run -- that phrase came
    from phase-1's own blind, previous-TP-unaware judgment attempt,
    concatenated in by combine_compound_rule_result. This function's OWN
    evidence text is written to be unambiguous on its own terms
    regardless of what phase-1 said, so a reviewer never gets misled).
    """
    current_score, current_method = _get_acf_score(current_fields, tracker=tracker, model_override=model_override)
    previous_score, previous_method = _get_acf_score(previous_fields, tracker=tracker, model_override=model_override)

    if current_score is None or previous_score is None:
        missing = []
        if current_score is None:
            missing.append("current TP")
        if previous_score is None:
            missing.append("previous TP")
        return _not_checkable(
            f"A previous TP was found and read directly for this comparison. Could not find a numeric "
            f"assessment score -- checked a boxed/labeled field, a rendered milestone-grid image (if one "
            f"was found in the document), and narrative text -- on: {', '.join(missing)}."
        )

    current_tool = (current_fields.get("acf_fields") or {}).get("assessment_tool") or "the assessment tool"
    # Confidence: "boxed" is the highest-confidence source (a real
    # structured/labeled field); "vision (milestone grid)" and "narrative
    # (judgment)" are both judgment-derived, same lower confidence. (Bug
    # caught in an earlier round's own testing: the original
    # "narrative" in (a, b) check was TUPLE MEMBERSHIP, not a substring
    # check, and always evaluated False -- fixed then, and this
    # not-boxed check generalizes cleanly to the new "vision" method too.)
    any_non_boxed = any(m != "boxed" for m in (current_method, previous_method) if m)
    confidence = 0.7 if any_non_boxed else 0.8
    if current_score < previous_score:
        return _finding(
            "fail",
            (
                f"{current_tool} score dropped from {previous_score:g} (previous TP, {previous_method}) to "
                f"{current_score:g} (current TP, {current_method})."
            ),
            confidence,
        )
    return _finding(
        "pass",
        (
            f"{current_tool} score did not drop: {previous_score:g} (previous TP, {previous_method}) -> "
            f"{current_score:g} (current TP, {current_method})."
        ),
        confidence,
    )


# --- QA-PROB-04 (no confirmed real example yet -- see this round's report) --


_PROB04_SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "new_or_changed_content": {
            "type": "string",
            "description": "Quote or describe anything genuinely NEW in the CURRENT text that does not appear in "
                            "the PREVIOUS text -- real progress notes, status changes, added/removed findings, "
                            "'(in progress)'-style annotations, etc. Leave this EMPTY (\"\") only if the current "
                            "text is a genuine word-for-word or paraphrased repeat with nothing added or changed. "
                            "Do not leave this empty just because the two texts share the same overall topic or "
                            "category -- if the CURRENT text adds even one real detail the PREVIOUS text lacks, "
                            "quote it here.",
        },
        "current_explains_limited_services": {
            "type": "boolean",
            "description": "true only if the CURRENT text itself states/explains that the findings are unchanged "
                            "because very limited or no additional services were provided. Only meaningful when "
                            "new_or_changed_content is empty -- ignored otherwise.",
        },
        "reasoning": {"type": "string", "description": "One sentence explaining the judgment."},
    },
    "required": ["new_or_changed_content", "current_explains_limited_services", "reasoning"],
}


def _compare_prob04(
    current_fields: dict, previous_fields: dict, *, tracker: CallTracker, model_override: str | None,
) -> dict[str, Any]:
    """STILL NOT VERIFIED against a real worked example (Ms. Yachnes has
    not sent one for this rule despite being asked twice) -- built from
    QA-PROB-04's own rules.json description: "Problem Areas should not be
    identical to the previous TP unless services provided are very
    limited; if identical, TP should state this is because no additional
    services were provided." Flag the result of this function plainly as
    "corrected extraction, still awaiting her confirmation" wherever it's
    surfaced -- the extraction fix below is confirmed against the real
    documents directly (Bug 3), but the RULE's pass/fail judgment itself
    has no confirmed real answer yet.

    Fix Round (Previous TP: 3 Real Bugs, Jacob F), Bug 3 -- REAL BUG FOUND
    AND FIXED, confirmed against real documents: this used to compare
    `problem_areas` (fields.py::_extract_problem_areas), which captures
    the Problem Area LABEL's own rubric/template text -- the DSM-style
    boilerplate description ("Deficits in social-emotional reciprocity,
    ranging, for example...") that's IDENTICAL for every patient's document
    by design, not patient-specific content. Confirmed on Jacob Freund's
    real documents: that boilerplate text genuinely is identical across
    both TPs (correctly), but the real client-specific findings live in
    each category's "As evidenced by:" block instead -- the current TP adds
    real progress annotations ("Jacob struggles to approach peers -
    improved since last auth", "(in progress)") that don't appear on the
    previous TP. Comparing the wrong span made every patient's Problem
    Areas look "identical" regardless of real progress. Now uses
    fields.py::_extract_evidenced_by_blocks, which reuses
    _EVIDENCED_BY_BLOCK_RE VERBATIM (already used by _check_PROB01, per
    this round's own explicit instruction not to build a new regex).

    A genuine semantic "is this substantively the same" read needs real
    language understanding (brittle exact-string matching would miss
    reworded-but-same-meaning text, and false-positive on genuinely
    different text that happens to share boilerplate phrasing) -- one real,
    narrow judgment call, same call_tool_json primitive as QA-ACF-04's
    narrative fallback above, per this round's own explicit instruction not
    to avoid a real model call here.

    U3 re-run round -- REAL BUG FOUND AND FIXED (self-contradiction):
    confirmed live, the model's own free-text `reasoning` explicitly named
    real added progress content ("...with progress notes added...") while
    the separate `substantively_identical` boolean it ALSO returned still
    said true -- the schema asked the model to make two independent
    judgment calls (a holistic "same or different" boolean, and a prose
    explanation) that could silently disagree with each other, and
    nothing in the code caught it. Root cause wasn't a missing branch in
    THIS function (it always faithfully branched on whatever
    `substantively_identical` said) -- it was the SCHEMA letting the model
    assert "identical" and separately narrate a real difference in the
    same response. Fixed by removing `substantively_identical` as
    something the model asserts directly: it now must name the specific
    new/changed content instead (`new_or_changed_content`), and
    `identical` is DERIVED in code from whether that field came back
    empty -- the model can no longer contradict itself, because there is
    no longer a second, independent field to contradict.
    """
    current_blocks = _extract_evidenced_by_blocks(current_fields.get("full_text", ""))
    previous_blocks = _extract_evidenced_by_blocks(previous_fields.get("full_text", ""))
    if not current_blocks or not previous_blocks:
        return _not_checkable(
            "Could not find an 'As evidenced by:' block with content on both the current and previous TP."
        )

    current_text = "\n".join(b["text"] for b in current_blocks)
    previous_text = "\n".join(b["text"] for b in previous_blocks)
    if not current_text.strip() or not previous_text.strip():
        return _not_checkable("'As evidenced by:' block(s) found but empty on one or both documents.")

    prompt = (
        "Compare the CURRENT treatment plan's 'As evidenced by:' findings (the patient-specific evidence "
        "for each Problem Area) against the PREVIOUS treatment plan's own 'As evidenced by:' findings for "
        "the same patient. Carefully identify anything genuinely NEW in the CURRENT text -- a real progress "
        "note, a status change, an added or removed finding, an '(in progress)'-style annotation -- that "
        "does not appear in the PREVIOUS text. Quote it if you find it. Only report nothing new if the "
        "current text is truly a word-for-word or paraphrased repeat with no real addition or change. ONLY "
        "if you find nothing new, also decide whether the CURRENT text itself explains this is because "
        "very limited or no additional services were provided since the previous TP.\n\n"
        f"--- PREVIOUS TP 'As evidenced by' findings ---\n{previous_text[:4000]}\n\n"
        f"--- CURRENT TP 'As evidenced by' findings ---\n{current_text[:4000]}"
    )
    result = call_tool_json(
        prompt_text=prompt,
        tool_name="compare_problem_areas",
        tool_description="Identify any new/changed content between two Problem Areas texts, and if none, "
                          "whether the current one explains why.",
        input_schema=_PROB04_SEMANTIC_SCHEMA,
        tracker=tracker,
        model_override=model_override,
        call_reason="prob04_semantic_compare",
    )

    new_content = (result.get("new_or_changed_content") or "").strip()
    # DERIVED, not asserted by the model -- see this function's own
    # docstring for the real contradiction this fixes.
    identical = not new_content
    explained = bool(result.get("current_explains_limited_services"))
    reasoning = result.get("reasoning") or ""
    # STILL AWAITING CONFIRMATION from Ms. Yachnes for this rule -- see this
    # function's own docstring. Said plainly in every evidence string below
    # so this never reads as a fully-verified answer.
    unconfirmed = "[Corrected extraction (As evidenced by findings, not template text) -- still awaiting Ms. Yachnes's confirmed real answer for this rule.]"

    if not identical:
        return _finding(
            "pass",
            (
                f"{unconfirmed} 'As evidenced by' findings are NOT identical to the previous TP -- new/changed "
                f"content found: {new_content} {reasoning}"
            ).strip(),
            0.6,
        )
    if explained:
        return _finding(
            "pass",
            (
                f"{unconfirmed} 'As evidenced by' findings are substantively identical to the previous TP, "
                f"but the current TP explains this is due to very limited/no additional services provided. "
                f"{reasoning}"
            ).strip(),
            0.6,
        )
    return _finding(
        "fail",
        (
            f"{unconfirmed} 'As evidenced by' findings are substantively identical to the previous TP, and "
            f"the current TP does NOT explain this as due to limited/no additional services. {reasoning}"
        ).strip(),
        0.6,
    )


# --- top-level entry point ---------------------------------------------------


def compare_previous_tp_to_tp(
    current_fields: dict, previous_fields: dict, *, tracker: CallTracker, model_override: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Runs all 5 comparisons and returns {rule_id: {result, evidence,
    confidence}} -- same top-level shape as
    session_note_comparison.py::compare_session_notes_to_tp. `tracker` is
    shared across every real-call comparison below (QA-ACF-04, QA-PROB-04)
    so a single ceiling covers both, same discipline as every other
    real-call surface in this pipeline.
    """
    return {
        "QA-MAST-01": _compare_mast01(current_fields, previous_fields),
        "QA-MAST-02": _compare_mast02(current_fields, previous_fields),
        "QA-RPT-05": _compare_rpt05_previous_auth_end(current_fields, previous_fields),
        "QA-ACF-04": _compare_acf04(current_fields, previous_fields, tracker=tracker, model_override=model_override),
        "QA-PROB-04": _compare_prob04(current_fields, previous_fields, tracker=tracker, model_override=model_override),
    }
