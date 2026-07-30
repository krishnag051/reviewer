"""Synthetic-only coverage for the HF-01 self-contradiction bug (evidence
text concludes the correct answer, then `result` disagrees with it anyway,
identically across all 3 attempts). No live document, no live API.

Two structural fixes, verified separately:

1. FINDINGS_TOOL's per-finding schema now asks for `evidence` before
   `result` (and puts `evidence_supports_result` right after `result`, as a
   final gate) instead of `result` first — a well-documented mitigation for
   models committing to a categorical answer before writing the reasoning
   that's supposed to justify it. This is a generation-order effect: nothing
   in a non-live test can prove the model itself reasons differently now.
   What CAN be verified without a live call is that the schema really was
   reordered, and that the existing evidence_supports_result gate (added in
   the previous round) still catches this exact contradiction shape if the
   model produces it again regardless of ordering.
2. `_build_prompt` now forwards each rule's `params` (previously dropped
   entirely), so a rule like HF-01 — whose real thresholds live in
   `params`, not just free-text `description`/`notes` — actually gets them
   in front of the model.

If items 1 continues to reproduce live after this change, that is the one
place confirming the fix needs a real model call — not something to run
here.
"""
import json

from pipeline import judge


def _schema_properties():
    return judge.FINDINGS_TOOL["input_schema"]["properties"]["findings"]["items"]["properties"]


def test_evidence_is_defined_before_result_in_the_schema():
    """The actual bug this round: `result` used to appear before `evidence`
    in FINDINGS_TOOL, so the model could be committing to the categorical
    answer before generating the reasoning meant to justify it."""
    keys = list(_schema_properties().keys())
    assert keys.index("evidence") < keys.index("result"), (
        "evidence must be defined before result so the model reasons before "
        "committing to a categorical answer"
    )


def test_required_list_also_orders_evidence_before_result():
    required = judge.FINDINGS_TOOL["input_schema"]["properties"]["findings"]["items"]["required"]
    assert required.index("evidence") < required.index("result")


def test_evidence_supports_result_is_a_gate_immediately_after_result():
    """Keeps the self-consistency check adjacent to the field it's checking,
    rather than buried among unrelated metadata fields (page/confidence)."""
    keys = list(_schema_properties().keys())
    assert keys.index("result") < keys.index("evidence_supports_result") < keys.index("page")


def test_build_prompt_forwards_params_for_a_rule_that_has_them():
    """Previously _build_prompt's rules_summary only sent rule_id/category/
    description/notes — a rule's `params` (e.g. HF-01's age_threshold/
    short_range_months/long_range_months) never reached the model at all,
    so the only numbers it could rely on were whatever happened to be in
    free-text description/notes."""
    rule = {
        "rule_id": "HF-01",
        "category": "Healthfirst-Specific",
        "description": "Patients >13: auth dates = 3-month range instead of 6",
        "notes": "some notes",
        "params": {"age_threshold": 13, "short_range_months": 3, "long_range_months": 6},
    }
    fields = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}

    content = judge._build_prompt([rule], fields, rendered_images={})
    rules_json_block = next(b["text"] for b in content if "Rules to check (JSON):" in b["text"])

    assert '"age_threshold": 13' in rules_json_block
    assert '"short_range_months": 3' in rules_json_block
    assert '"long_range_months": 6' in rules_json_block


def test_build_prompt_handles_rule_with_no_params_gracefully():
    rule = {"rule_id": "QA-OBS-01", "category": "X", "description": "d", "notes": None}
    fields = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}
    content = judge._build_prompt([rule], fields, rendered_images={})
    rules_json_block = next(b["text"] for b in content if "Rules to check (JSON):" in b["text"])
    assert '"params": null' in rules_json_block


def _finding_reproducing_the_hf01_contradiction(evidence_supports_result: bool):
    """Reproduces the exact shape from the pasted transcript: evidence text
    reasons its way to 'this matches the expected pattern... should be
    reconsidered' and then result is still 'fail' anyway."""
    return {
        "rule_id": "HF-01",
        "result": "fail",
        "evidence": (
            "The patient is 17 (>13). The Authorization Dates Requested are "
            "07/30/2026 to 10/30/2026, which spans 3 months. Since the rule "
            "requires patients >13 to have a 3-month range instead of 6, and "
            "the patient is 17 (>13) with a 3-month range, this actually "
            "matches the expected pattern for >13, so this should be "
            "reconsidered."
        ),
        "page": None,
        "confidence": 0.8,
        "evidence_supports_result": evidence_supports_result,
    }


def test_contradiction_pattern_is_rejected_when_model_flags_it_correctly():
    """This is what actually happened live, per the rejection log: the model
    DID mark evidence_supports_result=False on all 3 attempts, which is why
    the run correctly failed with an IntegrityError instead of silently
    recording the wrong 'fail'. Confirms that path is intact after the
    schema reorder."""
    findings = judge._findings_dict_from_list([
        _finding_reproducing_the_hf01_contradiction(evidence_supports_result=False)
    ])
    assert "HF-01" not in findings


def test_contradiction_pattern_would_slip_through_if_flag_were_true():
    """Documents the residual risk plainly: evidence_supports_result is a
    self-report. If the model ever set it to True on a contradictory
    finding like this, nothing in _findings_dict_from_list itself would
    catch it — the schema reorder is what's meant to reduce how often that
    self-report is wrong, not a second independent check on top of it.
    Not a regression introduced this round; unchanged from before."""
    findings = judge._findings_dict_from_list([
        _finding_reproducing_the_hf01_contradiction(evidence_supports_result=True)
    ])
    assert findings["HF-01"]["result"] == "fail"


def test_hf01_rule_definition_has_explicit_params_and_criteria_in_notes():
    rules_path = judge.Path(__file__).parent.parent / "rules" / "rules.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))["rules"]
    hf01 = next(r for r in rules if r["rule_id"] == "HF-01")

    assert hf01["params"] == {
        "age_threshold": 13,
        "short_range_months": 3,
        "long_range_months": 6,
    }
    assert "PASS" in hf01["notes"]
    assert "FAIL" in hf01["notes"]
