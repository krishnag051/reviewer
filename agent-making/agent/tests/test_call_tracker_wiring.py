"""Proves the tracker is actually wired into judge.py/integrity.py correctly
— every real call increments it, retries increment it too, and the cap
stops execution BEFORE an over-budget call is made. Mocks anthropic.Anthropic
itself (not judge.run_judgment_checks), so the check-before-call/record-
after-call code inside judge.py actually executes — this is the level
change #3's evidence_supports_result rejection lives at too, so this is the
right seam to verify the cap against.

Since the 2026-07-28 self-consistency round, judge.run_judgment_checks
itself makes TWO real calls per invocation (_run_judgment_checks_once,
twice, reconciled) — every count in this file that used to assume "1 call
per attempt" is now "2 calls per attempt" to match. response_fn is keyed on
a monotonically increasing call counter `n` across the whole fake client,
so a single logical attempt spans two consecutive n values.

Zero real API calls, zero cost — per the standing rule against spending
real money to verify a cost guardrail.
"""
import pytest

from pipeline import judge
from pipeline.call_tracker import ApiCallCapExceeded, ApiCallTracker
from pipeline.integrity import IntegrityError, run_judgment_with_integrity_check


class _FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class _FakeResponse:
    def __init__(self, findings, stop_reason="tool_use"):
        self.content = [_FakeToolUseBlock({"findings": findings})]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._response


class _FakeMessages:
    """response_fn(kwargs) -> _FakeResponse, called once per real "call"."""

    def __init__(self, response_fn):
        self._response_fn = response_fn
        self.call_count = 0

    def stream(self, **kwargs):
        self.call_count += 1
        return _FakeStreamCM(self._response_fn(kwargs, self.call_count))


class _FakeClient:
    def __init__(self, response_fn):
        self.messages = _FakeMessages(response_fn)


def _finding(rule_id, evidence_supports_result=True):
    return {
        "rule_id": rule_id,
        "result": "pass",
        "evidence": "ok",
        "page": None,
        "confidence": 0.9,
        "evidence_supports_result": evidence_supports_result,
    }


def _rule(rule_id):
    return {"rule_id": rule_id, "category": "Test", "description": "d", "notes": None}


def test_single_clean_call_increments_tracker_by_two(monkeypatch):
    """One logical run_judgment_checks() call is now two real calls (the
    self-consistency pair) — both return the same fixed response here, so
    they agree and the pair counts as one clean, non-retried attempt."""
    fake_client = _FakeClient(lambda kwargs, n: _FakeResponse([_finding("A-1"), _finding("A-2")]))
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    tracker = ApiCallTracker(max_calls=5)
    results = judge.run_judgment_checks(
        [_rule("A-1"), _rule("A-2")], {"pages": []}, {}, tracker=tracker, call_reason="initial batch"
    )

    assert tracker.count == 2
    assert fake_client.messages.call_count == 2
    assert set(results.keys()) == {"A-1", "A-2"}


def test_retry_increments_tracker_for_each_real_call(monkeypatch):
    # Attempt 1 (real calls 1-2, the consistency pair): both agree A-2 is
    # simply absent (model dropped it both times) -> A-1 present, A-2 missing.
    # Retry attempt (real calls 3-4): both agree A-2 comes back fine.
    def response_fn(kwargs, n):
        if n in (1, 2):
            return _FakeResponse([_finding("A-1")])  # A-2 missing entirely, both times
        return _FakeResponse([_finding("A-2")])

    fake_client = _FakeClient(response_fn)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    tracker = ApiCallTracker(max_calls=8)
    results = run_judgment_with_integrity_check(
        [_rule("A-1"), _rule("A-2")], {"pages": []}, {}, max_retries=2, tracker=tracker
    )

    assert tracker.count == 4  # 2 (initial consistency pair) + 2 (1 retry's consistency pair)
    assert fake_client.messages.call_count == 4
    assert set(results.keys()) == {"A-1", "A-2"}


def test_rejected_evidence_supports_result_also_counts_as_a_retry_call(monkeypatch):
    # Attempt 1 (real calls 1-2): both reject A-1 (evidence_supports_result=False)
    # -> _findings_dict_from_list drops it from both -> treated as missing.
    # Retry attempt (real calls 3-4): both agree A-1 is consistent (pass).
    def response_fn(kwargs, n):
        if n in (1, 2):
            return _FakeResponse([_finding("A-1", evidence_supports_result=False)])
        return _FakeResponse([_finding("A-1", evidence_supports_result=True)])

    fake_client = _FakeClient(response_fn)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    tracker = ApiCallTracker(max_calls=8)
    results = run_judgment_with_integrity_check([_rule("A-1")], {"pages": []}, {}, max_retries=2, tracker=tracker)

    assert tracker.count == 4
    assert results["A-1"]["result"] == "pass"


def test_cap_stops_mid_retry_loop_before_the_over_budget_call(monkeypatch):
    """The model NEVER resolves (always drops the rule_id). The very first
    logical attempt already spends the whole cap on its own consistency
    pair (2 real calls); the retry's first internal call would be the 3rd
    real call and must never happen.
    """
    def response_fn(kwargs, n):
        return _FakeResponse([])  # never returns the rule_id, ever

    fake_client = _FakeClient(response_fn)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    tracker = ApiCallTracker(max_calls=2)

    with pytest.raises(ApiCallCapExceeded):
        run_judgment_with_integrity_check([_rule("A-1")], {"pages": []}, {}, max_retries=5, tracker=tracker)

    assert tracker.count == 2, "must stop exactly at the cap, not one over"
    assert fake_client.messages.call_count == 2, "the 3rd (over-budget) real call must never have been made"


def test_without_cap_this_scenario_would_raise_integrity_error_instead(monkeypatch):
    """Sanity check that the cap-stopping test above isn't just coincidentally
    matching IntegrityError's own retry limit — confirms that with no cap,
    the SAME never-resolves scenario runs all the way to IntegrityError.
    max_retries=2 means 3 attempts (initial + 2 retries), each attempt now
    spending 2 real calls on its own consistency pair -> 6 real calls total.
    """
    def response_fn(kwargs, n):
        return _FakeResponse([])

    fake_client = _FakeClient(response_fn)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    tracker = ApiCallTracker(max_calls=None)

    with pytest.raises(IntegrityError):
        run_judgment_with_integrity_check([_rule("A-1")], {"pages": []}, {}, max_retries=2, tracker=tracker)

    assert tracker.count == 6  # 3 attempts x 2 real calls each
    assert fake_client.messages.call_count == 6


def test_tracker_is_optional_backward_compatible(monkeypatch):
    """Existing call sites that don't pass a tracker must keep working
    exactly as before — tracker is opt-in, not required."""
    fake_client = _FakeClient(lambda kwargs, n: _FakeResponse([_finding("A-1")]))
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)

    results = judge.run_judgment_checks([_rule("A-1")], {"pages": []}, {})  # no tracker at all
    assert results["A-1"]["result"] == "pass"
