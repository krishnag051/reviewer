"""Locks in the self-consistency double-call fix (2026-07-28 round): the
judgment-layer non-determinism confirmed via a live probe (QA-ACF-07 flipped
result across identical repeated calls, even in complete isolation from
other rules -- ruling out batching as the sole cause) is addressed by
calling the model twice with identical input and downgrading to "uncertain"
on disagreement, rather than silently keeping whichever call came back.

temperature=0 was confirmed NOT available as a cheaper fix via one live
call: passing a non-default temperature to claude-sonnet-5 returns a 400
("`temperature` is deprecated for this model"); only the model's own
default is accepted, as a no-op.

No live document, no live API -- _run_judgment_checks_once is monkeypatched
with canned per-call responses so this tests _reconcile_consistency_check's
logic in isolation.
"""
from pipeline import judge


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def test_agreeing_calls_keep_the_result():
    first = {"A-1": _finding("pass")}
    second = {"A-1": _finding("pass")}
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "pass"


def test_disagreeing_calls_downgrade_to_uncertain():
    first = {"A-1": _finding("pass", "looks fine")}
    second = {"A-1": _finding("fail", "actually a problem")}
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "uncertain"
    assert reconciled["A-1"]["confidence"] == 0.0
    # Both original evidence texts survive in the explanation, so a
    # reviewer (or a future diagnosis) can see exactly what each call said.
    assert "looks fine" in reconciled["A-1"]["evidence"]
    assert "actually a problem" in reconciled["A-1"]["evidence"]


def test_rule_id_missing_from_either_call_is_left_out_entirely():
    """Not guessed at -- integrity.py's existing missing-rule_id retry
    already handles this case correctly; reconciliation shouldn't invent a
    result for a rule_id that only one of the two calls answered."""
    first = {"A-1": _finding("pass"), "A-2": _finding("pass")}
    second = {"A-1": _finding("pass")}  # A-2 dropped by the second call
    reconciled = judge._reconcile_consistency_check(first, second)
    assert set(reconciled.keys()) == {"A-1"}


def test_mixed_batch_some_agree_some_disagree_some_missing():
    first = {"A-1": _finding("pass"), "A-2": _finding("fail"), "A-3": _finding("pass")}
    second = {"A-1": _finding("pass"), "A-2": _finding("uncertain")}  # A-3 missing
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "pass"
    assert reconciled["A-2"]["result"] == "uncertain"
    assert "A-3" not in reconciled


def test_run_judgment_checks_makes_exactly_two_underlying_calls_and_reconciles(monkeypatch):
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call"):
        call_log.append(call_reason)
        if len(call_log) == 1:
            return {"A-1": _finding("pass")}
        return {"A-1": _finding("fail")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)

    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks(rules, {"pages": []}, {}, call_reason="initial batch")

    assert len(call_log) == 2
    assert "1/2" in call_log[0]
    assert "2/2" in call_log[1]
    assert result["A-1"]["result"] == "uncertain"


def test_run_judgment_checks_with_no_rules_makes_zero_calls(monkeypatch):
    monkeypatch.setattr(
        judge, "_run_judgment_checks_once",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert judge.run_judgment_checks([], {"pages": []}, {}) == {}
