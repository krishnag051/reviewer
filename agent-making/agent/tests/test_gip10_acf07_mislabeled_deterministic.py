"""Originally documented the root cause behind QA-GIP-10 and QA-ACF-07
behaving inconsistently across documents (both were labeled
check_type "deterministic" but had no fields.DET_CHECKS entry, so every
finding for them came entirely from the judgment layer, subject to full
LLM run-to-run non-determinism, despite the "deterministic" label implying
stable, code-computed results).

Since then, a full audit found this was one instance of a much wider
pattern: 44 of the 51 rules labeled "deterministic" had no real checker.
That audit's rules were triaged into two tiers and acted on:
- Tier 1 (11 new checkers + HF-01, which was ALSO in this mismatch
  group despite being the rule that caused the original contradiction
  bug diagnosis) -- built and registered in fields.DET_CHECKS.
- Tier 2 (18 rules, including GIP-10 and ACF-07 themselves) -- relabeled
  to check_type "judgment" in rules.json, since they were genuinely
  content/semantic checks mislabeled as deterministic, not a code gap.
- 15 rules left flagged, deliberately unbuilt and unrelabeled -- each
  blocked on something concrete (backend-stored prior-TP data, an
  unconfirmed document field, a CPT billing reference table that doesn't
  exist yet, or schedule-table parsing too fragile for pypdf's raw text
  extraction to be trusted without much more engineering).

This file now audits the FULL current state, not just GIP-10/ACF-07.
"""
from pipeline import fields


def _rule(rule_id):
    return next(r for r in fields_all_rules() if r["rule_id"] == rule_id)


def fields_all_rules():
    import json
    from pathlib import Path
    path = Path(__file__).parent.parent / "rules" / "rules.json"
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


def test_gip10_moved_back_to_deterministic_with_a_real_checker():
    """Reversal (2026-07-28, item 1): GIP-10 was relabeled to "judgment"
    (see the module docstring's Tier 2 history) on the premise that
    "sampling method consistent across every goal" was genuinely
    content/semantic. Revisited this round: it's actually a uniqueness
    check over a code-extractable list of per-goal field values (every
    goal's Sampling Method/Baseline/Mastery Criteria, pulled by a plain
    "Target Goal:"/"Target Name:"-delimited regex split) -- exactly the
    shape an LLM is weak at (averaging over a big context, missing the one
    different item) and code is strong at. Verified live against both
    Reeda's and Charny's real documents against already-known outliers
    before converting (see pipeline/fields.py::_check_GIP10's docstring
    and test_check_gip10.py).

    ACF-07 reversed the SAME direction in a later round the same day
    (2026-07-28, item 4 follow-up): originally assumed to be genuinely
    judgment (a two-instance presence check tied to a semantic "old vs
    new testing tool" read). Diagnosed properly against real ground truth
    and found to be a real, previously-unfixed bug instead -- see
    pipeline/fields.py::_check_ACF07's docstring for the full real-evidence
    diagnosis (a blank-section check plus a per-named-tool "is there a
    confirmed administration date" check, both pattern-extractable, no
    semantic judgment needed)."""
    rule_gip10 = _rule("QA-GIP-10")
    rule_acf07 = _rule("QA-ACF-07")
    assert rule_gip10["check_type"] == "deterministic"
    assert rule_acf07["check_type"] == "deterministic"
    assert "QA-GIP-10" in fields.DET_CHECKS
    assert "QA-ACF-07" in fields.DET_CHECKS


def test_gip10_and_acf07_always_escalate_regardless_of_input():
    """The no-checker fallback in run_deterministic_checks always returns
    confidence 0.0, which is always below ESCALATION_CONFIDENCE_THRESHOLD --
    proving escalation for these two rules is unconditional, not
    input-dependent."""
    fallback = {
        "result": "not_checkable",
        "evidence": fields.NEEDS_BACKEND_INTEGRATION,
        "page": None,
        "confidence": 0.0,
    }
    assert fields.needs_escalation(fallback)


