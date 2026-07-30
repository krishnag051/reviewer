"""Standing regression harness against Ms. Yachnes's confirmed real-document
answers (2026-07-28 round, item 4).

Every round so far has required manually diffing a CSV export against the
human reviewer's own review to check whether a fix actually worked. This
file turns every rule_id where we already have a confirmed ground-truth
answer -- on Reeda's and/or Charny's real TP -- into a permanent, automated
assertion, so a future round doesn't have to re-derive "does this still
work" by hand.

Two tiers, run separately:

1. Every rule_id now check_type "deterministic" (GIP-10, GIP-16, TEMP-01,
   PPI-02, PPI-03, PPI-05, BIP-01, GIP-03, HRS-06, ACF-07 as of the
   2026-07-28 round-3 item-1/2/4 conversions) -- calls the checker function
   directly against extracted fields, NO live API call, NO cost, runs as
   part of the normal fast suite. This is the ideal shape for a
   ground-truth test: exact, free, deterministic. This tier grows every
   time a rule moves from judgment to deterministic -- that's the payoff
   the user asked for explicitly: "these become free, permanent test cases
   since they're deterministic now, no API cost."

2. Every other rule_id below is check_type "judgment" -- ground truth here
   can only be confirmed by actually running the live judgment layer, which
   costs a real, billed API call every time this file runs. These are
   marked @pytest.mark.skipif on HAS_ANTHROPIC_CREDENTIALS (same convention
   as test_regression_snapshot.py) and scoped to ONLY the rule_ids with
   confirmed ground truth per document (not all 120 rules), to keep the
   cost of running this file bounded and visible rather than an accidental
   full-pipeline run.

   COST NOTE: unlike the rest of this suite, the live tests below are NOT
   free to run. Each document's test is one run_full_pipeline call scoped
   to a handful of rule_ids -- on the order of $0.05-$0.15 per document per
   run at current Sonnet 5 pricing (see pipeline/call_tracker.py). Running
   this on every commit would add real, recurring cost for marginal signal
   beyond the fast deterministic tier; running it periodically (e.g. before
   a release, or after any change that touches judge.py's prompt or a
   judgment rule's notes) is the better tradeoff. Not wired into CI as an
   always-on gate for that reason -- a human decision to run it, same as
   test_regression_snapshot.py's live counterpart.

GROUND TRUTH PROVENANCE: every rule_id/expected-result pair below traces to
either (a) the user's own confirmed real-failure list from this round's
"missed fails" evidence (verbatim in this round's own request), or (b) a
live-verified deterministic conversion (GIP-10, and as of round 3: GIP-16,
TEMP-01, PPI-02, PPI-03, PPI-05, BIP-01, GIP-03, HRS-06, ACF-07). Three
entries are deliberately EXCLUDED below (QA-BIP-05, QA-PAR-01, QA-BIO-16)
-- see the note next to DISPUTED_NOT_SEEDED for each one's specific reason.
"""
import json
import os
from pathlib import Path

import pytest

from pipeline import fields as fields_module
from pipeline import run_full_pipeline
from pipeline.extract import extract_pdf_text
from pipeline.flag_pages import flag_image_only_pages

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
RULES_BY_ID = {r["rule_id"]: r for r in RULES}

HAS_ANTHROPIC_CREDENTIALS = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))

# --- Tier 1: deterministic rules, free, always run, no live call ----------

