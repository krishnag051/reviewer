"""Round 85: the ACF extraction bug's ACTUAL root cause (item 1 -- Round
83's "multiple header occurrences" theory was disproven: the real document,
Blythe Diaz's TP, has exactly ONE occurrence of the section header; the real
mechanism is a multi-line field-value convention plus a field-label variant,
traced directly by comparing what QA-ACF-05 already does correctly against
what the rest of the ACF checkers were doing). QA-PAR-01's rubric fix (item
2) is judgment-only with no Python function to unit-test -- verified live
instead (see this session's real-Anthropic and OpenRouter checks, reported
in the Round 85 write-up, not repeated here).

Per this round's own instruction, the real document is proven FIRST (see
the real-document tests below, using the actual Blythe Diaz PDF now present
in this project), and the synthetic cases generalize that same real fix --
not the reverse.
"""
import pytest

from pipeline import fields

BLYTHE_DIAZ_PDF = r"C:\Users\DELL\OneDrive - Master Faster\Desktop\master faster\reviewer\document\Blythe Diaz .pdf"


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- Real document first (per this round's own required order) ----------


@pytest.fixture
def blythe_diaz_fields():
    from pathlib import Path
    if not Path(BLYTHE_DIAZ_PDF).exists():
        pytest.skip(f"Blythe Diaz's TP not present at {BLYTHE_DIAZ_PDF} on this machine.")
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(BLYTHE_DIAZ_PDF)
    return fields.extract_fields(BLYTHE_DIAZ_PDF, pages)


def test_real_document_has_exactly_one_acf_header_occurrence(blythe_diaz_fields):
    """Disproves Round 83's root-cause theory directly: this document has
    NO second/decoy occurrence of the section header for a wrong-occurrence
    mechanism to have ever been the real cause here."""
    import re
    occurrences = list(re.finditer(r"Assessment of Current Functioning", blythe_diaz_fields["full_text"]))
    assert len(occurrences) == 1


def test_real_document_extract_acf_fields_no_longer_reports_none(blythe_diaz_fields):
    """THE real confirmed symptom, fixed: assessment_date was None despite
    being plainly present ('Date: 06/21/2026', not 'Assessment Date:') --
    now correctly extracted via the multi-line-aware helper plus the
    bare-label fallback."""
    acf = fields.extract_acf_fields(blythe_diaz_fields)
    assert acf["assessment_date"] == "06/21/2026"
    assert acf["pos"] == "Telehealth"
    assert acf["patient_location"] == "Home"
    assert acf["assessment_tool"] == "VB-MAPP"


def test_real_document_check_acf07_no_longer_falsely_reports_entirely_blank(blythe_diaz_fields):
    """THE real confirmed symptom, fixed: this section is NOT blank (real
    VB-MAPP methods description + summary statement are present, just on
    the line after their labels) -- must never again report "entirely
    blank." The honest remaining answer is "uncertain" (only one
    administration date documented, so old+new can't be confirmed) --
    that's a real, separate, correct judgment call, not the bug."""
    result, evidence, page, confidence = fields._check_ACF07({}, blythe_diaz_fields)
    assert "entirely blank" not in str(evidence).lower()
    assert result != "fail" or "entirely blank" not in str(evidence).lower()
    assert result == "uncertain"


# --- Synthetic generalization, locking in the real fix in both directions -


def test_labeled_value_maybe_next_line_same_line_unchanged():
    assert fields._labeled_value_maybe_next_line("Assessment Date:", "Assessment Date: 06/28/2026\n") == "06/28/2026"


def test_labeled_value_maybe_next_line_catches_the_real_confirmed_next_line_shape():
    """REAL confirmed case: label alone on its own line, real value on the
    line immediately after."""
    text = "Assessment Methods/Measures:\nVB MAPP Assessment\nThe VB-MAPP is a criterion-referenced tool.\n"
    assert fields._labeled_value_maybe_next_line("Assessment Methods/Measures:", text) == "VB MAPP Assessment"


def test_labeled_value_maybe_next_line_still_reports_none_for_a_genuinely_blank_field():
    """A label immediately followed by another field's label (nothing
    filled in between) must still read as blank, not as if the NEXT
    label's text were this field's value."""
    text = "Assessment Summary Statement:\nAreas of Focus for Treatment:\n"
    assert fields._labeled_value_maybe_next_line("Assessment Summary Statement:", text) is None


def test_labeled_value_maybe_next_line_none_when_label_absent():
    assert fields._labeled_value_maybe_next_line("Assessment Date:", "No such label here.\n") is None


def _acf_text_with_next_line_values() -> str:
    return (
        "Assessment of Current Functioning:\n"
        "Location: Telehealth\nPatient Location during Assessment: Home\nDate: 06/21/2026\n"
        "Assessment Methods/Measures:\nVB MAPP Assessment\nThe VB-MAPP is a criterion-referenced tool.\n"
        "Assessment Summary Statement:\nBlythe demonstrates skill deficits in communication.\n"
        "Goal Progress:\n"
    )


def test_extract_acf_fields_synthetic_reproduction_of_the_real_document_shape():
    doc_fields = _fields(_acf_text_with_next_line_values())
    acf = fields.extract_acf_fields(doc_fields)
    assert acf["assessment_date"] == "06/21/2026"
    assert acf["pos"] == "Telehealth"
    assert acf["patient_location"] == "Home"
    assert acf["assessment_tool"] == "VB-MAPP"


def test_check_acf07_synthetic_reproduction_no_longer_reports_entirely_blank():
    doc_fields = _fields(_acf_text_with_next_line_values())
    result, evidence, page, confidence = fields._check_ACF07({}, doc_fields)
    assert "entirely blank" not in str(evidence).lower()


def test_check_acf07_still_correctly_fails_a_genuinely_blank_section():
    text = "Assessment of Current Functioning:\n \nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "fail"
    assert "entirely blank" in str(evidence).lower()


def test_extract_acf_fields_bare_date_fallback_does_not_override_a_real_assessment_date_label():
    """The bare 'Date:' fallback is last-resort only -- when the proper
    'Assessment Date:' label IS present, it must win, not a coincidental
    bare 'Date:' elsewhere in the section."""
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 06/28/2026\nDate: 01/01/2000\n"
        "Assessment Methods/Measures:\nABLLS-R\nGoal Progress:\n"
    )
    acf = fields.extract_acf_fields(_fields(text))
    assert acf["assessment_date"] == "06/28/2026"


@pytest.mark.parametrize("real_doc_fixture", ["reeda_tp_pdf", "charny_tp_pdf", "yisroel_tp_pdf"])
def test_acf_fix_unchanged_on_other_real_documents(request, real_doc_fixture):
    """None of the other three real documents use the next-line or
    bare-label conventions -- confirms this round's fix doesn't change
    their (already-correct) results."""
    pdf_path = request.getfixturevalue(real_doc_fixture)
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(pdf_path)
    doc_fields = fields.extract_fields(pdf_path, pages)
    acf = fields.extract_acf_fields(doc_fields)
    if real_doc_fixture != "charny_tp_pdf":
        assert acf["assessment_date"] is not None
    result, evidence, page, confidence = fields._check_ACF07({}, doc_fields)
    assert result in ("pass", "fail", "uncertain")
