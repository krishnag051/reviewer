"""Fix Round (2026-08-27): REAL PRODUCTION CRASH, confirmed via a real 500
-- GET /api/uploads/:id/session-notes/:id/extraction crashed because a
cache entry written before `note_detail_level` was added to
SessionNoteExtraction's shape (the QA-COC-01 fix round) fails Pydantic
validation, uncaught. See app/agent_client.py::extract_session_note's own
docstring for the fix: catch the ValidationError, retry exactly once with
force_refresh=True (skips the stale cached read, forces one real fresh
extraction, and -- unlike use_cache=False -- still re-caches the fresh
result so this file self-heals for every read after this one).

Mocks app.agent_client._extract_session_note_file directly -- zero real
model calls anywhere in this file.
"""
import pytest
from pydantic import ValidationError

import app.agent_client as agent_client_module
from app.agent_client import SessionNoteExtraction, extract_session_note

_VALID_FIELD = {"value": "09/20/2026", "confidence": "high", "source_quote": "q"}

# The pre-note_detail_level shape -- exactly what a stale cache entry from
# before that field existed would look like on disk.
_STALE_SHAPE_RAW = {
    "session_date": _VALID_FIELD,
    "session_location": _VALID_FIELD,
    "clinician_telehealth_location": _VALID_FIELD,
    "patient_telehealth_location": _VALID_FIELD,
    "assessment_activity": _VALID_FIELD,
    # note_detail_level deliberately absent -- the real bug.
}

_CURRENT_SHAPE_RAW = {**_STALE_SHAPE_RAW, "note_detail_level": _VALID_FIELD}


def test_stale_cache_shape_confirmed_to_fail_validation_directly():
    """Sanity check on the fixture itself -- confirms _STALE_SHAPE_RAW
    genuinely reproduces the real crash (SessionNoteExtraction(**raw)
    raising ValidationError), not a fixture that happens to validate fine."""
    with pytest.raises(ValidationError):
        SessionNoteExtraction(**_STALE_SHAPE_RAW)


def test_stale_cached_shape_triggers_a_clean_re_extraction_not_a_crash(monkeypatch):
    calls = []

    def _fake_extract(file_path, *, tracker=None, model_override=None, force_refresh=False):
        calls.append(force_refresh)
        if not force_refresh:
            return _STALE_SHAPE_RAW  # the stale cache "hit"
        return _CURRENT_SHAPE_RAW  # the forced fresh re-extraction

    monkeypatch.setattr(agent_client_module, "_extract_session_note_file", _fake_extract)

    result = extract_session_note("some/path.pdf")

    assert isinstance(result, SessionNoteExtraction)
    assert result.note_detail_level.value == "09/20/2026"
    # Confirms the real end-user result is still produced -- not swallowed
    # into an empty/None response.
    assert result.session_date.value == "09/20/2026"
    # Confirms exactly one retry happened, with force_refresh=True the
    # second time -- not use_cache=False, and not more than one retry.
    assert calls == [False, True]


def test_a_genuinely_valid_current_shape_cache_hit_is_unaffected_no_retry(monkeypatch):
    """Don't accidentally make every cache hit re-extract -- a current-
    shape cached read must load instantly with exactly one call, no retry."""
    calls = []

    def _fake_extract(file_path, *, tracker=None, model_override=None, force_refresh=False):
        calls.append(force_refresh)
        return _CURRENT_SHAPE_RAW

    monkeypatch.setattr(agent_client_module, "_extract_session_note_file", _fake_extract)

    result = extract_session_note("some/path.pdf")

    assert isinstance(result, SessionNoteExtraction)
    assert calls == [False], "a genuinely valid cached read must never trigger a force_refresh retry"


def test_a_second_genuinely_broken_extraction_still_raises_not_silently_retried_forever():
    """If the SECOND attempt (force_refresh=True) ALSO fails validation,
    that's a real, different bug -- must surface loudly, not be silently
    swallowed or retried again."""
    import app.agent_client as acm

    def _fake_extract_always_stale(file_path, *, tracker=None, model_override=None, force_refresh=False):
        return _STALE_SHAPE_RAW  # broken even after force_refresh

    import pytest as _pytest
    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(acm, "_extract_session_note_file", _fake_extract_always_stale)
        with pytest.raises(ValidationError):
            extract_session_note("some/path.pdf")
