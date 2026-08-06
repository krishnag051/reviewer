"""Round 55: replaces Round 52-54's blanket approach (append the WHOLE
supporting_doc JSON to EVERY judgment-layer prompt, regardless of which
rule it's for) with a scoped, two-phase design.

Phase 1 is the normal, unmodified 120-rule pipeline (judge.py's
_build_prompt no longer references supporting_doc at all -- see that
file). Phase 1 runs exactly as it did before Round 52 existed, for every
rule, including the 3 identified in Round 54.

Phase 2 (this module) is a small, CONDITIONAL follow-up:
1. After phase 1 completes, find_taggable_findings() checks only the known
   small set of rules capable of resolving via the supporting document
   (TAGGABLE_RULE_FIELDS below). A finding is tagged only if: the rule is
   in that set, phase 1's own result for it is "uncertain" or
   "not_checkable" (i.e. genuinely a dead end, not something already
   resolved), a supporting document was actually provided for this
   upload, and at least one of that rule's relevant supporting_doc fields
   has confidence other than "none" (there's actually something to check
   against -- tagging a finding when the supporting doc has nothing
   relevant would just waste a call).
2. If nothing is tagged, resolve_tagged_findings() is never called --
   zero additional real API calls for the ~117 (now ~118, since QA-PPI-05
   is excluded here -- see below) rules that were never candidates, and
   zero additional calls even for the 2 candidate rules when either phase
   1 already resolved them or the supporting document has nothing useful
   for them.
3. If something IS tagged, exactly ONE real API call is made, sending
   ONLY: each tagged rule's own description + phase 1's own evidence for
   it (a short string, not the whole TP) + only the specific supporting-
   doc field(s) relevant to that rule (not the whole supporting_doc dict,
   and never the TP's full page text/images) -- a small, scoped prompt,
   not a second full pipeline pass.

QA-PPI-05 is deliberately NOT part of TAGGABLE_RULE_FIELDS. It's
deterministic (fields.py::_check_PPI05), not judgment -- its Round 54
cross-check already runs in-process, in the SAME (free) call that runs
every other deterministic checker, and either resolves fully (pass/fail)
or stays not_checkable for a reason no amount of supporting-document data
would fix (the TP itself never states an NPI at all -- there's nothing to
hold "correct" about). There is no "uncertain dead end" state for it that
a phase-2 call could improve on, so tagging it here and spending a real
call on it would be pure waste. See _check_PPI05's own docstring.

Explicit limitation, not to be glossed over: this module's correctness
has only been checked against the same proxy materials Round 54 used
(Ullah_Zyaan_Redacted.pdf + TP_Supporting_Information_Example_converted.pdf)
-- NOT against Ms. Yachnes's real example set (a real TP plus her actual
filled-in review columns), which does not exist in this repo yet. Passing
every test in this module's own test file proves the MECHANISM works
correctly; it does not prove the mechanism's pass/fail/uncertain
resolutions would match her real-world judgment.
"""
from __future__ import annotations

import json
from typing import Any

import anthropic

from .call_tracker import ApiCallTracker

MODEL = "claude-sonnet-5"
MAX_TOKENS = 4096

# rule_id -> the supporting_doc_extraction.SUPPORTING_DOC_FIELDS keys that
# are actually relevant to resolving THAT rule. Deliberately explicit and
# small rather than derived -- adding a new taggable rule is a one-line,
# reviewable addition here, not a change to shared judgment/prompt code.
TAGGABLE_RULE_FIELDS: dict[str, list[str]] = {
    "QA-HRS-01": ["cpt_97153_hours_pos_schedule", "requested_hours"],
    "QA-BIO-01": ["diagnostic_report_match"],
}

_DEAD_END_RESULTS = {"uncertain", "not_checkable"}

RESOLUTION_TOOL = {
    "name": "record_supporting_doc_resolutions",
    "description": (
        "Record a resolution for each tagged rule, using ONLY the phase-1 finding and the "
        "specific supporting-document field(s) given for that rule -- no other document "
        "content is available in this call."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "resolutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "result": {
                            "type": "string",
                            "enum": ["pass", "fail", "uncertain"],
                            "description": (
                                "'uncertain' is a legitimate outcome here -- if the supporting "
                                "document's field doesn't actually let you resolve this rule "
                                "(e.g. it's vague, or doesn't address what the rule asks), say so "
                                "rather than forcing a pass or fail."
                            ),
                        },
                        "evidence": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["rule_id", "result", "evidence", "confidence"],
                },
            },
        },
        "required": ["resolutions"],
    },
}