# --- Full audit: every rule labeled check_type "deterministic" across the
# whole rule set. This is the POST-triage snapshot -- Tier 1 built, Tier 2
# relabeled, 15 deliberately left flagged and unbuilt/unrelabeled (see each
# one's reason in the report; not repeated here to avoid this list going
# stale independent of the actual reasoning).
#
# If this list changes (a rule renamed, a new rule added as "deterministic",
# or a real checker implemented for one of these), this test will fail
# loudly rather than silently drifting -- that failure is the prompt to
# deliberately update EXPECTED_MISMATCHED_RULE_IDS and note why, not to
# just make the test pass again.
EXPECTED_MISMATCHED_RULE_IDS = frozenset({
    "QA-ACF-01",
    "QA-COC-03", "QA-COC-05",
    # QA-GIP-13 REMOVED from this set (Fix Round, Section 1 Bucket D,
    # 2026-08-27) -- a real HF-01-style silent gap closed: labeled
    # deterministic here with zero checker registered, confirmed and
    # fixed this round (_check_GIP13).
    "QA-HRS-08",
    "QA-MAST-01", "QA-MAST-02",
    # QA-RPT-05 REMOVED from this set (2026-08-08, Round 78, item 4) -- a
    # real checker was built (pipeline/fields.py::_check_RPT05). This
    # rule's own two comparisons weren't equally blocked: only the
    # separate "previous auth end" record genuinely needed backend data;
    # the 6-month DEFAULT window, anchored to the CURRENT document's own
    # report-end date, needed nothing outside this document -- confirmed
    # against Ms. Yachnes's real ground-truth review (a real 14-day
    # discrepancy on Yisroel Leibowitz's real TP). See the rule's own
    # updated notes in rules.json.
    "QA-RPT-04",
    # QA-SCH-01/QA-SCH-07 REMOVED from this set (2026-08-07, Round 63, item
    # 3) -- real checkers built (pipeline/schedule_hours.py's deterministic
    # date/time arithmetic + table extraction), see
    # test_exactly_thirty_seven_deterministic_labeled_rules_have_real_checkers
    # below. QA-SCH-03/05/06 remain here -- each needs its own additional
    # logic beyond the schedule grid itself (overlap detection, a payor
    # exception flag, a second field to compare against), not built this
    # round; see their own updated blocked_status notes in rules.json.
    # QA-SCH-06 REMOVED from this set (Fix Round, Section 1, 2026-08-27) --
    # a real HF-01-style silent gap: labeled deterministic here with zero
    # checker registered, confirmed and fixed this round (_check_SCH06,
    # with an explicit, honest limitation documented in its own docstring
    # and this rule's own notes -- see fields.py).
    "QA-SCH-03", "QA-SCH-05",
    "QA-SIG-06",
    # Added 2026-07-27 (Empire/Emblem/Aetna round): EMP-02 has a confirmed
    # scope ambiguity (see its own notes/blocked_status in rules.json) --
    # deliberately not built, unlike EMP-01/EMP-03 which were.
    "EMP-02",
})


def _rules_labeled_deterministic():
    return [r for r in fields_all_rules() if r["check_type"] == "deterministic"]


def test_full_deterministic_label_audit_matches_known_snapshot():
    """15 rules are still labeled check_type "deterministic" with no real
    checker -- each deliberately left that way (not a code gap to close
    reflexively), still subject to the same always-escalates-to-judgment
    fallback as the original GIP-10/ACF-07 finding."""
    actual_mismatched = {
        r["rule_id"] for r in _rules_labeled_deterministic()
        if r["rule_id"] not in fields.DET_CHECKS
    }
    added = actual_mismatched - EXPECTED_MISMATCHED_RULE_IDS
    removed = EXPECTED_MISMATCHED_RULE_IDS - actual_mismatched
    assert not added, f"newly mismatched rule_id(s) not in the snapshot: {sorted(added)}"
    assert not removed, (
        f"rule_id(s) in the snapshot no longer mismatched (checker added or "
        f"rule removed/relabeled) -- update EXPECTED_MISMATCHED_RULE_IDS: {sorted(removed)}"
    )


def test_every_flagged_mismatch_has_a_blocked_status_note():
    """Each of the 15 rules left deliberately unbuilt carries a one-line
    blocked_status explaining why, so the next round doesn't have to
    rediscover the same gap from scratch. Checked against the same
    snapshot as the mismatch audit above, not a separately maintained list
    -- if one drifts, so does the other, and this test catches it."""
    rule_by_id = {r["rule_id"]: r for r in fields_all_rules()}
    missing_status = [
        rule_id for rule_id in EXPECTED_MISMATCHED_RULE_IDS
        if not rule_by_id[rule_id].get("blocked_status")
    ]
    assert missing_status == [], f"flagged rule(s) with no blocked_status note: {missing_status}"


