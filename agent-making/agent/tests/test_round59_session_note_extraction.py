"""Round 59, Step 1: extraction mechanics + local cache. Most of this file
is mocked (zero network) -- one test at the bottom makes a real call to
the free OpenRouter model, against a clearly-labeled SYNTHETIC session
note (explicitly NOT Yisroel Leibowitz's, Kendra Djissodey's, or Charny
Gluck's real data -- his real session-note file doesn't exist yet this
round, and the round's own instructions say not to fabricate one to stand
in for it). That real call proves the wiring genuinely works end to end,
ready for his real file the moment it's uploaded -- it does not claim to
have verified anything about his actual session notes.
"""
import json

import pytest

from pipeline.model_provider import CallTracker
from pipeline.session_note_extraction import (
    SESSION_NOTE_FIELDS,
    _build_prompt,
    _content_hash,
    _normalize,
    extract_session_note_file,
    extract_session_note_text,
)

# Deliberately synthetic -- see module docstring. Never presented as real
# patient data anywhere in this file's assertions or output.
SYNTHETIC_SESSION_NOTE_TEXT = """
ABA Session Note (SYNTHETIC TEST FIXTURE -- not a real patient)
Session Date: 09/20/2026
Place of Service: Office
Assessment Activity: [x] Direct observation   [ ] Interview   [ ] Review records
Notes: Standard in-person session, no telehealth component.
"""


# ------------------------------------------------------------- pure helpers


def test_prompt_lists_all_5_fields():
    prompt = _build_prompt("irrelevant text")
    for field in SESSION_NOTE_FIELDS:
        assert field in prompt


def test_normalize_fills_in_missing_field_as_honest_none():
    normalized = _normalize({"session_date": {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}})
    assert normalized["session_date"]["value"] == "09/20/2026"
    for field in SESSION_NOTE_FIELDS:
        if field != "session_date":
            assert normalized[field] == {"value": None, "confidence": "none", "source_quote": None}


def test_normalize_rejects_an_invalid_confidence_value():
    normalized = _normalize({
        "session_date": {"value": "x", "confidence": "extremely-sure", "source_quote": "q"},
    })
    assert normalized["session_date"] == {"value": None, "confidence": "none", "source_quote": None}


def test_normalize_guarantees_every_field_present_even_from_an_empty_dict():
    normalized = _normalize({})
    assert set(normalized.keys()) == set(SESSION_NOTE_FIELDS)
    assert all(v["confidence"] == "none" for v in normalized.values())


# ------------------------------------------------------- mocked extraction


def _full_extraction_result(**overrides) -> dict:
    result = {f: {"value": None, "confidence": "none", "source_quote": None} for f in SESSION_NOTE_FIELDS}
    result.update(overrides)
    return result


def test_extract_session_note_text_calls_through_model_provider_and_counts_tracker(monkeypatch):
    import pipeline.session_note_extraction as sne

    captured = {}

    def _fake_call_tool_json(**kwargs):
        captured.update(kwargs)
        tracker = kwargs["tracker"]
        tracker.record(reason="fake", provider="openrouter", model="fake-model", usage={"input_tokens": 5, "output_tokens": 5})
        return {"session_date": {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}}

    monkeypatch.setattr(sne, "call_tool_json", _fake_call_tool_json)

    tracker = CallTracker(max_calls=5)
    result = extract_session_note_text("some text", tracker=tracker)

    assert result["session_date"]["value"] == "09/20/2026"
    assert result["session_location"]["confidence"] == "none"  # normalized, not left out
    assert tracker.count == 1
    assert captured["tool_name"] == "record_session_note_extraction"
    assert "some text" in captured["prompt_text"]


def test_extract_session_note_file_missing_file_raises_before_any_call(monkeypatch, tmp_path):
    import pipeline.session_note_extraction as sne

    def _should_never_be_called(**kwargs):
        pytest.fail("call_tool_json must never be reached for a missing file")

    monkeypatch.setattr(sne, "call_tool_json", _should_never_be_called)
    tracker = CallTracker(max_calls=5)
    with pytest.raises(FileNotFoundError):
        extract_session_note_file(str(tmp_path / "does-not-exist.txt"), tracker=tracker)
    assert tracker.count == 0


