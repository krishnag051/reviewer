"""Regression snapshot test — the point of this file.

Every round of fixes so far has fixed 3-4 rules and broken 3-4 different
ones, and every regression was only caught by a human manually diffing two
CSV exports after a run. This test makes that check automatic: it runs the
full pipeline against the real Zyaan Ullah TP and compares each rule_id's
`result` against a checked-in baseline. Any rule_id whose result differs
fails the test with every diff listed — a deliberate behavior change means
updating the baseline file on purpose (with a one-line reason passed to
`_generate_baseline.py`, or in the commit message), not silently
regenerating it.

History: this test originally ran against a synthetic, generated-on-the-fly
placeholder PDF (conftest.py's synthetic_tp_pdf), because the real TP wasn't
in the repo yet. That fixture proved unusable as a strict gate — three
consecutive live runs, the last two with zero code change in between,
produced three different sets of ~15-18 rule_id diffs, because a toy 3-page
document has almost no real content for most of the 112 rules to anchor a
stable answer on. The test was marked `xfail` for that reason.

The real Zyaan Ullah TP (agent/sample_tps/Ullah_Zyaan_Redacted.pdf, 48
pages) is now in the repo. This test runs against it via conftest.py's
real_tp_pdf fixture, and the `xfail` marker is removed — a real document
should give the judgment layer enough actual content to answer consistently
run-to-run, so a genuine diff here should mean a genuine behavior change.
If it turns out to still be flaky even against real content, that itself is
a real, reportable finding about the judgment layer's run-to-run
consistency — not something to mark around again.
"""
import json
import os
from pathlib import Path

import pytest

from pipeline import run_full_pipeline

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "zyaan_ullah_baseline.json"

HAS_ANTHROPIC_CREDENTIALS = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _results_by_rule_id(pdf_path: str) -> dict[str, str]:
    result = run_full_pipeline(pdf_path, RULES)
    return {rule_id: entry["result"] for rule_id, entry in result["findings"].items()}


@pytest.mark.skipif(not HAS_ANTHROPIC_CREDENTIALS, reason="No Anthropic credentials configured in this environment.")
def test_no_rule_result_regressed_since_baseline_snapshot(real_tp_pdf):
    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"No baseline snapshot at {SNAPSHOT_PATH}. Generate one deliberately "
            f"(see the docstring in this file) before this test can run — it must "
            f"never be auto-created silently by a normal test run."
        )

    baseline = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))["results"]
    current = _results_by_rule_id(real_tp_pdf)

    changed = {
        rule_id: {"was": baseline[rule_id], "now": current[rule_id]}
        for rule_id in baseline
        if rule_id in current and baseline[rule_id] != current[rule_id]
    }
    missing_from_current = sorted(set(baseline) - set(current))
    new_in_current = sorted(set(current) - set(baseline))

    if changed or missing_from_current or new_in_current:
        lines = ["Regression snapshot mismatch — one or more rule_ids changed since the baseline:"]
        for rule_id, diff in sorted(changed.items()):
            lines.append(f"  CHANGED  {rule_id}: {diff['was']} -> {diff['now']}")
        for rule_id in missing_from_current:
            lines.append(f"  MISSING  {rule_id}: was in baseline, absent from this run")
        for rule_id in new_in_current:
            lines.append(f"  NEW      {rule_id}: not in baseline, present in this run")
        lines.append(
            "\nIf every one of these is a deliberate, reviewed fix: regenerate "
            f"{SNAPSHOT_PATH.name} and note why in the commit message. If any of "
            "these is unexpected: you just found a regression before a human had "
            "to diff two CSVs to catch it."
        )
        pytest.fail("\n".join(lines))
