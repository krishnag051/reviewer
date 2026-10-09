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
#
# UN-PINNED (Fix Round, Jacob Freund 10-2026-U1): QA-HRS-07 (Item 3, real
# deterministic no-increase gate built), QA-BIO-06 (Item 7, real
# medication-mention checker built), QA-ACF-11 (Item 11, real
# Vineland-vs-other-tool scoping checker built), QA-MAST-04 (Item 17, real
# checker built) -- see each one's own docstring in fields.py.
# QA-SCH-09 (Item 6) stays pinned, deliberately, this round -- Ms. Yachnes
# has offered to help define what real signal this rule can be checked
# against, and nothing was built without that input; see this round's
# report for the specific question back to her.
#
# UN-PINNED (Fix Round, Matthielly Cruz 9-2026-U1): QA-PAR-02 (Item 25,
# real lives-with-parents N/A gate built -- see fields.py::_check_PAR02),
# QA-TEMP-06 (Item 3, real multi-page blank-field checker built -- see
# fields.py::_check_TEMP06), QA-SCH-09 (new rule build -- she finally gave
# the concrete POS/schedule-grid spec needed; see fields.py::_check_SCH09).
# HF-05 STAYS pinned but its own context-preview extractor was fixed
# (Item 2, wrong-domain evidence) -- still genuinely image-dependent, not
# unpinned.
#
# UN-PINNED (Fix Round, Full Rule-by-Rule Fix List): QA-GIP-17 (Item 14,
# real hybrid DET precondition built -- see fields.py::_check_GIP17) and
# QA-GIP-29 (Item 11, registered for real vision access -- see
# VISION_ELIGIBLE_RULE_SECTIONS). QA-AI-05 (Item 15) is ALSO un-pinned
# this round -- spelling/grammar checking is a well-established,
# tractable judgment task (per her own explicit instruction), unlike a
# clinical judgment call; there is no keyword-shaped structural half to
# build deterministically the way QA-GIP-17 has one, so the real attempt
# here is letting it actually reach a real judgment call for the first
# time, instead of hand-building a dictionary-based spell-checker out of
# proportion to this fix. DISCLOSED, NOT YET VERIFIED: this rule was
# never confirmed working before being pinned in the first place, and
# unpinning without a real 2-run stability check (real, billed API
# calls) genuinely could reintroduce the exact coin-flip problem this
# list exists to prevent -- flagged plainly rather than run that
# verification without explicit per-instance approval.
STABILIZED_UNCERTAIN_RULE_IDS = frozenset({
    "QA-GIP-14",  # original 2 minus QA-MAST-04, unpinned this round (see above)
    "QA-AI-03", "QA-BIP-09", "QA-BIP-10", "QA-BIP-12",
    "QA-COC-07", "QA-GIP-02", "QA-GIP-20", "QA-GIP-23",
    "QA-GIP-25", "QA-GIP-27", "QA-GIP-34", "QA-GIP-35",
    "HF-05", "QA-ACF-03", "QA-PPI-05",
    "QA-GIP-11",
})
# QA-GIP-29 UN-PINNED (Fix Round, Full Rule-by-Rule Fix List, Item 11):
# was riding the generic stabilized-uncertain template (a raw
# Baseline/Current-Data/Mastery-Criteria goal-context DUMP, never
# actually answering "is a graph present, and if not, is a rationale
# given") -- registered under VISION_ELIGIBLE_RULE_SECTIONS's own
# "gip_graph" section (same real per-goal image QA-GIP-28/32/34/35
# already read) so it now gets a real judgment call WITH the actual
# rendered graph image, instead of never attempting a real answer at
# all. NOT YET VERIFIED against a real document run (that needs a real,
# billed judgment call -- flagged plainly rather than run without
# explicit per-instance approval).

# Fix Round (2026-09-15), "Language Regression": REAL FIX -- this text
# used internal engineering language ("repeated sampling", "near-random
# verdict", "confirmed genuinely stable") that a BCBA reviewer wouldn't
# use or need. Rewritten in plain English -- same real meaning (we're
# still working on this question and it's not ready to trust yet, so
# please check it by hand), no internal terms.
_STABILIZED_UNCERTAIN_FRAMING = (
    "Needs human review. We're still refining how this question is checked, so for now please "
    "confirm this item yourself rather than relying on an automated answer."
)

