"""Step 5 of the pipeline (Section 4): a single Claude call for every
check_type == "judgment" and active rule. Output is forced via tool-use into
the Findings schema (Section 3) — one entry required per rule_id sent in.

Model: claude-sonnet-5 (Section 5's choice for this judgment call).

Note on the "previous finalized TP" input the design doc mentions (Section 4,
step 5): this POC has no backend integration, so there is no prior-version
data to pass. The model is told plainly that no prior version is available
for this run, so it can answer prior-version-dependent rules with
"not_checkable" rather than guessing.
"""
import base64
import json
from collections import Counter
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MODEL = "claude-sonnet-5"

FINDINGS_TOOL = {
    "name": "record_findings",
    "description": (
        "Record one finding per rule_id given in the judgment rule list. "
        "You must return exactly one entry for every rule_id provided — no "
        "more, no fewer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "evidence": {
                            "anyOf": [
                                {
                                    "type": "string",
                                    "description": "A specific, quoted or closely-paraphrased justification grounded in the document. Never a restatement of the rule. Work out your reasoning here BEFORE choosing a result below — do not decide the result first and write justifying evidence afterward.",
                                },
                                {
                                    "type": "array",
                                    "description": (
                                        "Use this array form instead of a single string when the SAME problem "
                                        "shows up as a genuinely distinct, page-specific issue on more than one "
                                        "page — one entry per page, each naming that page's specific problem. "
                                        "Never collapse multiple pages into one summary sentence like 'pages "
                                        "13, 15, 35, 40-48 are missing X' — a reviewer needs to see each page's "
                                        "actual issue individually."
                                    ),
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "page": {"type": "integer", "description": "1-indexed page number."},
                                            "detail": {
                                                "type": "string",
                                                "description": "The specific problem found on this exact page — not a shared generic description reused across pages.",
                                            },
                                        },
                                        "required": ["page", "detail"],
                                    },
                                },
                            ],
                        },
                        "result": {
                            "type": "string",
                            "enum": ["pass", "fail", "uncertain", "not_applicable", "not_checkable"],
                            "description": "Choose this AFTER writing the evidence above, and make sure it's the conclusion that evidence actually points to — not a categorical judgment made before working through the reasoning.",
                        },
                        "evidence_supports_result": {
                            "type": "boolean",
                            "description": (
                                "Must be true. Re-read your own evidence text and confirm it actually "
                                "supports the result you chose before setting this — if your evidence "
                                "describes something as absent, resolved, or not applicable, result "
                                "cannot be 'fail'; if it names an unresolved problem, result cannot be "
                                "'pass.' If you cannot honestly mark this true, change result to "
                                "'uncertain' instead of submitting a contradiction — do not set this "
                                "to false and submit anyway, it will be rejected and re-asked."
                            ),
                        },
                        "page": {
                            "anyOf": [
                                {"type": "integer", "description": "A single 1-indexed page number."},
                                {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "minItems": 2,
                                    "description": (
                                        "Use this array form when the SAME finding genuinely depends on "
                                        "or references more than one specific page together — e.g. a "
                                        "reviewer comment on one page pointing to content established on "
                                        "an earlier page, or an issue only visible by comparing two pages "
                                        "against each other. This is different from the {page, detail} "
                                        "list form above: that form is for the same problem recurring "
                                        "independently on many pages (one row per page); this form is one "
                                        "finding whose evidence spans a specific, small set of pages "
                                        "together. Only include the pages actually load-bearing to this "
                                        "finding, not every page the topic happens to appear on."
                                    ),
                                },
                                {"type": "null", "description": "Not page-specific."},
                            ],
                            "description": (
                                "1-indexed page number(s) the evidence came from — a single integer for "
                                "the common case, an array of 2+ integers when the finding genuinely spans "
                                "multiple specific pages together, or null if not page-specific. Must be "
                                "null when evidence is the {page, detail} array form above (each item "
                                "already carries its own page)."
                            ),
                        },
                        "confidence": {"type": "number", "description": "0.0-1.0"},
                    },
                    "required": ["rule_id", "evidence", "result", "evidence_supports_result", "page", "confidence"],
                },
            }
        },
        "required": ["findings"],
    },
}


