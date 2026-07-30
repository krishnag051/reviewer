"""Unit tests for the 3-way (N-way) majority-vote alternative to the
production 2-call self-consistency check (2026-07-28 round, item 1): not
wired into the pipeline, tested here in isolation before any live
comparison probe. No live document, no live API.
"""
from pipeline import judge


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def test_unanimous_three_calls_keeps_the_result():
    results = [{"A-1": _finding("fail")}, {"A-1": _finding("fail")}, {"A-1": _finding("fail")}]
    reconciled = judge._reconcile_majority_vote(results)
    assert reconciled["A-1"]["result"] == "fail"


def test_two_of_three_majority_wins_over_the_outlier():
    """The exact case this is meant to fix: first call correct (fail),
    second call an outlier (uncertain), third call breaks the tie toward
    the majority (fail) instead of the 2-way version's forced "uncertain"."""
    results = [{"A-1": _finding("fail", "clear violation")}, {"A-1": _finding("uncertain", "hedging")}, {"A-1": _finding("fail", "confirmed")}]
    reconciled = judge._reconcile_majority_vote(results)
    assert reconciled["A-1"]["result"] == "fail"


def test_all_three_disagree_falls_back_to_uncertain():
    results = [{"A-1": _finding("pass")}, {"A-1": _finding("fail")}, {"A-1": _finding("uncertain")}]
    reconciled = judge._reconcile_majority_vote(results)
    assert reconciled["A-1"]["result"] == "uncertain"
    assert reconciled["A-1"]["confidence"] == 0.0
    # all three calls' own results are visible in the explanation
    assert "pass" in reconciled["A-1"]["evidence"]
    assert "fail" in reconciled["A-1"]["evidence"]
    assert "uncertain" in reconciled["A-1"]["evidence"]


def test_rule_id_missing_from_any_single_call_is_left_out_entirely():
    results = [
        {"A-1": _finding("pass"), "A-2": _finding("pass")},
        {"A-1": _finding("pass")},  # A-2 dropped by this call
        {"A-1": _finding("pass"), "A-2": _finding("pass")},
    ]
    reconciled = judge._reconcile_majority_vote(results)
    assert set(reconciled.keys()) == {"A-1"}


def test_empty_results_list_returns_empty_dict():
    assert judge._reconcile_majority_vote([]) == {}


def test_run_judgment_checks_majority_vote_makes_exactly_n_calls(monkeypatch):
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call"):
        call_log.append(call_reason)
        return {"A-1": _finding("fail")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks_majority_vote(rules, {"pages": []}, {}, n_calls=3, call_reason="initial batch")

    assert len(call_log) == 3
    assert all("majority vote" in c for c in call_log)
    assert result["A-1"]["result"] == "fail"


def test_run_judgment_checks_majority_vote_with_no_rules_makes_zero_calls(monkeypatch):
    monkeypatch.setattr(
        judge, "_run_judgment_checks_once",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert judge.run_judgment_checks_majority_vote([], {"pages": []}, {}) == {}


def test_majority_vote_is_not_wired_into_production_run_judgment_checks(monkeypatch):
    """Confirms this stays a testable alternative, not a silent production
    change -- run_judgment_checks (the real pipeline path) still makes
    exactly 2 calls, not 3."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call"):
        call_log.append(call_reason)
        return {"A-1": _finding("pass")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    judge.run_judgment_checks(rules, {"pages": []}, {})
    assert len(call_log) == 2