# rule_id -> {fixture_name: expected_result}. Every entry confirmed live
# against the real documents this round (2026-07-28, round 3) before being
# seeded here -- see each checker's own docstring in pipeline/fields.py for
# the specific verification detail.
DET_GROUND_TRUTH = {
    "QA-GIP-10": {
        "reeda_tp_pdf": "fail",   # page 32 'Precent correct', page 37 'Page', page 52 'percentage correct'
        "charny_tp_pdf": "fail",  # page 27, blank Mastery Criteria on a Frequency-sampled goal
    },
    "QA-GIP-16": {
        "reeda_tp_pdf": "fail",   # page 26 Tantrum + page 27 Elopement, both 'Target Name:' blocks
        "charny_tp_pdf": "pass",  # one goal reads '0-2 occurrences...', a range, not a zero endpoint
    },
    "QA-TEMP-01": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},  # 'BCBA, LBA' consistent on both
    "QA-PPI-02": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},   # DOB/Age consistent + age-correct on both
    "QA-PPI-03": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},   # patient name spelled consistently on both
    "QA-PPI-05": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},   # single NPI/License, trivially consistent
    "QA-BIP-01": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},   # at least one Moderate+ rating on both
    "QA-GIP-03": {"reeda_tp_pdf": "pass", "charny_tp_pdf": "pass"},   # shares BIP-01's checker
    # RESOLVED (2026-07-28, item 2 then a same-day follow-up round):
    # QA-HRS-06 was originally assumed "fail" on BOTH documents (this
    # round's "missed fails" evidence list). The FIRST conversion attempt
    # (increase-vs-previous-auth-hours only) found NEITHER document
    # supported "fail" under that literal scope -- Reeda's one real
    # increase (97151-Assessment, 5->8 hrs) has rationale present; Charny
    # has no CPT code increase anywhere. That pointed at the real mechanism
    # instead: an embedded, unresolved reviewer annotation questioning
    # hours (flat, in both real cases) -- the same shape as QA-TRANS-01,
    # confirmed in two different structural slots (Charny: a full question
    # in the rationale slot -- "Why are hours remaining the same?... I
    # would add a plan for titration"; Reeda: short interjections in the
    # gap before the code label -- "Verifying", "Change if increasing").
    # Added as a second sub-check under this same rule_id (see
    # pipeline/fields.py::_check_HRS06's docstring) -- both documents now
    # correctly come back fail, confirming the ORIGINAL "fail" assumption
    # after all, just via a different real mechanism than first assumed.
    "QA-HRS-06": {"reeda_tp_pdf": "fail", "charny_tp_pdf": "fail"},
    # QA-ACF-07: diagnosed as a real bug (item 4) and fixed -- both
    # documents now correctly come back fail (Charny: entire ACF section
    # blank; Reeda: Vineland-3 present with no confirmed administration
    # date). This DOES confirm the original "fail" assumption on both.
    "QA-ACF-07": {"reeda_tp_pdf": "fail", "charny_tp_pdf": "fail"},
    # Follow-up round, item 1: fixes a confirmed regression (this rule's
    # judgment-only behavior had narrowed to only recognizing email-header
    # text) -- see pipeline/fields.py::_check_TEMP04's docstring. Both
    # documents have many confirmed embedded reviewer comments (8 each).
    "QA-TEMP-04": {"reeda_tp_pdf": "fail", "charny_tp_pdf": "fail"},
}

_DET_GROUND_TRUTH_CASES = [
    (rule_id, fixture_name, expected)
    for rule_id, per_doc in DET_GROUND_TRUTH.items()
    for fixture_name, expected in per_doc.items()
]


@pytest.mark.parametrize("rule_id,fixture_name,expected", _DET_GROUND_TRUTH_CASES)
def test_det_ground_truth(request, rule_id, fixture_name, expected):
    pdf_path = request.getfixturevalue(fixture_name)
    pages = extract_pdf_text(pdf_path)
    pages = flag_image_only_pages(pages)
    extracted_fields = fields_module.extract_fields(pdf_path, pages)
    checker = fields_module.DET_CHECKS[rule_id]
    result, evidence, page, confidence = checker(RULES_BY_ID[rule_id], extracted_fields)
    assert result == expected, f"{rule_id} on {fixture_name}: expected {expected!r}, got {result!r} ({evidence!r})"


# --- Tier 2: judgment-layer rules, live, costs real money -----------------

# Confirmed real "fail" that production's 2-call self-consistency missed,
# from this round's own evidence list. Every one of these has since been
# re-confirmed at least once this round (via the majority-vote probe or the
# notes-fix probe) as coming back "fail" on live Sonnet 5.
#
# QA-HRS-06 and QA-ACF-07 REMOVED from here (2026-07-28, round 3, items 2
# and 4): both converted to check_type "deterministic" this round -- see
# DET_GROUND_TRUTH above, which seeds their real (and for HRS-06, revised)
# ground truth instead. Leaving them here too would mean asserting the same
# rule_id's result twice via two different mechanisms -- and for HRS-06,
# the live/deterministic answers actually disagree (see the note above),
# so keeping both would silently assert something no longer believed true.
REEDA_JUDGMENT_GROUND_TRUTH = {
    "QA-TEMP-03": "fail",
    "QA-BIO-07": "fail",
    "QA-HRS-07": "fail",
    "QA-HRS-09": "fail",
    "QA-GIP-06": "fail",
}
CHARNY_JUDGMENT_GROUND_TRUTH = {
    "QA-HRS-09": "fail",
    "QA-SCH-07": "fail",
    "QA-PROB-01": "fail",
    "QA-ACF-02": "fail",
    "QA-GIP-06": "fail",
    "QA-GIP-07": "fail",
    "QA-GIP-11": "fail",
    "QA-GIP-17": "fail",
}

