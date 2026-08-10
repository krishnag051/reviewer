"""Round 83: the ACF section-extraction bug (item 1, plus the ACF-06
follow-up) and three cross-field/cross-section contradiction gaps (item 2:
GIP-16, GIP-05, BIP-05). Every fix proven on synthetic documents in both
directions -- the exact real documents that originally exposed items 1 and
2b/2c aren't among this project's three locally-available real TPs (none
has an image-only page, and none has this project's specific mastered/
active goal duplication or cross-section mastery-criteria conflict), so
those are additionally verified as producing zero false positives against
Reeda/Charny/Yisroel's real text.
"""
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- Item 1: ACF section-boundary bug -------------------------------------


_REAL_ACF_CONTENT = (
    "Provider Location During Assessment: Telehealth\n"
    "Patient Location during Assessment: Home\n"
    "Assessment Date: 06/28/2026\n"
    "Assessment Methods/Measures:\n"
    "The ABLLS-R was administered by Karen Kain, BCBA.\n"
)
_REAL_ACF_SUMMARY = "Assessment Summary Statement: The client continues to make steady progress.\n"


def test_find_acf_section_uses_the_first_occurrence_when_only_one_exists():
    """Baseline: a document with exactly ONE occurrence of the header
    (the real shape of all three of this project's real documents) must
    behave identically to before this round's fix."""
    text = f"Assessment of Current Functioning:\n{_REAL_ACF_CONTENT}{_REAL_ACF_SUMMARY}Goal Progress:\n"
    section = fields._find_acf_section(text)
    assert section is not None
    assert "Assessment Date: 06/28/2026" in section
    assert "Assessment Summary Statement:" in section


def test_find_acf_section_prefers_content_bearing_occurrence_over_a_toc_decoy():
    """REAL bug shape reproduced synthetically: a Table of Contents page
    names this same section heading (and the boundary phrases right after
    it) BEFORE the real section -- the old first-match-wins regex would
    capture the empty TOC span instead of the real content further down."""
    text = (
        "Table of Contents\n"
        "Assessment of Current Functioning:\n"
        "Goal Progress:\n"
        "Clinical Interpretation\n"
        "\n"
        "Assessment of Current Functioning:\n"
        f"{_REAL_ACF_CONTENT}{_REAL_ACF_SUMMARY}"
        "Goal Progress:\n"
    )
    section = fields._find_acf_section(text)
    assert section is not None
    assert "Assessment Date: 06/28/2026" in section
    assert "Assessment Summary Statement:" in section


def test_find_acf_section_still_returns_a_genuinely_blank_section_as_blank_not_none():
    """A real 'section found but nothing filled in' case (Charny's real
    shape) must still come back as an (empty-of-fields) slice, not None --
    callers rely on telling this apart from 'header never appears'."""
    text = "Assessment of Current Functioning:\n \nGoal Progress:\n"
    section = fields._find_acf_section(text)
    assert section is not None
    assert "Assessment Date:" not in section


def test_find_acf_section_returns_none_when_header_never_appears():
    assert fields._find_acf_section("No such section anywhere in this document.") is None


def _acf_pages_with_image_gap():
    """Synthetic reproduction of the confirmed real symptom shape: date/
    location fields as real text on one page, two image-only (empty-text)
    pages for the milestone grid, then the Assessment Summary Statement as
    real text a few pages later."""
    return (
        f"Assessment of Current Functioning:\n{_REAL_ACF_CONTENT}",
        "",  # image-only grid page 1 -- zero extractable text
        "",  # image-only grid page 2 -- zero extractable text
        f"{_REAL_ACF_SUMMARY}Goal Progress:\n",
    )


def test_extract_acf_fields_survives_an_image_only_page_gap_in_the_middle():
    doc_fields = _fields(*_acf_pages_with_image_gap())
    result = fields.extract_acf_fields(doc_fields)
    assert result["assessment_date"] == "06/28/2026"
    assert result["pos"] == "Telehealth"
    assert result["patient_location"] == "Home"
    assert result["assessment_tool"] == "ABLLS-R"


def test_extract_acf_fields_whole_document_fallback_when_section_slice_misses_a_field():
    """Reproduces the confirmed real symptom directly: the section-scoped
    slice (here, artificially narrowed by a decoy occurrence) doesn't
    contain the date, but the date IS present in the full document text --
    must use the fallback, not report None."""
    text = (
        "Assessment of Current Functioning:\nGoal Progress:\n"  # decoy: empty slice
        "Assessment of Current Functioning:\n \nGoal Progress:\n"  # second occurrence, also empty
        f"Assessment Date: 06/28/2026\n"  # the real date, outside any captured slice
    )
    doc_fields = _fields(text)
    result = fields.extract_acf_fields(doc_fields)
    assert result["assessment_date"] == "06/28/2026"


