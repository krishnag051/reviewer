"""Round 66 — the ONLY file in this backend allowed to import from
`agent-making`. Every other backend module that needs a real rule-checking
result goes through the functions/models defined here, never through
`pipeline.*` directly.

Why this exists: `agent-making`'s own internal shapes (its raw
`review_treatment_plan` dict, its `page` field's int/None/string-range
mess, its own result vocabulary) have changed at least once every round
for the last several rounds (Rounds 59-65), and every one of those changes
was a pure `agent-making`-side refactor that had zero reason to touch this
backend — except that `app/rule_engine/client.py` imported `pipeline.api`
directly, so any shape drift there was one `sys.path` hop away from
breaking backend code. This module is the fix: a single, stable boundary.
`agent_client.py`'s own job is narrow and specific — adapt whatever
`agent-making` hands back into the fixed Pydantic contract below. If
`agent-making`'s internal output format changes in some future round, only
the adapter code in THIS file should ever need to change; nothing calling
into it should need to know or care.

What this module deliberately does NOT do: no backend-specific business
logic lives here. Translating `agent-making`'s own rule_id (a human-
readable code like "QA-TEMP-01") into this backend's `rules.id` UUID,
translating `agent-making`'s 5-value result vocabulary
(pass/fail/uncertain/not_applicable/not_checkable) into this backend's own
`model_status` spelling (pass/fail/uncertain/na/not_checkable), and
building a `RuleResultDraft` — all of that stays in
`app/rule_engine/client.py`, unchanged in behavior, just now reading from
this module's typed `ReviewResult`/`RuleResult` objects instead of a raw
dict. This module is a faithful, stable, structured MIRROR of what
`agent-making` actually said — not yet backend business logic.

Zero behavior change (Round 66's own explicit scope): this file's
`review_treatment_plan` calls the exact same underlying function with the
exact same arguments agent_making's own `review_treatment_plan` always
took: no rule-checking logic lives here, only translation shape.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

from pydantic import BaseModel, ValidationError

from app.config import settings

# agent-making isn't an installed package -- make its `pipeline` package
# importable by path. Resolved once, at import time, not per-call. Moved
# here from app/rule_engine/client.py (Round 66) -- this is now the only
# place in the backend that does this.
_AGENT_MAKING_PATH = Path(settings.agent_making_agent_path)
if not _AGENT_MAKING_PATH.is_absolute():
    _AGENT_MAKING_PATH = (Path(__file__).resolve().parents[1] / _AGENT_MAKING_PATH).resolve()
if str(_AGENT_MAKING_PATH) not in sys.path:
    sys.path.insert(0, str(_AGENT_MAKING_PATH))

if settings.anthropic_api_key:
    # setdefault, not direct assignment -- agent-making's own .env (loaded
    # the moment pipeline.api is imported below, via judge.py's own
    # load_dotenv call) wins if it already set this; this is only a
    # fallback for a deploy that doesn't ship that second .env file.
    os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

from pipeline.api import _load_rules as _load_agent_making_rules  # noqa: E402
from pipeline.api import review_treatment_plan as _raw_review_treatment_plan  # noqa: E402
from pipeline.extract import extract_pdf_text as _extract_pdf_text  # noqa: E402
from pipeline.fields import _find_labeled_date_range  # noqa: E402
from pipeline.fields import extract_acf_fields as _extract_acf_fields  # noqa: E402
from pipeline.fields import extract_fields as _extract_fields  # noqa: E402
from pipeline.model_provider import CallTracker as _CallTracker  # noqa: E402
from pipeline.session_note_comparison import compare_session_notes_to_tp as _compare_session_notes_to_tp  # noqa: E402
from pipeline.session_note_comparison import combine_compound_rule_result as _combine_compound_rule_result  # noqa: E402
from pipeline.session_note_extraction import extract_session_note_file as _extract_session_note_file  # noqa: E402
from pipeline.schedule_hours import check_schedule_hours_against_intake as _check_schedule_hours_against_intake  # noqa: E402
from pipeline.humanize import humanize_evidence_with_llm as _humanize_evidence_with_llm  # noqa: E402
from pipeline.humanize import humanize_evidence as _humanize_evidence  # noqa: E402

RuleCheckStatus = Literal["pass", "fail", "uncertain", "not_applicable", "not_checkable"]

# Rule metadata (category/action_lane/action_tag) for the 3 session-notes-only
# rule_ids -- compare_session_notes_to_tp's own return shape only carries
# {result, evidence, confidence} (see session_note_comparison.py), not the
# rule metadata a RuleResult needs. Looked up once, from the SAME rules.json
# agent-making's own pipeline already uses, rather than hardcoding category
# strings a rules.json edit could silently drift out of sync with.
# Fix Round (2026-08-27): QA-COC-01 added. It's compound (also has a
# TP-only half) -- run_rule_checks combines its result with phase 1's own
# draft instead of overwriting wholesale, unlike the other 3.
_SESSION_NOTES_RULE_IDS = ("QA-RPT-03", "QA-ACF-02", "QA-ACF-08", "QA-COC-01", "QA-ACF-12")
# Fix Round, Section 1 Bucket C (2026-08-27): QA-ACF-12 added -- also
# compound (has its own TP-only phase-1 half, fields.py::_check_ACF12, same
# as QA-COC-01) -- see pipeline/session_note_comparison.py::
# compare_session_notes_to_tp's own docstring for the real gap this closes.
_SESSION_NOTES_COMPOUND_RULE_IDS = ("QA-COC-01", "QA-ACF-12")
_AGENT_MAKING_RULES_BY_ID = {r["rule_id"]: r for r in _load_agent_making_rules()}


class RuleResult(BaseModel):
    """One rule's real finding from agent-making, faithfully structured --
    NOT yet translated into this backend's own vocabulary or identifiers.

    `rule_id` here is agent-making's own human-readable code (e.g.
    "QA-TEMP-01", matching this backend's `rules.rule_code`) -- never a
    backend UUID. `status` is agent-making's own 5-value result
    vocabulary, unchanged -- never this backend's `model_status` spelling
    (which uses "na" instead of "not_applicable"). Both of those
    translations are backend-specific business logic that belongs in
    app/rule_engine/client.py, not here.

    `page` is always a clean list[int] (possibly empty) -- agent-making's
    own raw `page` field is an int, None, or a display string like "3" /
    "3-5" / "3, 5, 9"; that parsing is done once, here, so every caller
    gets the same stable shape regardless of which raw form agent-making
    happened to produce this round.
    """

    rule_id: str
    category: str
    status: RuleCheckStatus
    page: list[int]
    evidence: str
    confidence: float | None = None
    action_lane: str | None = None
    action_tag: str | None = None


class UsageInfo(BaseModel):
    api_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float


class ReviewError(BaseModel):
    code: str
    message: str


class ReviewResult(BaseModel):
    """The full, stable result of one `review_treatment_plan()` call.

    Mirrors agent-making's own `ReviewResult` shape (see agent-making's
    `INTEGRATION_PLAN.md` Section 1 / `pipeline/api.py`) field-for-field,
    just re-typed into backend-owned Pydantic models instead of a raw
    dict, with `results` (was `findings`) built from `RuleResult` above.
    """

    schema_version: str
    status: Literal["complete", "failed"]
    detected_payor: str | None
    detected_plan_type: str | None
    supporting_doc_extraction: dict[str, Any] | None
    results: list[RuleResult]
    bcba_fix_rule_ids: list[str]
    facilitator_assign_rule_ids: list[str]
    counts_by_result: dict[str, int]
    usage: UsageInfo
    error: ReviewError | None


def _parse_pages(page: Any) -> list[int]:
    """agent-making's raw `page` field (merge.py::_format_page_display) is
    an int, None, or a display string like "3" / "3-5" / "3, 5, 9" -- moved
    here (Round 66, from app/rule_engine/client.py) so every caller of this
    module always receives a clean list[int], never agent-making's own raw
    shape. Byte-for-byte the same parsing logic as before the move.
    """
    if page is None:
        return []
    if isinstance(page, int):
        return [page]
    pages: list[int] = []
    for token in str(page).split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            start, _, end = token.partition("-")
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(token))
    return pages


def _to_review_result(raw: dict[str, Any]) -> ReviewResult:
    return ReviewResult(
        schema_version=raw["schema_version"],
        status=raw["status"],
        detected_payor=raw.get("detected_payor"),
        detected_plan_type=raw.get("detected_plan_type"),
        supporting_doc_extraction=raw.get("supporting_doc_extraction"),
        results=[
            RuleResult(
                rule_id=row["rule_id"],
                category=row["category"],
                status=row["result"],
                page=_parse_pages(row["page"]),
                evidence=row["detail"],
                confidence=row.get("confidence"),
                action_lane=row.get("action_lane"),
                action_tag=row.get("action_tag"),
            )
            for row in raw["findings"]
        ],
        bcba_fix_rule_ids=raw["summary"]["bcba_fix_rule_ids"],
        facilitator_assign_rule_ids=raw["summary"]["facilitator_assign_rule_ids"],
        counts_by_result=raw["summary"]["counts_by_result"],
        usage=UsageInfo(**raw["usage"]),
        error=ReviewError(**raw["error"]) if raw.get("error") else None,
    )


def review_treatment_plan(
    pdf_path: str,
    *,
    supporting_doc_path: str | None = None,
    payor_override: str | None = None,
    plan_type_override: str | None = None,
    source_filename: str | None = None,
    max_calls: int | None = None,
    extra_rule_context: dict[str, str] | None = None,
    extra_fields: dict[str, str] | None = None,
) -> ReviewResult:
    """The one function this backend calls to run a real TP review.

    Same call signature as agent-making's own `review_treatment_plan`
    (agent-making/agent/pipeline/api.py) -- this wraps it, unchanged
    behaviorally, and returns the stable `ReviewResult` contract above
    instead of a raw dict. Never raises (agent-making's own function
    already catches every known pipeline failure mode and returns
    `status="failed"` + `error` instead) -- callers check `.status`.

    `source_filename` (Round 86): the TP's real, client-supplied upload
    filename (now stored on `Upload.original_filename` -- see
    app/rule_engine/client.py::run_rule_checks, the one real caller that
    passes this). Forwarded unchanged to agent-making's own
    `source_filename` param (added Round 82 of that project, previously
    always left at its default and therefore always inert in production
    -- `pdf_path`'s basename is a generated storage key with no name-like
    tokens to compare against QA-PPI-03's own patient-name check). `None`
    (the default, matching every pre-Round-86 caller) keeps this
    parameter's own inert fallback behavior unchanged.

    `extra_rule_context` (Fix Round, 2026-08-27): {rule_id: text} --
    forwarded unchanged to agent-making's own same-named param (see that
    function's own docstring). The real caller, app/rule_engine/client.py::
    run_rule_checks, uses this to give the main judgment call the upload's
    own Patient Central Reach Information intake answers for the specific
    rules that reference them -- so, e.g., QA-SCH-02's judgment isn't
    reasoning blind to the real intake answer it's supposed to compare
    against.

    `extra_fields` (Fix Round, 2026-08-27): {key: text} -- forwarded
    unchanged to agent-making's own same-named param, for a DETERMINISTIC
    checker to read (e.g. _check_PPI05's real cross-check against the
    intake's "BCBA Name, Credentials & NPI" answer).
    """
    raw = _raw_review_treatment_plan(
        pdf_path,
        supporting_doc_path=supporting_doc_path,
        payor_override=payor_override,
        plan_type_override=plan_type_override,
        source_filename=source_filename,
        max_calls=max_calls,
        extra_rule_context=extra_rule_context,
        extra_fields=extra_fields,
    )
    return _to_review_result(raw)


def review_session_notes(
    tp_pdf_path: str,
    session_note_paths: dict[str, str],
    *,
    model_override: str | None = None,
    max_calls: int | None = None,
    phase1_results: dict[str, RuleResult] | None = None,
) -> list[RuleResult]:
    """Round 67 — the second (and, per this round's own audit, now the
    LAST) capability the Streamlit POC (`agent-making/agent/app.py`) calls
    into agent-making for that this backend didn't yet have a wrapper for.
    Session-note extraction (Rounds 59-61) + comparison (Rounds 63-65)
    were real, tested, working agent-making capabilities that no backend
    code had ever actually called — they only existed inside that
    standalone script. This is the real connection.

    `tp_pdf_path`: the upload's own TP file (same path `review_treatment_
    plan` above already receives) -- re-extracted here (a second, cheap,
    zero-model-call text-extraction pass; `review_treatment_plan` doesn't
    hand back its own internal extracted_fields dict) to pull the TP's
    "Date of Current Report" range and its "Assessment of Current
    Functioning" section values (QA-RPT-03/QA-ACF-02/QA-ACF-08's own TP-
    side facts) -- exactly what `agent-making/agent/app.py` itself does
    (see that file's own comment on why this second pass exists).

    `session_note_paths`: {original_filename: real_file_path} for every
    session-note file attached to this same upload. Returns `[]`
    (immediately, no model call at all) if this is empty -- there is
    nothing to extract or compare against.

    `model_override`: forwarded, unchanged, to every real model call this
    makes (both the extraction step and -- there is none, comparison is
    deterministic Python, zero model calls, see session_note_comparison.py).
    This function makes NO decision of its own about which provider to
    use -- `None` here means "whatever agent-making's own model_provider.py
    resolves as its default" (currently the free OpenRouter tier, per
    Round 59's own design), exactly the same neutral pass-through
    `review_treatment_plan` above already does for the main TP pipeline.
    Which provider a REAL backend call site should actually pass here is a
    deliberate product/spend decision that belongs to that call site (see
    app/rule_engine/client.py's own comment on this), not to this wrapper.

    Returns 4 `RuleResult`s (QA-RPT-03, QA-ACF-02, QA-ACF-08, QA-COC-01) when
    session notes are present, using the SAME agent-making functions
    `agent-making/agent/app.py` already calls
    (`extract_session_note_file`, `compare_session_notes_to_tp`,
    `select_matching_session_note` internally) -- no rule-checking logic
    of its own, same discipline as `review_treatment_plan` above. `page`
    is always `[]` for these four: the evidence is a cross-document
    comparison (TP vs. session note), not a single page reference.

    Fix Round (2026-08-27): QA-COC-01 added -- its "session note detailed"
    half only (the SAME already-existing, already-free per-note extraction
    call now also asks for `note_detail_level` -- see
    pipeline/session_note_extraction.py -- zero new spend). Unlike the
    other 3, QA-COC-01 is a COMPOUND rule (also checks the TP's own COC
    section for provider name/title/date, from the TP text alone) -- the
    caller (app/rule_engine/client.py::run_rule_checks) must COMBINE this
    result with phase 1's own draft for QA-COC-01, never overwrite it
    wholesale the way the other 3 (pure session-note comparisons, nothing
    to preserve from phase 1) are merged. `phase1_results` (rule_id ->
    that rule's own phase-1 RuleResult) is how the caller hands that draft
    in -- the actual combine policy itself lives in agent-making
    (pipeline/session_note_comparison.py::combine_compound_rule_result),
    keeping this file's own role limited to plumbing, same discipline as
    app/rule_engine/client.py's own boundary comment.
    """
    if not session_note_paths:
        return []

    tracker = _CallTracker(max_calls=max_calls)

    tp_pages = _extract_pdf_text(tp_pdf_path)
    tp_fields = _extract_fields(tp_pdf_path, tp_pages)
    tp_acf = _extract_acf_fields(tp_fields)
    tp_report_range = _find_labeled_date_range(tp_fields["full_text"], "Date of Current Report")
    tp_report_period = f"{tp_report_range[0]} to {tp_report_range[1]}" if tp_report_range else None

    extractions_by_filename = {
        filename: _extract_session_note_file(path, tracker=tracker, model_override=model_override)
        for filename, path in session_note_paths.items()
    }

    raw_results = _compare_session_notes_to_tp(
        extractions_by_filename,
        tp_current_report_period=tp_report_period,
        tp_assessment_date=tp_acf["assessment_date"],
        tp_pos=tp_acf["pos"],
        tp_patient_location=tp_acf["patient_location"],
        tp_assessment_tool=tp_acf["assessment_tool"],
    )

    results = []
    for rule_id in _SESSION_NOTES_RULE_IDS:
        raw = raw_results.get(rule_id)
        if raw is None:
            continue
        if rule_id in _SESSION_NOTES_COMPOUND_RULE_IDS:
            phase1 = (phase1_results or {}).get(rule_id)
            phase1_plain = (
                {"result": phase1.status, "evidence": phase1.evidence, "confidence": phase1.confidence}
                if phase1 is not None else None
            )
            raw = _combine_compound_rule_result(phase1_plain, raw)
        rule_meta = _AGENT_MAKING_RULES_BY_ID.get(rule_id, {})
        results.append(RuleResult(
            rule_id=rule_id,
            category=rule_meta.get("category", "Unknown"),
            status=raw["result"],
            page=[],
            evidence=raw["evidence"],
            confidence=raw.get("confidence"),
            action_lane=rule_meta.get("action_lane"),
            action_tag=rule_meta.get("action_tag"),
        ))
    return results


_INTAKE_ANSWERS_RULE_IDS = ("QA-SCH-02",)


def review_intake_answers(
    tp_pdf_path: str,
    *,
    pos_schedule_vs_97153_hours: str | None,
    hours_requesting: str | None,
    phase1_results: dict[str, RuleResult] | None = None,
) -> list[RuleResult]:
    """Fix Round (2026-08-26) -- the real fix for a confirmed gap: QA-SCH-02
    ("Schedule matches with the one inputted by CR information") is
    check_type=judgment in rules.json, but `review_treatment_plan` above has
    no parameter for the upload's own Patient Central Reach Information
    intake answers at all -- the AI judge was never given this data to
    compare against, regardless of what the rule's description said.

    Closes the HOURS half of that gap only, using agent-making's own real
    schedule-grid arithmetic (pipeline/schedule_hours.py, the same module
    QA-SCH-01 already uses for a different comparison) rather than
    duplicating it or attempting a full free-text schedule/POS semantic
    match deterministically -- see check_schedule_hours_against_intake's
    own docstring for why that broader half is deliberately left to
    not_checkable/judgment.

    Returns `[]` (no model call, no work at all -- this is 100% deterministic
    Python, same as the session-note comparison above) if BOTH intake fields
    are empty/None -- nothing to compare.

    Fix Round (2026-08-27): QA-SCH-02 is compound the same way QA-COC-01 is
    (see review_session_notes above) -- the judgment layer now ALSO gets
    the real intake answer as context (via review_treatment_plan's
    extra_rule_context) and may itself reach a real, informed verdict on
    the broader schedule/POS narrative match. `phase1_results` lets that
    verdict combine with this function's own hours-only deterministic
    check, instead of the deterministic check silently overwriting a now-
    informed judgment attempt whenever it comes back not_checkable.
    """
    if not pos_schedule_vs_97153_hours and not hours_requesting:
        return []

    tp_pages = _extract_pdf_text(tp_pdf_path)
    tp_fields = _extract_fields(tp_pdf_path, tp_pages)

    result, evidence, page, confidence = _check_schedule_hours_against_intake(
        tp_fields["full_text"],
        pos_schedule_text=pos_schedule_vs_97153_hours,
        hours_requesting_text=hours_requesting,
    )
    raw = {"result": result, "evidence": evidence, "confidence": confidence}

    results = []
    for rule_id in _INTAKE_ANSWERS_RULE_IDS:
        combined = raw
        phase1 = (phase1_results or {}).get(rule_id)
        if phase1 is not None:
            phase1_plain = {"result": phase1.status, "evidence": phase1.evidence, "confidence": phase1.confidence}
            combined = _combine_compound_rule_result(phase1_plain, raw)
        rule_meta = _AGENT_MAKING_RULES_BY_ID.get(rule_id, {})
        results.append(RuleResult(
            rule_id=rule_id,
            category=rule_meta.get("category", "Unknown"),
            status=combined["result"],
            page=[page] if page is not None else [],
            evidence=combined["evidence"],
            confidence=combined.get("confidence"),
            action_lane=rule_meta.get("action_lane"),
            action_tag=rule_meta.get("action_tag"),
        ))
    return results


class SessionNoteExtractionField(BaseModel):
    """One field's real extracted value, straight from agent-making's own
    Round 59 extraction step (pipeline/session_note_extraction.py) --
    never re-derived or guessed at here."""

    value: str | None
    confidence: Literal["none", "low", "medium", "high"]
    source_quote: str | None


class SessionNoteExtraction(BaseModel):
    """Round 79, Item 2 -- the exact field shape
    `pipeline.session_note_extraction.SESSION_NOTE_FIELDS` defines, kept
    as its own real fields (not a generic dict) so a shape drift on
    agent-making's side is a visible type error here, not a silent typo
    in a dict key somewhere downstream. `note_detail_level` added Fix
    Round (2026-08-27) -- see that module's own field list."""

    session_date: SessionNoteExtractionField
    session_location: SessionNoteExtractionField
    clinician_telehealth_location: SessionNoteExtractionField
    patient_telehealth_location: SessionNoteExtractionField
    assessment_activity: SessionNoteExtractionField
    note_detail_level: SessionNoteExtractionField


def extract_session_note(
    file_path: str,
    *,
    model_override: str | None = None,
    max_calls: int | None = None,
) -> SessionNoteExtraction:
    """Round 79, Item 2 -- the one missing wrapper the Round 78 audit's
    deferred items flagged: `review_session_notes` above already calls
    agent-making's real `extract_session_note_file` internally, but only
    to feed `compare_session_notes_to_tp` -- the raw per-file extraction
    itself (session_date/session_location/clinician_telehealth_location/
    patient_telehealth_location/assessment_activity, each with its own
    confidence + source_quote) was never exposed anywhere a human could
    see it directly. This is that real connection, for real display, not
    a rebuild of the extraction logic here -- same discipline as every
    other function in this module.

    Same content-hash cache as `review_session_notes` uses internally
    (`pipeline/session_note_extraction.py`'s own local cache) -- viewing
    this panel for a file that's already been extracted (e.g. because the
    upload's session-notes rule check already ran) costs zero real model
    calls; only a genuinely new file triggers one real (free-tier
    OpenRouter, per this round's own call site) extraction call.

    Fix Round (2026-08-27): REAL PRODUCTION CRASH FOUND AND FIXED,
    confirmed via a real 500 -- a cache entry written before
    note_detail_level (the QA-COC-01 fix round) was added to this
    function's own expected shape fails SessionNoteExtraction(**raw)'s
    validation, and that exception was never caught -- it crashed the
    whole request instead of being treated as what it actually is: a
    cache-shape mismatch, not a real extraction failure. Now caught and
    retried exactly once with force_refresh=True (skips the stale cached
    read, forces one real fresh extraction, and -- unlike use_cache=False
    -- still WRITES the fresh result back to the cache, so this file
    self-heals for every read after this one rather than needing a real
    model call forever). If the SECOND attempt also fails validation,
    that's let through uncaught -- a fresh extraction that still doesn't
    match this function's expected shape is a genuinely different, real
    bug worth surfacing loudly, not one to silently retry forever.
    """
    tracker = _CallTracker(max_calls=max_calls)
    raw = _extract_session_note_file(file_path, tracker=tracker, model_override=model_override)
    try:
        return SessionNoteExtraction(**raw)
    except ValidationError:
        logger.warning(
            "extract_session_note: cached extraction for %s failed validation against the "
            "current SessionNoteExtraction shape (likely a stale cache entry from before a "
            "field was added) -- forcing one fresh real extraction and re-caching it.",
            file_path,
        )
        raw = _extract_session_note_file(
            file_path, tracker=tracker, model_override=model_override, force_refresh=True,
        )
        return SessionNoteExtraction(**raw)


def humanize_finding(text: str, *, tracker: "_CallTracker | None" = None) -> tuple[str, str, dict]:
    """Next Round, Part 2: real, wired-in call for the LLM humanize pass --
    see pipeline/humanize.py::humanize_evidence_with_llm's own docstring
    for the model choice, the page-ref safety net, and the real bug it was
    built to catch.

    Returns (raw_text, humanized_text, usage) -- `raw_text` is the
    deterministically-cleaned "before" (usage["pre_humanize_text"]),
    `humanized_text` is the real rewrite (or the same deterministic text,
    unchanged, if the rewrite was rejected by the page-ref safety net or
    never attempted for empty input). Callers persist BOTH -- see
    app/services/upload_pipeline.py, the one real caller, for why both are
    kept as separate, permanent columns rather than one overwriting the
    other.

    `tracker` is optional but should always be passed in production (the
    real caller does) -- same discipline as every other real-call site in
    this module; without one, this makes an uncapped real call.

    No real call is made at all for empty/whitespace-only input (see
    humanize_evidence_with_llm's own docstring) -- checked before the cap
    check runs, so a batch of mostly-empty findings never burns cap
    headroom on calls that were never going to happen anyway.
    """
    cleaned_probe = _humanize_evidence(text)
    makes_real_call = bool(cleaned_probe and cleaned_probe.strip())
    if makes_real_call and tracker is not None:
        tracker.check_before_call()
    humanized, usage = _humanize_evidence_with_llm(text)
    if makes_real_call and tracker is not None:
        tracker.record(
            reason="humanize_finding",
            provider="anthropic",
            model="claude-haiku-4-5",
            usage=usage,
        )
    return usage["pre_humanize_text"], humanized, usage


def humanize_findings(
    texts: list[str], *, max_calls: int, labels: list[str] | None = None,
) -> list[tuple[str, str, dict]]:
    """Batch entry point for `app/services/upload_pipeline.py` -- ONE shared
    tracker across every finding in a single upload's run, same pattern as
    `review_session_notes` sharing one tracker across its per-file calls
    above. Returns one (raw_text, humanized_text, usage) tuple per input
    text, same order.

    Fix Round (2026-08-27): REAL BUG FOUND AND FIXED, confirmed via an
    actual crash on a real staging upload -- each finding's own
    humanize_finding call is now isolated in its own try/except. Before
    this round, a single bad model response (the stray-page-ref bug
    pipeline/humanize.py's own safety net now also catches -- see that
    module's docstring -- or any future different failure) crashed
    UNCAUGHT out of this whole function, and the caller's own outer
    try/except then discarded EVERY finding's result for the whole
    upload, including 20+ real, already-paid-for Haiku calls that had
    already succeeded earlier in the same batch. Confirmed directly
    against a real CSV export from that run: all 182 rows had identical
    pre/post/final evidence text, meaning the entire batch's real spend
    was thrown away over one bad response. Now: only the ONE finding
    whose humanize_finding call actually fails falls back to raw text;
    every other finding in the same batch keeps its own real result,
    unaffected.

    `max_calls` is the caller's job to supply (from `settings.
    humanize_max_calls`) -- this function stays free of backend config,
    same boundary discipline as the rest of this module.

    `labels` (optional, one per text -- the caller passes each draft's
    own rule_id) makes a failure loud and specific in the log, not just
    "something in this batch failed" -- see the log line below. Falls
    back to a positional index when not given.
    """
    tracker = _CallTracker(max_calls=max_calls)
    results: list[tuple[str, str, dict]] = []
    for i, text in enumerate(texts):
        label = labels[i] if labels else f"finding at index {i}"
        try:
            results.append(humanize_finding(text, tracker=tracker))
        except Exception:
            logger.exception(
                "humanize_finding failed for %s -- falling back to raw/un-humanized text for "
                "THIS finding only; every other finding already processed in this same batch "
                "keeps its own real result, unaffected.",
                label,
            )
            results.append((text, text, {}))
    return results