def _build_prompt(judgment_rules: list[dict], fields: dict, rendered_images: dict[int, bytes]) -> list[dict]:
    rules_summary = [
        {
            "rule_id": r["rule_id"],
            "category": r["category"],
            "description": r["description"],
            "notes": r.get("notes"),
            # Rules escalated from the deterministic layer (no checker
            # implemented, or low-confidence) often carry their real
            # pass/fail thresholds in params rather than notes — send it
            # through explicitly so the model isn't relying on whatever
            # numbers happen to already be in the free-text description.
            "params": r.get("params"),
        }
        for r in judgment_rules
    ]

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "You are reviewing an ABA Treatment Plan (TP) against a set of "
                "compliance rules. For each rule below, determine pass / fail / uncertain / "
                "not_applicable / not_checkable, grounded in the actual document text and "
                "images provided — never guess, and use 'uncertain' rather than a confident-"
                "sounding guess when the evidence is genuinely ambiguous.\n\n"
                "Where a rule includes a 'params' object, treat those values as the exact, "
                "authoritative thresholds for that rule (e.g. an age cutoff or a numeric cap) — "
                "use them directly rather than re-deriving numbers from the prose description.\n\n"
                "IMPORTANT: no previous finalized version of this patient's TP is available "
                "for this run (standalone prototype, no backend integration yet). Any rule "
                "that depends on comparing against a prior TP version must be answered "
                "'not_checkable' with evidence saying so — do not fabricate a prior version.\n\n"
                "Before finalizing each finding, check that your evidence text is consistent "
                "with the result you chose — if your evidence describes something as absent, "
                "resolved, or not applicable, the result cannot be 'fail'; if your evidence "
                "names an unresolved problem, the result cannot be 'pass.' Set "
                "evidence_supports_result to true only when this check genuinely passes for "
                "that finding. If it doesn't, don't set evidence_supports_result to false and "
                "submit anyway — instead change result to 'uncertain' (and update the evidence "
                "to match) so the finding is honest the first time. This check is about LOGICAL "
                "CONTRADICTION between your own evidence and result, not about your overall "
                "certainty — a well-supported pass or fail should stay pass or fail even if some "
                "peripheral detail is ambiguous. Reserve 'uncertain' for when the evidence itself "
                "genuinely doesn't point to any single result; don't downgrade a finding you can "
                "actually support just because the rule involves some subjective judgment.\n\n"
                "If a rule's problem shows up as a distinct, page-specific issue on more than one "
                "page, set evidence to a list of {page, detail} objects — one entry per page, each "
                "naming that exact page's specific problem — instead of a single summary string. "
                "Only use the plain string form when the finding is confined to one page or is "
                "genuinely page-agnostic.\n\n"
                "When a rule's violation is a REPEATING PATTERN across many pages (e.g. the same "
                "stale date, the same missing field, the same malformed value recurring throughout "
                "the document), enumerate every page where it actually recurs using the list form "
                "above — do not cite only one or a few representative examples with phrasing like "
                "'e.g., pages X, Y, Z' while pages you also saw the pattern on go unlisted. A "
                "reviewer reading this finding needs the complete scope of the problem, not a "
                "sample of it; under-citing makes a document-wide issue look narrower than it is.\n\n"
                "Rules to check (JSON):\n" + json.dumps(rules_summary, indent=2)
            ),
        },
        {"type": "text", "text": "Full extracted page text, in page order:"},
    ]

    for page in fields["pages"]:
        low_text_note = " [LOW TEXT — likely image-only; see rendered image if provided below]" if page.get("low_text") else ""
        content.append({
            "type": "text",
            "text": f"--- Page {page['page_number']}{low_text_note} ---\n{page['text']}",
        })

    if rendered_images:
        content.append({"type": "text", "text": "Rendered images of pages with little/no extractable text, in page order:"})
        for page_number in sorted(rendered_images):
            content.append({"type": "text", "text": f"--- Rendered page {page_number} ---"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(rendered_images[page_number]).decode("utf-8"),
                },
            })

    return content


MAX_TOKENS = 32000


