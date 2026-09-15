"""Fix Round (2026-08-27): real production bugs found in a real completed
review (patient Amir, upload EX001-U7).

Bug 1 -- PAGEREF placeholders leaking into reviewer-facing evidence text,
confirmed root cause: adjacent placeholder tokens (no separator between
them, e.g. from a merged/concatenated tie-break evidence string) broke the
old \\b-word-boundary-anchored regex, both for restoration itself AND for
the safety net meant to catch exactly this. Fixed by making the placeholder
template self-delimiting.

Bug 2 -- long tie-break/merge evidence cut off mid-sentence with no
indication, confirmed root cause: humanize's own real rewrite call had
max_tokens=200 with no truncation check at all.

Bug 3 -- raw internal field names/status tokens leaking into evidence text
(covered directly in test_fix_round_bucketcd.py's own gip02 test and the
session_note_comparison/judge module docstrings -- the before/after text
examples are in this round's own report).

Mocks the Anthropic client boundary directly -- zero real API spend.
"""
from types import SimpleNamespace

from pipeline.humanize import (
    _PLACEHOLDER_RE,
    _PLACEHOLDER_TEMPLATE,
    _protect_page_tags,
    _restore_page_tags,
    humanize_evidence_with_llm,
)
from pipeline.judge import _natural_result_phrase, _three_way_majority_finding, _two_way_uncertain_finding


class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text, input_tokens=100, output_tokens=20, stop_reason="end_turn"):
        self.content = [_FakeTextBlock(text)]
        self.usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
        self.stop_reason = stop_reason


class _FakeClient:
    def __init__(self, response_text, stop_reason="end_turn"):
        messages = SimpleNamespace()
        messages.create = lambda **kwargs: _FakeResponse(response_text, stop_reason=stop_reason)
        self.messages = messages


# --- Bug 1: adjacent PAGEREF tokens -----------------------------------------

def test_protect_and_restore_survive_adjacent_page_tags_with_no_separator():
    """The exact real shape: multiple [Page N] citations with NO whitespace
    between them (e.g. from a merged tie-break evidence string), confirmed
    real via the round's own reported example ('...narrative [Page 1]
    [Page 4][Page 71] -- all accounted...')."""
    text = "Evidence accounted for on [Page 1][Page 4][Page 71] -- all consistent."
    protected, tags = _protect_page_tags(text)
    assert tags == ["[Page 1]", "[Page 4]", "[Page 71]"]
    # Old \b-anchored regex would find zero matches here -- confirm the
    # fixed regex finds all three, even fully adjacent with no separator.
    found = _PLACEHOLDER_RE.findall(protected)
    assert found == ["0", "1", "2"]
    restored = _restore_page_tags(protected, tags)
    assert restored == text


def test_humanize_restores_adjacent_page_tags_through_a_real_rewrite_call():
    """End-to-end: the model faithfully copies the adjacent placeholder run
    through unchanged (the realistic case for a well-behaved model), and
    restoration must actually replace all three, not silently leave any
    PAGEREF token in the final text."""
    text = "Evidence accounted for on [Page 1][Page 4][Page 71] -- all consistent."
    placeholder_run = (
        _PLACEHOLDER_TEMPLATE.format(i=0) + _PLACEHOLDER_TEMPLATE.format(i=1) + _PLACEHOLDER_TEMPLATE.format(i=2)
    )
    fake = _FakeClient(f"Accounted for on {placeholder_run} -- all consistent.")
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert "PAGEREF" not in rewritten
    assert "[Page 1]" in rewritten and "[Page 4]" in rewritten and "[Page 71]" in rewritten
    assert usage["rejected_missing_page_ref"] is False


def test_safety_net_still_catches_a_genuinely_missing_adjacent_tag():
    """Confirms the fix didn't accidentally make the safety net blind to a
    REAL missing-token case just because tokens are adjacent -- if the
    model drops one of three adjacent tags, that must still be caught."""
    text = "Evidence accounted for on [Page 1][Page 4][Page 71] -- all consistent."
    # Only 2 of 3 adjacent placeholders echoed back -- PAGEREF1 dropped.
    placeholder_run = _PLACEHOLDER_TEMPLATE.format(i=0) + _PLACEHOLDER_TEMPLATE.format(i=2)
    fake = _FakeClient(f"Accounted for on {placeholder_run} -- all consistent.")
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == text  # falls back to the deterministic-only original
    assert usage["rejected_missing_page_ref"] is True
    assert usage["rejection_reason"] == "missing_page_ref"


