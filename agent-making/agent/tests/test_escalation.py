"""Locks in the deterministic-layer escalation wiring (run_full_pipeline)
without hitting the live API — judge.run_judgment_checks is monkeypatched
with a canned response, so this test only proves the orchestration logic:
weak deterministic findings get escalated into the same judgment batch, the
judgment result wins, and the original deterministic attempt survives as
det_attempt for debugging.
"""
import fitz
import pytest

import pipeline as pipeline_module
from pipeline import judge


@pytest.fixture
def minimal_pdf(tmp_path) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Treatment Plan\nAll staff mentioned are RBT/BT credentialed.")
    path = tmp_path / "minimal.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _rule(rule_id, check_type, params=None):
    return {
        "rule_id": rule_id,
        "category": "Test",
        "description": f"Test rule {rule_id}",
        "notes": None,
        "applies_to_payor": "ALL",
        "applies_to_plan_type": "Both",
        "check_type": check_type,
        "params": params,
        "action_lane": "BCBA-fix",
        "action_tag": None,
        "active": True,
    }


def test_low_confidence_det_result_escalates_and_judgment_wins(minimal_pdf, monkeypatch):
    # HF-02: no "97151" mention in minimal_pdf -> deterministic result is
    # not_applicable at confidence 0.5, which is below the 0.6 escalation
    # threshold -> must be escalated to judgment. (Genuinely Healthfirst-
    # specific rule, hence "HF-" not "QA-".)
    # QA-TEMP-05: no bare "RBT" -> deterministic pass at confidence 0.85, well
    # above threshold -> must NOT be escalated, stays purely deterministic.
    # (This is a universal rule, hence "QA-" not "HF-".)
    # (rule_ids must match fields.DET_CHECKS's real keys exactly, or the
    # checker lookup silently misses and everything falls through to
    # not_checkable instead.)
    rules = [
        _rule("HF-02", "deterministic", {"max_hours": 5, "cpt_code": "97151"}),
        _rule("QA-TEMP-05", "deterministic"),
    ]

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        sent_ids = {r["rule_id"] for r in judgment_rules}
        assert sent_ids == {"HF-02"}, f"expected only the escalated HF-02, got {sent_ids}"
        return {
            "HF-02": {
                "result": "fail",
                "evidence": "The model found 97151 hours documented on page 2 that the regex missed.",
                "page": 2,
                "confidence": 0.9,
            }
        }

    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    findings = result["findings"]

    # Escalated rule: judgment result wins, det attempt preserved alongside.
    assert findings["HF-02"]["result"] == "fail"
    assert findings["HF-02"]["confidence"] == 0.9
    assert "det_attempt" in findings["HF-02"]
    assert findings["HF-02"]["det_attempt"]["result"] == "not_applicable"

    # Non-escalated rule: untouched, no det_attempt field at all.
    assert findings["QA-TEMP-05"]["result"] == "pass"
    assert "det_attempt" not in findings["QA-TEMP-05"]


def test_escalated_rule_confirmed_not_checkable_by_judgment_too(minimal_pdf, monkeypatch):
    """If judgment also can't check it, that's a real confirmation the rule
    needs external data — not a code gap — and det_attempt still shows what
    the deterministic layer originally tried.
    """
    rules = [_rule("HF-02", "deterministic", {"max_hours": 5, "cpt_code": "97151"})]

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "HF-02": {
                "result": "not_checkable",
                "evidence": "No 97151 hours anywhere in the document or images either.",
                "page": None,
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    finding = result["findings"]["HF-02"]

    assert finding["result"] == "not_checkable"
    assert finding["det_attempt"]["result"] == "not_applicable"
