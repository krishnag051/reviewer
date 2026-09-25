"""Fix Round 7: QA-BAR-01's reported "regression back to the old hours-
threshold logic" traced end to end. _check_BAR01's own current code has
zero hours-threshold logic anywhere (confirmed by reading it directly --
the old gate was genuinely deleted, not reintroduced). The actual root
cause: pipeline/api.py's content-hash review cache never included the
pipeline's own CODE, only the PDF/supporting-doc/rules.json bytes and
params -- so a document reviewed once BEFORE a checker fix, then
resubmitted after the fix with no rules.json change, silently replayed
the stale pre-fix cached result forever. Confirmed for real: two existing
.cache/tp_reviews/*.json entries in this repo contain the exact deleted
"25-hour threshold" QA-BAR-01 wording verbatim. Fixed via
_pipeline_code_hash(), folded into the cache key.
"""

from pipeline import fields
from pipeline.api import _pipeline_code_hash


def test_check_bar01_current_code_has_no_hours_threshold_logic():
    """Direct proof _check_BAR01 itself was never actually reverted --
    the reported regression could not have come from this function."""
    import inspect

    source = inspect.getsource(fields._check_BAR01)
    assert "hour" not in source.lower()
    assert "threshold" not in source.lower()


def test_check_bar01_produces_real_barriers_reasoning_not_hours_text():
    text = (
        "Assessment of Current Functioning:\n"
        "The family reports a Spanish-language barrier makes some sessions difficult to schedule "
        "due to caregiver availability constraints.\n"
        "Barriers to Treatment:\n"
        "There are no noted barriers to treatment at this time.\n"
        "Results of Preference Assessment:\n"
        "unrelated text\n"
    )
    f = {"full_text": text, "pages": [{"page_number": 8, "text": text}]}
    result, evidence, page, confidence = fields._check_BAR01({}, f)
    assert result == "fail"
    assert "hour" not in evidence.lower()
    assert "threshold" not in evidence.lower()
    assert "Spanish-language barrier" in evidence
    assert page == 8


def test_pipeline_code_hash_changes_when_a_pipeline_file_changes(tmp_path, monkeypatch):
    """The actual fix: any change to a .py file in the pipeline package
    must change the cache key, so a stale pre-fix result can never be
    replayed again after a real code change."""
    import pipeline.api as api_module

    fake_pkg = tmp_path / "pipeline"
    fake_pkg.mkdir()
    (fake_pkg / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(api_module, "_PIPELINE_PACKAGE_DIR", fake_pkg)
    before = _pipeline_code_hash()

    (fake_pkg / "a.py").write_text("x = 2\n", encoding="utf-8")
    after = _pipeline_code_hash()

    assert before != after


def test_pipeline_code_hash_is_stable_for_unchanged_code():
    assert _pipeline_code_hash() == _pipeline_code_hash()
