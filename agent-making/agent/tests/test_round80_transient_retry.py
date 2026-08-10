"""Live incident fix (2026-08): a real production failure --
OpenRouter's free-tier shared worker pool returning a 200-status response
wrapping "Upstream error from Nvidia: ResourceExhausted: Worker local
total request limit reached (32/32)" during session-note extraction --
used to propagate all the way up and fail the ENTIRE upload, discarding
every other rule's real, already-computed finding along with it.

Three layers, each tested here:
1. model_provider.py's call_tool_json retries a TransientModelCallError
   with backoff, but does NOT retry a plain (non-transient) ModelCallError.
2. session_note_extraction.py's extract_session_note_file catches an
   EXHAUSTED transient failure and returns an honest failure marker
   instead of raising; a non-transient error still raises, unchanged.
3. session_note_comparison.py's compare_session_notes_to_tp recognizes
   that marker and produces a real, distinctive not_checkable finding for
   the affected rule(s)/file, while every other file/rule passes through
   untouched.

Zero real network calls anywhere in this file -- every provider call site
is monkeypatched at the same seam test_round59_model_provider.py's own
tests already use.
"""
import pytest

from pipeline.model_provider import CallTracker, ModelCallError, TransientModelCallError, call_tool_json
from pipeline.session_note_comparison import compare_session_notes_to_tp
from pipeline.session_note_extraction import EXTRACTION_ERROR_KEY, extract_session_note_text


# --- Layer 1: call_tool_json's retry-with-backoff ---------------------------


