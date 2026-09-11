"""Fix Round (2026-09-11 evening) -- direct regression coverage for the
real root cause of the "13 newly-found flipping rules" round:
`api.py::_run_pipeline_with_extras` -- a hand-duplicated copy of
`pipeline/__init__.py::run_full_pipeline`'s orchestration -- never applied
STABILIZED_UNCERTAIN_RULE_IDS's filtering at all, in either pool
(judgment_rules or escalated_rules). Confirmed live: since a supporting
document has been mandatory on every real backend upload since Round
51/52, THIS function -- not run_full_pipeline -- is the orchestration
path every real upload actually takes, so the stabilization safety net
had likely never been active against real production traffic since it
was built. Already-listed rule_ids (QA-GIP-17, QA-GIP-22, QA-GIP-34,
QA-SCH-09, QA-TEMP-06) still flipping on a real two-run test was the
direct, confirmed symptom.

No real API spend -- judge._run_judgment_checks_once is mocked throughout;
supporting_doc_path is left None so extract_supporting_document is never
reached (this test targets the stabilization filter itself, not the
two-phase supporting-doc mechanism, which has its own dedicated coverage
in test_round55_two_phase_supporting_doc.py).
"""
import fitz

from pipeline import api, judge
from pipeline import fields as fields_module
from pipeline.call_tracker import ApiCallTracker


def _rule(rule_id, check_type="judgment"):
    return {
        "rule_id": rule_id, "category": "Test", "description": "d", "notes": None,
        "check_type": check_type, "active": True, "applies_to_payor": "ALL", "applies_to_plan_type": "Both",
    }


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def _blank_pdf(tmp_path, name):
    path = tmp_path / name
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return str(path)


def test_judgment_layer_stabilized_rule_id_never_reaches_the_real_call(monkeypatch, tmp_path):
    """A rule_id already in STABILIZED_UNCERTAIN_RULE_IDS via the normal
    judgment_rules pool (check_type=judgment) must be filtered out here,
    same as run_full_pipeline already correctly did before this round."""
    seen_rule_ids = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        seen_rule_ids.extend(r["rule_id"] for r in judgment_rules)
        return {r["rule_id"]: _finding("pass") for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    monkeypatch.setattr(fields_module, "run_deterministic_checks", lambda rules, fields: {})
    monkeypatch.setattr(fields_module, "partition_rules_by_scope", lambda rules, fields: (rules, {}))
    monkeypatch.setattr(fields_module, "vision_eligible_pages", lambda rules, fields: set())

    stabilized_rid = next(iter(api.STABILIZED_UNCERTAIN_RULE_IDS))
    rules = [_rule(stabilized_rid), _rule("QA-NORMAL-01")]
    pdf_path = _blank_pdf(tmp_path, "tp.pdf")

    result = api._run_pipeline_with_extras(
        pdf_path, rules, ApiCallTracker(),
        payor_override=None, plan_type_override=None, supporting_doc_path=None,
    )

    assert stabilized_rid not in seen_rule_ids, "a stabilized rule_id must never reach the real judgment call"
    finding = next(f for f in result["export_rows"] if f["rule_id"] == stabilized_rid)
    assert finding["result"] == "uncertain"
    assert "QA-NORMAL-01" in seen_rule_ids


def test_escalated_stabilized_rule_id_never_reaches_the_real_call_either(monkeypatch, tmp_path):
    """THE direct regression test: a rule_id in STABILIZED_UNCERTAIN_RULE_IDS
    whose check_type is "deterministic" and always escalates (confirmed
    real shape: QA-PPI-05, no det checker at all) must ALSO be filtered
    out here -- this is the exact real bug (escalated_rules bypassing the
    filter, in this specific function) confirmed on a real document run.
    """
    seen_rule_ids = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        seen_rule_ids.extend(r["rule_id"] for r in judgment_rules)
        return {r["rule_id"]: _finding("pass") for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    monkeypatch.setattr(
        fields_module, "run_deterministic_checks",
        lambda rules, fields: {"QA-PPI-05": {"result": "not_checkable", "evidence": "no checker", "page": None, "confidence": 0.0}},
    )
    monkeypatch.setattr(fields_module, "needs_escalation", lambda r: True)
    monkeypatch.setattr(fields_module, "partition_rules_by_scope", lambda rules, fields: (rules, {}))
    monkeypatch.setattr(fields_module, "vision_eligible_pages", lambda rules, fields: set())

    assert "QA-PPI-05" in api.STABILIZED_UNCERTAIN_RULE_IDS
    rules = [_rule("QA-PPI-05", check_type="deterministic")]
    pdf_path = _blank_pdf(tmp_path, "tp.pdf")

    result = api._run_pipeline_with_extras(
        pdf_path, rules, ApiCallTracker(),
        payor_override=None, plan_type_override=None, supporting_doc_path=None,
    )

    assert "QA-PPI-05" not in seen_rule_ids, "an escalated, stabilized rule_id must never reach the real judgment call"
    finding = next(f for f in result["export_rows"] if f["rule_id"] == "QA-PPI-05")
    assert finding["result"] == "uncertain"
