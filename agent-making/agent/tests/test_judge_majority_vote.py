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
    """Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    the per-call disagreement now surfaces each distinct result's own
    real evidence text (plain-English label + real content), not a bare
    vote-count or a fully generic sentence -- the real invariant (no
    majority -> uncertain, needs manual review) still holds."""
    results = [{"A-1": _finding("pass")}, {"A-1": _finding("fail")}, {"A-1": _finding("uncertain")}]
    reconciled = judge._reconcile_majority_vote(results)
    assert reconciled["A-1"]["result"] == "uncertain"
    assert reconciled["A-1"]["confidence"] == 0.0
    assert "confirm manually" in reconciled["A-1"]["evidence"].lower()
    assert "pass" in reconciled["A-1"]["evidence"]
    assert "fail" in reconciled["A-1"]["evidence"]


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

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
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


def test_majority_vote_does_not_change_the_plain_run_judgment_checks_function(monkeypatch):
    """Fix Round (Judgment Layer Stability) renamed/re-scoped this test:
    `run_judgment_checks_majority_vote` IS now wired into the real
    pipeline (via integrity.py's own initial-batch call site -- see
    test_integrity.py's own confirmation of that) -- what this test still
    confirms is narrower and still true: the PLAIN `run_judgment_checks`
    function itself is untouched, still makes exactly 2 calls, not 3 --
    integrity.py's retry pass for missing rule_ids still uses this exact
    function, deliberately kept cheap/unchanged (see integrity.py's own
    updated docstring for why)."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("pass")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    judge.run_judgment_checks(rules, {"pages": []}, {})
    assert len(call_log) == 2


# --- Fix Round (Judgment Layer Stability): min_agreement -------------------


def test_min_agreement_none_preserves_old_simple_majority_behavior():
    """4-of-7 is a simple majority (> 3.5) -- must still win with
    min_agreement=None, byte-identical to before this round."""
    results = [{"A-1": _finding("fail")}] * 4 + [{"A-1": _finding("pass")}] * 3
    reconciled = judge._reconcile_majority_vote(results, min_agreement=None)
    assert reconciled["A-1"]["result"] == "fail"


def test_min_agreement_stricter_than_simple_majority_falls_back_to_uncertain():
    """4-of-7 IS a simple majority, but is NOT >= min_agreement=5 -- must
    fall back to uncertain under the stricter bar, even though the old
    default would have committed to 'fail'."""
    results = [{"A-1": _finding("fail")}] * 4 + [{"A-1": _finding("pass")}] * 3
    reconciled = judge._reconcile_majority_vote(results, min_agreement=5)
    assert reconciled["A-1"]["result"] == "uncertain"
    # Fix Round (2026-09-15), "Language Regression": the internal "needed
    # N+ agreeing" phrasing doesn't reach reviewer-facing text.
    # Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    # but the real substance from both sides now does.
    assert "needed" not in reconciled["A-1"]["evidence"].lower()
    assert "confirm manually" in reconciled["A-1"]["evidence"].lower()
    assert "fail" in reconciled["A-1"]["evidence"]
    assert "pass" in reconciled["A-1"]["evidence"]


def test_min_agreement_exactly_met_commits_to_the_answer():
    results = [{"A-1": _finding("fail")}] * 5 + [{"A-1": _finding("pass")}] * 2
    reconciled = judge._reconcile_majority_vote(results, min_agreement=5)
    assert reconciled["A-1"]["result"] == "fail"


def test_run_judgment_checks_majority_vote_forwards_min_agreement_and_model_override(monkeypatch):
    captured = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        captured.append(model_override)
        return {"A-1": _finding("fail")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks_majority_vote(
        rules, {"pages": []}, {}, n_calls=7, min_agreement=5, model_override="anthropic:claude-sonnet-5",
    )
    assert len(captured) == 7
    assert all(m == "anthropic:claude-sonnet-5" for m in captured)
    assert result["A-1"]["result"] == "fail"