def test_transient_error_is_retried_then_succeeds(monkeypatch):
    """Confirmed real shape: fails twice with the exact live-incident
    error text, then succeeds on the 3rd attempt -- within the default
    max_transient_retries=2 (3 total attempts) budget."""
    import pipeline.model_provider as mp

    attempts = {"n": 0}

    def fake_call_openrouter(**kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise TransientModelCallError(
                'OpenRouter response had no usable \'choices\' (status 200): {"error": {"message": '
                '"Upstream error from Nvidia: ResourceExhausted: Worker local total request limit '
                'reached (32/32)", "code": 502}}'
            )
        return {"arguments": {"ok": True}, "usage": {"input_tokens": 10, "output_tokens": 5}}

    monkeypatch.setattr(mp, "_call_openrouter", fake_call_openrouter)

    sleeps = []
    result = call_tool_json(
        prompt_text="x", tool_name="t", tool_description="d", input_schema={},
        tracker=CallTracker(), model_override="openrouter", sleep_fn=sleeps.append,
    )

    assert result == {"ok": True}
    assert attempts["n"] == 3
    # Short exponential backoff: 1s, then 2s (default backoff_seconds=1.0).
    assert sleeps == [1.0, 2.0]


def test_transient_error_raises_after_exhausting_retries(monkeypatch):
    """Confirmed shape: persistently transient (worker pool never frees
    up within the retry budget) -- must still raise eventually, not retry
    forever, and the caller (session_note_extraction.py) is what turns
    THIS into a graceful degradation, not this layer."""
    import pipeline.model_provider as mp

    attempts = {"n": 0}

    def always_transient(**kwargs):
        attempts["n"] += 1
        raise TransientModelCallError("Upstream error from Nvidia: ResourceExhausted: still full")

    monkeypatch.setattr(mp, "_call_openrouter", always_transient)

    sleeps = []
    with pytest.raises(TransientModelCallError):
        call_tool_json(
            prompt_text="x", tool_name="t", tool_description="d", input_schema={},
            tracker=CallTracker(), model_override="openrouter",
            max_transient_retries=2, sleep_fn=sleeps.append,
        )
    assert attempts["n"] == 3  # 1 initial + 2 retries
    assert sleeps == [1.0, 2.0]


def test_non_transient_error_is_never_retried(monkeypatch):
    """A genuinely broken request (bad schema, auth failure, anything
    that ISN'T the worker-pool-capacity shape) must raise on the FIRST
    attempt -- retrying it would just waste calls on a guaranteed failure,
    and could make a real bug look like "just flaky infrastructure."
    """
    import pipeline.model_provider as mp

    attempts = {"n": 0}

    def broken_request(**kwargs):
        attempts["n"] += 1
        raise ModelCallError("OpenRouter call failed: 401 Unauthorized")

    monkeypatch.setattr(mp, "_call_openrouter", broken_request)

    sleeps = []
    with pytest.raises(ModelCallError):
        call_tool_json(
            prompt_text="x", tool_name="t", tool_description="d", input_schema={},
            tracker=CallTracker(), model_override="openrouter", sleep_fn=sleeps.append,
        )
    assert attempts["n"] == 1
    assert sleeps == []  # never slept -- never retried


@pytest.mark.parametrize("error_text,expected_transient", [
    ('{"error": {"message": "Upstream error from Nvidia: ResourceExhausted: Worker local total '
     'request limit reached (32/32)", "code": 502}}', True),
    ('{"error": {"message": "Rate limit exceeded, please try again later."}}', True),
    ('{"error": {"message": "Invalid API key."}}', False),
    ('{"error": {"message": "This model does not support tool calling."}}', False),
])
def test_is_transient_error_text_classification(error_text, expected_transient):
    from pipeline.model_provider import _is_transient_error_text
    assert _is_transient_error_text(error_text) is expected_transient


# --- Layer 2: extract_session_note_file's graceful degradation -------------


def test_extraction_returns_failure_marker_not_raise_on_exhausted_transient_error(monkeypatch):
    import pipeline.session_note_extraction as sne

    def always_transient(**kwargs):
        raise TransientModelCallError("Upstream error from Nvidia: ResourceExhausted: still full")

    monkeypatch.setattr(sne, "call_tool_json", always_transient)

    result = extract_session_note_text("some session note text", tracker=object())

    assert EXTRACTION_ERROR_KEY in result
    assert "ResourceExhausted" in result[EXTRACTION_ERROR_KEY]
    # Every real field is still present, all confidence="none" -- a caller
    # that doesn't know about EXTRACTION_ERROR_KEY (e.g. the backend's own
    # Pydantic model) still gets something well-formed and harmless.
    for field in sne.SESSION_NOTE_FIELDS:
        assert result[field] == {"value": None, "confidence": "none", "source_quote": None}


def test_extraction_still_raises_on_a_non_transient_error(monkeypatch):
    """The whole point of distinguishing transient from non-transient:
    a real, permanent failure must still surface loudly, not get quietly
    absorbed into a not_checkable-shaped result."""
    import pipeline.session_note_extraction as sne

    def broken(**kwargs):
        raise ModelCallError("OpenRouter call failed: 401 Unauthorized")

    monkeypatch.setattr(sne, "call_tool_json", broken)

    with pytest.raises(ModelCallError):
        extract_session_note_text("some session note text", tracker=object())


# --- Layer 3: session_note_comparison.py's graceful degradation ------------


def _ok_extraction(session_date: str) -> dict:
    empty = {"value": None, "confidence": "none", "source_quote": None}
    return {
        "session_date": {"value": session_date, "confidence": "high", "source_quote": f"Session Date: {session_date}"},
        "session_location": dict(empty), "clinician_telehealth_location": dict(empty),
        "patient_telehealth_location": dict(empty), "assessment_activity": dict(empty),
    }


def _failed_extraction(error: str) -> dict:
    from pipeline.session_note_extraction import _extraction_failed_result
    return _extraction_failed_result(error)


def test_one_file_extraction_failure_among_several_becomes_not_checkable_others_unaffected():
    """The real shape this incident produced: 2 session notes uploaded,
    one extracts fine and is genuinely in the report's date range, the
    OTHER hit the upstream failure. RPT-03 must not silently pass (as if
    the failed file said nothing) or crash -- it must be not_checkable,
    with the real failure visible in the evidence, while still naming the
    OK file's own real result."""
    extractions = {
        "good_note.pdf": _ok_extraction("07/28/2026"),
        "bad_note.pdf": _failed_extraction("Upstream error from Nvidia: ResourceExhausted: still full"),
    }
    result = compare_session_notes_to_tp(
        extractions,
        tp_current_report_period="07/28/2026 to 08/03/2026",
        tp_assessment_date="07/28/2026",
    )
    assert result["QA-RPT-03"]["result"] == "not_checkable"
    assert "good_note.pdf" in result["QA-RPT-03"]["evidence"]
    assert "bad_note.pdf" in result["QA-RPT-03"]["evidence"]
    assert "ResourceExhausted" in result["QA-RPT-03"]["evidence"]
    # The good file's own real result is still visible in the combined
    # evidence -- not discarded because a SIBLING file failed.
    assert "falls within the current-report date range" in result["QA-RPT-03"]["evidence"]


def test_a_real_fail_on_another_file_still_takes_priority_over_a_sibling_extraction_failure():
    """A CONFIRMED real problem (a note genuinely outside the report
    range) is more actionable than "we couldn't check a different file"
    -- fail must win over not_checkable in the combined result."""
    extractions = {
        "out_of_range.pdf": _ok_extraction("01/01/2020"),
        "bad_note.pdf": _failed_extraction("Upstream error: still full"),
    }
    result = compare_session_notes_to_tp(
        extractions,
        tp_current_report_period="07/28/2026 to 08/03/2026",
        tp_assessment_date="07/28/2026",
    )
    assert result["QA-RPT-03"]["result"] == "fail"


def test_acf02_acf08_not_checkable_when_the_only_file_fails_extraction():
    """The failed file is the ONLY uploaded note -- it can never match the
    TP's stated assessment date (its own session_date is unreadable), so
    ACF-02/ACF-08 must land on a real, distinctive not_checkable, not the
    generic "no note's date matches" message (which would misleadingly
    imply every file was read fine)."""
    extractions = {"bad_note.pdf": _failed_extraction("Upstream error: still full")}
    result = compare_session_notes_to_tp(
        extractions,
        tp_current_report_period="07/28/2026 to 08/03/2026",
        tp_assessment_date="07/28/2026",
    )
    assert result["QA-ACF-02"]["result"] == "not_checkable"
    assert result["QA-ACF-08"]["result"] == "not_checkable"
    assert "could not be extracted" in result["QA-ACF-02"]["evidence"]


def test_acf02_acf08_unaffected_when_a_different_ok_file_matches():
    """A sibling file's extraction failure must not affect ACF-02/ACF-08
    at all when the REAL matching file extracted fine."""
    extractions = {
        "matching_note.pdf": _ok_extraction("07/28/2026"),
        "unrelated_bad_note.pdf": _failed_extraction("Upstream error: still full"),
    }
    result = compare_session_notes_to_tp(
        extractions,
        tp_current_report_period="07/28/2026 to 08/03/2026",
        tp_assessment_date="07/28/2026",
        tp_pos=None, tp_patient_location=None, tp_assessment_tool=None,
    )
    # Runs the real comparison against the matching file -- not forced
    # into not_checkable just because a sibling file failed.
    assert result["QA-ACF-02"]["result"] != "not_checkable"
    assert result["QA-ACF-08"]["result"] != "not_checkable"