_STABILIZED_UNCERTAIN_NO_CONTEXT = "No additional automated context is available for this item yet."


def _stabilized_uncertain_finding(rule_id: str | None = None, fields: dict | None = None) -> dict:
    """Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence"
    -- REAL FIX: this used to return byte-identical evidence for every
    call regardless of rule_id or document, which was honest about the
    tone but gave a reviewer nothing to start from -- confirmed real
    complaint, this defeats a large part of the point of the tool for
    exactly the findings a human has to act on manually.

    Still makes ZERO model calls and stays fully deterministic -- the
    real invariant an earlier round actually needed (zero variance across
    repeated runs of the SAME document) still holds, because
    `fields_module.get_stabilized_rule_context` is a plain, zero-API-cost
    text scan (same shape as any other checker's own extraction), never
    a model call. What changes: the evidence text now varies by rule_id
    and by document (surfacing that document's own real goal data, dates,
    or field values), not "byte-identical no matter what" -- byte-
    identical-across-DOCUMENTS was never the actual point; byte-identical
    across REPEATED RUNS of the same document is, and a deterministic
    text scan guarantees exactly that.

    `rule_id`/`fields` are optional (default None) so any caller that
    hasn't been updated yet still gets the honest framing sentence alone,
    same as before this round -- never a crash for a missing argument.
    """
    if rule_id is None or fields is None:
        return {"result": "uncertain", "evidence": _STABILIZED_UNCERTAIN_FRAMING, "page": None, "confidence": 0.0}
    # Fix Round (real re-verification, MC 9-2026-U1), Item 5: HF-05 is
    # about Parent/Caregiver Training goals specifically -- if there are
    # ZERO such goals in the document at all, this rule's own precondition
    # doesn't apply, and it must resolve not_applicable directly rather
    # than escalate into the generic "no automated context available"
    # Uncertain template. Confirmed on the real document that surfaced
    # this bug: QA-MAST-04's own checker already correctly detects zero
    # Parent Training goals here -- fields_module._has_any_parent_training_goal
    # reuses that exact, already-proven-working detection. Scoped to
    # HF-05 only; every other stabilized rule_id is completely unaffected.
    if rule_id == "HF-05" and not fields_module._has_any_parent_training_goal(fields):
        return (
            {
                "result": "not_applicable",
                "evidence": "No Parent/Caregiver Training goals found in this document -- this rule's "
                             "precondition doesn't apply.",
                "page": None,
                "confidence": 0.85,
            }
        )
    context = fields_module.get_stabilized_rule_context(rule_id, fields)
    tail = context if context else _STABILIZED_UNCERTAIN_NO_CONTEXT
    return {
        "result": "uncertain",
        "evidence": f"{_STABILIZED_UNCERTAIN_FRAMING} Here's what was found: {tail}",
        "page": None,
        "confidence": 0.0,
    }


