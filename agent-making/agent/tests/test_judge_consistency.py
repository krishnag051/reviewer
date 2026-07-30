"""Locks in change #3: a finding with evidence_supports_result=False must be
rejected (excluded from the returned dict), not recorded as-is. The pure
parsing function is tested directly (no API call); a second test proves the
rejection actually triggers integrity.py's retry-then-raise path end to end.
"""
import pytest

from pipeline import judge
from pipeline.integrity import IntegrityError, run_judgment_with_integrity_check


def _finding(rule_id, result="pass", evidence="ok", evidence_supports_result=True):
    return {
        "rule_id": rule_id,
        "result": result,
        "evidence": evidence,
        "page": None,
        "confidence": 0.8,
        "evidence_supports_result": evidence_supports_result,
    }


def test_consistent_finding_is_kept():
    findings = judge._findings_dict_from_list([_finding("A-1")])
    assert "A-1" in findings
    assert findings["A-1"]["result"] == "pass"


def test_inconsistent_finding_is_dropped_not_recorded():
    findings = judge._findings_dict_from_list([_finding("A-1", evidence_supports_result=False)])
    assert "A-1" not in findings, "a rejected finding must not appear in the returned dict at all"


def test_mixed_batch_keeps_consistent_drops_inconsistent():
    findings = judge._findings_dict_from_list([
        _finding("A-1", evidence_supports_result=True),
        _finding("A-2", evidence_supports_result=False),
    ])
    assert set(findings.keys()) == {"A-1"}


def test_missing_evidence_supports_result_key_treated_as_rejected():
    """Defensive default: if the model somehow omits the field despite it
    being required, treat that the same as an explicit False — never as an
    implicit pass."""
    bad_finding = _finding("A-1")
    del bad_finding["evidence_supports_result"]
    findings = judge._findings_dict_from_list([bad_finding])
    assert "A-1" not in findings


def test_rejected_finding_triggers_retry_then_integrity_error(monkeypatch):
    """End-to-end (mocked): a finding that's always inconsistent looks
    identical to a rule_id the model never returned — it must exhaust
    integrity.py's retries and raise, not get silently recorded.
    """
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]

    call_count = {"n": 0}

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        call_count["n"] += 1
        # Always comes back inconsistent -> always filtered out -> always "missing".
        return judge._findings_dict_from_list([_finding("A-1", evidence_supports_result=False)])

    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    with pytest.raises(IntegrityError):
        run_judgment_with_integrity_check(rules, fields={}, rendered_images={}, max_retries=2)

    assert call_count["n"] == 3  # initial attempt + 2 retries


def test_finding_that_becomes_consistent_on_retry_is_accepted(monkeypatch):
    """A finding rejected on the first attempt but returned consistently on
    retry must end up in the final result — proving this is a real retry,
    not a permanent rejection.
    """
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    call_count = {"n": 0}

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return judge._findings_dict_from_list([_finding("A-1", evidence_supports_result=False)])
        return judge._findings_dict_from_list([_finding("A-1", result="fail", evidence_supports_result=True)])

    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    results = run_judgment_with_integrity_check(rules, fields={}, rendered_images={}, max_retries=2)
    assert results["A-1"]["result"] == "fail"
    assert call_count["n"] == 2
