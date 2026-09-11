"""Fix Round (2026-09-11 evening) -- Stop the Retry-Exhaustion Regression,
Maximize Real Page Coverage, Confirm Stability.

Dedicated coverage for integrity.py's new `_run_page_recovery_pass`: the
mechanism that lets a rule which already has a real, accepted Pass/Fail/
Uncertain answer -- just no page -- get retried SPECIFICALLY for a page,
without ever being able to discard or change that answer. This is the
direct fix for the confirmed real regression: 7 rule_ids on one real
document run (QA-BIO-17, QA-GIP-32, QA-GIP-14, QA-GIP-28, QA-AI-02,
QA-AI-03, QA-AI-04) had their real, repeatedly-reaffirmed judgment
discarded and replaced with a guessed "not_checkable" purely because a
page number never came back within the retry limit.

Zero real API spend -- `judge._run_judgment_checks_once` is mocked
throughout, same discipline as test_integrity_majority_vote_wiring.py.
"""
from pipeline import integrity, judge


def _finding(result="pass", page=None, page_unresolved=None):
    f = {"result": result, "evidence": "real evidence", "page": page, "confidence": 0.8}
    if page_unresolved:
        f["page_unresolved"] = True
    return f


RULES = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]


def test_a_confirmed_answer_missing_a_page_is_never_downgraded_to_not_checkable(monkeypatch):
    """The core regression fix: every call, initial and every retry, keeps
    reaffirming a real 'pass' with no page -- the final result must still
    be 'pass', never 'not_checkable'."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("pass", page=None, page_unresolved=True)}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = integrity.run_judgment_with_integrity_check(RULES, {"pages": []}, {})
    assert result["A-1"]["result"] == "pass", "the real answer must survive, never discarded for lacking a page"
    assert result["A-1"]["page"] is None
    assert "page_unresolved" not in result["A-1"], "internal bookkeeping flag must never leak into the final result"
    assert "could not be confirmed" in result["A-1"]["evidence"], (
        "an honest note must explain why there's no page, without changing the result"
    )


def test_a_page_recovery_retry_that_finds_a_page_upgrades_the_result(monkeypatch):
    """'Maximize real page coverage': if a later attempt DOES cite a real
    page for the SAME already-accepted result, adopt it."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        if "page-recovery" in call_reason:
            return {"A-1": _finding("pass", page=12)}
        return {"A-1": _finding("pass", page=None, page_unresolved=True)}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = integrity.run_judgment_with_integrity_check(RULES, {"pages": []}, {})
    assert result["A-1"]["result"] == "pass"
    assert result["A-1"]["page"] == 12


def test_a_page_recovery_retry_that_disagrees_on_the_verdict_is_ignored_for_stability(monkeypatch):
    """STABILITY, non-negotiable: a page-recovery retry that comes back
    with a DIFFERENT result (a genuine disagreement, not a page-only
    refinement) must never override the already-accepted answer -- doing
    so would make this pass a hidden second vote on the substance, which
    is exactly the kind of run-to-run instability this round must not
    introduce."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        if "page-recovery" in call_reason:
            # Disagrees on the substance AND happens to have a page --
            # must still be rejected, since the result doesn't match.
            return {"A-1": _finding("fail", page=9)}
        return {"A-1": _finding("pass", page=None, page_unresolved=True)}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = integrity.run_judgment_with_integrity_check(RULES, {"pages": []}, {})
    assert result["A-1"]["result"] == "pass", "the original accepted answer must never be overridden by a disagreeing retry"
    assert result["A-1"]["page"] is None


def test_page_recovery_is_bounded_not_unbounded(monkeypatch):
    """The recovery pass must stop after its own bounded number of
    attempts, not retry forever chasing a page that never comes."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("uncertain", page=None, page_unresolved=True)}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = integrity.run_judgment_with_integrity_check(RULES, {"pages": []}, {})
    assert result["A-1"]["result"] == "uncertain"
    assert result["A-1"]["page"] is None
    # 5 (initial batch) + up to 2 page-recovery attempts x 2 calls each = 9 max
    assert len(call_log) <= 9, f"page recovery must be bounded, got {len(call_log)} calls"


def test_rule_ids_with_a_real_page_from_the_start_never_trigger_recovery_calls(monkeypatch):
    """Zero-cost when there's nothing to recover -- a rule_id that already
    has a real page must not trigger any extra calls at all."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("pass", page=5)}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = integrity.run_judgment_with_integrity_check(RULES, {"pages": []}, {})
    assert result["A-1"]["page"] == 5
    assert len(call_log) == 5, "only the initial 5-way vote should run -- no page-recovery calls needed"