def _merge_gip12_candidate_pages(result: dict, candidates: list[tuple], fields: dict | None = None) -> dict:
    """Round 7 real fix (QA-GIP-12 regression) -- see the call site's own
    comment above for why this exists. Handles all three real shapes
    `page`/`evidence` can take here: `page` as list[int]; `evidence` as
    the `[{page, detail}, ...]` list form; and (Round 13 addition) `page`
    as a single int with plain-string `evidence` -- upgraded to the
    list[int] form when Pass 1 has real pages beyond that one, since
    list[int] and plain-string evidence are both already-documented,
    already-supported shapes (merge.py's own docstrings), not an
    invented one. A genuinely single-page result with nothing else for
    Pass 1 to add is returned byte-identical, unchanged.

    Round 13 real fix, root cause of the reported regression: the actual
    coverage gap traced this round turned out to be a test-harness bug
    in a PRIOR round's own diagnostic reconstruction (missing all 12 of
    the real target pages' text entirely, silently replaced by generic
    filler) -- not a defect in this merge logic itself, which a corrected
    real run confirmed already unions Pass 1's real candidates in
    correctly for the list-shaped cases. The single-page-int gap fixed
    here is a genuinely new, real, additional gap this round's corrected
    real run then surfaced on top of that.

    Round 9 real fix: `fields` (optional, default None for backward
    compatibility with any existing caller/test) enables a second real
    check -- real evidence showed judgment citing a page (46) that,
    checked directly against the actual document, names no
    verbal-operant term anywhere on it at all, a confirmed hallucinated
    citation. Any of judgment's OWN cited pages that fails a real,
    whole-page verification (fields_module.page_contains_verbal_operant_
    term) is dropped -- never one of Pass 1's own candidate pages, which
    are already real by construction and never need this check. This is
    the other half of "floor, not ceiling": Pass 1's real pages can only
    be ADDED, judgment's own unverifiable pages can be REMOVED, but a
    page confirmed real by either side always survives.
    """
    candidate_pages = {page for page, _name, _term in candidates if page is not None}
    candidates_by_page = {}
    for page, name, term in candidates:
        if page is not None and page not in candidates_by_page:
            candidates_by_page[page] = (name, term)

    def _prune_hallucinated(pages: set[int]) -> set[int]:
        if fields is None:
            return pages
        return {
            p for p in pages
            if p in candidate_pages or fields_module.page_contains_verbal_operant_term(fields, p)
        }

    if isinstance(result.get("evidence"), list):
        evidence_pages = {item["page"] for item in result["evidence"] if item.get("page") is not None}
        # Round 12 real fix (mc_current.pdf, real bug found): confirmed
        # live against the real document that a reconciled majority-vote
        # result can carry a top-level `page` field (a plain list of
        # ints) that DISAGREES with its own `evidence` list -- in the
        # real case found, evidence came back an empty list while `page`
        # separately cited 3 real pages. merge.py's own export dispatch
        # (_explode_to_rows) reads a page-level entry's page from
        # `evidence` ONLY whenever evidence is list-shaped -- it never
        # looks at the top-level `page` field in that branch at all -- so
        # those 3 pages would otherwise silently vanish from the final
        # CSV/export the moment this branch returns, with nothing in this
        # function's own logic ever having looked at them. `page_only_
        # pages` tracks them separately from `evidence_pages` (pages that
        # already have a real evidence entry) specifically so a page that
        # was only ever cited via the `page` field -- and is kept by the
        # hallucination check -- still gets a real entry synthesized for
        # it below, instead of being treated as "already represented"
        # when it never actually was.
        # Round 13 real fix: `page` can ALSO come back as a bare single
        # int while `evidence` is (possibly empty) list-shaped -- a real
        # live run hit exactly this (evidence: [], page: 23) -- so this
        # now normalizes either shape into the same page-only-pages set,
        # not just the list[int] case Round 12's own fix only covered.
        raw_page = result.get("page")
        if isinstance(raw_page, list):
            page_only_pages = set(raw_page) - evidence_pages
        elif isinstance(raw_page, int):
            page_only_pages = {raw_page} - evidence_pages
        else:
            page_only_pages = set()
        all_judgment_pages = evidence_pages | page_only_pages
        kept_judgment_pages = _prune_hallucinated(all_judgment_pages)
        pruned = all_judgment_pages - kept_judgment_pages
        needs_new_entry = sorted((candidate_pages | page_only_pages) - evidence_pages - pruned)
        evidence = [item for item in result["evidence"] if item.get("page") not in pruned]
        if not needs_new_entry and not pruned:
            return result
        added = []
        for page in needs_new_entry:
            if page in candidates_by_page:
                name, term = candidates_by_page[page]
                detail = (
                    f"Deterministic keyword scan (real, not model-generated): goal '{name}' contains the "
                    f"literal verbal-operant term '{term}'."
                )
            else:
                detail = (
                    "Judgment cited this page separately (in its own page field) without a matching "
                    "evidence entry -- carried over here so it isn't silently lost from the export."
                )
            added.append({"page": page, "detail": detail})
        return {**result, "evidence": evidence + added}

    if isinstance(result.get("page"), list):
        covered = set(result["page"])
        kept = _prune_hallucinated(covered)
        missing = sorted(candidate_pages - kept)
        pruned = covered - kept
        final_pages = sorted((kept | candidate_pages))
        if not missing and not pruned:
            return result
        evidence = result.get("evidence")
        notes = []
        if missing:
            missing_desc = "; ".join(
                f"page {page}: goal '{candidates_by_page[page][0]}' contains the literal term "
                f"'{candidates_by_page[page][1]}'" for page in missing
            )
            notes.append(f"Deterministic keyword scan also confirmed these additional real pages: {missing_desc}.")
        if pruned:
            notes.append(
                f"Removed page(s) {sorted(pruned)} -- checked directly against the document and found no "
                f"literal verbal-operant term anywhere on that page."
            )
        extended_evidence = f"{evidence} {' '.join(notes)}" if isinstance(evidence, str) and notes else evidence
        return {**result, "page": final_pages, "evidence": extended_evidence}

    # Round 13 real fix (mc_current.pdf, real live run): confirmed real
    # gap -- a winning reconciled result can come back with `page` as a
    # single int and `evidence` as a plain string (the genuinely common
    # shape for a clean pass/fail with one representative citation), and
    # this function used to leave it completely untouched, on the theory
    # that upgrading it would invent an unsupported shape. That reasoning
    # was wrong: `page` as list[int] and a plain-string `evidence` are
    # BOTH already-documented, already-supported shapes (merge.py's own
    # docstrings) -- upgrading a single int into that list form when Pass
    # 1 has real additional pages isn't inventing anything new, it's
    # using a shape this pipeline was already built to expect. Confirmed
    # live: without this, a clean single-page "fail" result silently
    # never got Pass 1's floor applied AT ALL, regardless of how many
    # real pages Pass 1 found -- the exact "evidence text and page list
    # don't agree" gap this round's own report named directly.
    if isinstance(result.get("page"), int):
        single_page = result["page"]
        kept = _prune_hallucinated({single_page})
        missing = sorted(candidate_pages - kept)
        if not missing and single_page in kept:
            return result
        final_pages = sorted((kept | candidate_pages))
        if not final_pages:
            return result
        evidence = result.get("evidence")
        notes = []
        if missing:
            missing_desc = "; ".join(
                f"page {page}: goal '{candidates_by_page[page][0]}' contains the literal term "
                f"'{candidates_by_page[page][1]}'" for page in missing
            )
            notes.append(f"Deterministic keyword scan also confirmed these additional real pages: {missing_desc}.")
        if single_page not in kept:
            notes.append(
                f"Page {single_page} was removed -- checked directly against the document and found no "
                f"literal verbal-operant term anywhere on that page."
            )
        extended_evidence = f"{evidence} {' '.join(notes)}" if isinstance(evidence, str) and notes else evidence
        return {**result, "page": final_pages, "evidence": extended_evidence}

    return result