def _run_judgment_checks_once(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    tracker=None,
    call_reason: str = "call",
) -> dict[str, dict]:
    """A single real judgment-layer call. Returns {rule_id: {"result",
    "evidence", "page", "confidence"}} — one entry per rule_id the model
    both answered and self-confirmed (see _findings_dict_from_list).

    `tracker` (an ApiCallTracker) is optional but should always be passed in
    production paths — it's the only thing standing between "run this" and
    silently making an unbounded number of real, billed API calls. See
    pipeline/call_tracker.py for why this exists.
    """
    if not judgment_rules:
        return {}

    rule_ids = [r["rule_id"] for r in judgment_rules]

    if tracker is not None:
        tracker.check_before_call()

    client = anthropic.Anthropic()
    content = _build_prompt(judgment_rules, fields, rendered_images)

    # thinking disabled: this is a bounded classification/extraction task, not
    # open-ended reasoning, and Sonnet 5 runs adaptive thinking by default —
    # those tokens come out of the same max_tokens budget as the tool call
    # itself, and previously starved the JSON output before it could complete.
    # max_tokens > ~16000 needs streaming (SDK HTTP timeout guard).
    with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        tools=[FINDINGS_TOOL],
        tool_choice={"type": "tool", "name": "record_findings"},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = stream.get_final_message()

    if tracker is not None:
        tracker.record(reason=call_reason, rule_ids=rule_ids, usage=response.usage)

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Judgment call hit max_tokens ({MAX_TOKENS}) before finishing its tool "
            f"call — the findings JSON is truncated/incomplete. Raise judge.MAX_TOKENS "
            f"or send fewer judgment rules per call."
        )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError(
            f"No tool_use block in the judgment response (stop_reason={response.stop_reason!r}). "
            f"Content blocks returned: {[b.type for b in response.content]}."
        )
    if "findings" not in tool_use.input:
        raise RuntimeError(
            f"Judgment tool call returned without a 'findings' key "
            f"(stop_reason={response.stop_reason!r}); got keys: {list(tool_use.input.keys())}."
        )
    findings_list = tool_use.input["findings"]
    return _findings_dict_from_list(findings_list)


# Item 5 (2026-07-28 round 3): the 3-way majority vote (run_judgment_checks_
# majority_vote, below) measurably improved Fail-catch rate on rules with
# confirmed self-consistency instability, but at a real, permanent 1.5x
# call-count cost per batch. Applying it to every judgment rule would pay
# that cost everywhere for no benefit on the ~65 judgment rules that have
# never shown a live disagreement. This is a small, explicitly tracked
# allow-list -- NOT wired into any production code path yet (run_judgment_
# checks below is untouched and still makes exactly 2 calls for every rule,
# including these) -- of exactly which rule_ids have confirmed real
# instability across this project's rounds, each with its own evidence:
#
# - QA-GIP-06 ("General goals fully completed and include a rationale"):
#   the single most-confirmed unstable rule_id across this project --
#   flagged as a self-consistency tie-break miss on BOTH Reeda and Charny
#   in an earlier round, caught again live this round's ground-truth
#   harness run (came back "uncertain" on Charny in one run, "fail" in
#   another, both against the identical document/code).
# - QA-HRS-07 ("Increase in hours -> compared against previous mastery
#   criteria"): confirmed self-consistency tie-break miss on Reeda in an
#   earlier round (first call correctly said "fail," second call
#   disagreed, downgraded to "uncertain").
# - QA-HRS-09 ("Overlap with home health aide/speech/OT -> goals
#   differentiated"): confirmed tie-break miss on BOTH Reeda and Charny in
#   an earlier round -- the only rule_id besides GIP-06 to show instability
#   on both documents independently.
# - QA-GIP-07 ("Goals open >6mo have rationale reviewed by Eliana"):
#   confirmed tie-break miss on Charny in an earlier round.
# - QA-PROB-01 ("At least 2 each of social/communication/behavior,
#   narrative format"): confirmed unstable THIS round, live -- came back
#   "fail" in one ground-truth harness run and "uncertain" in a later run
#   against the identical document and code, after its notes fix already
#   landed (see rules.json) -- instability survived the content fix, which
#   is exactly the shape self-consistency ties produce regardless of how
#   good the rule's prompt is.
#
# QA-GIP-10 deliberately NOT here despite being in the original tie-break
# list -- it moved to check_type "deterministic" this round (item 1) and no
# longer goes through the judgment layer at all, so a majority vote over it
# is meaningless.
#
# To actually apply the 3rd call to just this list in production would mean
# wiring a lookup here into integrity.py's dispatch -- not done yet, since
# that's a real behavior/cost change warranting its own explicit go-ahead,
# same discipline as every other production-switch decision this project
# has deferred until asked for directly.
MAJORITY_VOTE_RULE_IDS = {
    "QA-GIP-06",
    "QA-HRS-07",
    "QA-HRS-09",
    "QA-GIP-07",
    "QA-PROB-01",
}


