"""Fix Round (Eliminate Coin-Flipping, For Real, Before Production), Part 1:
the 5 confirmed near-50/50 rules (QA-MAST-04, QA-GIP-14, QA-GIP-27,
QA-GIP-28, QA-GIP-22) are pulled out of the real judgment call entirely and
given a fixed, byte-identical "uncertain -- needs human review" finding,
zero model calls, zero variance by construction. No live document, no live
API -- judge._run_judgment_checks_once is mocked (and asserted NEVER
called for these 5 rule_ids) throughout.
"""
import pipeline as pipeline_module
from pipeline import fields, judge


def _rule(rule_id, check_type="judgment"):
    return {
        "rule_id": rule_id, "category": "Test", "description": "d", "notes": None,
        "check_type": check_type, "active": True, "applies_to_payor": "ALL", "applies_to_plan_type": "Both",
    }


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def test_all_stabilized_rules_return_the_fixed_finding_with_zero_model_calls(monkeypatch, tmp_path):
    seen_rule_ids = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        seen_rule_ids.extend(r["rule_id"] for r in judgment_rules)
        return {r["rule_id"]: _finding("pass") for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    monkeypatch.setattr(pipeline_module.fields_module, "run_deterministic_checks", lambda rules, fields: {})
    monkeypatch.setattr(pipeline_module.fields_module, "partition_rules_by_scope", lambda rules, fields: (rules, {}))
    monkeypatch.setattr(pipeline_module.fields_module, "vision_eligible_pages", lambda rules, fields: set())

    rules = [_rule(rid) for rid in sorted(pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS)] + [_rule("QA-NORMAL-01")]

    import fitz
    pdf_path = tmp_path / "tp.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    result = pipeline_module.run_full_pipeline(str(pdf_path), rules)

    # Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    # a blank synthetic PDF has no real document text, so every context
    # extractor correctly finds nothing -- the honest "no context" tail,
    # not a fabricated finding. See test_stabilized_evidence_includes_real_
    # extracted_context below for the real-content case.
    for rid in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS:
        assert rid not in seen_rule_ids, f"{rid} must never reach the real judgment call"
        assert result["findings"][rid]["result"] == "uncertain"
        assert pipeline_module._STABILIZED_UNCERTAIN_FRAMING in result["findings"][rid]["evidence"]
        assert pipeline_module._STABILIZED_UNCERTAIN_NO_CONTEXT in result["findings"][rid]["evidence"]

    # The normal rule is untouched -- confirms this is a narrow, rule_id-
    # scoped override, not a change to the judgment mechanism itself.
    assert "QA-NORMAL-01" in seen_rule_ids
    assert result["findings"]["QA-NORMAL-01"]["result"] == "pass"


def test_stabilized_finding_is_byte_identical_across_repeated_calls():
    """Directly confirms the round's own strictest requirement: not just
    the same result LABEL, the exact same evidence text, every time --
    calling the pure finding-builder function repeatedly (standing in for
    N separate real pipeline runs, since nothing about it is
    input-dependent) must never produce two different strings."""
    findings = [pipeline_module._stabilized_uncertain_finding() for _ in range(5)]
    assert len(set(f["evidence"] for f in findings)) == 1
    assert all(f["result"] == "uncertain" for f in findings)
    assert all(f["confidence"] == 0.0 for f in findings)


def test_stabilized_rule_ids_include_every_rule_confirmed_unstable_by_the_real_part_3_test():
    """Part 3's real, full-181-rule, 3-run test (see this round's report)
    found 21 rule_ids that actually flip in the full production batch --
    including QA-GIP-22/QA-GIP-27, whose isolated Part 2 re-test looked
    stable but didn't hold up at full scale (a real gap in that narrower
    testing methodology, confirmed and reported, not hidden). Every one
    of those 21 must be here except QA-GIP-28, which DID hold up (no flip
    across all 3 real full-batch runs) and stays off this set.

    QA-BIP-03 is a deliberate, documented EXCEPTION to "must be here" as
    of Fix Round (2026-09-11), item 17: this rule was changed to a
    genuinely different (inverted) question that confirmed go-ahead
    round asked for, and the Part 3 instability data below was measured
    against the OLD question -- it doesn't carry over. Kept in
    `confirmed_unstable` here as an honest historical record of what Part
    3 actually found, but excluded from the subset/equality assertions
    against the CURRENT STABILIZED_UNCERTAIN_RULE_IDS (see that rule's
    own notes in pipeline/__init__.py)."""
    confirmed_unstable = {
        "QA-AI-03", "QA-AI-05", "QA-BIP-03", "QA-BIP-09", "QA-BIP-10", "QA-BIP-12",
        "QA-COC-07", "QA-GIP-02", "QA-GIP-17", "QA-GIP-20", "QA-GIP-22", "QA-GIP-23",
        "QA-GIP-25", "QA-GIP-27", "QA-GIP-29", "QA-GIP-34", "QA-GIP-35", "QA-HRS-07",
        "QA-PAR-02", "QA-SCH-09", "QA-TEMP-06",
    }
    # Fix Round (2026-09-11 night), "Stop Over-Using the Uncertain Safety
    # Net": QA-GIP-22 is a SECOND deliberate, documented exception -- a
    # real deterministic checker was built for it this round (reusing the
    # Date-Initiated-vs-report-range anchor QA-GIP-07 already proved out),
    # so it's un-pinned like QA-GIP-28 before it, not a coincidental gap.
    #
    # Fix Round (Jacob Freund 10-2026-U1), Item 3: QA-HRS-07 is a THIRD
    # deliberate exception -- a real deterministic no-increase gate was
    # built (fields.py::_check_HRS07), un-pinned this round.
    still_applicable = confirmed_unstable - {"QA-BIP-03", "QA-GIP-22", "QA-HRS-07"}
    assert still_applicable.issubset(pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS)
    # Fix Round (2026-09-11 evening) added 8 more real, confirmed-unstable
    # rule_ids on top of this Part 3 baseline (see that round's own comment
    # in pipeline/__init__.py) -- exact equality against the Part 3 set
    # alone no longer holds; the real invariant this test protects is
    # "every Part 3 finding is still covered", asserted above as a subset,
    # not "nothing has been added since."
    assert "QA-BIP-03" not in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS


def test_stabilized_rule_ids_still_include_the_ones_not_fixed_this_round():
    """Fix Round (2026-09-11 night), "Stop Over-Using the Uncertain Safety
    Net": of the 13 rule_ids confirmed flipping on the real two-run test
    (see pipeline/__init__.py's own triage comment), 7 got real
    deterministic/hybrid fixes and are un-pinned (checked in the sibling
    test below); the other 6 are genuinely NOT fixable this round for a
    real, specific reason (image-dependency discrepancy, or genuine
    residual judgment-call ambiguity) and correctly stay here."""
    # Fix Round (Jacob Freund 10-2026-U1), Items 7/11/17: QA-BIO-06,
    # QA-ACF-11, and QA-MAST-04 (the original-2 rule from Part 2, not
    # listed in this specific set but see the sibling module-level
    # assertions below) all got real checkers built and are un-pinned this
    # round -- moved out of "still pinned."
    still_pinned = {
        "HF-05", "QA-ACF-03",  # image/graph-dependent (approved to stay)
        "QA-GIP-17", "QA-GIP-11", "QA-SCH-09", "QA-TEMP-06",  # genuine residual judgment calls
    }
    assert still_pinned.issubset(pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS)
    assert "QA-BIO-06" not in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS
    assert "QA-ACF-11" not in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS
    assert "QA-MAST-04" not in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS


def test_stabilized_rule_ids_no_longer_include_the_7_real_fixes_this_round():
    """The other 7 of the 13 got real deterministic/hybrid checkers built
    this round (fields.py, right above DET_CHECKS) and are un-pinned."""
    fixed_this_round = {"QA-COC-06", "QA-GIP-21", "QA-HRS-08", "QA-MAST-03", "HF-06", "QA-SCH-05", "QA-GIP-22"}
    assert fixed_this_round.isdisjoint(pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS)
    for rid in fixed_this_round:
        assert rid in fields.DET_CHECKS, f"{rid} should have a real checker now that it's un-pinned"


def test_qa_gip_28_is_the_one_rewrite_confirmed_stable_at_full_batch_scale():
    """The one Part 2 rewrite that held up under the real, decisive Part
    3 test -- no flip across all 3 real full-batch runs -- genuinely off
    the safety net, not just optimistically freed on a narrow test."""
    assert "QA-GIP-28" not in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS


def test_a_stabilized_rule_id_that_is_also_scope_excluded_still_gets_not_applicable_not_the_stabilized_uncertain(monkeypatch, tmp_path):
    """A rule genuinely out of scope for this document (wrong payor/plan
    type) must still resolve to not_applicable, same as any other rule --
    the stabilization override must not silently swallow a real
    not_applicable into a fake uncertain."""
    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        return {r["rule_id"]: _finding("pass") for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    monkeypatch.setattr(pipeline_module.fields_module, "run_deterministic_checks", lambda rules, fields: {})

    def fake_partition(rules, fields):
        excluded = {
            "QA-GIP-14": {"result": "not_applicable", "evidence": "out of scope", "page": None, "confidence": 1.0},
        }
        applicable = [r for r in rules if r["rule_id"] not in excluded]
        return applicable, excluded

    monkeypatch.setattr(pipeline_module.fields_module, "partition_rules_by_scope", fake_partition)
    monkeypatch.setattr(pipeline_module.fields_module, "vision_eligible_pages", lambda rules, fields: set())

    rules = [_rule("QA-GIP-14")]

    import fitz
    pdf_path = tmp_path / "tp.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    result = pipeline_module.run_full_pipeline(str(pdf_path), rules)
    assert result["findings"]["QA-GIP-14"]["result"] == "not_applicable"


def test_a_stabilized_rule_id_that_only_ever_escalates_is_still_stabilized(monkeypatch, tmp_path):
    """Fix Round (2026-09-11 evening) -- direct regression test for the
    real bug this round found: a rule_id in STABILIZED_UNCERTAIN_RULE_IDS
    whose check_type is "deterministic" and always escalates (a real
    checker that returns low confidence, or no checker at all) used to
    bypass the stabilization filter entirely -- the filter only ever ran
    on `judgment_rules` BEFORE `escalated_rules` was unioned in, so a
    rule_id that enters solely through escalation was never removed from
    the real judgment call, no matter how long it sat in this frozenset.
    Confirmed live: QA-PPI-05 (no det checker at all) kept flipping
    result across two identical real runs despite being added here.
    """
    seen_rule_ids = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        seen_rule_ids.extend(r["rule_id"] for r in judgment_rules)
        return {r["rule_id"]: _finding("pass") for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    # A deterministic-labeled rule with a low-confidence result -- exactly
    # the shape that makes fields_module.needs_escalation return True.
    monkeypatch.setattr(
        pipeline_module.fields_module, "run_deterministic_checks",
        lambda rules, fields: {"QA-PPI-05": {"result": "not_checkable", "evidence": "no checker", "page": None, "confidence": 0.0}},
    )
    monkeypatch.setattr(pipeline_module.fields_module, "needs_escalation", lambda r: True)
    monkeypatch.setattr(pipeline_module.fields_module, "partition_rules_by_scope", lambda rules, fields: (rules, {}))
    monkeypatch.setattr(pipeline_module.fields_module, "vision_eligible_pages", lambda rules, fields: set())

    rules = [_rule("QA-PPI-05", check_type="deterministic")]

    import fitz
    pdf_path = tmp_path / "tp.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf_path))
    doc.close()

    result = pipeline_module.run_full_pipeline(str(pdf_path), rules)

    assert "QA-PPI-05" not in seen_rule_ids, "an escalated, stabilized rule_id must never reach the real judgment call"
    assert result["findings"]["QA-PPI-05"]["result"] == "uncertain"
    # Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    # blank synthetic PDF -> no real NPI/License text -> honest "no context".
    assert pipeline_module._STABILIZED_UNCERTAIN_FRAMING in result["findings"]["QA-PPI-05"]["evidence"]
    assert result["findings"]["QA-PPI-05"]["det_attempt"]["evidence"] == "no checker", (
        "the original det attempt must still be visible for debugging, same as any other escalated rule"
    )


def test_stabilized_evidence_includes_real_extracted_context():
    """Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence"
    -- the core ask, directly: a stabilized rule's Uncertain evidence must
    surface real, document-specific content when it exists, not just the
    generic framing sentence. Zero model calls -- get_stabilized_rule_
    context is a plain text scan, same as any other checker's extraction."""
    fields_dict = {
        "full_text": (
            "Target Name: Reduce Tantrum\n"
            "Baseline: 5 per session\n"
            "Current Data: 2 per session\n"
            "Anticipated Mastery Date: 12/15/2026\n"
            "Status: In Progress\n"
        ),
        "pages": [{"page_number": 1, "text": "Target Name: Reduce Tantrum\nBaseline: 5 per session\n"}],
    }
    finding = pipeline_module._stabilized_uncertain_finding("HF-05", fields_dict)
    assert finding["result"] == "uncertain"
    assert pipeline_module._STABILIZED_UNCERTAIN_FRAMING in finding["evidence"]
    assert "Reduce Tantrum" in finding["evidence"]
    assert "Baseline: 5 per session" in finding["evidence"]
    assert pipeline_module._STABILIZED_UNCERTAIN_NO_CONTEXT not in finding["evidence"]


def test_stabilized_evidence_is_byte_identical_across_repeated_runs_of_the_same_document():
    """The real invariant an earlier round needed (zero variance) still
    holds: calling this repeatedly with the SAME fields dict must always
    produce the exact same evidence string -- no randomness anywhere,
    even though the text now varies BY document/rule_id (that's the point)."""
    fields_dict = {
        "full_text": "Target Goal: Skill X\nCurrent Data: 50%\n",
        "pages": [{"page_number": 1, "text": "Target Goal: Skill X\nCurrent Data: 50%\n"}],
    }
    results = [pipeline_module._stabilized_uncertain_finding("QA-GIP-02", fields_dict)["evidence"] for _ in range(5)]
    assert len(set(results)) == 1


def test_stabilized_evidence_falls_back_honestly_with_no_extractor_or_no_match():
    """QA-AI-05 has no extractor at all (see fields.STABILIZED_RULE_CONTEXT's
    own comment -- no reliable deterministic detector for spelling/grammar
    errors exists); a rule WITH an extractor that finds nothing must look
    identical to a rule with no extractor at all -- both are equally
    honest "nothing to show" cases."""
    fields_dict = {"full_text": "Nothing relevant here.", "pages": [{"page_number": 1, "text": "Nothing relevant here."}]}
    no_extractor = pipeline_module._stabilized_uncertain_finding("QA-AI-05", fields_dict)
    found_nothing = pipeline_module._stabilized_uncertain_finding("QA-HRS-07", fields_dict)
    assert pipeline_module._STABILIZED_UNCERTAIN_NO_CONTEXT in no_extractor["evidence"]
    assert pipeline_module._STABILIZED_UNCERTAIN_NO_CONTEXT in found_nothing["evidence"]


def test_a_broken_context_extractor_never_crashes_the_whole_review(monkeypatch):
    """Same isolation discipline as merge.py's own per-rule fallback -- one
    rule_id's own extractor throwing must not take down anything else."""
    def _broken(_fields):
        raise ValueError("simulated extraction bug")

    monkeypatch.setitem(fields.STABILIZED_RULE_CONTEXT, "HF-05", _broken)
    finding = pipeline_module._stabilized_uncertain_finding("HF-05", {"full_text": "x", "pages": []})
    assert finding["result"] == "uncertain"
    assert pipeline_module._STABILIZED_UNCERTAIN_NO_CONTEXT in finding["evidence"]
