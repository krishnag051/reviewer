"""Orchestrates the pipeline steps in Section 4's fixed sequence. Plain
functions, no orchestration library — see Section 8 of the design doc.
"""
from . import fields as fields_module
from . import integrity
from . import merge as merge_module
from .extract import extract_pdf_text
from .flag_pages import flag_image_only_pages, flagged_page_numbers
from .render import render_flagged_pages

# Fix Round (Eliminate Coin-Flipping, For Real, Before Production), Part 1
# -- REAL, CONFIRMED near-50/50 raw per-call splits (a pool of 7
# independent real calls against a real document, Fix Round: Judgment
# Layer Stability's own report has the exact numbers: 4-of-7, ~57%
# dominant, for all 5 rule_ids originally in this set) -- not fixable by
# voting harder, only by rewriting the rule's own criteria (Part 2 of this
# same round). Until a given rule_id is confirmed genuinely stable under
# rewritten criteria and removed from this set, it is held OUT of the real
# judgment call entirely (zero model calls, zero variance by construction,
# not just "usually stable") and given a fixed finding instead -- "we are
# not accepting coin-flip sometimes... even temporarily" was this round's
# own explicit standing instruction. A stable, honest "needs human review"
# beats an unstable pass/fail for a compliance tool, full stop.
#
# Part 2 RESULT (same round, real 7-call re-test against 4 rewritten
# rules, ISOLATED/narrow context -- see this round's own report):
# QA-GIP-27 (0.57 -> 0.86), QA-GIP-22 (0.57 -> 1.00), QA-GIP-28
# (0.57 -> 1.00) all looked genuinely fixed in that narrow test.
# QA-MAST-04 was not attempted (a PRIOR round's own notes already
# concluded real ma'am clarification is needed, still honored). QA-GIP-14
# was rewritten too but showed no improvement (real clinical judgment,
# this rule's own notes call it "the canonical LLM-judgment example").
#
# Fix Round (Eliminate Coin-Flipping, For Real, Before Production), Part
# 3 -- REAL BUG IN THE TESTING METHODOLOGY ITSELF, FOUND: the narrow-
# context isolated re-test above does NOT reliably predict full ~120-rule
# production-batch behavior. Confirmed directly: a real 3-run test of the
# FULL rule set (not just the 14 originally suspect ones) found 21 of 181
# rule_ids produced a different verdict across 3 identical runs --
# INCLUDING QA-GIP-22 (isolated test: 7/7 unanimous pass; full batch:
# uncertain/uncertain/not_applicable -- the isolated result did not
# transfer) and QA-GIP-27 (isolated: 6/7; full batch: pass/pass/
# uncertain -- improved, but still a real flip). QA-GIP-28 DID hold up
# (no flip across all 3 full-batch runs) -- stays off this set, genuinely
# confirmed at the scale that actually matters. QA-MAST-04/QA-GIP-14
# (never left this set) also correctly showed zero flips, confirming
# Part 1's own mechanism works for real at full scale too.
#
# The other 15 rule_ids below were NEVER part of the originally-suspected
# 14 -- discovered only by finally running a real full-rule-set repeat
# test, exactly the risk this round's own brief anticipated ("don't
# assume the list of 14 is exhaustive"). Given this round's own explicit,
# standing bar ("No rule should be capable of returning pass one run and
# fail the next by the end of this round, full stop") and this round's
# real spend already at ~$7 of its $8 cap (not enough left for a genuine
# rewrite-and-reverify cycle on 20 more rules), EVERY rule_id confirmed
# unstable by this real test is held here now, same zero-model-call
# mechanism as QA-MAST-04/QA-GIP-14 -- a real, immediate, structurally-
# guaranteed stop to the coin-flipping, even though the REAL fix (Part
# 2-style rewrite-and-reverify, or a deterministic conversion) for these
# 20 is genuinely not done and is this round's own clearly-flagged
# follow-up, not something to silently claim finished. See this round's
# own report for the exact real data behind every rule_id here.
# Master Fix Round (2026-09-08), Priority 5 -- explicit decision, not left
# implicit: the master checklist audit found QA-BIP-03's rules.json
# description was stale/wrong ("Medical BIP -> all medical causes ruled
# out" instead of the real behavior-list wording), and fixed it. That fix
# does NOT change whether QA-BIP-03 belongs in this set -- it's parked here
# because real, repeated sampling showed near-random verdicts, a property
# of how the model reasons about this rule's CONTENT under repetition, not
# of a stale label. Fixing the label corrects what a reviewer sees this
# rule is nominally checking; it does not touch, and cannot by itself
# resolve, the coin-flip risk. Re-running the same real sampling test this
# round's Part 2 used, against the corrected wording, would be needed
# before removing QA-BIP-03 from this set -- not done this round (no
# budget approved for it), so it stays here, correctly labeled but still
# inert.
#
# QA-GIP-34/QA-GIP-35 (graph-final-data-point-matches-current-data;
# target-name-matches-x-axis) are parked here for a different, structural
# reason: both need real GRAPH-VALUE extraction (reading actual plotted
# values off a rendered image) to ever produce a grounded answer at all --
# no such extraction primitive exists anywhere in this codebase (confirmed
# during the master checklist audit). This isn't a wording-ambiguity
# problem Part-2-style rewriting can fix; it needs real vision/graph-
# reading engineering, which is out of scope for a fix round. Whether
# that's built in a future round, or these two are accepted as permanent
# manual-review items, is a real product-scope decision for the user to
# make explicitly -- not assumed here either way.
STABILIZED_UNCERTAIN_RULE_IDS = frozenset({
    "QA-MAST-04", "QA-GIP-14",  # original 2, unchanged (see Part 2 above)
    "QA-AI-03", "QA-AI-05", "QA-BIP-03", "QA-BIP-09", "QA-BIP-10", "QA-BIP-12",
    "QA-COC-07", "QA-GIP-02", "QA-GIP-17", "QA-GIP-20", "QA-GIP-22", "QA-GIP-23",
    "QA-GIP-25", "QA-GIP-27", "QA-GIP-29", "QA-GIP-34", "QA-GIP-35", "QA-HRS-07",
    "QA-PAR-02", "QA-SCH-09", "QA-TEMP-06",
})