def should_use_majority_vote(rule_id: str) -> bool:
    return rule_id in MAJORITY_VOTE_RULE_IDS


def run_judgment_checks(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    tracker=None,
    call_reason: str = "call",
) -> dict[str, dict]:
    """Self-consistency wrapper (2026-07-28 round): calls
    _run_judgment_checks_once TWICE with identical inputs and reconciles.
    Where both calls agree on a rule_id's result, that result is kept.
    Where they disagree, the finding is downgraded to "uncertain" rather
    than silently reporting whichever call happened to run second — this
    is the fix for the confirmed judgment-layer non-determinism (live
    consistency probe: some rules flip result across identical repeated
    calls on the same document, even in complete isolation from other
    rules in the batch). temperature/top_p/top_k are not available as a
    cheaper fix on this model — confirmed live, not just from docs:
    passing a non-default temperature returns a 400
    ("`temperature` is deprecated for this model"); only the model's own
    default is accepted, as a no-op.

    Doubles the real API call count (and cost) for every judgment batch —
    this is the deliberate tradeoff: a finding a reviewer can trust over
    one that's cheaper but may silently be whichever answer the model
    happened to land on that run. If a rule_id is missing from either
    call (rejected internally via evidence_supports_result, or dropped),
    it's left out of the returned dict entirely rather than guessed at —
    integrity.py's existing missing-rule_id retry already handles that
    case correctly, and re-asking is more honest than picking the
    surviving half of a pair that didn't fully agree.
    """
    if not judgment_rules:
        return {}
    first = _run_judgment_checks_once(
        judgment_rules, fields, rendered_images, tracker=tracker,
        call_reason=f"{call_reason} (consistency check 1/2)",
    )
    second = _run_judgment_checks_once(
        judgment_rules, fields, rendered_images, tracker=tracker,
        call_reason=f"{call_reason} (consistency check 2/2)",
    )
    return _reconcile_consistency_check(first, second)


def _reconcile_consistency_check(first: dict[str, dict], second: dict[str, dict]) -> dict[str, dict]:
    reconciled = {}
    for rule_id in set(first) & set(second):
        f, s = first[rule_id], second[rule_id]
        if f["result"] == s["result"]:
            reconciled[rule_id] = f
            continue
        f_evidence = f["evidence"] if isinstance(f["evidence"], str) else json.dumps(f["evidence"])
        s_evidence = s["evidence"] if isinstance(s["evidence"], str) else json.dumps(s["evidence"])
        reconciled[rule_id] = {
            "result": "uncertain",
            "evidence": (
                f"Judgment layer disagreed across two consistency-check calls for this "
                f"rule with identical input: first call said '{f['result']}' ({f_evidence}); "
                f"second call said '{s['result']}' ({s_evidence}). Flagged uncertain rather "
                f"than silently keeping one of the two answers."
            ),
            "page": None,
            "confidence": 0.0,
        }
    return reconciled