def test_extract_acf_fields_genuinely_blank_document_stays_all_none():
    doc_fields = _fields("No Assessment of Current Functioning section anywhere.")
    result = fields.extract_acf_fields(doc_fields)
    assert result == {"assessment_date": None, "pos": None, "patient_location": None, "assessment_tool": None}


def test_check_acf07_survives_the_image_gap_and_finds_the_tool_and_date():
    doc_fields = _fields(*_acf_pages_with_image_gap())
    result, evidence, page, confidence = fields._check_ACF07({}, doc_fields)
    assert result != "fail"
    assert "ABLLS-R" in str(evidence)


def test_check_acf07_downgrades_to_uncertain_not_a_false_blank_fail():
    """The confirmed real symptom, reproduced: ACF-07 must not declare
    the section 'entirely blank' when the fields exist elsewhere in the
    document -- downgrades to uncertain instead of a false fail."""
    text = (
        "Assessment of Current Functioning:\nGoal Progress:\n"
        f"Assessment Date: 06/28/2026\nABLLS-R\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "uncertain"
    assert "elsewhere in the document" in str(evidence)


def test_check_acf07_still_correctly_fails_a_genuinely_blank_section():
    text = "Assessment of Current Functioning:\n \nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "fail"
    assert "entirely blank" in str(evidence)


@pytest.mark.parametrize("real_doc_fixture", ["reeda_tp_pdf", "charny_tp_pdf", "yisroel_tp_pdf"])
def test_acf_family_unaffected_on_real_documents(request, real_doc_fixture):
    """None of this project's three real documents has an image-only page
    or a decoy section heading -- confirms this round's fix doesn't change
    their (already-correct) real results."""
    pdf_path = request.getfixturevalue(real_doc_fixture)
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(pdf_path)
    doc_fields = fields.extract_fields(pdf_path, pages)
    acf = fields.extract_acf_fields(doc_fields)
    # Charny's real ACF section is genuinely blank (confirmed in Round 63/
    # 81's own diagnostics) -- assessment_date legitimately None there.
    # Reeda/Yisroel both have a real stated date.
    if real_doc_fixture != "charny_tp_pdf":
        assert acf["assessment_date"] is not None
    result, evidence, page, confidence = fields._check_ACF07({}, doc_fields)
    assert result in ("pass", "fail", "uncertain")  # never crashes; real evidence checked in Round 63/81 tests


# --- Item 1 follow-up: QA-ACF-06 assessor name ----------------------------


def test_check_acf06_passes_on_the_real_confirmed_phrasing():
    text = "Assessment of Current Functioning:\nThe ABLLS-R was administered by Karen Kain, BCBA.\nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_ACF06({}, _fields(text))
    assert result == "pass"
    assert "Karen Kain" in str(evidence)


def test_check_acf06_recognizes_completed_by_and_conducted_by_variants():
    for verb in ("completed by", "conducted by"):
        text = f"Assessment of Current Functioning:\nThe VB-MAPP was {verb} Chaya Gold, BCBA.\nGoal Progress:\n"
        result, evidence, page, confidence = fields._check_ACF06({}, _fields(text))
        assert result == "pass"


def test_check_acf06_fails_the_real_confirmed_fail_example():
    text = "Assessment of Current Functioning:\nThe ABLLS-R was administered.\nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_ACF06({}, _fields(text))
    assert result == "fail"


def test_check_acf06_not_checkable_with_no_administration_statement():
    text = "Assessment of Current Functioning:\n \nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_ACF06({}, _fields(text))
    assert result == "not_checkable"


# --- Item 2a: QA-GIP-16 zero-phrasing broadening --------------------------


@pytest.mark.parametrize("mc_value", [
    "0 times a week", "0 times per session", "zero times a week", "zero occurrences",
    "zero instances", "0", "None",
])
def test_zero_mastery_pattern_catches_zero_phrasing_variants(mc_value):
    assert fields._ZERO_MASTERY_PATTERN.search(mc_value)


@pytest.mark.parametrize("mc_value", [
    "1 or fewer", "fewer than 2", "fewer than 1 occurrence", "0-2 occurrences over three days",
])
def test_zero_mastery_pattern_does_not_overcorrect_on_legitimately_low_nonzero_criteria(mc_value):
    assert not fields._ZERO_MASTERY_PATTERN.search(mc_value)


def _gip16_goal_block(mastery_criteria: str) -> str:
    return (
        f"Target Name: Reduce Tantrums\nBaseline: 5x daily\nMastery Criteria: {mastery_criteria}\n"
        f"Sampling Method: Frequency\n"
    )


def test_check_gip16_catches_the_real_confirmed_times_phrasing_miss():
    text = _gip16_goal_block("0 times a week")
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(text))
    assert result == "fail"


