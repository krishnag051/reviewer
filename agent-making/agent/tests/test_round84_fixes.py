"""Round 84: the QA-BIP-05 repeated-block label-equivalence investigation
(item 1 -- confirmed the real root cause was _parse_occurrence_ceiling's
phrasing coverage, not a label mismatch), the systemic overconfident-pass
pattern (item 2: QA-PPI-05's code fix, plus judge.py's new general prompt
instruction), and QA-PROB-01's new narrative-format signal (item 3).
"""
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- Item 1: occurrence-ceiling phrasing coverage + label equivalence ----


@pytest.mark.parametrize("phrase,expected", [
    ("1 instance or less per day for 2 consecutive weeks", 1.0),
    ("0 times a week for 2 consecutive weeks", 0.0),
    ("2 instances or fewer", 2.0),
    ("3 times", 3.0),
    ("fewer than 1 occurrence", 0.5),  # unchanged existing behavior
])
def test_parse_occurrence_ceiling_recognizes_instance_and_times_phrasing(phrase, expected):
    assert fields._parse_occurrence_ceiling(phrase) == expected


def test_check_bip05_catches_the_real_confirmed_case_with_different_field_labels():
    """REAL confirmed case (the exact document became available this
    round): Target Name: page 15 ('1 instance or less per day for 2
    consecutive weeks') vs Target Goal: page 64 ('0 times a week for 2
    consecutive weeks') -- same goal, conflicting criteria, different
    field labels."""
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\n"
        "Mastery Criteria: 1 instance or less per day for 2 consecutive weeks\n"
        "Target Goal: Reduce Elopement\nBaseline: 5\n"
        "Mastery Criteria: 0 times a week for 2 consecutive weeks\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "fail"


def test_check_bip05_same_label_repeat_with_the_same_phrasing_also_fails():
    """Control: confirms the fix is in the phrasing parser, not something
    that only works when labels differ -- the SAME label repeated with
    this same conflicting phrasing must fail too (this is what proved the
    root cause wasn't a label mismatch: this control case reproduced the
    identical miss before the phrasing fix)."""
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\n"
        "Mastery Criteria: 1 instance or less per day for 2 consecutive weeks\n"
        "Target Name: Reduce Elopement\nBaseline: 5\n"
        "Mastery Criteria: 0 times a week for 2 consecutive weeks\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "fail"


def test_check_bip05_still_does_not_flag_two_different_goals_with_mixed_labels():
    text = (
        "Target Name: Reduce Elopement\nBaseline: 5\nMastery Criteria: 0-1 occurrences per week\n"
        "Target Goal: Increase Manding\nBaseline: 5\nMastery Criteria: 3-4 occurrences per week\n"
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result != "fail"


def test_check_gip05_already_correctly_treats_target_goal_and_target_name_as_equivalent():
    """Confirms _check_GIP05's own label handling (via _goal_block_starts,
    which already covers both marker forms) needed no change -- same
    identical wording, mastered under one marker convention and active
    under the other, is still caught."""
    text = (
        "Mastered Goals:\nName of Skill: Reeda will independently mand for one preferred item\n"
        "Date Mastered: 03/16/2026,  Last Three Days Average in Maintenance: 0\n"
        "Goals in Progress:\n"
        "Target Goal: Reeda will independently mand for one preferred item\nGoal Status: In progress\n"
        "Date Initiated: 01/18/2026 \nBaseline:   0%\nMastery Criteria: 80%\n"
    )
    result, evidence, page, confidence = fields._check_GIP05({}, _fields(text))
    assert result == "fail"


# --- Item 2: overconfident-pass pattern -----------------------------------


def _ppi05_doc(npi: str) -> str:
    return f"NPI: {npi}\nLicense: 12345\n" * 2


def test_check_ppi05_internal_consistency_only_now_reports_uncertain_not_pass():
    """REAL bug found and fixed: internal consistency alone (no
    supporting-doc ground truth) used to return a confident 'pass' for a
    rule named '...correct' -- now correctly 'uncertain'."""
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(_ppi05_doc("1234567890")))
    assert result == "uncertain"
    assert "not evidence of correctness" in str(evidence).lower()