def _inject_gip12_candidate_context(
    extracted_fields: dict, applicable_rules: list[dict], rules_by_id: dict[str, dict],
) -> tuple[list[tuple], list[dict], dict[str, dict]]:
    """QA-GIP-12 real fix (Round 6, Zaith 9-2026-U1): two-pass hybrid,
    Pass 2 -- feed Pass 1's deterministic literal-verbal-operant-term
    page scan (fields_module.gip12_verbal_operant_candidate_pages) into
    the judgment call as forced additional context, using the SAME
    extra_context convention pipeline/api.py's own extra_rule_context
    param already established (judge.py::_build_prompt reads it as
    "additional_real_data"). A staging run confirmed judgment alone
    missed several real literal occurrences on the real Zaith document
    (7 of ~12 real pages found); this gives the judge an explicit,
    page-numbered floor to confirm and build on, closing that specific
    miss without pretending the whole rule is deterministic -- a goal
    that's operant-SHAPED without using one of these 4 literal words
    still needs real judgment, and still gets it, same as before.

    Extracted into its own function in Round 13 -- REAL BUG FOUND AND
    FIXED: this logic (and the matching _merge_gip12_candidate_pages call
    after judgment returns) existed ONLY inline in run_full_pipeline. It
    was never duplicated into pipeline/api.py::_run_pipeline_with_extras,
    which is a hand-maintained COPY of run_full_pipeline's own
    orchestration (see that function's own docstring) -- and, since
    supporting_doc_path is mandatory on every real backend upload (Round
    51), _run_pipeline_with_extras, not run_full_pipeline, is the
    orchestration path every real upload actually takes. This is the
    exact same class of bug already found and fixed once before for the
    STABILIZED_UNCERTAIN_RULE_IDS filter (see _run_pipeline_with_extras's
    own comment on that fix) -- confirmed real: QA-GIP-12's entire
    two-pass hybrid mechanism (Rounds 6-12) has never actually run
    against real production traffic at all, only against direct
    run_full_pipeline callers and this round's own diagnostic scripts.
    Pulling this into one shared function that BOTH orchestration paths
    call closes the gap structurally, not just for today -- a future
    change to this logic can no longer silently apply to only one path.

    Returns `(gip12_candidates, applicable_rules, rules_by_id)` --
    `applicable_rules`/`rules_by_id` are returned back out (not mutated
    in place) since callers hold their own references to the lists/dicts
    passed in and Python's own copy-on-write-via-rebinding here means the
    caller must reassign, exactly as run_full_pipeline's own pre-Round-13
    inline version already required of itself.
    """
    gip12_candidates = fields_module.gip12_verbal_operant_candidate_pages(extracted_fields)
    if gip12_candidates and "QA-GIP-12" in rules_by_id:
        candidate_lines = "; ".join(
            f"page {page if page is not None else '?'}: goal '{name}' contains the literal term '{term}'"
            for page, name, term in gip12_candidates
        )
        # Round 7 real fix: reworded after a confirmed regression -- the
        # previous wording ("treat this as a floor... must be included")
        # is consistent with the model anchoring on this list and citing
        # FEWER pages than it found unaided before this context existed
        # (real evidence: 5 pages after vs. 7 before, all 5 a subset of
        # the 7). This is now explicitly framed as a starting point to
        # read PAST, not a list to reconcile down to, and the actual
        # completeness guarantee is enforced in code afterward
        # (_merge_gip12_candidate_pages below), not left to the model to
        # honor on its own.
        gip12_context = (
            "As a starting point (not a complete list -- read the full document yourself for more), a "
            f"deterministic keyword scan already found a literal verbal-operant term on these pages: "
            f"{candidate_lines}. Your own citation list should be AT LEAST this long, most likely longer: "
            "read the whole document for every goal naming an operant (mand/tact/intraverbal/echoic) "
            "explicitly OR phrased that way without the literal word (e.g. 'will request...' counts as "
            "mand-shaped)."
        )
        rules_by_id = {**rules_by_id, "QA-GIP-12": {**rules_by_id["QA-GIP-12"], "extra_context": gip12_context}}
        applicable_rules = [
            rules_by_id["QA-GIP-12"] if r["rule_id"] == "QA-GIP-12" else r for r in applicable_rules
        ]
    return gip12_candidates, applicable_rules, rules_by_id


