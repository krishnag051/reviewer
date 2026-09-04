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


def test_malformed_non_dict_entry_is_dropped_not_a_crash():
    """Confirmed live: a real model response can put a bare string in the
    findings array where the tool schema requires an object. This must be
    dropped (retried as if missing), never raise AttributeError."""
    findings = judge._findings_dict_from_list(["QA-TEMP-03"])
    assert findings == {}


def test_malformed_entry_mixed_with_a_valid_one_keeps_the_valid_one():
    findings = judge._findings_dict_from_list(["QA-TEMP-03", _finding("A-1")])
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
    attempt_labels = set()

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, call_reason="call", **kwargs):
        call_count["n"] += 1
        # Fix Round (Judgment Layer Stability): the initial batch is now 5
        # real calls (run_judgment_checks_majority_vote), not 1 -- track
        # LOGICAL attempts (initial batch, retry 1, retry 2) via the
        # attempt-level call_reason prefix (stripping each call's own
        # "(majority vote N/5)"/"(consistency check N/2)" suffix), not raw
        # call count, since that's what this test actually means by
        # "attempt."
        attempt_labels.add(call_reason.split(" (")[0])
        # Always comes back inconsistent -> always filtered out -> always "missing".
        return judge._findings_dict_from_list([_finding("A-1", evidence_supports_result=False)])

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_run_judgment_checks)  # Fix Round (Judgment Layer Stability): the initial-batch call site is now run_judgment_checks_majority_vote, which itself calls _run_judgment_checks_once repeatedly -- mocking at this shared, lower-level primitive keeps this fixture correct across BOTH the retry path (still run_judgment_checks) and the new majority-vote path.

    with pytest.raises(IntegrityError):
        run_judgment_with_integrity_check(rules, fields={}, rendered_images={}, max_retries=2)

    assert len(attempt_labels) == 3  # initial attempt + 2 retries
    assert call_count["n"] == 5 + 2 + 2  # 5-way initial batch + 2-call retry x 2


def test_one_persistently_missing_rule_id_among_many_degrades_gracefully_not_raise(monkeypatch):
    """Real live incident (2026-08): a persistently-missing rule_id
    (confirmed case: QA-GIP-11) used to raise IntegrityError, discarding
    every OTHER rule_id's real, already-computed finding along with it --
    a whole real, paid-for review thrown away over one stubborn rule.
    Reproduces that exact shape (many rule_ids sent, exactly one always
    missing) and asserts the FIX: no exception, every other rule_id's
    real answer comes through untouched, and the stubborn one gets an
    honest not_checkable finding, not a guess and not a silent drop.
    """
    rules = [
        {"rule_id": "A-1", "category": "Test", "description": "d", "notes": None},
        {"rule_id": "A-2", "category": "Test", "description": "d", "notes": None},
        {"rule_id": "A-3", "category": "Test", "description": "d", "notes": None},
    ]

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        # A-1/A-2 always answer fine; A-3 always comes back rejected/missing,
        # regardless of whether it's in the initial batch or a solo retry.
        findings = [_finding(r["rule_id"]) for r in judgment_rules if r["rule_id"] != "A-3"]
        if any(r["rule_id"] == "A-3" for r in judgment_rules):
            findings.append(_finding("A-3", evidence_supports_result=False))
        return judge._findings_dict_from_list(findings)

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_run_judgment_checks)  # Fix Round (Judgment Layer Stability): the initial-batch call site is now run_judgment_checks_majority_vote, which itself calls _run_judgment_checks_once repeatedly -- mocking at this shared, lower-level primitive keeps this fixture correct across BOTH the retry path (still run_judgment_checks) and the new majority-vote path.

    results = run_judgment_with_integrity_check(rules, fields={}, rendered_images={}, max_retries=2)

    # No exception raised -- the whole point of the fix.
    assert results["A-1"]["result"] == "pass"
    assert results["A-2"]["result"] == "pass"
    assert results["A-3"]["result"] == "not_checkable"
    assert "not produce a confirmed answer" in results["A-3"]["evidence"]
    assert results["A-3"]["confidence"] == 0.0


def test_finding_that_becomes_consistent_on_retry_is_accepted(monkeypatch):
    """A finding rejected on the first attempt but returned consistently on
    retry must end up in the final result — proving this is a real retry,
    not a permanent rejection.
    """
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    call_count = {"n": 0}

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, call_reason="call", **kwargs):
        call_count["n"] += 1
        # Fix Round (Judgment Layer Stability): every call during the
        # INITIAL batch (now 5 calls, not 1) must reject, so the whole
        # attempt genuinely comes back "missing" -- only the retry
        # (a real, later, distinct attempt) accepts. Branching on
        # call_reason's own "initial batch" vs "retry" text is what this
        # test actually means by "first attempt" vs "on retry," not raw
        # call count.
        if "initial batch" in call_reason:
            return judge._findings_dict_from_list([_finding("A-1", evidence_supports_result=False)])
        return judge._findings_dict_from_list([_finding("A-1", result="fail", evidence_supports_result=True)])

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_run_judgment_checks)  # Fix Round (Judgment Layer Stability): the initial-batch call site is now run_judgment_checks_majority_vote, which itself calls _run_judgment_checks_once repeatedly -- mocking at this shared, lower-level primitive keeps this fixture correct across BOTH the retry path (still run_judgment_checks) and the new majority-vote path.

    results = run_judgment_with_integrity_check(rules, fields={}, rendered_images={}, max_retries=2)
    assert results["A-1"]["result"] == "fail"
    assert call_count["n"] == 5 + 2  # 5-way initial batch (all rejected) + the retry's own 2-call consistency check (both agree, no tie-break needed)
