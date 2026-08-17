"""Round 91 (169-rule reconciliation): QA-PPI-07, the AKA/alias check --
a brand-new rule_id, NOT a repoint of QA-PPI-06 (which keeps its own,
unrelated, already-shipped narrative-name-contamination meaning). Same
shape as QA-PPI-03 (internal-consistency check), applied to the 'AKA:'
field instead of 'Patient Name:'.
"""
from pipeline import fields
from pipeline.extract import extract_pdf_text


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --------------------------------------------------------------- synthetic


def test_no_aka_label_at_all_is_not_checkable():
    text = "Patient Name: Priya Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n"
    result, evidence, page, confidence = fields._check_PPI07({}, _fields(text))
    print(f"[PPI-07] no AKA label at all: {result} -- {evidence}")
    assert result == "not_checkable"


def test_blank_aka_field_passes():
    text = "Patient Name: Priya Ferreira  AKA: N/A Patient DOB: 03/03/2019\n"
    result, evidence, page, confidence = fields._check_PPI07({}, _fields(text))
    print(f"[PPI-07] blank/N-A AKA field: {result} -- {evidence}")
    assert result == "pass"


def test_real_alias_present_and_consistent_passes():
    text = "Patient Name: Priya Ferreira  AKA: Pri Patient DOB: 03/03/2019\n"
    result, evidence, page, confidence = fields._check_PPI07({}, _fields(text))
    print(f"[PPI-07] real, consistent alias: {result} -- {evidence}")
    assert result == "pass"
    assert "Pri" in evidence


def test_inconsistent_alias_spelling_fails():
    """Made-up two-mention document (this template's own AKA field only
    ever repeats in real documents checked so far when it repeats at
    all) -- confirms the mismatch path itself, not just the common
    single-mention real-document shape."""
    text = (
        "Patient Name: Priya Ferreira  AKA: Pri Patient DOB: 03/03/2019\n"
        "Patient Name: Priya Ferreira  AKA: Prya Patient DOB: 03/03/2019\n"
    )
    result, evidence, page, confidence = fields._check_PPI07({}, _fields(text))
    print(f"[PPI-07] inconsistent alias spelling: {result} -- {evidence}")
    assert result == "fail"
    assert "Pri" in evidence and "Prya" in evidence


# ----------------------------------------------------- real-document regression


def _run_ppi07(pdf_path: str) -> tuple:
    pages = extract_pdf_text(pdf_path)
    full_text = "\n".join(p["text"] for p in pages)
    return fields._check_PPI07({}, {"pages": pages, "full_text": full_text})


def test_real_reeda_no_alias_stated_passes(reeda_tp_pdf):
    """Confirmed live: AKA: 'N/A' -- no real alias."""
    result, evidence, page, confidence = _run_ppi07(reeda_tp_pdf)
    print(f"[PPI-07] Reeda (real): {result} -- {evidence}")
    assert result == "pass"


def test_real_blythe_no_alias_stated_passes(blythe_tp_pdf):
    """Confirmed live: AKA: 'N/A' -- no real alias."""
    result, evidence, page, confidence = _run_ppi07(blythe_tp_pdf)
    print(f"[PPI-07] Blythe (real): {result} -- {evidence}")
    assert result == "pass"


def test_real_charny_alias_present_and_consistent_passes(charny_tp_pdf):
    """Confirmed live: AKA: 'Charna' -- one real mention, passes."""
    result, evidence, page, confidence = _run_ppi07(charny_tp_pdf)
    print(f"[PPI-07] Charny (real): {result} -- {evidence}")
    assert result == "pass"
    assert "Charna" in evidence


def test_real_yisroel_alias_present_and_consistent_passes(yisroel_tp_pdf):
    """Confirmed live: AKA: 'Sruly' -- one real mention, passes."""
    result, evidence, page, confidence = _run_ppi07(yisroel_tp_pdf)
    print(f"[PPI-07] Yisroel (real): {result} -- {evidence}")
    assert result == "pass"
    assert "Sruly" in evidence


def test_real_zohan_no_aka_field_in_this_template_is_not_checkable(zohan_tp_pdf):
    """Confirmed live: this template variant has no 'AKA:' label anywhere
    -- genuinely different from Reeda/Charny/Yisroel/Blythe's shared
    template, not a real absence-of-alias signal."""
    result, evidence, page, confidence = _run_ppi07(zohan_tp_pdf)
    print(f"[PPI-07] Zohan (real): {result} -- {evidence}")
    assert result == "not_checkable"


# ------------------------------------------------------- wiring / registration


def test_ppi07_registered_as_deterministic_and_present_in_rules_json():
    import json
    from pathlib import Path

    rules = json.loads((Path(__file__).parent.parent / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
    rule = next(r for r in rules if r["rule_id"] == "QA-PPI-07")
    assert rule["check_type"] == "deterministic"
    assert rule["active"] is True
    assert "AKA" in rule["description"]
    assert fields.DET_CHECKS["QA-PPI-07"] is fields._check_PPI07


def test_ppi06_untouched_by_this_round():
    """The whole point of this round's decision: QA-PPI-06 keeps its own
    meaning, completely unaffected by QA-PPI-07 existing."""
    import json
    from pathlib import Path

    rules = json.loads((Path(__file__).parent.parent / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
    rule = next(r for r in rules if r["rule_id"] == "QA-PPI-06")
    assert "Narrative sections do not name a person" in rule["description"]
    assert fields.DET_CHECKS["QA-PPI-06"] is fields._check_narrative_name_contamination