def _inject_hrs09_schedule_page_context(
    extracted_fields: dict, applicable_rules: list[dict], rules_by_id: dict[str, dict],
) -> tuple[list[dict], dict[str, dict]]:
    """QA-HRS-09 real fix (Round 20, 2026-10-09) -- see
    fields_module.hrs09_schedule_section_pages's own docstring for the
    real gap this closes. Same forced-additional-context convention as
    _inject_gip12_candidate_context above (and must be wired into BOTH
    orchestration paths for the same reason that function's own docstring
    documents -- this was found and fixed once before for a different
    rule, so both call sites are updated together here from the start).
    """
    schedule_pages = fields_module.hrs09_schedule_section_pages(extracted_fields)
    if schedule_pages and "QA-HRS-09" in rules_by_id:
        pages_str = ", ".join(str(p) for p in schedule_pages)
        hrs09_context = (
            f"A deterministic scan already found this document's own 'School and ABA Schedule' grid -- "
            f"the primary source for any schedule-overlap finding -- on page(s) {pages_str}. If your "
            f"finding is based on, or cites, the School and ABA Schedule, your own page citation must "
            f"include {pages_str} alongside any other page you cite; do not cite only a different section."
        )
        rules_by_id = {**rules_by_id, "QA-HRS-09": {**rules_by_id["QA-HRS-09"], "extra_context": hrs09_context}}
        applicable_rules = [
            rules_by_id["QA-HRS-09"] if r["rule_id"] == "QA-HRS-09" else r for r in applicable_rules
        ]
    return applicable_rules, rules_by_id