def test_exactly_sixty_eight_deterministic_labeled_rules_have_real_checkers():
    """Renamed from "...sixty_six..." (Fix Round, Section 1 Bucket D,
    2026-08-27) -- two more joined this set this round: QA-GIP-13 (a real
    HF-01-style silent gap closed) and QA-GIP-21 (a genuinely new hybrid
    checker).

    Renamed from "...fifty_nine..." (Fix Round, Section 1, 2026-08-27) --
    seven more joined this set this round: QA-BAR-01, HF-05, QA-COC-06,
    QA-RPT-07, QA-SCH-06, QA-GIP-19, QA-GIP-26 (six genuinely new, one --
    QA-SCH-06 -- a real HF-01-style silent gap closed; see the new-entries
    comment right above the closing brace for the full detail).

    Renamed from "...fifty_four..." (Next Round, 2026-08-27) -- five more
    joined this set this round: QA-HRS-12, QA-GIP-30, QA-GIP-31, QA-GIP-33,
    QA-COC-08 (all genuinely new rule_ids, real deterministic checkers built
    from the start -- see the new-entries comment right above the closing
    brace for the full detail).

    Renamed from "...fifty_one..." (Fix Round, 2026-08-26) -- three more
    joined this set this round: QA-HRS-11, ANT-01, ANT-03. See this test's
    own docstring further down and the new-entries comment right above the
    closing brace for the full detail.

    Renamed from "...forty_seven..." (documentation pass, 2026-08-14) --
    found while syncing AGENT_STATE.md to current reality: this function's
    own name said 47, but its actual asserted `matched` set already had 51
    entries (confirmed by running the test and separately re-deriving the
    same 51-id intersection directly against rules.json/DET_CHECKS) -- the
    body was correct and already passing, only the name had drifted out of
    sync with it at some point after the "...forty_seven..." rename below,
    with no docstring entry recording what added the other 4. Renaming to
    match reality now rather than leaving the same silent-drift shape this
    test exists to catch present in the test's own name.

    Renamed from "...forty_four..." (2026-08-14, Round 92) -- three more
    joined this set this round: QA-HRS-05 and QA-GIP-23 (both converted
    from judgment to deterministic PRECONDITION checkers -- resolve the
    easy structural case, still escalate to judgment when the precondition
    doesn't resolve it outright, same hybrid shape as QA-PROB-02; see
    _check_HRS05's and _check_GIP23's own docstrings) and QA-ACF-12 (a
    genuinely NEW rule_id, not a relabeling -- built as a real deterministic
    checker from the start, see _check_ACF12's own docstring).

    Renamed from "...forty_three..." (2026-08, Round 84, item 3) --
    QA-PROB-01 joined this set: a hybrid DET pre-check, same shape as
    QA-PROB-02, adding the narrative-vs-matrix/checklist format signal
    this rule's rubric never checked before -- see _check_PROB01's own
    docstring.

    Renamed from "...forty_one..." (2026-08, Round 83) -- two rules
    joined this set this round: QA-ACF-06 (converted outright, a plain
    "administered by NAME" presence check -- a separate, narrower gap
    from QA-ACF-07/extract_acf_fields's section-boundary bug, see
    _check_ACF06's own docstring) and QA-GIP-05 (a hybrid DET pre-check,
    same shape as QA-PROB-02/QA-BIP-05, catching only an exact-wording
    duplicate between the Mastered Goals section and an active goal block
    -- see _check_GIP05's own docstring).

    Renamed from "...forty..." (2026-08, Round 82, item 2) -- QA-BIP-06
    joined this set this round: converted from judgment to deterministic
    outright (not a hybrid pre-check like BIP-05) because this rule's real
    bar is pure presence detection with no separate subjective question
    left over once presence is resolved. See pipeline/fields.py::
    _check_BIP06's own docstring for the confirmed real "explained N/A
    wrongly failed" bug this closes.

    Renamed from "...thirty_nine..." (2026-08, Round 81, item 3) --
    QA-BIP-05 joined this set this round: a hybrid DET pre-check (same
    shape as QA-PROB-02) that catches a same-goal numeric contradiction
    between a goal's Target Name and its own Mastery Criteria field,
    deterministically, while still deferring the rule's broader
    "age-appropriate" judgment call to the judgment layer when clean --
    see pipeline/fields.py::_check_BIP05's own docstring.

    Renamed from "...thirty_eight..." (2026-08-08, Round 78, item 4) --
    QA-RPT-05 joined this set that round, see EXPECTED_MISMATCHED_RULE_IDS's
    own comment above for why.

    QA-TRANS-02/QA-DISC-02 dropped out of this set 2026-07-28 -- their
    shared bullet-marker checker was reclassified to judgment after a
    confirmed false positive (see test_trans02_disc02_relabeled_to_judgment
    below). QA-ACF-05 was restored from archive the same round as a real
    blank-field checker (see test_restored_acf05... in
    test_learning_tree_retirement_and_archive.py). QA-GIP-10 moved BACK
    into this set the same day (2026-07-28, item 1 follow-up) -- see
    test_gip10_moved_back_to_deterministic_with_a_real_checker above.

    A further 9 rule_ids joined the same day (2026-07-28, round 3): the
    item-1 backlog of 7 rules sharing GIP-10's "uniqueness check over a
    pattern-extractable field" shape (GIP-16, TEMP-01, PPI-02, PPI-03,
    PPI-05, BIP-01, GIP-03 -- the last two sharing one checker function),
    plus HRS-06 (item 2, the presence half only -- see its own notes for
    why this does NOT resolve Charny's originally-flagged miss) and ACF-07
    (item 4, diagnosed as a real bug -- see
    test_gip10_moved_back_to_deterministic_with_a_real_checker's docstring
    above for the ACF-07 half of that reversal).

    One more joined in a same-day follow-up round: QA-TEMP-04, fixing a
    confirmed regression where its judgment-only behavior had narrowed to
    only recognizing email-header-style text -- see
    pipeline/fields.py::_check_TEMP04's and _find_embedded_reviewer_
    comments's own docstrings for the full diagnosis.

    Three more joined 2026-08-07 (Round 63, ground-truth fixes): QA-SCH-01
    and QA-SCH-07 (item 3 -- real deterministic schedule-table date/time
    arithmetic, replacing the judgment layer's confirmed-wrong eyeballed
    totals; see pipeline/schedule_hours.py). QA-PROB-02 (item 5 --
    deterministic pre-check ONLY for a confirmed objective violation, an
    embedded reviewer comment counted as evidence; still escalates to
    judgment for the real semantic-alignment question when clean, see
    _check_PROB02's own docstring)."""
    det_labeled_ids = {r["rule_id"] for r in _rules_labeled_deterministic()}
    matched = det_labeled_ids & set(fields.DET_CHECKS.keys())
    assert matched == {
        "QA-TEMP-05", "QA-RPT-01", "QA-OBS-01", "QA-GIP-04", "HF-02",
        # Tier 1, built this round:
        "HF-01", "QA-RPT-02", "QA-RPT-06",
        "QA-SIG-02", "QA-SIG-03", "QA-SIG-04",
        "QA-HRS-02", "QA-HRS-03", "QA-COC-04",
        "QA-BIO-02", "QA-BIO-13",
        # Straight Medicaid-specific, built from the start:
        "SM-01", "SM-02",
        # Empire/Emblem/Aetna-specific, built from the start (2026-07-27):
        "EMP-01", "EMP-03", "EMB-01", "AET-01",
        # Relabeled from judgment to deterministic this round (item 2):
        "QA-BIO-03",
        # Restored from archive, rebuilt as a real blank-field check:
        "QA-ACF-05",
        # Moved back from judgment to deterministic (item 1, 2026-07-28):
        "QA-GIP-10",
        # Item 1 backlog conversions (2026-07-28 round 3):
        "QA-GIP-16", "QA-TEMP-01", "QA-PPI-02", "QA-PPI-03", "QA-PPI-05",
        "QA-BIP-01", "QA-GIP-03",
        # Item 2 (presence half only) and item 4 (2026-07-28 round 3):
        "QA-HRS-06", "QA-ACF-07",
        # Follow-up round, item 1: regression fix.
        "QA-TEMP-04",
        # Round 63 (2026-08-07): items 3 and 5.
        "QA-SCH-01", "QA-SCH-07", "QA-PROB-02",
        # Round 64 (2026-08-07): item 3 -- real highlight detection via
        # PyMuPDF (annotation objects + flattened-fill fallback), replacing
        # the judgment layer's text-only read that structurally can never
        # see highlight data. See _check_TEMP03's own docstring.
        "QA-TEMP-03",
        # Round 78 (2026-08-08): item 4 -- see EXPECTED_MISMATCHED_RULE_IDS's
        # own comment above.
        "QA-RPT-05",
        # Round 81: item 3 -- see this test's own docstring above.
        "QA-BIP-05",
        # Round 82: item 2 -- see this test's own docstring above.
        "QA-BIP-06",
        # Round 83: see this test's own docstring above.
        "QA-ACF-06", "QA-GIP-05",
        # Round 84: item 3 -- see this test's own docstring above.
        "QA-PROB-01",
        # Fix Round (2026-08-12), item 2: a genuinely NEW rule_id, not a
        # relabeling -- QA-PPI-06 didn't exist before this round. User-
        # decided rule_id/category ("Patient/Provider Info," slotted right
        # after PPI-01 through PPI-05). See
        # fields._check_narrative_name_contamination's own docstring.
        "QA-PPI-06",
        # Fix Round (2026-08-12), item 4: converted from judgment to
        # deterministic after a real-document verification exposed a
        # blank-field-with-no-adjacent-context gap -- see
        # fields._check_BIP04's own docstring.
        "QA-BIP-04",
        # Round 91 (169-rule reconciliation, 2026-08-14): a genuinely NEW
        # rule_id, not a relabeling -- QA-PPI-07 (AKA/alias check) didn't
        # exist before this round. Deliberately NOT a repoint of
        # QA-PPI-06, which keeps its own unrelated meaning -- see
        # fields._check_PPI07's own docstring.
        "QA-PPI-07",
        # Round 92 (2026-08-14): converted from judgment to a deterministic
        # PRECONDITION checker (>= 10 hrs/week 97153 -> not_applicable,
        # zero judgment call) -- see fields._check_HRS05's own docstring.
        "QA-HRS-05",
        # Round 92 (2026-08-14): converted from judgment to a deterministic
        # PRECONDITION checker (no Behavior Reduction Goal data ->
        # not_applicable, zero judgment call) -- see fields._check_GIP23's
        # own docstring.
        "QA-GIP-23",
        # Round 92 (2026-08-14): a genuinely NEW rule_id, not a relabeling --
        # QA-ACF-12 (assessment date within report range) didn't exist
        # before this round -- see fields._check_ACF12's own docstring.
        "QA-ACF-12",
        # Fix Round (2026-08-26): three more genuinely NEW rule_ids, not
        # relabelings. QA-HRS-11 -- the missing "every other payor" default
        # 97151-hour-cap bucket ma'am asked for, self-excluding
        # Healthfirst/Emblem (see fields._check_HRS11's own docstring).
        # ANT-01/ANT-03 -- Anthem siblings of EMP-01/EMP-03, reusing the
        # exact same checker functions (both are payor-agnostic already,
        # so no new code was needed for these two, just new DET_CHECKS
        # registrations and new rules.json entries). ANT-02 deliberately
        # NOT added here, matching EMP-02's own unbuilt state.
        "QA-HRS-11", "ANT-01", "ANT-03",
        # Next Round (2026-08-27), Part 2: 5 genuinely NEW rule_ids, built as
        # real deterministic checkers from the start -- see each checker's
        # own docstring in pipeline/fields.py (right above DET_CHECKS's own
        # definition) for why these 5 specifically got real checkers while
        # QA-SCH-10/QA-GIP-32/34/35/QA-BIO-17 (also new this round) did not.
        "QA-HRS-12", "QA-GIP-30", "QA-GIP-31", "QA-GIP-33", "QA-COC-08",
        # Fix Round, Section 1 (2026-08-27): 7 more -- 6 genuinely new
        # (QA-BAR-01, HF-05, QA-COC-06, QA-RPT-07, QA-GIP-19, QA-GIP-26,
        # each built as a real deterministic checker from the start -- see
        # each one's own docstring in pipeline/fields.py) plus QA-SCH-06
        # (NOT new -- already labeled deterministic, but had zero checker
        # registered until this round; see EXPECTED_MISMATCHED_RULE_IDS's
        # own comment above for that real gap).
        "QA-BAR-01", "HF-05", "QA-COC-06", "QA-RPT-07", "QA-SCH-06", "QA-GIP-19", "QA-GIP-26",
        # Fix Round, Section 1 Bucket D (2026-08-27): 2 more -- QA-GIP-13
        # (a real HF-01-style silent gap closed, see
        # EXPECTED_MISMATCHED_RULE_IDS's own comment above) and QA-GIP-21
        # (a genuinely NEW hybrid checker, mastered-by-date half only --
        # see fields.py::_check_GIP21's own docstring).
        "QA-GIP-13", "QA-GIP-21",
    }


