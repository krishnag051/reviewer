"""Next Round (2026-08-27), Part 1: humanize_evidence_with_llm. Mocked-
boundary tests (same standing convention as every other real-Anthropic
call site's own test file in this repo, e.g. test_call_tracker_wiring.py)
-- zero real spend on every future run of this file. The actual real,
billed verification (5-8 real calls, real before/after, real measured
cost) was run once, manually, and is reported in chat/the round's own
report, not repeated here on every CI run.
"""
from types import SimpleNamespace

from pipeline.humanize import humanize_evidence_with_llm, _PLACEHOLDER_TEMPLATE


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, input_tokens=100, output_tokens=20, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, response_text, input_tokens=100, output_tokens=20, stop_reason="end_turn"):
        self._response_text = response_text
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._response_text, self._input_tokens, self._output_tokens, self._stop_reason)


class _FakeClient:
    def __init__(self, response_text, input_tokens=100, output_tokens=20, stop_reason="end_turn"):
        self.messages = _FakeMessages(response_text, input_tokens, output_tokens, stop_reason)


def test_returns_deterministic_cleanup_unchanged_for_empty_text():
    rewritten, usage = humanize_evidence_with_llm("", client=_FakeClient("should never be used"))
    assert rewritten == ""
    assert usage == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "pre_humanize_text": ""}


def test_usage_always_includes_the_pre_humanize_text():
    fake = _FakeClient(f"Rewritten with {_PLACEHOLDER_TEMPLATE.format(i=0)} kept.")
    _, usage = humanize_evidence_with_llm("Some evidence: 8.0 [Page 4] here.", client=fake)
    # The deterministic pass already ran (8.0 -> 8) -- pre_humanize_text
    # is what the LLM actually saw, not the truly-raw original.
    assert usage["pre_humanize_text"] == "Some evidence: 8 [Page 4] here."


def test_makes_no_call_at_all_for_empty_text():
    fake = _FakeClient("should never be used")
    humanize_evidence_with_llm("", client=fake)
    assert fake.messages.calls == []


def test_real_call_shape_sends_system_prompt_and_protected_text():
    fake = _FakeClient("Rewritten text.")
    humanize_evidence_with_llm("Some evidence [Page 4] here.", client=fake)
    assert len(fake.messages.calls) == 1
    call = fake.messages.calls[0]
    assert call["model"] == "claude-haiku-4-5"
    assert "system" in call
    sent_text = call["messages"][0]["content"]
    assert "[Page" not in sent_text  # the real tag must never reach the model
    assert _PLACEHOLDER_TEMPLATE.format(i=0) in sent_text


def test_successful_rewrite_restores_page_tag_correctly():
    fake = _FakeClient(f"Rewritten with {_PLACEHOLDER_TEMPLATE.format(i=0)} kept in place.")
    rewritten, usage = humanize_evidence_with_llm("Some evidence [Page 4] here.", client=fake)
    assert rewritten == "Rewritten with [Page 4] kept in place."
    assert usage["rejected_missing_page_ref"] is False
    assert usage["rejection_reason"] is None


def test_successful_rewrite_restores_multiple_page_tags_in_original_order():
    text = "Found on [Page 6] and also on [Page 9]."
    fake = _FakeClient(
        f"It showed up on {_PLACEHOLDER_TEMPLATE.format(i=0)} and {_PLACEHOLDER_TEMPLATE.format(i=1)} too."
    )
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == "It showed up on [Page 6] and [Page 9] too."
    assert usage["rejected_missing_page_ref"] is False


def test_rejects_rewrite_and_falls_back_when_a_page_ref_is_dropped():
    """The exact real failure mode a real, cheap test run caught: the
    model 'explaining' a placeholder instead of copying it through. This
    locks that safety net in as a real, permanent regression test."""
    text = "Found on [Page 6] and also on [Page 9]."
    fake = _FakeClient("It showed up in location 0 and location 1 too.")  # drops both real tokens
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == "Found on [Page 6] and also on [Page 9]."  # deterministic-only fallback
    assert usage["rejected_missing_page_ref"] is True
    assert usage["rejection_reason"] == "missing_page_ref"


def test_rejects_rewrite_when_the_model_invents_a_stray_out_of_range_page_ref():
    """Fix Round (2026-08-27): the real bug, confirmed via an actual crash
    on a real staging upload -- the model echoed back an EXTRA, out-of-
    range placeholder (PAGEREF1 when only PAGEREF0 was ever sent) on top
    of the real one. The old safety net only checked "every real token
    present, exactly once" -- that check alone passes here (PAGEREF0 IS
    present, exactly once), so the old code would have gone on to crash
    in _restore_page_tags with IndexError: list index out of range trying
    tags[1] on a 1-element list. Confirms this is now caught and rejected
    BEFORE _restore_page_tags ever runs, not crashing.
    """
    text = "Found on [Page 6]."  # only ONE real tag -> tags == ["[Page 6]"], valid index range is {0}
    fake = _FakeClient(f"Found on {_PLACEHOLDER_TEMPLATE.format(i=0)} and also {_PLACEHOLDER_TEMPLATE.format(i=1)}.")
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == text  # deterministic-only fallback, not a crash
    assert usage["rejected_missing_page_ref"] is True
    assert usage["rejection_reason"] == "stray_page_ref"


def test_rejects_rewrite_when_a_page_ref_is_duplicated_instead_of_one_of_each():
    text = "Found on [Page 6] and also on [Page 9]."
    fake = _FakeClient(
        f"Found on {_PLACEHOLDER_TEMPLATE.format(i=0)} and {_PLACEHOLDER_TEMPLATE.format(i=0)} too."
    )
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == text
    assert usage["rejected_missing_page_ref"] is True


def test_real_measured_usage_and_cost_are_returned_not_estimated():
    fake = _FakeClient("Rewritten.", input_tokens=619, output_tokens=45)
    _, usage = humanize_evidence_with_llm("Some text with no page tag.", client=fake)
    assert usage["input_tokens"] == 619
    assert usage["output_tokens"] == 45
    # $1.00/Mtok input, $5.00/Mtok output -- real, current claude-haiku-4-5 pricing.
    expected_cost = (619 / 1_000_000) * 1.00 + (45 / 1_000_000) * 5.00
    assert abs(usage["cost_usd"] - expected_cost) < 1e-9


def test_runs_the_free_deterministic_pass_first():
    """The LLM never even sees the float artifact/list-repr -- confirms
    the deterministic pass genuinely runs first, not just documented to."""
    fake = _FakeClient("Rewritten.")
    humanize_evidence_with_llm("97151 hours requested: 8.0, exceeds the cap.", client=fake)
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "8.0" not in sent_text
    assert "8," in sent_text or "8 " in sent_text