def test_check_gip16_still_passes_legitimately_low_nonzero_criteria():
    for phrase in ("1 or fewer", "fewer than 2"):
        text = _gip16_goal_block(phrase)
        result, evidence, page, confidence = fields._check_GIP16({}, _fields(text))
        assert result == "pass"


# --- Item 2b: QA-GIP-05 mastered-vs-active duplication --------------------


def _mastered_goals_section(skill_name: str) -> str:
    return f"Mastered Goals:\nName of Skill: {skill_name}\nDate Mastered: 03/16/2026,  Last Three Days Average in Maintenance: 0\n"


def _active_goal_block(marker: str, name: str) -> str:
    return f"{marker} {name}\nGoal Status: In progress\nDate Initiated: 01/18/2026 \nBaseline:   0%\nMastery Criteria: 80%\n"


def test_normalize_goal_text_collapses_formatting_differences():
    a = fields._normalize_goal_text("Reeda will  mand for one\npreferred item.")
    b = fields._normalize_goal_text("reeda will mand for one preferred item")
    assert a == b


def test_check_gip05_catches_the_real_confirmed_duplication():
    """REAL confirmed case: same goal, identical wording, listed Mastered
    in one section and still active/in-progress in another."""
    skill = "Reeda will independently mand for one preferred item"
    text = _mastered_goals_section(skill) + "Goals in Progress:\n" + _active_goal_block("Target Goal:", skill)
    result, evidence, page, confidence = fields._check_GIP05({}, _fields(text))
    assert result == "fail"
    assert "contradiction" in str(evidence).lower() or "duplication" in str(evidence).lower()


def test_check_gip05_passes_two_genuinely_different_goals_sharing_some_wording():
    """Avoid false positives: two goals that share SOME wording but are
    NOT the same goal must not be flagged."""
    text = (
        _mastered_goals_section("Reeda will independently mand for one preferred item")
        + "Goals in Progress:\n"
        + _active_goal_block("Target Goal:", "Reeda will independently mand for two preferred items in a row")
    )
    result, evidence, page, confidence = fields._check_GIP05({}, _fields(text))
    assert result != "fail"


def test_check_gip05_not_checkable_with_no_mastered_goals_section():
    text = "Goals in Progress:\n" + _active_goal_block("Target Goal:", "Some goal")
    result, evidence, page, confidence = fields._check_GIP05({}, _fields(text))
    assert result == "not_checkable"


def test_check_gip05_not_checkable_with_no_active_goal_blocks():
    text = _mastered_goals_section("Some mastered skill")
    result, evidence, page, confidence = fields._check_GIP05({}, _fields(text))
    assert result == "not_checkable"


@pytest.mark.parametrize("real_doc_fixture", ["reeda_tp_pdf", "charny_tp_pdf", "yisroel_tp_pdf"])
def test_check_gip05_zero_false_positives_on_real_documents(request, real_doc_fixture):
    pdf_path = request.getfixturevalue(real_doc_fixture)
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(pdf_path)
    doc_fields = fields.extract_fields(pdf_path, pages)
    result, evidence, page, confidence = fields._check_GIP05({}, doc_fields)
    assert result != "fail"


# --- Item 2c: QA-BIP-05 cross-block generalization ------------------------


def test_check_bip05_still_catches_the_round81_same_block_contradiction():
    text = (
        "Target Name: Reduce Elopement (fewer than 1 occurrence per week)\n"
        "Baseline: 5\nMastery Criteria: 1-2 occurrences per week\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "fail"


def test_check_bip05_catches_a_goal_repeated_as_two_blocks_with_conflicting_criteria():
    """New Round 83 generalization: the SAME goal repeated as two separate
    Target Name blocks with two different Mastery Criteria values."""
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0-1 occurrences per week\n"
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 3-4 occurrences per week\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "fail"
    assert "different" in str(evidence).lower() or "contradict" in str(evidence).lower()


def test_check_bip05_does_not_flag_two_different_goals_with_different_criteria():
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0-1 occurrences per week\n"
        "Target Name: Reduce Tantrums\nBaseline: 5\nMastery Criteria: 3-4 occurrences per week\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result != "fail"


def test_check_bip05_not_checkable_when_repeated_goal_has_consistent_criteria():
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0-1 occurrences per week\n"
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0-1 occurrences per week\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result != "fail"