_STABILIZED_UNCERTAIN_EVIDENCE = (
    "Uncertain — needs human review. This rule's judgment criteria were confirmed (real, "
    "repeated sampling against real documents) to produce a near-random verdict across "
    "identical input, and are being rewritten to remove that ambiguity. Until the rewrite is "
    "confirmed genuinely stable, this rule is intentionally held at a fixed, honest "
    "\"needs human review\" status rather than risk reporting an unstable pass/fail that could "
    "differ from one review of the same document to the next."
)


def _stabilized_uncertain_finding() -> dict:
    """Same finding, every single call, every single rule_id in
    STABILIZED_UNCERTAIN_RULE_IDS -- byte-identical evidence text too (not
    just the same result label with different reasoning each time), per
    this round's own explicit verification requirement. No randomness
    anywhere in this function -- that's the entire point.
    """
    return {"result": "uncertain", "evidence": _STABILIZED_UNCERTAIN_EVIDENCE, "page": None, "confidence": 0.0}


def run_full_pipeline(pdf_path: str, rules: list[dict], tracker=None, model_override: str | None = None) -> dict:
    """Runs extract -> flag -> render -> scope filter -> deterministic ->
    (escalate weak det findings into) judgment (with integrity check) ->
    merge, and returns merge.merge_findings's output.

    `tracker` (an ApiCallTracker, see pipeline/call_tracker.py) is optional
    but should be passed by any caller that runs this more than once in a
    script (a consistency probe, a batch of test documents, etc.) — it's
    what makes every real API call visible and cappable, since a single
    call to this function can itself make 1-3+ real calls internally via
    integrity.py's retry loop.

    `model_override` (Round 61) is forwarded, unchanged, all the way down to
    judge.py's real judgment call. Defaults to None, which keeps this
    function's behavior identical to every round before this one — the only
    caller that passes a non-None value is the Streamlit POC (app.py),
    whose own UI defaults to Round 59's free OpenRouter model and only
    reaches the real Anthropic API when a developer explicitly flips and
    confirms a toggle. See judge.py's docstring on this same parameter.
    """
    pages = extract_pdf_text(pdf_path)
    pages = flag_image_only_pages(pages)

    extracted_fields = fields_module.extract_fields(pdf_path, pages)

    # Fix Round, item 5: pages rendered for vision input are no longer
    # JUST the low-text-flagged ones -- any rule opted into
    # fields_module.VISION_ELIGIBLE_RULE_SECTIONS also gets its own
    # section's real page range rendered, regardless of whether those
    # pages are low-text (the actual gap this closes is an embedded image
    # on an otherwise text-heavy page, which flagged_page_numbers alone
    # structurally cannot catch). See fields_module.vision_eligible_pages's
    # own docstring.
    to_render = sorted(set(flagged_page_numbers(pages)) | fields_module.vision_eligible_pages(rules, extracted_fields))
    rendered_images = render_flagged_pages(pdf_path, to_render) if to_render else {}

    # Rules whose applies_to_plan_type/applies_to_payor doesn't match this TP
    # never reach either layer — they come back pre-filled as not_applicable.
    applicable_rules, excluded_findings = fields_module.partition_rules_by_scope(rules, extracted_fields)

    det_results = fields_module.run_deterministic_checks(applicable_rules, extracted_fields)

    rules_by_id = {r["rule_id"]: r for r in rules}

    # Any deterministic finding that came back not_checkable/uncertain, or
    # with confidence below the escalation threshold, gets a second look from
    # the judgment layer in the same call — it has the rendered images and
    # can reason about ambiguous text, where the regex-based checkers can't.
    escalated_ids = [rid for rid, r in det_results.items() if fields_module.needs_escalation(r)]
    escalated_rules = [rules_by_id[rid] for rid in escalated_ids]

    judgment_rules = [r for r in applicable_rules if r["check_type"] == "judgment" and r["active"]]

    # Fix Round (Eliminate Coin-Flipping, For Real, Before Production),
    # Part 1: pull the confirmed-near-50/50 rule_ids OUT of the real
    # judgment call entirely -- see STABILIZED_UNCERTAIN_RULE_IDS's own
    # comment above for why this is a real, zero-model-call, zero-
    # variance-by-construction override, not just "the vote usually lands
    # on uncertain for these." None of these 5 are escalated_rules (all
    # confirmed check_type="judgment" in rules.json, never det-checked),
    # so this filter alone is sufficient -- no interaction with the
    # det-escalation merge below.
    stabilized_rule_ids = {r["rule_id"] for r in judgment_rules if r["rule_id"] in STABILIZED_UNCERTAIN_RULE_IDS}
    judgment_rules = [r for r in judgment_rules if r["rule_id"] not in STABILIZED_UNCERTAIN_RULE_IDS]
    full_judgment_batch = judgment_rules + escalated_rules

    judgment_results = integrity.run_judgment_with_integrity_check(
        full_judgment_batch, extracted_fields, rendered_images, tracker=tracker, model_override=model_override,
    )
    for rule_id in stabilized_rule_ids:
        judgment_results[rule_id] = _stabilized_uncertain_finding()

    # For escalated rules, the judgment result wins (more context to work
    # with) — but the original deterministic attempt is kept as a secondary
    # "det_attempt" field so a disagreement between the two layers is visible
    # for debugging, not silently overwritten. If judgment also comes back
    # not_checkable, that's a real confirmation the rule needs external data
    # this POC doesn't have — not a gap in either layer's code.
    for rule_id in escalated_ids:
        det_attempt = det_results[rule_id]
        merged = {**judgment_results[rule_id], "det_attempt": det_attempt}
        # The deterministic layer's page number is computed directly from
        # scanning fields["pages"] for a specific match — it isn't guessed.
        # Judgment's page comes from the model counting through a long,
        # multi-page prompt, which is exactly what produced a confirmed
        # off-by-one on QA-RPT-01 against CS TP.pdf. When the det layer
        # found a specific page, prefer it over judgment's re-derived one.
        # Doesn't apply when judgment's evidence is the multi-page list
        # form — that form already carries its own per-item pages and a
        # single det page wouldn't fit its shape. Also doesn't apply when
        # judgment's own `page` is itself a multi-page list (2026-07-28
        # multi-page-finding support): that's genuine information a
        # single-page det checker structurally cannot produce, and forcing
        # det's one page into that slot would silently discard it — proven
        # by a real fixture where judgment's evidence explicitly discussed
        # two specific pages and det's unrelated single page overwrote both.
        if (
            det_attempt.get("page") is not None
            and isinstance(merged.get("evidence"), str)
            and not isinstance(merged.get("page"), list)
        ):
            merged["page"] = det_attempt["page"]
        det_results[rule_id] = merged

    # Route each excluded rule's not_applicable finding into the dict
    # matching its own check_type, so merge_findings's existing det/judgment
    # dispatch picks it up without any change to merge.py.
    for rule_id, finding in excluded_findings.items():
        rule = rules_by_id[rule_id]
        if rule["check_type"] == "deterministic":
            det_results[rule_id] = finding
        else:
            judgment_results[rule_id] = finding

    result = merge_module.merge_findings(rules, det_results, judgment_results)
    # Surfaced so callers (app.py) can display what was actually detected —
    # never assumed — for this specific document, instead of hardcoding a
    # payor name anywhere in the UI.
    result["detected_payor"] = extracted_fields.get("payor")
    result["detected_plan_type"] = extracted_fields.get("plan_type")
    # Fix Round, item 3: a post-processing pass over EVERY rule's result
    # (det + judgment together, after both layers and the escalation merge
    # above have all finished) -- catches a pair of rules in the same
    # rule_id group disagreeing about whether a section/field is blank or
    # populated (see fields_module.find_cross_rule_contradictions's own
    # docstring for the confirmed real ACF-01/ACF-05-vs-ACF-07 case this
    # generalizes from). Never resolves the disagreement itself — both
    # rules' own results are untouched; this only adds a visible flag.
    result["cross_rule_contradictions"] = fields_module.find_cross_rule_contradictions(
        {**det_results, **judgment_results}
    )
    return result
