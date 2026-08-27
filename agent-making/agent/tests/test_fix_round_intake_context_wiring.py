"""Fix Round (2026-08-27): Part 2's real fixes --
1. _check_PPI05's second ground-truth source: the CURRENT default mode's
   own intake "BCBA Name, Credentials & NPI" answer (fields["intake_bcba_
   name_credentials_npi"]), alongside the OLD document-mode supporting_doc
   field (dormant since structured_form became the default -- confirmed
   real gap).
2. review_treatment_plan's extra_rule_context/extra_fields params actually
   reach _build_prompt/extracted_fields (the plumbing itself, not the
   comparison logic -- that's covered by test_hf01_contradiction_fix.py's
   own precedent for extra prompt content).
Synthetic-only, zero model calls.
"""
from pipeline import fields, judge


def _fields(text: str) -> dict:
    return {"pages": [{"page_number": 1, "text": text}], "full_text": text}


# ---------------------------------------- _check_PPI05's intake ground truth


def test_ppi05_fails_when_tp_npi_disagrees_with_intake_answer():
    f = _fields("NPI: 1578293197\n")
    f["intake_bcba_name_credentials_npi"] = "Jane Smith, BCBA-D - NPI 9999999999"
    result, evidence, page, confidence = fields._check_PPI05({}, f)
    assert result == "fail"
    assert "1578293197" in evidence and "9999999999" in evidence


def test_ppi05_passes_when_tp_npi_matches_intake_answer():
    f = _fields("NPI: 1578293197\n")
    f["intake_bcba_name_credentials_npi"] = "Jane Smith, BCBA-D - NPI 1578293197"
    result, evidence, page, confidence = fields._check_PPI05({}, f)
    assert result == "pass"


def test_ppi05_ignores_intake_answer_when_it_has_no_npi_digits():
    """A real intake answer that names credentials but no NPI (or one the
    regex can't find a 10-digit run in) contributes no ground truth --
    stays uncertain (internal-consistency-only), same as no supporting_doc
    at all -- never a guessed mismatch."""
    f = _fields("NPI: 1578293197\n")
    f["intake_bcba_name_credentials_npi"] = "Jane Smith, BCBA-D"
    result, evidence, page, confidence = fields._check_PPI05({}, f)
    assert result == "uncertain"


def test_ppi05_intake_and_supporting_doc_are_additive_ground_truth_sources():
    """Both sources can supply ground truth at once -- the TP's NPI only
    needs to match ONE of them, not both, to pass (they SHOULD agree with
    each other in practice, but this checker's own job is TP-vs-ground-
    truth, not cross-validating the two ground-truth sources against each
    other)."""
    f = _fields("NPI: 1578293197\n")
    f["supporting_doc"] = {"bcba_credentials_npi": {"value": "NPI 0000000000", "confidence": "high", "source_quote": None}}
    f["intake_bcba_name_credentials_npi"] = "Jane Smith, BCBA-D - NPI 1578293197"
    result, evidence, page, confidence = fields._check_PPI05({}, f)
    assert result == "pass"


# ---------------------------------------- extra_rule_context / extra_fields plumbing


def test_build_prompt_forwards_additional_real_data_for_a_rule_that_has_it():
    rule = {
        "rule_id": "QA-SCH-02",
        "category": "School & ABA Schedule",
        "description": "d",
        "notes": None,
        "params": None,
        "extra_context": "Patient Central Reach Information intake answer -- Schedule and POS: 'Home, 15 hrs/week'.",
    }
    fields_dict = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}
    content = judge._build_prompt([rule], fields_dict, rendered_images={})
    rules_json_block = next(b["text"] for b in content if "Rules to check (JSON):" in b["text"])
    assert "Home, 15 hrs/week" in rules_json_block
    assert '"additional_real_data"' in rules_json_block


def test_build_prompt_additional_real_data_is_null_when_not_set():
    rule = {"rule_id": "QA-OBS-01", "category": "X", "description": "d", "notes": None}
    fields_dict = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}
    content = judge._build_prompt([rule], fields_dict, rendered_images={})
    rules_json_block = next(b["text"] for b in content if "Rules to check (JSON):" in b["text"])
    assert '"additional_real_data": null' in rules_json_block
