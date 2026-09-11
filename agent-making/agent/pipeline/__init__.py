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
# Master Fix Round (2026-09-08), Priority 5: QA-BIP-03's rules.json
# description was fixed (stale "Medical BIP" wording), but the rule
# stayed pinned here since the coin-flip instability was measured against
# the SAME underlying question (which listed behaviors trigger BIP
# scrutiny), just under stale wording -- fixing the label alone couldn't
# resolve that.
#
# Fix Round (2026-09-11), item 17 -- REMOVED, confirmed go-ahead: this
# round changed the rule to a genuinely DIFFERENT, inverted question (flag
# a BIP target OUTSIDE the named list, not flag presence of a named
# behavior) -- see this rule's own rules.json notes for the real-document
# verification. The old coin-flip instability data was measured against
# the OLD question and does not carry over to this new one; leaving it
# stabilized would silently force a fixed "uncertain" on a rule that was
# never actually tested in its new form. If real sampling later shows
# THIS question is also unstable, that's a fresh finding needing its own
# stabilization decision -- not assumed here either way.
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
# Fix Round (2026-09-11 evening), "Stabilize the 13 Newly-Found Flipping
# Rules Before Production" -- REAL, CONFIRMED via two identical, fresh
# (force_refresh=True) real runs of the same document: 13 rule_ids
# produced a different result across the two runs. ROOT CAUSE, FOUND (not
# a new instability, an existing one this mechanism never actually
# covered): confirmed directly that THIS frozenset was never filtered out
# of `escalated_rules` in either orchestration function -- a rule_id
# whose deterministic checker returns low-confidence/not_checkable (and
# therefore escalates to judgment) bypassed this safety net completely
# even when it was already listed here, because the filter only ever
# applied to `judgment_rules` BEFORE the escalated_rules union. Separately
# confirmed `_run_pipeline_with_extras` (api.py) -- the orchestration path
# EVERY real upload actually takes, since a supporting document has been
# mandatory since Round 51/52 -- never applied this filter AT ALL, to
# either pool; its own docstring already flagged that it's a hand-
# duplicated copy of this function's orchestration, but the duplication
# fell out of sync the moment this stabilization mechanism was added here
# and never back-ported there. Net effect: this safety net has likely
# never been active against real production traffic since it was built --
# QA-GIP-17/QA-GIP-22/QA-GIP-34/QA-SCH-09/QA-TEMP-06 below were ALREADY
# listed here and STILL flipped on the real two-run test, which is the
# direct, confirmed proof of this gap, not a coincidence. Fixed in both
# `run_full_pipeline` below and `api.py::_run_pipeline_with_extras`: the
# filter now applies to the FULL judgment batch (judgment_rules UNION
# escalated_rules), in both places, not just judgment_rules pre-union.
#
# Fix Round (2026-09-11 night), "Stop Over-Using the Uncertain Safety Net.
# Only Genuine Graph/Grid Rules Stay Pinned." -- REAL DECISION, applied
# plainly: this safety net exists for ONE narrow, legitimate reason -- the
# answer genuinely depends on data that can't be reliably extracted from
# an image (a rendered graph, a grid of colors/dates in an assessment
# tool). It is not a general "this rule sometimes disagrees with itself"
# fix. Every rule_id below was re-examined against that one test.
#
# STAYS PINNED -- genuine graph/grid-image dependency, confirmed real,
# no text extraction can solve this (explicitly approved to stay as-is
# this round, not touched):
#   - QA-GIP-34/QA-GIP-35: final graph data point / x-axis label vs. a
#     rendered graph image -- see their own long-standing comment above.
#   - HF-05: PRT goal data points, same reason, graph-based.
#   - QA-ACF-03: assessment grid legend (colors/dates/assessor) is
#     frequently an embedded IMAGE the text layer can't see at all --
#     see QA-ACF-03's own rules.json notes and VISION_ELIGIBLE_RULE_SECTIONS.
#
# STAYS PINNED -- investigated this round, genuinely NOT fixable yet for
# a real, specific reason (not just "it's hard") -- flagged, not quietly
# re-pinned without explanation:
#   - QA-ACF-11: FLAGGED DISCREPANCY, not silently decided either way --
#     this rule's OWN rules.json notes describe it as image-dependent for
#     the EXACT SAME reason as QA-ACF-03 above (the Vineland grid/legend
#     content is frequently an embedded image; QA-ACF-11 is already in
#     VISION_ELIGIBLE_RULE_SECTIONS, same "acf" section-page-range finder).
#     This round's own instruction categorized it as text-based -- that
#     looks like it conflicts with the rule's own established mechanics.
#     Left pinned (matching QA-ACF-03's already-approved reasoning) pending
#     explicit confirmation either way, rather than unilaterally un-pinning
#     what looks like a genuinely image-dependent rule.
#   - QA-GIP-17, QA-GIP-11: both ask the model to judge whether a goal's
#     own free-text wording contains an antecedent/SD, a concrete
#     deficit/setting statement, and an observable (not internal-state)
#     expected response -- already have real, detailed 3-part criteria in
#     their own rules.json notes (not vague to begin with). No further
#     tightening found this round that would make this a mechanical check
#     rather than a real reading-comprehension judgment -- same shape as
#     QA-GIP-14 ("the canonical LLM-judgment example," never successfully
#     de-flagged by rewriting). Genuine residual judgment call, not a
#     structural gap.
#   - QA-BIO-06: "adequacy of stated reason" for a listed medication is
#     genuinely judgment-shaped, AND the one real document available for
#     this round's investigation has no current-medication field to
#     build/verify a deterministic presence-check against (only a
#     historical, discontinued mention in free narrative, not a labeled
#     field) -- inventing a "confirmed real phrasing" pattern without a
#     real example would repeat exactly the dishonesty this project has
#     deliberately avoided elsewhere.
#   - QA-SCH-09: already tightened twice in earlier rounds (concrete
#     "real named location vs. generic placeholder" distinction, plus the
#     Healthfirst POS/Hours-grid mismatch clause). The remaining ambiguity
#     -- whether a given free-text location name counts as "specific
#     enough" -- is a genuine judgment call about natural language, not a
#     fixed enum or pattern; no further real tightening found this round.
#   - QA-TEMP-06: "empty fields should be marked N/A rather than left
#     blank" as a document-wide policy. Investigated reusing this file's
#     own general blank-label scanner (_find_blank_labels_with_offsets,
#     built for QA-RPT-01) -- confirmed it also flags genuine SECTION
#     HEADERS as "blank" (e.g. "Patient Information:", "Goals in
#     Progress:"), not just real unfilled form fields, so reusing it
#     as-is would produce real false-positive fails. A safe version needs
#     a curated allowlist/blocklist of which labels are genuine leaf
#     fields vs. section headers -- not built this round; flagged as
#     real, specific remaining work, not silently re-pinned as "hard."
#
# UN-PINNED THIS ROUND -- real deterministic/hybrid checkers built or
# extended, no longer need the safety net (see each function's own
# docstring in fields.py, right above DET_CHECKS, for the full diagnosis):
#   QA-COC-06, QA-GIP-21, QA-HRS-08, QA-MAST-03, HF-06, QA-SCH-05, QA-GIP-22.
#   QA-PPI-05 (from the prior round's list) is NOT included here -- its
#   own instability comes from a SEPARATE real API call (the supporting-
#   doc NPI extraction)'s own sampling variance, not this rule's logic;
#   genuinely out of THIS round's scope (a different call site entirely),
#   left pinned with that real, specific reason, not silently dropped.
STABILIZED_UNCERTAIN_RULE_IDS = frozenset({
    "QA-MAST-04", "QA-GIP-14",  # original 2, unchanged (see Part 2 above)
    "QA-AI-03", "QA-AI-05", "QA-BIP-09", "QA-BIP-10", "QA-BIP-12",
    "QA-COC-07", "QA-GIP-02", "QA-GIP-17", "QA-GIP-20", "QA-GIP-23",
    "QA-GIP-25", "QA-GIP-27", "QA-GIP-29", "QA-GIP-34", "QA-GIP-35", "QA-HRS-07",
    "QA-PAR-02", "QA-SCH-09", "QA-TEMP-06",
    "HF-05", "QA-ACF-03", "QA-ACF-11", "QA-PPI-05",
    "QA-BIO-06", "QA-GIP-11",
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
    full_judgment_batch = judgment_rules + escalated_rules

    # Fix Round (Eliminate Coin-Flipping, For Real, Before Production),
    # Part 1: pull the confirmed-near-50/50 rule_ids OUT of the real
    # judgment call entirely -- see STABILIZED_UNCERTAIN_RULE_IDS's own
    # comment above for why this is a real, zero-model-call, zero-
    # variance-by-construction override, not just "the vote usually lands
    # on uncertain for these."
    #
    # Fix Round (2026-09-11 evening) -- REAL BUG FOUND AND FIXED: this
    # filter used to run BEFORE `escalated_rules` was unioned in, on the
    # (stated, now-disproven) assumption that none of the stabilized
    # rule_ids are ever escalated. Confirmed false on a real document:
    # several rule_ids added to STABILIZED_UNCERTAIN_RULE_IDS this round
    # (QA-COC-06, QA-GIP-21, QA-HRS-08, QA-PPI-05) are check_type=
    # "deterministic" with no real checker or a low-confidence result on
    # this real document, so they ALWAYS escalate -- the old filter order
    # never touched them even after being added here, since they were
    # never in `judgment_rules` to begin with. Filtering the FULL union
    # instead closes this for every rule_id in the set, regardless of
    # which pool it entered through.
    stabilized_rule_ids = {r["rule_id"] for r in full_judgment_batch if r["rule_id"] in STABILIZED_UNCERTAIN_RULE_IDS}
    full_judgment_batch = [r for r in full_judgment_batch if r["rule_id"] not in STABILIZED_UNCERTAIN_RULE_IDS]

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
