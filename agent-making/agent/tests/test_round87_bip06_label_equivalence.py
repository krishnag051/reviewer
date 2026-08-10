"""Round 87, item 1: QA-BIP-06's "Current Level:"/"Current Data:" label
equivalence fix. Real before/after confirmed directly against Zohan
Hossain's and Yisroel Leibowitz's real documents (see the Round 87 report);
this file locks the fix in generically.
"""
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def _bip_block(label: str, value: str) -> str:
    return (
        f"Target Name: Reduce Elopement\nBaseline: 5\n{label} {value}\n"
        f"Mastery Criteria: 0 occurrences\n"
    )


def test_check_bip06_catches_the_real_confirmed_current_data_pass():
    """REAL confirmed case (Yisroel's document): a Behavior Reduction goal
    using 'Current Data:' (never 'Current Level:') with a real value must
    now pass -- this is the confirmed real ground-truth regression."""
    text = _bip_block("Current Data:", "0  Frequency")
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "pass"


def test_check_bip06_still_passes_current_level_unchanged():
    text = _bip_block("Current Level:", "2x daily")
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "pass"


@pytest.mark.parametrize("label", ["Current Level:", "Current Data:"])
def test_check_bip06_still_fails_a_bare_unexplained_na_under_either_label(label):
    """REAL confirmed case (Zohan Hossain's document): a bare, unexplained
    N/A under 'Current Data:' must still fail, unchanged from Round 82's
    original intent -- the label fix doesn't make N/A always pass."""
    text = _bip_block(label, "N/A")
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "fail"
    assert "unexplained" in str(evidence).lower()


@pytest.mark.parametrize("label", ["Current Level:", "Current Data:"])
def test_check_bip06_still_passes_an_explained_na_under_either_label(label):
    text = _bip_block(label, "N/A There were no direct sessions due to issues with staffing")
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "pass"


def test_check_bip06_still_fails_when_the_field_is_missing_entirely():
    text = "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0 occurrences\n"
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "fail"


# --- Real-document re-verification (both documents that exposed this bug) -

_ZOHAN_PDF = r"C:\Users\DELL\OneDrive - Master Faster\Desktop\zohan hossian\Zohran Hossain TP.pdf"
_YISROEL_PDF = r"C:\Users\DELL\OneDrive - Master Faster\Desktop\yl\YL.pdf"


def _real_fields(path):
    from pathlib import Path
    if not Path(path).exists():
        pytest.skip(f"real document not present at {path} on this machine.")
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(path)
    return fields.extract_fields(path, pages)


def test_real_yisroel_document_now_passes_matching_ground_truth():
    """THE confirmed real ground-truth regression, fixed: Ms. Yachnes's own
    checklist explicitly credits these four goals as Pass ('Current Data
    is provided for all four behavior targets')."""
    doc_fields = _real_fields(_YISROEL_PDF)
    result, evidence, page, confidence = fields._check_BIP06({}, doc_fields)
    assert result == "pass"
    assert "4" in str(evidence)


def test_real_zohan_document_still_correctly_fails_with_accurate_evidence():
    """Zohan's one real Behavior Reduction goal's Current Data value is a
    genuine bare, unexplained N/A -- the fix doesn't flip this verdict
    (there's no real data to find), but the evidence text is now accurate
    ('bare, unexplained N/A') instead of the old, misleading 'no value
    filled in at all' (which was never true -- Current Data: N/A WAS
    filled in, just unexplained)."""
    doc_fields = _real_fields(_ZOHAN_PDF)
    result, evidence, page, confidence = fields._check_BIP06({}, doc_fields)
    assert result == "fail"
    assert "unexplained" in str(evidence).lower()


@pytest.mark.parametrize("real_doc_fixture", ["reeda_tp_pdf", "charny_tp_pdf"])
def test_check_bip06_unchanged_on_prior_real_documents(request, real_doc_fixture):
    """Confirms this fix doesn't change Reeda's/Charny's already-verified
    Round 82 results."""
    pdf_path = request.getfixturevalue(real_doc_fixture)
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(pdf_path)
    doc_fields = fields.extract_fields(pdf_path, pages)
    result, evidence, page, confidence = fields._check_BIP06({}, doc_fields)
    assert result in ("pass", "fail", "not_checkable")