def _inject_hrs10_generic_rationale_context(
    extracted_fields: dict, applicable_rules: list[dict], rules_by_id: dict[str, dict],
) -> tuple[list[dict], dict[str, dict]]:
    """QA-HRS-10 real fix (Round 20, 2026-10-09) -- see
    fields_module.hrs10_generic_rationale_flags's own docstring. Same
    forced-additional-context convention as the two injectors above;
    wired into both orchestration paths from the start for the same
    reason.
    """
    flags = fields_module.hrs10_generic_rationale_flags(extracted_fields)
    if flags and "QA-HRS-10" in rules_by_id:
        flag_lines = "; ".join(
            f"{f['code']}-{f['desc']} changed from {f['old_hours']} to {f['new_hours']} hours (page "
            f"{f['page'] if f['page'] is not None else '?'}), but a deterministic scan found its "
            f"nearby rationale text contains neither the old nor new hour figure, nor any "
            f"increase/decrease/change language referencing a number"
            for f in flags
        )
        hrs10_context = (
            f"A deterministic scan already found the following likely-generic rationale(s): {flag_lines}. "
            "Do not count a rationale as adequate just because it describes what the CPT code is for "
            "in general (e.g. generic language about what supervision/treatment accomplishes) -- it "
            "must specifically reference the magnitude of THIS change (the actual old/new numbers, or "
            "language tied to this specific increase/decrease) to pass. If, on reading the full "
            "document yourself, you find real magnitude-specific language the scan above missed, you "
            "may still pass it -- this is a floor to check against, not an automatic fail."
        )
        rules_by_id = {**rules_by_id, "QA-HRS-10": {**rules_by_id["QA-HRS-10"], "extra_context": hrs10_context}}
        applicable_rules = [
            rules_by_id["QA-HRS-10"] if r["rule_id"] == "QA-HRS-10" else r for r in applicable_rules
        ]
    return applicable_rules, rules_by_id


def _inject_ai05_spelling_inconsistency_context(
    extracted_fields: dict, applicable_rules: list[dict], rules_by_id: dict[str, dict],
) -> tuple[list[dict], dict[str, dict]]:
    """QA-AI-05 real fix (Round 20, 2026-10-09) -- see
    fields_module.doubled_letter_spelling_inconsistencies's own docstring
    for the real, generalized (not hard-coded) detection this uses. Same
    forced-additional-context convention as the injectors above.
    """
    flags = fields_module.doubled_letter_spelling_inconsistencies(extracted_fields)
    if flags and "QA-AI-05" in rules_by_id:
        flag_lines = "; ".join(
            f"{' / '.join(f['spellings'])!r} (pages {f['pages']})" for f in flags
        )
        ai05_context = (
            f"A deterministic scan already found the same word spelled inconsistently (a doubled-letter "
            f"typo class -- one occurrence has an extra or missing doubled letter compared to another "
            f"occurrence of the same word elsewhere in this document) in: {flag_lines}. Include these as "
            f"real spelling errors in your findings alongside anything else you find yourself."
        )
        rules_by_id = {**rules_by_id, "QA-AI-05": {**rules_by_id["QA-AI-05"], "extra_context": ai05_context}}
        applicable_rules = [
            rules_by_id["QA-AI-05"] if r["rule_id"] == "QA-AI-05" else r for r in applicable_rules
        ]
    return applicable_rules, rules_by_id


