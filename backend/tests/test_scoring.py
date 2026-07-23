"""Dedicated unit coverage for app/services/scoring.py::compute_score.
Previously only exercised indirectly through 1-2 concrete scenarios inside
the finalize/override integration tests — this covers the edge cases that
were never actually asserted: all-na, uncertain excluded, mixed exclusion.
"""
from dataclasses import dataclass

from app.services.scoring import compute_score


@dataclass
class _FakeResult:
    final_status: str


def test_compute_score_all_pass():
    results = [_FakeResult("pass") for _ in range(5)]
    score, audit_result = compute_score(results)
    assert score == 100.0
    assert audit_result == "pass"


def test_compute_score_mixed_pass_fail():
    results = [_FakeResult("pass"), _FakeResult("pass"), _FakeResult("fail")]
    score, audit_result = compute_score(results)
    assert abs(score - (2 / 3 * 100)) < 0.0001
    assert audit_result == "fail"


def test_compute_score_all_na_returns_none():
    results = [_FakeResult("na") for _ in range(24)]
    score, audit_result = compute_score(results)
    assert score is None
    assert audit_result is None


def test_compute_score_empty_list_returns_none():
    score, audit_result = compute_score([])
    assert score is None
    assert audit_result is None


def test_compute_score_na_and_uncertain_excluded_from_denominator():
    """NA and uncertain must not count in either the numerator or the
    denominator — only pass/fail determine the score.
    """
    results = [
        _FakeResult("pass"),
        _FakeResult("na"),
        _FakeResult("na"),
        _FakeResult("uncertain"),
        _FakeResult("uncertain"),
    ]
    score, audit_result = compute_score(results)
    assert score == 100.0, "1 pass, 0 fail, rest excluded -> 100%, not diluted by na/uncertain"
    assert audit_result == "pass"


def test_compute_score_one_fail_among_many_passes_is_not_100():
    results = [_FakeResult("pass") for _ in range(23)] + [_FakeResult("fail")]
    score, audit_result = compute_score(results)
    assert score is not None and score < 100.0
    assert audit_result == "fail", "no critical-fail special case exists anymore — any fail means audit_result=fail only via score < 100"
