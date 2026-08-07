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

import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

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
from pipeline.session_note_extraction import extract_session_note_file as _extract_session_note_file  # noqa: E402

RuleCheckStatus = Literal["pass", "fail", "uncertain", "not_applicable", "not_checkable"]

# Rule metadata (category/action_lane/action_tag) for the 3 session-notes-only
# rule_ids -- compare_session_notes_to_tp's own return shape only carries
# {result, evidence, confidence} (see session_note_comparison.py), not the
# rule metadata a RuleResult needs. Looked up once, from the SAME rules.json
# agent-making's own pipeline already uses, rather than hardcoding category
# strings a rules.json edit could silently drift out of sync with.
_SESSION_NOTES_RULE_IDS = ("QA-RPT-03", "QA-ACF-02", "QA-ACF-08")
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
    max_calls: int | None = None,
) -> ReviewResult:
    """The one function this backend calls to run a real TP review.

    Same call signature as agent-making's own `review_treatment_plan`
    (agent-making/agent/pipeline/api.py) -- this wraps it, unchanged
    behaviorally, and returns the stable `ReviewResult` contract above
    instead of a raw dict. Never raises (agent-making's own function
    already catches every known pipeline failure mode and returns
    `status="failed"` + `error` instead) -- callers check `.status`.
    """
    raw = _raw_review_treatment_plan(
        pdf_path,
        supporting_doc_path=supporting_doc_path,
        payor_override=payor_override,
        plan_type_override=plan_type_override,
        max_calls=max_calls,
    )
    return _to_review_result(raw)


def review_session_notes(
    tp_pdf_path: str,
    session_note_paths: dict[str, str],
    *,
    model_override: str | None = None,
    max_calls: int | None = None,
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

    Returns exactly 3 `RuleResult`s (QA-RPT-03, QA-ACF-02, QA-ACF-08) when
    session notes are present, using the SAME agent-making functions
    `agent-making/agent/app.py` already calls
    (`extract_session_note_file`, `compare_session_notes_to_tp`,
    `select_matching_session_note` internally) -- no rule-checking logic
    of its own, same discipline as `review_treatment_plan` above. `page`
    is always `[]` for these three: the evidence is a cross-document
    comparison (TP vs. session note), not a single page reference.
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