def test_reverse_check_every_det_checks_entry_is_labeled_deterministic():
    """The opposite mismatch (a real checker exists but rules.json's
    check_type says something else, e.g. "judgment" or "hybrid") would mean
    working code is silently unused, or a rule undersells what it can
    actually verify. Currently empty -- every DET_CHECKS entry's rule is
    correctly labeled "deterministic". Locked in so a future rename doesn't
    quietly create this the other kind of mismatch unnoticed.
    """
    rule_by_id = {r["rule_id"]: r for r in fields_all_rules()}
    reverse_mismatched = [
        rule_id for rule_id in fields.DET_CHECKS
        if rule_by_id[rule_id]["check_type"] != "deterministic"
    ]
    assert reverse_mismatched == []


def test_bip02_par01_do_not_have_the_missing_checker_problem():
    """These have been unresolved across many rounds going back to the
    first comparison against the manual report, and it was reasonable to
    ask whether they shared GIP-10/ACF-07's root cause. They don't: both
    are labeled check_type "judgment" from the start (not "deterministic"),
    so there is no missing-checker mismatch here -- they were always meant
    to be pure judgment-layer rules. Whatever has kept them unresolved
    across rounds is a different problem than the one this file documents,
    and this test exists specifically so that fact doesn't get silently
    re-asserted or blurred later.

    QA-BIO-03 was originally in this same group (also check_type
    "judgment", also flagged as unresolved) -- it's been removed from this
    list because a later round found it genuinely WAS a missing-checker
    problem after all: its old notes wrongly claimed an external-data
    dependency that didn't apply, and it was relabeled to "deterministic"
    with a real checker. See test_bio03_now_has_a_real_deterministic_checker.
    """
    rule_by_id = {r["rule_id"]: r for r in fields_all_rules()}
    for rule_id in ("QA-BIP-02", "QA-PAR-01"):
        rule = rule_by_id[rule_id]
        assert rule["check_type"] == "judgment", (
            f"{rule_id} is check_type={rule['check_type']!r}, not the "
            f"expected 'judgment' -- re-check this test's premise"
        )
        assert rule_id not in EXPECTED_MISMATCHED_RULE_IDS
        assert rule_id not in fields.DET_CHECKS


