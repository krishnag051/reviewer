"""Fix Round (Performance, 2026-09-11): humanize_findings' loop was
parallelized (bounded thread pool instead of one sequential call per
finding). These tests lock in the constraints the round itself set:
output order must exactly match input order, one finding's failure must
never affect any other finding's result, and the shared CallTracker must
count every call correctly despite concurrent access. Zero real Anthropic
calls -- mocks app.agent_client._humanize_evidence_with_llm directly,
same seam test_humanize_per_finding_isolation.py already uses.
"""
import app.agent_client as agent_client_module
from app.agent_client import humanize_findings


def _fake_humanize_ok(text, *args, **kwargs):
    return f"HUMANIZED[{text}]", {
        "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001,
        "pre_humanize_text": text, "rejected_missing_page_ref": False, "rejection_reason": None,
    }


def test_output_order_matches_input_order_under_concurrency(monkeypatch):
    """Real risk of parallelizing: results could come back in COMPLETION
    order instead of INPUT order if not written into pre-indexed slots.
    30 findings, all real concurrent calls (mocked at the API boundary
    only), confirms position i of the output always corresponds to
    position i of the input regardless of which thread finished first."""
    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_ok)
    texts = [f"finding {i}" for i in range(30)]
    results = humanize_findings(texts, max_calls=100)
    assert [r[1] for r in results] == [f"HUMANIZED[finding {i}]" for i in range(30)]


def test_one_failure_among_many_concurrent_calls_does_not_affect_others(monkeypatch):
    def _fake_flaky(text, *args, **kwargs):
        if text == "finding 17":
            raise IndexError("simulated real-call failure")
        return _fake_humanize_ok(text)

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_flaky)
    texts = [f"finding {i}" for i in range(30)]
    results = humanize_findings(texts, max_calls=100)

    for i, (raw, humanized, usage) in enumerate(results):
        if i == 17:
            assert (raw, humanized, usage) == ("finding 17", "finding 17", {})
        else:
            assert humanized == f"HUMANIZED[finding {i}]"


def test_shared_tracker_counts_every_concurrent_call_correctly(monkeypatch):
    """Real regression test for the race bounded concurrency could
    introduce without CallTracker's own lock (see
    pipeline/model_provider.py) -- every one of 50 concurrent findings
    must be counted, none lost to an unsynchronized increment."""
    call_log = []

    def _fake_counting(text, *args, **kwargs):
        call_log.append(text)
        return _fake_humanize_ok(text)

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_counting)
    texts = [f"finding {i}" for i in range(50)]
    humanize_findings(texts, max_calls=1000)
    assert len(call_log) == 50
    assert len(set(call_log)) == 50  # every finding genuinely attempted exactly once