# DISPUTED, deliberately NOT seeded: QA-BIP-05 (Reeda) and QA-PAR-01
# (Charny) are the two rules item 2/3 could NOT get to a confirmed "fail"
# across three separate fix attempts (a notes rewrite, a system-level
# posture instruction, and a two-stage extract-then-judge split) -- all
# three attempts came back "pass" on live Sonnet 5. For QA-PAR-01/Charny
# specifically, this round's two-stage extraction step surfaced a further
# complication: it found THREE current "Parent/Caregiver Goals:" entries
# (page 45-47: "Mother will prompt..." x3), not the ONE this round initially
# assumed from an earlier, incomplete manual grep -- which would actually
# satisfy the rule's "3+" requirement. Whether these two rules are still
# real misses, or whether the original "confirmed fail" premise itself
# needs re-checking against the human reviewer's own stated reason, is
# unresolved. Asserting "fail" here would risk locking in a wrong answer as
# permanent ground truth; leaving them out is the honest choice until that's
# settled.
#
# QA-BIO-16 added to this set (2026-07-28, round 3, item 3): its own notes
# already said "out of scope - no live Central Reach integration in V1,"
# and this round confirmed why directly against real evidence rather than
# assuming it. Neither real document shows a genuine SELF-CONTAINED school-
# name contradiction: Reeda's TP narrates a past school ("HeartShare
# School") transitioning to a current one ("District 75... P.S. Q4") --
# ordinary history, not a conflict; Charny's formal 'School Name:' field
# reads 'N/A', which is plausibly correct given she "recently graduated
# from high school" per the same document's own narrative, not a visible
# contradiction either. A human reviewer with real Central Reach access
# could still see (and correctly flag) a genuine CR/TP mismatch neither
# real document demonstrates from its own text -- that's fully consistent
# with "genuinely undetectable without CR access," not a bug in this
# system. Confirmed live this round: production comes back not_applicable
# on Reeda, matching this conclusion, not contradicting it. Asserting
# "fail" here would lock in an unverifiable answer as permanent ground
# truth.
DISPUTED_NOT_SEEDED = {"QA-BIP-05", "QA-PAR-01", "QA-BIO-16"}


def _judgment_results(pdf_path: str, rule_ids: list[str]) -> dict[str, str]:
    rules = [RULES_BY_ID[rid] for rid in rule_ids]
    result = run_full_pipeline(pdf_path, rules)
    return {rule_id: entry["result"] for rule_id, entry in result["findings"].items()}


@pytest.mark.skipif(not HAS_ANTHROPIC_CREDENTIALS, reason="No Anthropic credentials configured in this environment.")
def test_reeda_judgment_ground_truth(reeda_tp_pdf):
    actual = _judgment_results(reeda_tp_pdf, list(REEDA_JUDGMENT_GROUND_TRUTH))
    mismatches = {
        rid: {"expected": expected, "actual": actual.get(rid)}
        for rid, expected in REEDA_JUDGMENT_GROUND_TRUTH.items()
        if actual.get(rid) != expected
    }
    assert not mismatches, f"Reeda ground-truth mismatch(es): {mismatches}"


@pytest.mark.skipif(not HAS_ANTHROPIC_CREDENTIALS, reason="No Anthropic credentials configured in this environment.")
def test_charny_judgment_ground_truth(charny_tp_pdf):
    actual = _judgment_results(charny_tp_pdf, list(CHARNY_JUDGMENT_GROUND_TRUTH))
    mismatches = {
        rid: {"expected": expected, "actual": actual.get(rid)}
        for rid, expected in CHARNY_JUDGMENT_GROUND_TRUTH.items()
        if actual.get(rid) != expected
    }
    assert not mismatches, f"Charny ground-truth mismatch(es): {mismatches}"


def test_disputed_rules_are_not_silently_seeded_anywhere():
    """Guards against a future edit accidentally adding QA-BIP-05/QA-PAR-01
    back into one of the ground-truth dicts above without deliberately
    resolving the dispute noted next to DISPUTED_NOT_SEEDED first."""
    for rid in DISPUTED_NOT_SEEDED:
        assert rid not in REEDA_JUDGMENT_GROUND_TRUTH
        assert rid not in CHARNY_JUDGMENT_GROUND_TRUTH
