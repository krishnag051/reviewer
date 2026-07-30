"""Step 8: basic pipeline tests.

The end-to-end test runs the real pipeline (including the live judgment-layer
Claude call) against a synthetic placeholder PDF and asserts the integrity
check passes — all 114 rule_ids present in the merged output. It's skipped
automatically when no Anthropic credentials are configured (this dev
environment has none); it will run for real once ANTHROPIC_API_KEY is set.

The synthetic PDF here is placeholder text only, built purely to exercise
pipeline mechanics (extraction, image-only flagging, integrity coverage) —
it is NOT a substitute for validating accuracy against a real redacted TP,
which the user will supply separately.
"""
import json
import os
from pathlib import Path

import pytest

from pipeline import run_full_pipeline
from pipeline.extract import extract_pdf_text
from pipeline.flag_pages import flag_image_only_pages, flagged_page_numbers
from pipeline.integrity import missing_rule_ids

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]

HAS_ANTHROPIC_CREDENTIALS = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def test_extract_and_flag_mechanics(synthetic_tp_pdf):
    pages = extract_pdf_text(synthetic_tp_pdf)
    assert len(pages) == 3
    assert "Page 1" in pages[0]["text"]

    flagged = flag_image_only_pages(pages)
    low_text_pages = flagged_page_numbers(flagged)
    assert low_text_pages == [3], "the near-blank third page should be flagged image-only"


def test_missing_rule_ids_detects_gaps():
    sent = ["A-1", "A-2", "A-3"]
    results = {"A-1": {}, "A-3": {}}
    assert missing_rule_ids(sent, results) == ["A-2"]


def test_missing_rule_ids_empty_when_complete():
    sent = ["A-1", "A-2"]
    results = {"A-1": {}, "A-2": {}}
    assert missing_rule_ids(sent, results) == []


@pytest.mark.skipif(not HAS_ANTHROPIC_CREDENTIALS, reason="No Anthropic credentials configured in this environment.")
def test_end_to_end_integrity_check_passes(synthetic_tp_pdf):
    result = run_full_pipeline(synthetic_tp_pdf, RULES)

    active_rule_ids = {r["rule_id"] for r in RULES if r["active"]}
    found_rule_ids = set(result["findings"].keys())

    assert found_rule_ids == active_rule_ids, (
        f"Missing: {active_rule_ids - found_rule_ids}, "
        f"Unexpected: {found_rule_ids - active_rule_ids}"
    )
    assert len(found_rule_ids) == 112  # 114 total, 2 inactive in this rule set
