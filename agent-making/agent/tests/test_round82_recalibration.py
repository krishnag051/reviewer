"""Round 82: filename/name-mismatch signal (item 1) and explained-N/A
recalibration (item 2) -- both proven generically on synthetic cases in
both directions, not just re-run against the one real document that
exposed each gap. Items 3 (QA-CI-01) and 4 (QA-HRS-09) are judgment-layer
rubric recalibrations verified live via the OpenRouter free tier (see
r82_judgment_verify.py in the scratchpad, not part of this repo) -- there is
no Python function to unit-test for those two, since neither has (or gets,
this round) a deterministic checker.
"""
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- Item 1: patient-name-vs-filename mismatch signal --------------------


@pytest.mark.parametrize("filename,expected_tokens", [
    ("Zohran Hossain TP.pdf", ["zohran", "hossain"]),
    ("Zohran_Hossain_2026-08-10_v2.pdf", ["zohran", "hossain"]),
    ("upload-3.pdf", ["upload"]),
    ("Charny Gluck TP Feedback.pdf", ["charny", "gluck"]),
])
def test_filename_name_tokens_strips_junk_dates_and_version_tags(filename, expected_tokens):
    assert fields._filename_name_tokens(filename) == expected_tokens


def test_name_token_mismatch_detail_exact_match_is_none():
    assert fields._name_token_mismatch_detail("Zohran Hossain", "Zohran Hossain TP.pdf") is None


def test_name_token_mismatch_detail_catches_the_real_confirmed_typo():
    """REAL confirmed case: document body reads 'Zohan Hossain' throughout,
    filename is 'Zohran Hossain TP.pdf' -- a one-letter typo."""
    detail = fields._name_token_mismatch_detail("Zohan Hossain", "Zohran Hossain TP.pdf")
    assert detail is not None
    assert "zohran" in detail.lower() and "zohan" in detail.lower()


def test_name_token_mismatch_detail_ignores_innocuous_filename_variation():
    """A date and a version tag added to the filename must not themselves
    register as a mismatch -- _filename_name_tokens already strips them,
    so the remaining tokens still match exactly."""
    assert fields._name_token_mismatch_detail("Zohran Hossain", "Zohran_Hossain_2026-08-10_v2.pdf") is None


def test_name_token_mismatch_detail_none_when_filename_has_no_name_tokens():
    """A generated storage-key filename (today's real production shape,
    per backend/app/storage.py::save_blob) carries no name-like tokens at
    all -- nothing to compare, must not be flagged."""
    assert fields._name_token_mismatch_detail("Zohran Hossain", "upload-3.pdf") is None


def test_name_token_mismatch_detail_does_not_flag_unrelated_low_similarity_word():
    """A filename word that's just unrelated to the patient's name (not a
    typo of it) should NOT be flagged -- low similarity means this isn't
    confidently a misspelling of THIS name."""
    assert fields._name_token_mismatch_detail("Zohran Hossain", "Intake Packet.pdf") is None


def _ppi03_doc(name: str) -> str:
    return f"Patient Name: {name} Patient DOB: 01/01/2020 Patient Insurance: 12345\n" * 2


def test_check_ppi03_passes_on_exact_filename_match():
    doc_fields = _fields(_ppi03_doc("Zohran Hossain"))
    doc_fields["source_filename"] = "Zohran Hossain TP.pdf"
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    assert result == "pass"


def test_check_ppi03_flags_the_real_confirmed_typo_as_uncertain_not_fail():
    doc_fields = _fields(_ppi03_doc("Zohan Hossain"))
    doc_fields["source_filename"] = "Zohran Hossain TP.pdf"
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    assert result == "uncertain"
    assert "Zohan" in str(evidence) and "Zohran" in str(evidence)


def test_check_ppi03_passes_on_innocuous_filename_variation():
    doc_fields = _fields(_ppi03_doc("Zohran Hossain"))
    doc_fields["source_filename"] = "Zohran_Hossain_2026-08-10_v2.pdf"
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    assert result == "pass"


def test_check_ppi03_passes_when_no_filename_signal_available():
    """Today's real production shape: no source_filename given, pdf_path
    is a generated storage key -- must remain a plain pass, unaffected by
    this round's new signal."""
    doc_fields = _fields(_ppi03_doc("Zohran Hossain"))
    doc_fields["pdf_path"] = "/tmp/storage/upload-3.pdf"
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    assert result == "pass"


def test_check_ppi03_internal_inconsistency_still_fails_regardless_of_filename():
    """The pre-existing internal-consistency check must still take
    priority -- a filename match must never mask a real internal
    inconsistency."""
    text = (
        "Patient Name: Zohran Hossain Patient DOB: 01/01/2020 Patient Insurance: 12345\n"
        "Patient Name: Zohran Hosein Patient DOB: 01/01/2020 Patient Insurance: 12345\n"
    )
    doc_fields = _fields(text)
    doc_fields["source_filename"] = "Zohran Hossain TP.pdf"
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    assert result == "fail"


# --- Item 2: QA-BIP-06 explained-N/A recalibration ------------------------


def _bip_block(current_level: str) -> str:
    return (
        f"Target Name: Reduce Elopement\nBaseline: 5 per week\nCurrent Level: {current_level}\n"
        f"Mastery Criteria: 0 occurrences\n"
    )


def test_check_bip06_passes_on_a_real_value():
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(_bip_block("2x daily")))
    assert result == "pass"


def test_check_bip06_passes_on_the_real_confirmed_explained_na():
    """REAL confirmed case: Current Level literally 'N/A' with a real
    explanatory note -- must now PASS, not fail."""
    text = _bip_block("N/A There were no direct sessions due to issues with staffing")
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "pass"


def test_check_bip06_still_fails_a_bare_unexplained_na():
    """The point of this fix isn't to make N/A always pass -- a bare N/A
    with nothing else must still fail."""
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(_bip_block("N/A")))
    assert result == "fail"
    assert "unexplained" in str(evidence).lower()


def test_check_bip06_still_fails_a_genuinely_blank_field():
    text = "Target Name: Reduce Elopement\nBaseline: 5 per week\nCurrent Level:\nMastery Criteria: 0 occurrences\n"
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "fail"


def test_check_bip06_still_fails_when_the_field_is_missing_entirely():
    text = "Target Name: Reduce Elopement\nBaseline: 5 per week\nMastery Criteria: 0 occurrences\n"
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "fail"


def test_check_bip06_not_checkable_with_no_goal_blocks_at_all():
    result, evidence, page, confidence = fields._check_BIP06({}, _fields("No goals mentioned anywhere."))
    assert result == "not_checkable"


def test_check_bip06_ignores_skill_acquisition_target_goal_blocks():
    """'Target Goal:' (skill-acquisition) blocks don't carry a Current
    Level field at all -- a document with only these must be
    not_checkable, not incorrectly failed for a field that never applies
    to that block type."""
    text = "Target Goal: Increase Manding\nBaseline: 10%\nMastery Criteria: 80% across 3 sessions\n"
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    assert result == "not_checkable"