def _inject_bip0910_spelling_normalization_context(
    extracted_fields: dict, applicable_rules: list[dict], rules_by_id: dict[str, dict],
) -> tuple[list[dict], dict[str, dict]]:
    """QA-BIP-09/QA-BIP-10 real fix, part 1 of 2 (Round 20, 2026-10-09):
    reuses fields_module.doubled_letter_spelling_inconsistencies (built
    for QA-AI-05 above, same round) to tell the judgment call explicitly
    that two differently-spelled occurrences are the SAME real behavior
    name, so matching a BIP entry to its goal (BIP-09) or comparing their
    baseline/current numbers (BIP-10) isn't tripped up by the same
    "Aggression"/"Agression" class of real document typo already fixed
    for the deterministic QA-BIP-08 in Round 19.

    IMPORTANT, stated plainly rather than left implicit: both rule_ids
    are CURRENTLY on STABILIZED_UNCERTAIN_RULE_IDS (see that set's own
    definition above), which means the real judgment call for them is
    never actually made at all right now -- this context has zero live
    effect until/unless they come off that list. This is intentionally
    built now so the normalization already exists the moment a real,
    measured stability re-test (part 2 -- requires real, billed API
    calls, not run without explicit per-instance approval, per this
    project's standing cost-approval rule) confirms it's safe to
    un-stabilize them. Do not treat this function's mere existence as
    proof the underlying instability is fixed -- it is not yet verified.
    """
    flags = fields_module.doubled_letter_spelling_inconsistencies(extracted_fields)
    if not flags:
        return applicable_rules, rules_by_id
    flag_lines = "; ".join(f"{' / '.join(f['spellings'])!r} (pages {f['pages']})" for f in flags)
    context = (
        f"A deterministic scan found the same real behavior/term spelled two different ways "
        f"elsewhere in this document (a doubled-letter typo, not two different things): "
        f"{flag_lines}. Treat these spellings as the SAME behavior/goal when matching a BIP entry "
        f"to its corresponding goal, or comparing baseline/current data between them -- do not "
        f"conclude a BIP or goal is missing, or numbers don't match, just because of this spelling "
        f"difference alone."
    )
    for rid in ("QA-BIP-09", "QA-BIP-10"):
        if rid in rules_by_id:
            rules_by_id = {**rules_by_id, rid: {**rules_by_id[rid], "extra_context": context}}
            applicable_rules = [rules_by_id[rid] if r["rule_id"] == rid else r for r in applicable_rules]
    return applicable_rules, rules_by_id


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

    # QA-GIP-12 real fix (Round 6, Zaith 9-2026-U1; extracted into its own
    # shared helper in Round 13 -- see that function's own docstring for
    # why): two-pass hybrid, Pass 2 -- feed Pass 1's deterministic
    # literal-verbal-operant-term page scan into the judgment call as
    # forced additional context.
    gip12_candidates, applicable_rules, rules_by_id = _inject_gip12_candidate_context(
        extracted_fields, applicable_rules, rules_by_id,
    )
    applicable_rules, rules_by_id = _inject_hrs09_schedule_page_context(
        extracted_fields, applicable_rules, rules_by_id,
    )
    applicable_rules, rules_by_id = _inject_hrs10_generic_rationale_context(
        extracted_fields, applicable_rules, rules_by_id,
    )
    applicable_rules, rules_by_id = _inject_ai05_spelling_inconsistency_context(
        extracted_fields, applicable_rules, rules_by_id,
    )
    applicable_rules, rules_by_id = _inject_bip0910_spelling_normalization_context(
        extracted_fields, applicable_rules, rules_by_id,
    )

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
        judgment_results[rule_id] = _stabilized_uncertain_finding(rule_id, extracted_fields)

    # Round 7 real fix (QA-GIP-12 regression): real evidence showed the
    # two-pass design (built last round) making things WORSE, not better
    # -- page coverage went from 7 pages to 5, all 5 a SUBSET of the
    # original 7. Root cause: Pass 1's candidate list was only ever
    # HANDED to the judge as a prompt instruction ("treat this as a
    # floor") and trusted to be honored -- nothing in code actually
    # enforced it. A model given a specific, confidently-worded candidate
    # list can anchor on it and stop looking further instead of treating
    # it as a floor, which is exactly consistent with the real symptom
    # (the final page list shrank toward Pass 1's own candidates instead
    # of growing to their union with judgment's own independent read).
    # Fixed by making the floor a real, code-enforced guarantee instead
    # of a prompt request: after judgment returns, union any Pass-1
    # candidate page judgment didn't already cite back into the result.
    # This can only ADD real, deterministically-sourced pages -- it can
    # never remove one judgment found on its own, so this is strictly a
    # floor, not a ceiling, by construction rather than by asking the
    # model nicely.
    if "QA-GIP-12" in judgment_results:
        judgment_results["QA-GIP-12"] = _merge_gip12_candidate_pages(
            judgment_results["QA-GIP-12"], gip12_candidates, fields=extracted_fields,
        )

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
        # Fix Round 17 (2026-10-06) -- REAL BUG FOUND AND FIXED on a live
        # zaith_new.pdf production run: integrity.py's own
        # reconcile_page_citation (Round 15) runs INSIDE
        # run_judgment_with_integrity_check, which returns BEFORE this
        # escalation merge -- so a real correction it made to
        # judgment_results[rule_id]["page"] could be silently overwritten
        # by the det-layer-page-wins override directly above (confirmed
        # real case: QA-SCH-06's det checker returns an off-topic page
        # alongside its own escalating "uncertain" verdict, which then
        # overwrote judgment's already-corrected page right back to the
        # wrong one). Calling it again here, on the FINAL merged finding
        # after this override has already run, means it always has the
        # last word regardless of which layer's page won -- not just a
        # pre-merge interim result downstream code can still overwrite.
        merged = integrity.reconcile_page_citation(merged, fields=extracted_fields)
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