def run_judgment_checks_majority_vote(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    n_calls: int = 3,
    tracker=None,
    call_reason: str = "call",
) -> dict[str, dict]:
    """TESTABLE ALTERNATIVE to the production 2-call run_judgment_checks —
    not wired into the pipeline, used only to measure whether an N-way
    majority vote catches real failures the 2-call tie-break throws away
    (2026-07-28 round: found that in several confirmed real-document cases,
    the FIRST of the 2 calls was already correct and got dragged to
    "uncertain" only because the second call happened to disagree — a 3rd
    call breaks that tie in the direction of whichever answer the majority
    actually landed on, rather than always deferring to "uncertain").

    Makes n_calls real API calls per batch (default 3, vs. run_judgment_checks'
    fixed 2) — a real, larger cost increase, which is exactly why this is a
    separate function to test rather than a silent change to production.

    For each rule_id present in ALL n_calls responses: if a strict majority
    (> n_calls/2) share the same result, that result wins (kept from
    whichever call first produced it). If every call disagrees (no
    majority), falls back to "uncertain" — same honesty principle as the
    2-way version, just with a higher bar before giving up. A rule_id
    missing from any single call is left out of the returned dict entirely,
    same as the 2-way version — integrity.py's retry logic handles it.
    """
    if not judgment_rules:
        return {}
    all_results = [
        _run_judgment_checks_once(
            judgment_rules, fields, rendered_images, tracker=tracker,
            call_reason=f"{call_reason} (majority vote {i + 1}/{n_calls})",
        )
        for i in range(n_calls)
    ]
    return _reconcile_majority_vote(all_results)


def _reconcile_majority_vote(all_results: list[dict[str, dict]]) -> dict[str, dict]:
    if not all_results:
        return {}
    common_ids = set.intersection(*(set(r) for r in all_results))
    reconciled = {}
    for rule_id in common_ids:
        entries = [r[rule_id] for r in all_results]
        counts = Counter(e["result"] for e in entries)
        winning_result, winning_count = counts.most_common(1)[0]
        if winning_count > len(all_results) / 2:
            reconciled[rule_id] = next(e for e in entries if e["result"] == winning_result)
            continue
        summaries = []
        for i, e in enumerate(entries):
            ev = e["evidence"] if isinstance(e["evidence"], str) else json.dumps(e["evidence"])
            summaries.append(f"call {i + 1} said '{e['result']}' ({ev})")
        reconciled[rule_id] = {
            "result": "uncertain",
            "evidence": (
                f"Judgment layer split with no majority across {len(all_results)} "
                f"consistency-check calls for this rule with identical input: "
                + "; ".join(summaries)
                + ". Flagged uncertain rather than silently keeping one answer."
            ),
            "page": None,
            "confidence": 0.0,
        }
    return reconciled


def _findings_dict_from_list(findings_list: list[dict]) -> dict[str, dict]:
    """Converts the tool call's raw findings array into {rule_id: finding}.

    Structural enforcement of change #3: a finding the model itself marked
    evidence_supports_result=False is rejected, not recorded — it's simply
    left out of the returned dict, which makes it look identical to a
    rule_id the model dropped entirely. integrity.py's existing missing-
    rule_id retry logic (built for exactly that case) picks it back up and
    re-asks automatically, then raises IntegrityError if it's still
    inconsistent after max_retries — no separate error path needed.
    """
    rejected = [f for f in findings_list if not f.get("evidence_supports_result", False)]
    if rejected:
        # Log the actual result/evidence text for each rejected finding, not
        # just its rule_id — a rule_id alone is undiagnosable after the fact:
        # a prior round hit exactly this dead end (a rule rejected twice on
        # what looked like an unambiguous fact pattern) and had no way to
        # tell, from the log, what the model actually said that it then
        # disowned. This is what makes that diagnosable from the first
        # report instead of needing a live re-run just to see what happened.
        print(f"[judge] Rejecting {len(rejected)} finding(s) with evidence_supports_result=False (will be retried as if missing):")
        for f in rejected:
            evidence = f.get("evidence")
            evidence_str = evidence if isinstance(evidence, str) else json.dumps(evidence)
            print(
                f"  - {f.get('rule_id')!r}: result={f.get('result')!r}, "
                f"confidence={f.get('confidence')!r}, evidence={evidence_str!r}"
            )

    return {
        f["rule_id"]: {
            "result": f["result"],
            "evidence": f["evidence"],
            "page": f.get("page"),
            "confidence": f.get("confidence"),
        }
        for f in findings_list
        if f.get("evidence_supports_result", False)
    }
