"""Fix Round -- Judgment Layer Stability, fix #1: document-level result
caching, keyed by content hash. Same exact pattern already proven in
tests/test_round59_session_note_extraction.py's own cache tests -- mirrored
here for pipeline/api.py::review_treatment_plan's new cache.

Zero real API spend -- run_full_pipeline is monkeypatched throughout.
"""
import fitz
import pytest

import pipeline.api as api_module


def _make_pdf(path, text="a synthetic TP, for caching-mechanics testing only"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    doc.save(str(path))
    doc.close()


def _fake_complete_result(rule_count=2):
    """The real shape run_full_pipeline/_run_pipeline_with_extras actually
    return (raw, pre-_to_review_result) -- export_rows/bcba_fix/
    facilitator_assign, per merge.py::merge_findings' own real return
    shape. NOT the same shape as the final ReviewResult dict
    review_treatment_plan itself returns (that's built FROM this by
    _to_review_result, further down the call chain)."""
    return {
        "detected_payor": None,
        "detected_plan_type": None,
        "supporting_doc_extraction": None,
        "export_rows": [
            {
                "rule_id": f"R-{i}", "category": "Test", "result": "pass", "page": None,
                "detail": "ok", "confidence": 0.8, "action_lane": None, "action_tag": None,
            }
            for i in range(rule_count)
        ],
        "bcba_fix": [], "facilitator_assign": [],
    }


def test_review_treatment_plan_caches_and_a_second_call_makes_zero_additional_calls(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        if tracker is not None:
            tracker.count += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    # Isolate this test's cache from the repo's real .cache directory.
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    first = api_module.review_treatment_plan(str(pdf_path))
    assert first["status"] == "complete"
    assert call_count["n"] == 1

    second = api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 1, "identical file content must be a cache hit -- zero additional model calls"
    assert second == first, "a cache hit must return the exact same stored result"


def test_review_treatment_plan_different_content_is_a_real_cache_miss(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_a = tmp_path / "a.pdf"
    pdf_b = tmp_path / "b.pdf"
    _make_pdf(pdf_a, text="document A")
    _make_pdf(pdf_b, text="document B -- genuinely different content")

    api_module.review_treatment_plan(str(pdf_a))
    api_module.review_treatment_plan(str(pdf_b))
    assert call_count["n"] == 2, "genuinely different content must never be treated as a cache hit"


def test_review_treatment_plan_cache_key_includes_extra_rule_context(monkeypatch, tmp_path):
    """A real correctness requirement, not just plumbing: two reviews of
    the BYTE-IDENTICAL TP with DIFFERENT real intake answers
    (extra_rule_context) must never share a cached result -- the intake
    answer is real input that can change the real judgment output."""
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        return _fake_complete_result()

    def fake_run_pipeline_with_extras(pdf_path, rules, tracker, **kwargs):
        call_count["n"] += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_run_pipeline_with_extras", fake_run_pipeline_with_extras)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    api_module.review_treatment_plan(str(pdf_path), extra_fields={"k": "answer 1"})
    api_module.review_treatment_plan(str(pdf_path), extra_fields={"k": "answer 2"})
    assert call_count["n"] == 2, "different extra_fields content must never share a cached result"

    # But the SAME extra_fields content, submitted again, IS a real cache hit.
    api_module.review_treatment_plan(str(pdf_path), extra_fields={"k": "answer 1"})
    assert call_count["n"] == 2


def test_review_treatment_plan_use_cache_false_always_calls_through(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    api_module.review_treatment_plan(str(pdf_path), use_cache=False)
    api_module.review_treatment_plan(str(pdf_path), use_cache=False)
    assert call_count["n"] == 2, "use_cache=False must never read OR write the cache"


def test_review_treatment_plan_force_refresh_skips_lookup_but_still_writes(monkeypatch, tmp_path):
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 1

    api_module.review_treatment_plan(str(pdf_path), force_refresh=True)
    assert call_count["n"] == 2, "force_refresh must skip the cached read and call through for real"

    # An ordinary call afterward must hit the freshly-written cache.
    api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 2, "the force_refresh call must have re-saved the cache for future reads"


def test_review_treatment_plan_never_caches_a_failed_result(monkeypatch, tmp_path):
    """A transient failure must never be memorized -- the whole point of a
    retry is that the next attempt actually tries again."""
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        raise RuntimeError("simulated transient upstream failure")

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    first = api_module.review_treatment_plan(str(pdf_path))
    assert first["status"] == "failed"
    second = api_module.review_treatment_plan(str(pdf_path))
    assert second["status"] == "failed"
    assert call_count["n"] == 2, "a failed result must never be cached -- the second call must genuinely retry"


def test_review_treatment_plan_cache_is_invalidated_when_rules_json_changes(monkeypatch, tmp_path):
    """Fix Round (Eliminate Coin-Flipping, For Real, Before Production) --
    REAL BUG FOUND AND FIXED: the cache key never included the rules
    themselves. Confirmed real risk directly: this same round edited 4
    rules' own descriptions -- without this fix, re-submitting the same
    document after that edit would have silently returned the OLD,
    pre-edit cached result forever. Reproduces exactly that: same PDF,
    same params, but the on-disk rules.json changes between the two
    calls -- must be a real cache MISS, not a stale hit.
    """
    call_count = {"n": 0}

    def fake_run_full_pipeline(pdf_path, rules, tracker=None):
        call_count["n"] += 1
        return _fake_complete_result()

    monkeypatch.setattr(api_module, "run_full_pipeline", fake_run_full_pipeline)
    monkeypatch.setattr(api_module, "_REVIEW_CACHE_DIR", tmp_path / "cache")

    rules_path = tmp_path / "rules.json"
    rules_path.write_text('{"description": "v1", "rule_count": 0, "rules": []}', encoding="utf-8")
    monkeypatch.setattr(api_module, "RULES_PATH", rules_path)
    monkeypatch.setattr(api_module, "_load_rules", lambda: [])

    pdf_path = tmp_path / "tp.pdf"
    _make_pdf(pdf_path)

    api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 1

    # Same PDF, same params -- but the rules FILE's own content changed
    # (e.g. this round's own Part 2 rewrite).
    rules_path.write_text('{"description": "v2 -- rules edited", "rule_count": 0, "rules": []}', encoding="utf-8")
    api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 2, "a real rules.json content change must be a cache MISS, not a stale hit"

    # Reverting to the exact original rules content IS a real cache hit
    # again -- confirms this is genuinely content-keyed, not a one-way
    # "always miss after any change" hack.
    rules_path.write_text('{"description": "v1", "rule_count": 0, "rules": []}', encoding="utf-8")
    api_module.review_treatment_plan(str(pdf_path))
    assert call_count["n"] == 2