def test_check_ppi05_still_passes_when_a_real_supporting_doc_ground_truth_matches():
    doc_fields = _fields(_ppi05_doc("1234567890"))
    doc_fields["supporting_doc"] = {
        "bcba_credentials_npi": {"value": "NPI 1234567890", "confidence": "high"},
    }
    result, evidence, page, confidence = fields._check_PPI05({}, doc_fields)
    assert result == "pass"
    assert "supporting document" in str(evidence).lower()


def test_check_ppi05_still_fails_a_real_contradiction():
    text = "NPI: 1234567890\nLicense: 12345\nNPI: 9999999999\nLicense: 12345\n"
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(text))
    assert result == "fail"


def test_check_ppi05_still_not_checkable_with_no_fields_at_all():
    result, evidence, page, confidence = fields._check_PPI05({}, _fields("No NPI or License anywhere."))
    assert result == "not_checkable"


# --- Item 3: QA-PROB-01 narrative-format signal ---------------------------


_NARRATIVE_EVIDENCE = (
    "During assessment and caregiver interview, the client demonstrated significant deficits in "
    "social-emotional reciprocity. She rarely initiates social interactions or conversations, and "
    "when others attempt to engage her, she may briefly look in their direction before returning to "
    "her preferred activity."
)

_MATRIX_EVIDENCE = (
    "Eye contact: poor\n"
    "Turn taking: absent\n"
    "Joint attention: minimal\n"
    "Peer interest: low\n"
)


@pytest.mark.parametrize("real_evidence", [
    _NARRATIVE_EVIDENCE,
    # Confirmed real (Charny's TP): a stacked LIST of full sentences is
    # still narrative prose, not a matrix -- must not be flagged.
    (
        "Client avoids initiating conversation and often remains quiet or disengaged (in progress).\n"
        "Client provides single responses and does not independently continue the exchange.\n"
        "Client struggles to show interest in another person's comments.\n"
    ),
])
def test_looks_like_structured_matrix_does_not_flag_real_narrative_content(real_evidence):
    assert not fields._looks_like_structured_matrix(real_evidence)


def test_looks_like_structured_matrix_flags_a_synthetic_checklist_layout():
    assert fields._looks_like_structured_matrix(_MATRIX_EVIDENCE)


def test_check_prob01_passes_narrative_format_unchanged():
    text = f"Problem Areas:\nProblem Area:\nSome DSM criteria text.\nAs evidenced by: {_NARRATIVE_EVIDENCE}\nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_PROB01({}, _fields(text))
    assert result == "not_checkable"  # narrative confirmed clean; count still needs judgment
    assert "narrative prose" in str(evidence).lower()


def test_check_prob01_now_fails_a_matrix_checklist_layout():
    """Confirmed real gap: a checklist/matrix-formatted 'As evidenced by'
    section used to pass this rule despite the checklist requiring
    narrative format -- now flagged."""
    text = f"Problem Areas:\nProblem Area:\nSome DSM criteria text.\nAs evidenced by:\n{_MATRIX_EVIDENCE}\nGoal Progress:\n"
    result, evidence, page, confidence = fields._check_PROB01({}, _fields(text))
    assert result == "fail"


def test_check_prob01_not_checkable_with_no_evidenced_content():
    result, evidence, page, confidence = fields._check_PROB01({}, _fields("No problem areas section here."))
    assert result == "not_checkable"


@pytest.mark.parametrize("real_doc_fixture", ["reeda_tp_pdf", "charny_tp_pdf", "yisroel_tp_pdf"])
def test_check_prob01_zero_false_positives_on_real_documents(request, real_doc_fixture):
    pdf_path = request.getfixturevalue(real_doc_fixture)
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(pdf_path)
    doc_fields = fields.extract_fields(pdf_path, pages)
    result, evidence, page, confidence = fields._check_PROB01({}, doc_fields)
    assert result != "fail"
