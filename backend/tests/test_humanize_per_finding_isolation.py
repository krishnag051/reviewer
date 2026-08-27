"""Fix Round (2026-08-27): the real bug, confirmed via an actual crash on a
real staging upload -- see app/agent_client.py::humanize_findings' own
docstring for the full story. Two things locked in here:

1. One finding's humanize_finding call failing (for ANY reason -- these
   tests use a plain injected exception, not the specific stray-page-ref
   bug, since that bug itself is already covered directly in agent-
   making's own test_fix_round_llm_humanize.py) no longer takes down the
   whole batch.
2. Every OTHER finding in the same batch keeps its own real,
   already-computed result -- it isn't silently replaced with raw text
   just because a sibling finding in the same call failed.

Mocks app.agent_client._humanize_evidence_with_llm directly (the same
seam tests/conftest.py's own guardrail patches) -- zero real Anthropic
API calls anywhere in this file.
"""
import app.agent_client as agent_client_module
from app.agent_client import humanize_findings


def _fake_humanize_ok(text, *args, **kwargs):
    return f"HUMANIZED[{text}]", {
        "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001,
        "pre_humanize_text": text, "rejected_missing_page_ref": False, "rejection_reason": None,
    }


def test_one_finding_failing_does_not_take_down_the_whole_batch(monkeypatch):
    call_count = {"n": 0}

    def _fake_humanize_flaky(text, *args, **kwargs):
        call_count["n"] += 1
        if text == "bad finding":
            raise IndexError("list index out of range")  # the exact real bug's own exception type
        return _fake_humanize_ok(text)

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_flaky)

    texts = ["good finding 1", "bad finding", "good finding 2"]
    results = humanize_findings(texts, max_calls=10)

    assert len(results) == 3
    # The two good findings kept their real humanized result.
    assert results[0] == ("good finding 1", "HUMANIZED[good finding 1]", {
        "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0001,
        "pre_humanize_text": "good finding 1", "rejected_missing_page_ref": False, "rejection_reason": None,
    })
    assert results[2][1] == "HUMANIZED[good finding 2]"
    # The bad finding fell back to its own raw text, not a crash.
    assert results[1] == ("bad finding", "bad finding", {})
    # All three were genuinely attempted -- the failure didn't short-circuit the loop.
    assert call_count["n"] == 3


def test_every_finding_gets_its_own_real_result_when_none_fail(monkeypatch):
    """Confirms the isolation wrapper doesn't change anything about the
    happy path -- every finding still gets its own genuinely distinct
    real humanized result, not some shared/collapsed value."""
    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_ok)

    texts = ["finding A", "finding B", "finding C"]
    results = humanize_findings(texts, max_calls=10)

    humanized_texts = [r[1] for r in results]
    assert humanized_texts == ["HUMANIZED[finding A]", "HUMANIZED[finding B]", "HUMANIZED[finding C]"]
    assert len(set(humanized_texts)) == 3  # genuinely distinct, not collapsed to one shared fallback


def test_failure_is_logged_with_the_specific_label_not_just_generically(monkeypatch):
    """Next Round, item 3: a failure must be traceable to a specific
    finding, not just 'something in the batch failed.' Monkeypatches the
    module's own logger.exception directly rather than going through
    caplog, which doesn't reliably capture this codebase's logger
    hierarchy under TestClient -- same workaround already used for this
    exact reason in tests/test_real_api_guardrail.py's own history.
    """
    logged_calls = []
    monkeypatch.setattr(agent_client_module.logger, "exception", lambda msg, *args: logged_calls.append((msg, args)))

    def _fake_humanize_always_fails(text, *args, **kwargs):
        raise RuntimeError("simulated real-call failure")

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_always_fails)

    humanize_findings(["some evidence text"], max_calls=10, labels=["QA-TEMP-01"])

    assert len(logged_calls) == 1
    msg, args = logged_calls[0]
    assert "falling back to raw" in msg
    assert args == ("QA-TEMP-01",)


def test_falls_back_to_positional_index_label_when_no_labels_given(monkeypatch):
    logged_calls = []
    monkeypatch.setattr(agent_client_module.logger, "exception", lambda msg, *args: logged_calls.append((msg, args)))

    def _fake_humanize_always_fails(text, *args, **kwargs):
        raise RuntimeError("simulated real-call failure")

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_always_fails)

    humanize_findings(["some evidence text"], max_calls=10)

    assert len(logged_calls) == 1
    _, args = logged_calls[0]
    assert args == ("finding at index 0",)


def test_multiple_failures_each_fall_back_independently(monkeypatch):
    def _fake_humanize_all_fail(text, *args, **kwargs):
        raise ValueError("boom")

    monkeypatch.setattr(agent_client_module, "_humanize_evidence_with_llm", _fake_humanize_all_fail)

    results = humanize_findings(["a", "b", "c"], max_calls=10)
    assert results == [("a", "a", {}), ("b", "b", {}), ("c", "c", {})]
