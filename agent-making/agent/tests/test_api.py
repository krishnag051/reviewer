"""Regression coverage for pipeline/api.py — the additive-only integration
wrapper (see INTEGRATION_PLAN.md Section 1). The live end-to-end case is
gated behind real credentials, same convention as test_pipeline.py; it was
also run manually once against sample_tps/Ullah_Zyaan_Redacted.pdf during
this round and returned status="complete", 120 findings, all 5 result
values represented, ~$0.50 real cost — recorded here so a future reader
doesn't have to re-derive that this was actually exercised, not just
compiled.
"""
import os

import pytest

from pipeline.api import review_treatment_plan

HAS_ANTHROPIC_CREDENTIALS = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
SAMPLE_TP_PDF = os.path.join(os.path.dirname(__file__), "..", "sample_tps", "Ullah_Zyaan_Redacted.pdf")


def test_missing_pdf_returns_structured_error_not_an_exception():
    result = review_treatment_plan("does/not/exist.pdf")
    assert result["status"] == "failed"
    assert result["error"]["code"] == "pdf_not_found"
    assert result["findings"] == []
    assert result["usage"]["api_calls"] == 0


def test_error_result_shape_matches_success_shape_minus_content():
    """Every top-level key a caller might read must exist on BOTH the
    success and failure shape — a caller checking `result["usage"]["api_calls"]`
    shouldn't need a separate code path depending on `status`.
    """
    result = review_treatment_plan("does/not/exist.pdf")
    for key in ("schema_version", "status", "detected_payor", "detected_plan_type", "findings", "summary", "usage", "error"):
        assert key in result
    for key in ("bcba_fix_rule_ids", "facilitator_assign_rule_ids", "counts_by_result"):
        assert key in result["summary"]
    for key in ("api_calls", "input_tokens", "output_tokens", "estimated_cost_usd"):
        assert key in result["usage"]


@pytest.mark.skipif(not HAS_ANTHROPIC_CREDENTIALS, reason="requires ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN")
def test_review_treatment_plan_end_to_end_real_document():
    """Real live call, real cost (~$0.50 at current pricing) — not mocked.
    Confirms the wrapper's translation of run_full_pipeline's raw shape
    into the ReviewResult contract actually holds against a real document,
    not just against hand-constructed fixtures.
    """
    result = review_treatment_plan(SAMPLE_TP_PDF, max_calls=40)

    assert result["status"] == "complete"
    assert result["error"] is None
    assert result["detected_payor"] != "Unknown"  # this document has a real, detectable payor
    assert len(result["findings"]) == 120  # every active rule gets exactly one finding row-group

    seen_results = {f["result"] for f in result["findings"]}
    assert seen_results <= {"pass", "fail", "uncertain", "not_applicable", "not_checkable"}

    counts = result["summary"]["counts_by_result"]
    assert sum(counts.values()) == len(result["findings"])

    assert result["usage"]["api_calls"] >= 1
    assert result["usage"]["estimated_cost_usd"] > 0