def test_extract_session_note_file_caches_and_a_second_call_makes_zero_additional_calls(monkeypatch, tmp_path):
    import pipeline.session_note_extraction as sne

    call_count = {"n": 0}

    def _fake_call_tool_json(**kwargs):
        call_count["n"] += 1
        tracker = kwargs["tracker"]
        tracker.record(reason="fake", provider="openrouter", model="fake-model", usage={"input_tokens": 5, "output_tokens": 5})
        return {"session_date": {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}}

    monkeypatch.setattr(sne, "call_tool_json", _fake_call_tool_json)
    # Isolate this test's cache from the repo's real .cache directory.
    monkeypatch.setattr(sne, "_CACHE_DIR", tmp_path / "cache")

    note_file = tmp_path / "note.txt"
    note_file.write_text("a synthetic note, for caching-mechanics testing only", encoding="utf-8")

    tracker = CallTracker(max_calls=5)
    first = extract_session_note_file(str(note_file), tracker=tracker)
    assert call_count["n"] == 1
    assert tracker.count == 1

    second = extract_session_note_file(str(note_file), tracker=tracker)
    assert call_count["n"] == 1, "identical file content must be a cache hit -- zero additional model calls"
    assert tracker.count == 1, "the tracker must not move on a cache hit either"
    assert second == first


def test_extract_session_note_file_use_cache_false_always_calls_through(monkeypatch, tmp_path):
    import pipeline.session_note_extraction as sne

    call_count = {"n": 0}

    def _fake_call_tool_json(**kwargs):
        call_count["n"] += 1
        tracker = kwargs["tracker"]
        tracker.record(reason="fake", provider="openrouter", model="fake-model", usage={"input_tokens": 5, "output_tokens": 5})
        return {"session_date": {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}}

    monkeypatch.setattr(sne, "call_tool_json", _fake_call_tool_json)
    monkeypatch.setattr(sne, "_CACHE_DIR", tmp_path / "cache")

    note_file = tmp_path / "note.txt"
    note_file.write_text("another synthetic note", encoding="utf-8")

    tracker = CallTracker(max_calls=5)
    extract_session_note_file(str(note_file), tracker=tracker, use_cache=False)
    extract_session_note_file(str(note_file), tracker=tracker, use_cache=False)
    assert call_count["n"] == 2


def test_different_file_content_is_a_different_cache_key(monkeypatch, tmp_path):
    import pipeline.session_note_extraction as sne

    def _fake_call_tool_json(**kwargs):
        tracker = kwargs["tracker"]
        tracker.record(reason="fake", provider="openrouter", model="fake-model", usage={"input_tokens": 5, "output_tokens": 5})
        return {"session_date": {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}}

    monkeypatch.setattr(sne, "call_tool_json", _fake_call_tool_json)
    monkeypatch.setattr(sne, "_CACHE_DIR", tmp_path / "cache")

    file_a = tmp_path / "a.txt"
    file_a.write_text("content A", encoding="utf-8")
    file_b = tmp_path / "b.txt"
    file_b.write_text("content B", encoding="utf-8")

    assert _content_hash(file_a.read_bytes()) != _content_hash(file_b.read_bytes())

    tracker = CallTracker(max_calls=5)
    extract_session_note_file(str(file_a), tracker=tracker)
    extract_session_note_file(str(file_b), tracker=tracker)
    assert tracker.count == 2, "different content must not share a cache entry"


# ------------------------------------ ONE real call, proving the OpenRouter
# wiring works end to end (default provider, free model) -- see module
# docstring. Not gated behind a marker: OpenRouter's free tier is this
# round's sanctioned default for building/testing, per the round's own
# instructions. Still counted by the session-wide ceiling fixture in
# conftest.py like any other real call.


def test_real_openrouter_extraction_against_a_synthetic_session_note():
    tracker = CallTracker(max_calls=3)
    result = extract_session_note_text(SYNTHETIC_SESSION_NOTE_TEXT, tracker=tracker)

    assert tracker.count == 1
    assert set(result.keys()) == set(SESSION_NOTE_FIELDS)
    for field in SESSION_NOTE_FIELDS:
        assert result[field]["confidence"] in ("high", "medium", "low", "none")

    # The synthetic note states a session date and POS plainly -- a
    # competent extraction should find them with real confidence, not
    # "none". Session date first, since it's the field this round's
    # comparison logic actually depends on.
    assert result["session_date"]["confidence"] != "none", (
        f"expected a real session_date extraction from the synthetic note; got {result['session_date']}"
    )
    print(f"[round59] real OpenRouter extraction result:\n{json.dumps(result, indent=2)}")

    # The synthetic note explicitly says "no telehealth component" -- an
    # honest extraction should NOT invent a telehealth location for either
    # side just because the fields exist in the schema.
    assert result["clinician_telehealth_location"]["confidence"] == "none", (
        f"the synthetic note has no telehealth component; the model must not guess a location anyway. "
        f"got {result['clinician_telehealth_location']}"
    )
