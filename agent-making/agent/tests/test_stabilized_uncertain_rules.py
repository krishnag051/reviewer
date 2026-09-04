"""Fix Round (Eliminate Coin-Flipping, For Real, Before Production), Part 1:
the 5 confirmed near-50/50 rules (QA-MAST-04, QA-GIP-14, QA-GIP-27,
QA-GIP-28, QA-GIP-22) are pulled out of the real judgment call entirely and
given a fixed, byte-identical "uncertain -- needs human review" finding,
zero model calls, zero variance by construction. No live document, no live
API -- judge._run_judgment_checks_once is mocked (and asserted NEVER
called for these 5 rule_ids) throughout.
"""
import pipeline as pipeline_module
from pipeline import judge


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

    for rid in pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS:
        assert rid not in seen_rule_ids, f"{rid} must never reach the real judgment call"
        assert result["findings"][rid]["result"] == "uncertain"
        assert result["findings"][rid]["evidence"] == pipeline_module._STABILIZED_UNCERTAIN_EVIDENCE

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
    across all 3 real full-batch runs) and stays off this set."""
    confirmed_unstable = {
        "QA-AI-03", "QA-AI-05", "QA-BIP-03", "QA-BIP-09", "QA-BIP-10", "QA-BIP-12",
        "QA-COC-07", "QA-GIP-02", "QA-GIP-17", "QA-GIP-20", "QA-GIP-22", "QA-GIP-23",
        "QA-GIP-25", "QA-GIP-27", "QA-GIP-29", "QA-GIP-34", "QA-GIP-35", "QA-HRS-07",
        "QA-PAR-02", "QA-SCH-09", "QA-TEMP-06",
    }
    assert confirmed_unstable.issubset(pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS)
    assert pipeline_module.STABILIZED_UNCERTAIN_RULE_IDS == confirmed_unstable | {"QA-MAST-04", "QA-GIP-14"}


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