def find_taggable_findings(
    judgment_results: dict[str, dict[str, Any]],
    supporting_doc: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    """Returns the subset of judgment_results that phase 2 should attempt
    to resolve -- see this module's docstring for the exact conditions.
    Pure, side-effect-free; makes no API call and mutates nothing.
    """
    if not supporting_doc:
        return {}

    tagged: dict[str, dict[str, Any]] = {}
    for rule_id, relevant_fields in TAGGABLE_RULE_FIELDS.items():
        finding = judgment_results.get(rule_id)
        if finding is None or finding.get("result") not in _DEAD_END_RESULTS:
            continue
        has_usable_field = any(
            (supporting_doc.get(field) or {}).get("confidence") != "none" for field in relevant_fields
        )
        if has_usable_field:
            tagged[rule_id] = finding
    return tagged


def _build_resolution_prompt(
    tagged: dict[str, dict[str, Any]],
    rules_by_id: dict[str, dict[str, Any]],
    supporting_doc: dict[str, dict[str, Any]],
) -> str:
    sections = []
    for rule_id, finding in tagged.items():
        rule = rules_by_id[rule_id]
        relevant_fields = {
            field: supporting_doc[field]
            for field in TAGGABLE_RULE_FIELDS[rule_id]
            if field in supporting_doc and supporting_doc[field].get("confidence") != "none"
        }
        evidence = finding["evidence"]
        evidence_str = evidence if isinstance(evidence, str) else json.dumps(evidence)
        sections.append(
            f"Rule {rule_id}: {rule['description']}\n"
            f"Phase-1 finding (before the supporting document was considered): "
            f"{finding['result']} -- {evidence_str}\n"
            f"Relevant supporting-document field(s):\n{json.dumps(relevant_fields, indent=2)}"
        )
    return (
        "For each rule below, phase 1 of this review could not resolve it from the treatment "
        "plan's own text alone. A supporting document was separately provided and may contain "
        "exactly the missing fact. Using ONLY the phase-1 finding and the supporting-document "
        "field(s) given for that specific rule -- you do not have access to the rest of either "
        "document in this call -- decide whether the rule now passes, fails, or is still "
        "genuinely unresolvable ('uncertain'). Never guess beyond what's actually stated.\n\n"
        + "\n\n".join(sections)
    )


def resolve_tagged_findings(
    tagged: dict[str, dict[str, Any]],
    rules_by_id: dict[str, dict[str, Any]],
    supporting_doc: dict[str, dict[str, Any]],
    *,
    tracker: ApiCallTracker,
) -> dict[str, dict[str, Any]]:
    """The one additional real, billed API call -- only ever invoked by a
    caller that already checked `tagged` is non-empty (this function does
    not check that itself, so a caller mistake would still make a real
    call with an empty rules list; see pipeline/api.py's wiring, which
    only calls this inside `if tagged:`).

    Returns {rule_id: {"result", "evidence", "confidence"}} for every rule_id
    the model resolved. A tagged rule_id missing from the return value
    (model dropped it) is the caller's responsibility to leave as its
    original phase-1 finding -- this function doesn't retry or backfill.
    """
    tracker.check_before_call()
    client = anthropic.Anthropic()
    prompt = _build_resolution_prompt(tagged, rules_by_id, supporting_doc)
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[RESOLUTION_TOOL],
        tool_choice={"type": "tool", "name": "record_supporting_doc_resolutions"},
        messages=[{"role": "user", "content": prompt}],
    )
    tracker.record(
        reason="supporting_doc_resolution_phase2",
        rule_ids=list(tagged.keys()),
        usage=response.usage,
    )

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    resolutions = tool_use_block.input.get("resolutions", [])

    resolved: dict[str, dict[str, Any]] = {}
    for entry in resolutions:
        rule_id = entry.get("rule_id")
        if rule_id not in tagged:
            continue
        resolved[rule_id] = {
            "result": entry["result"],
            "evidence": entry["evidence"],
            "confidence": entry["confidence"],
        }
    return resolved