# --- Bug 2: truncated rewrite (max_tokens hit) ------------------------------

def test_truncated_response_is_rejected_falls_back_to_raw_text():
    text = "A long tie-break disagreement summary that runs on for a while [Page 12]."
    fake = _FakeClient(
        f"A long summary that runs on for a while {_PLACEHOLDER_TEMPLATE.format(i=0)} and then just stops mid",
        stop_reason="max_tokens",
    )
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == text  # deterministic-only fallback, not the truncated text
    assert usage["rejected_missing_page_ref"] is True
    assert usage["rejection_reason"] == "truncated"


def test_truncated_response_is_rejected_even_when_all_page_tags_survived():
    """The real confirmed shape: truncation landing in a TRAILING clause
    after every page citation was already restated -- the page-ref checks
    alone would have passed this, so this specifically tests the NEW,
    separate truncation check."""
    text = "Findings on [Page 8] confirm the pattern, and the narrative continues further."
    fake = _FakeClient(
        f"Findings on {_PLACEHOLDER_TEMPLATE.format(i=0)} confirm the pattern, and the narrative continues fur",
        stop_reason="max_tokens",
    )
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert rewritten == text
    assert usage["rejection_reason"] == "truncated"


def test_a_normal_complete_response_is_not_rejected_as_truncated():
    text = "Some evidence [Page 4] here."
    fake = _FakeClient(f"Some evidence {_PLACEHOLDER_TEMPLATE.format(i=0)} here.", stop_reason="end_turn")
    rewritten, usage = humanize_evidence_with_llm(text, client=fake)
    assert usage["rejected_missing_page_ref"] is False
    assert usage["rejection_reason"] is None


# --- Bug 3: natural-language result phrasing in tie-break summaries --------

def test_natural_result_phrase_covers_every_real_result_value():
    assert _natural_result_phrase("pass") == "pass"
    assert _natural_result_phrase("fail") == "fail"
    assert _natural_result_phrase("uncertain") == "this is uncertain"
    assert _natural_result_phrase("not_applicable") == "this doesn't apply"
    assert _natural_result_phrase("not_checkable") == "this can't be checked"


def test_two_way_disagreement_summary_has_no_raw_snake_case_status_tokens():
    """Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    _short_uncertain_summary now surfaces each side's real evidence text
    and a plain-English result label -- confirms the real invariant this
    test protects (no internal snake_case tokens leak into reviewer-facing
    text) still holds under the new, substance-bearing message, and that
    the real evidence text from both sides is actually present."""
    f = {"result": "not_applicable", "evidence": "Evidence A", "page": None, "confidence": 0.5}
    s = {"result": "not_checkable", "evidence": "Evidence B", "page": None, "confidence": 0.5}
    result = _two_way_uncertain_finding(f, s)
    assert "not_applicable" not in result["evidence"]
    assert "not_checkable" not in result["evidence"]
    assert "doesn't apply" in result["evidence"]
    assert "can't be checked" in result["evidence"]
    assert "Evidence A" in result["evidence"]
    assert "Evidence B" in result["evidence"]
    assert "confirm manually" in result["evidence"].lower()


def test_three_way_split_summary_has_no_raw_snake_case_status_tokens():
    f = {"result": "pass", "evidence": "A", "page": None, "confidence": 0.5}
    s = {"result": "not_applicable", "evidence": "B", "page": None, "confidence": 0.5}
    t = {"result": "not_checkable", "evidence": "C", "page": None, "confidence": 0.5}
    result = _three_way_majority_finding(f, s, t)
    assert result["result"] == "uncertain"  # genuine 3-way split, no majority
    assert "not_applicable" not in result["evidence"]
    assert "not_checkable" not in result["evidence"]
