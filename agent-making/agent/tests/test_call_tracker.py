"""Pure unit tests for ApiCallTracker — no API, no mocking needed at all."""
import pytest

from pipeline.call_tracker import ApiCallCapExceeded, ApiCallTracker


class _FakeUsage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


def test_starts_at_zero():
    tracker = ApiCallTracker(max_calls=5)
    assert tracker.count == 0
    assert tracker.estimated_cost() == 0.0


def test_record_increments_count_and_tokens():
    tracker = ApiCallTracker(max_calls=5)
    tracker.record(reason="initial batch", rule_ids=["A-1", "A-2"], usage=_FakeUsage(1000, 200))
    assert tracker.count == 1
    assert tracker.total_input_tokens == 1000
    assert tracker.total_output_tokens == 200


def test_record_accumulates_across_multiple_calls():
    tracker = ApiCallTracker(max_calls=5)
    tracker.record(reason="initial batch", rule_ids=["A-1"], usage=_FakeUsage(1000, 200))
    tracker.record(reason="retry 1/2", rule_ids=["A-1"], usage=_FakeUsage(500, 100))
    assert tracker.count == 2
    assert tracker.total_input_tokens == 1500
    assert tracker.total_output_tokens == 300


def test_estimated_cost_uses_real_pricing():
    tracker = ApiCallTracker(max_calls=5)
    # 1,000,000 input tokens + 1,000,000 output tokens at $2.00/$10.00 per MTok = $12.00
    tracker.record(reason="initial batch", rule_ids=["A-1"], usage=_FakeUsage(1_000_000, 1_000_000))
    assert tracker.estimated_cost() == pytest.approx(12.00)


def test_check_before_call_does_not_raise_under_cap():
    tracker = ApiCallTracker(max_calls=2)
    tracker.check_before_call()  # count=0, cap=2 -> fine
    tracker.record(reason="c1", rule_ids=[], usage=_FakeUsage(0, 0))
    tracker.check_before_call()  # count=1, cap=2 -> still fine


def test_check_before_call_raises_at_cap_before_incrementing():
    tracker = ApiCallTracker(max_calls=1)
    tracker.record(reason="c1", rule_ids=[], usage=_FakeUsage(0, 0))
    assert tracker.count == 1
    with pytest.raises(ApiCallCapExceeded):
        tracker.check_before_call()
    # The failed check must not itself count as a call.
    assert tracker.count == 1


def test_no_cap_means_unlimited():
    tracker = ApiCallTracker(max_calls=None)
    for _ in range(10):
        tracker.check_before_call()
        tracker.record(reason="c", rule_ids=[], usage=_FakeUsage(1, 1))
    assert tracker.count == 10
