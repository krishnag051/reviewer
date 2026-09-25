"""Fix Round 13: real root cause found for QA-GIP-12 only citing a
fraction of its real target pages on a genuine production run.
QA-GIP-12's whole two-pass hybrid mechanism (Pass 1 candidate injection,
and the merge-back after judgment returns) lived ONLY in
pipeline/__init__.py::run_full_pipeline -- it was never duplicated into
pipeline/api.py::_run_pipeline_with_extras, a hand-maintained copy of
run_full_pipeline's own orchestration. Since supporting_doc_path is
mandatory on every real backend upload, _run_pipeline_with_extras (not
run_full_pipeline) is the orchestration path every real upload actually
takes -- so this mechanism has never actually run against real
production traffic at all, only against direct run_full_pipeline callers
and past rounds' own diagnostic scripts. This is the exact same class of
bug already found and fixed once before for STABILIZED_UNCERTAIN_RULE_IDS
(see that fix's own comment in _run_pipeline_with_extras).

Fixed by extracting the injection logic into
pipeline/__init__.py::_inject_gip12_candidate_context, a single shared
function BOTH orchestration paths now call, so this can't silently drift
apart a second time.
"""
import tempfile

from pypdf import PdfWriter

import pipeline as pipeline_module
import pipeline.api as api_module
import pipeline.extract as extract_module


def _goal_pages():
    return [
        {"page_number": 10, "text": "Target Goal: Reeda will mand by calling BT's name\nGoal Status: In progress\n"},
        {"page_number": 11, "text": "Target Goal: Reeda will tact 10 common objects\nGoal Status: In progress\n"},
    ]


def _rules():
    return [
        {
            "rule_id": "QA-GIP-12", "check_type": "judgment", "active": True,
            "applies_to_payor": "ALL", "applies_to_plan_type": "Both",
            "description": "Goals include verbal operant/behavioral term", "category": "Goals in Progress",
            "action_lane": "BCBA-fix", "action_tag": None,
        },
    ]


def test_run_pipeline_with_extras_also_injects_gip12_candidate_context():
    """The exact real regression: this orchestration path (the one real
    production traffic actually takes, per its own docstring) must build
    QA-GIP-12's judgment batch with the same real extra_context
    run_full_pipeline already gets -- confirmed by capturing the batch
    handed to the (mocked, zero-cost) judgment call.
    """
    captured = {}
    orig_run_judgment = pipeline_module.integrity.run_judgment_with_integrity_check

    def fake_judgment(full_judgment_batch, *args, **kwargs):
        captured["batch"] = full_judgment_batch
        return {
            r["rule_id"]: {"result": "uncertain", "evidence": "", "page": None, "confidence": 0.0}
            for r in full_judgment_batch
        }

    pages = _goal_pages()
    orig_extract = extract_module.extract_pdf_text
    pipeline_module.integrity.run_judgment_with_integrity_check = fake_judgment
    extract_module.extract_pdf_text = lambda _path: pages
    pipeline_module.extract_pdf_text = extract_module.extract_pdf_text
    api_module.extract_pdf_text = extract_module.extract_pdf_text
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer = PdfWriter()
            for _ in range(12):
                writer.add_blank_page(width=612, height=792)
            writer.write(tmp.name)
            tmp_path = tmp.name

        # payor_override forces the _run_pipeline_with_extras path (the
        # real production path, per its own docstring) instead of the
        # plain run_full_pipeline passthrough.
        api_module._run_pipeline_with_extras(
            tmp_path, _rules(), api_module.ApiCallTracker(),
            payor_override="Healthfirst", plan_type_override=None, supporting_doc_path=None,
        )
    finally:
        pipeline_module.integrity.run_judgment_with_integrity_check = orig_run_judgment
        extract_module.extract_pdf_text = orig_extract
        pipeline_module.extract_pdf_text = orig_extract
        api_module.extract_pdf_text = orig_extract

    batch_by_id = {r["rule_id"]: r for r in captured["batch"]}
    assert "QA-GIP-12" in batch_by_id
    assert "mand" in batch_by_id["QA-GIP-12"]["extra_context"]
    assert "page 10" in batch_by_id["QA-GIP-12"]["extra_context"]
    assert "page 11" in batch_by_id["QA-GIP-12"]["extra_context"]


def test_run_pipeline_with_extras_also_applies_the_gip12_merge():
    """The other half: a judgment result citing fewer pages than Pass 1
    found must still get the missing real pages unioned back in through
    THIS orchestration path too, not just run_full_pipeline's."""
    orig_run_judgment = pipeline_module.integrity.run_judgment_with_integrity_check

    def fake_judgment(full_judgment_batch, *args, **kwargs):
        results = {}
        for r in full_judgment_batch:
            if r["rule_id"] == "QA-GIP-12":
                results[r["rule_id"]] = {
                    "result": "pass", "evidence": "partial", "page": [10], "confidence": 0.7,
                }
            else:
                results[r["rule_id"]] = {"result": "uncertain", "evidence": "", "page": None, "confidence": 0.0}
        return results

    pages = _goal_pages()
    orig_extract = extract_module.extract_pdf_text
    pipeline_module.integrity.run_judgment_with_integrity_check = fake_judgment
    extract_module.extract_pdf_text = lambda _path: pages
    pipeline_module.extract_pdf_text = extract_module.extract_pdf_text
    api_module.extract_pdf_text = extract_module.extract_pdf_text
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer = PdfWriter()
            for _ in range(12):
                writer.add_blank_page(width=612, height=792)
            writer.write(tmp.name)
            tmp_path = tmp.name

        result = api_module._run_pipeline_with_extras(
            tmp_path, _rules(), api_module.ApiCallTracker(),
            payor_override="Healthfirst", plan_type_override=None, supporting_doc_path=None,
        )
    finally:
        pipeline_module.integrity.run_judgment_with_integrity_check = orig_run_judgment
        extract_module.extract_pdf_text = orig_extract
        pipeline_module.extract_pdf_text = orig_extract
        api_module.extract_pdf_text = orig_extract

    gip12_row = next(row for row in result["export_rows"] if row["rule_id"] == "QA-GIP-12")
    # Page 11's real "tact" hit must survive the merge -- judgment only
    # cited page 10 on its own.
    assert gip12_row["page"] == "10-11" or "11" in str(gip12_row["page"])