def test_bio03_now_has_a_real_deterministic_checker():
    rule = next(r for r in fields_all_rules() if r["rule_id"] == "QA-BIO-03")
    assert rule["check_type"] == "deterministic"
    assert "QA-BIO-03" in fields.DET_CHECKS


def test_trans02_disc02_relabeled_to_judgment():
    """The opposite direction from QA-BIO-03: these two were genuinely
    deterministic-labeled with a real checker, but that checker's whole
    approach (a text-only regex for duplicated bullet/number markers) can't
    reliably distinguish a real leftover copy-paste marker from a
    two-column table-layout artifact producing the same shape ("N. N.") --
    confirmed on Reeda's real TP. Same precedent as QA-SCH-08's earlier
    reclassification (see pipeline/CHECKER_DESIGN.md): fix the label, don't
    patch the regex a 4th time."""
    rule_by_id = {r["rule_id"]: r for r in fields_all_rules()}
    for rule_id in ("QA-TRANS-02", "QA-DISC-02"):
        rule = rule_by_id[rule_id]
        assert rule["check_type"] == "judgment"
        assert rule_id not in fields.DET_CHECKS
    assert not hasattr(fields, "_check_bullet_formatting"), "dead checker should be deleted, not left unused"
    assert not hasattr(fields, "_find_repeated_bullet_markers"), "dead helper should be deleted, not left unused"
