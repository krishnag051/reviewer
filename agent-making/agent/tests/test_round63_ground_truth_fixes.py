"""Round 63: 8 real bugs found comparing the agent's real output for
Yisroel Leibowitz's TP against Ms. Yachnes's independent ground-truth
review. Every fixture in this file is SYNTHETIC and clearly labeled as
such -- none reference Yisroel's name, dates, or hour counts -- per this
round's own hard instruction to fix general root causes, not memorize one
patient's document. Zero model calls anywhere in this file.
"""
from pipeline import fields
from pipeline.session_note_comparison import compare_session_note_to_tp


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# ---------------------------------------------- item 2: extract_acf_fields --


def test_extract_acf_fields_finds_all_four_when_present():
    text = (
        "Assessment of Current Functioning:\n"
        "Provider Location During Assessment: Office\n"
        "Patient Location during Assessment: Office\n"
        "Assessment Date: 04/10/2025\n"
        "The PEAK was administered.\n"
        "Assessment Methods/Measures: standardized testing\n"
        "Assessment Summary Statement: client demonstrated age-appropriate skills.\n"
        "Goal Progress:\n"
    )
    result = fields.extract_acf_fields(_fields(text))
    assert result == {
        "assessment_date": "04/10/2025",
        "pos": "Office",
        "patient_location": "Office",
        "assessment_tool": "PEAK",
    }


def test_extract_acf_fields_returns_none_for_missing_fields_not_a_guess():
    text = (
        "Assessment of Current Functioning: Please add all info below.\n"
        "Provider Location During Assessment:   \nPatient Location during Assessment:   \n"
        "Assessment Date:   \nAssessment Methods/Measures:\nAssessment Summary Statement:\n"
        "Goal Progress:\n"
    )
    result = fields.extract_acf_fields(_fields(text))
    assert result == {"assessment_date": None, "pos": None, "patient_location": None, "assessment_tool": None}


def test_extract_acf_fields_none_when_section_missing_entirely():
    result = fields.extract_acf_fields(_fields("unrelated text with no ACF section"))
    assert result == {"assessment_date": None, "pos": None, "patient_location": None, "assessment_tool": None}


# --- item 2, end-to-end: extracted TP fields actually reach the comparison -


def _synthetic_session_extraction(**overrides) -> dict:
    base = {
        "session_date": {"value": "04/10/2025", "confidence": "high", "source_quote": "q"},
        "session_location": {"value": "Office", "confidence": "high", "source_quote": "q"},
        "clinician_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "patient_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "assessment_activity": {"value": "PEAK", "confidence": "high", "source_quote": "q"},
    }
    base.update(overrides)
    return base


def test_wired_end_to_end_matching_case_passes_acf02_and_acf08():
    """A TP whose extracted ACF fields genuinely agree with a synthetic
    session note -- proves the real extracted TP data reaches the
    comparison and produces a real pass, not an 'uncertain, TP doesn't
    state this' despite the TP actually stating it."""
    tp_text = (
        "Assessment of Current Functioning:\n"
        "Provider Location During Assessment: Office\n"
        "Patient Location during Assessment: Office\n"
        "Assessment Date: 04/10/2025\n"
        "The PEAK was administered.\n"
        "Goal Progress:\n"
    )
    acf = fields.extract_acf_fields(_fields(tp_text))
    result = compare_session_note_to_tp(
        _synthetic_session_extraction(),
        tp_current_report_period="04/01/2025 to 04/15/2025",
        tp_assessment_date=acf["assessment_date"],
        tp_pos=acf["pos"],
        tp_patient_location=acf["patient_location"],
        tp_assessment_tool=acf["assessment_tool"],
    )
    assert result["QA-ACF-02"]["result"] == "pass"
    assert result["QA-ACF-08"]["result"] == "pass"


def test_wired_end_to_end_mismatching_case_fails_acf02_and_acf08():
    """Same wiring, but the TP's real extracted fields deliberately
    DISAGREE with the session note -- proves the fix works in the other
    direction too, not just a lucky match."""
    tp_text = (
        "Assessment of Current Functioning:\n"
        "Provider Location During Assessment: Home\n"
        "Patient Location during Assessment: Home\n"
        "Assessment Date: 04/10/2025\n"
        "The ABLLS-R was administered.\n"
        "Goal Progress:\n"
    )
    acf = fields.extract_acf_fields(_fields(tp_text))
    result = compare_session_note_to_tp(
        _synthetic_session_extraction(),  # session note says Office / PEAK
        tp_current_report_period="04/01/2025 to 04/15/2025",
        tp_assessment_date=acf["assessment_date"],
        tp_pos=acf["pos"],
        tp_patient_location=acf["patient_location"],
        tp_assessment_tool=acf["assessment_tool"],
    )
    assert result["QA-ACF-02"]["result"] == "fail"
    assert result["QA-ACF-08"]["result"] == "fail"


# ------------------------------------------- item 3: QA-SCH-01 / QA-SCH-07 --
# SYNTHETIC schedules with hand-verified totals, deliberately different from
# Yisroel's real 31 hrs/week and from each other. See
# test_round63_schedule_hours.py for the arithmetic module's own thorough
# unit coverage -- these tests are specifically about the wired-in checker
# functions (rule dispatch, params, evidence text), not the arithmetic
# itself.

_SCH01_RULE = {"rule_id": "QA-SCH-01", "params": {"cpt_code": "97153"}}
_SCH07_RULE = {"rule_id": "QA-SCH-07", "params": {"daily_hours_threshold": 3}}


def _synthetic_schedule_tp_text(schedule_row: str, weekly_hours: float) -> str:
    return (
        "Sunday Monday Tuesday Wednesday Thursday Friday Saturday\n"
        "School Schedule n/a  8am-3pm  8am-3pm  8am-3pm  8am-3pm  8am-3pm  n/a  \n"
        "Patient Schedule\nof ABA Services\n"
        f"{schedule_row}\n"
        "POS Home  n/a  Home  Home  Home  Home  Home  \n"
        f"{weekly_hours}  hours per\nweek.\n97153-Direct Care Behavior\nTechnician\n"
    )


def test_sch01_pass_when_schedule_total_matches_requested_hours():
    # 4 weekdays x 4 hrs/day = 16 hrs/week, matching the requested 16.
    text = _synthetic_schedule_tp_text(
        "n/a  9am-1pm  9am-1pm  9am-1pm  9am-1pm  n/a  n/a  ", weekly_hours=16,
    )
    result, evidence, page, confidence = fields._check_SCH01(_SCH01_RULE, _fields(text))
    assert result == "pass"
    assert "16" in evidence


def test_sch01_fail_when_schedule_total_does_not_match_requested_hours():
    """Directly targets the confirmed real bug shape: requested hours say
    one number, the schedule table's real computed total is a DIFFERENT
    number -- must fail, not silently agree."""
    text = _synthetic_schedule_tp_text(
        "n/a  9am-1pm  9am-1pm  9am-1pm  9am-1pm  n/a  n/a  ", weekly_hours=20,
    )
    result, evidence, page, confidence = fields._check_SCH01(_SCH01_RULE, _fields(text))
    assert result == "fail"
    assert "16" in evidence and "20" in evidence


def test_sch01_not_checkable_when_schedule_table_unparseable():
    result, evidence, page, confidence = fields._check_SCH01(_SCH01_RULE, _fields("no schedule table at all"))
    assert result == "not_checkable"


def test_sch07_pass_when_no_day_exceeds_threshold():
    text = _synthetic_schedule_tp_text(
        "n/a  9am-11am  9am-11am  9am-11am  9am-11am  n/a  n/a  ", weekly_hours=8,
    )
    result, evidence, page, confidence = fields._check_SCH07(_SCH07_RULE, _fields(text))
    assert result == "pass"


def test_sch07_fail_when_a_day_exceeds_threshold():
    """A single long day (5 hrs, over the 3 hr/day threshold) must fail and
    name the specific day -- not average across the week."""
    text = _synthetic_schedule_tp_text(
        "n/a  9am-2pm  9am-11am  9am-11am  9am-11am  n/a  n/a  ", weekly_hours=13,
    )
    result, evidence, page, confidence = fields._check_SCH07(_SCH07_RULE, _fields(text))
    assert result == "fail"
    assert "Monday" in evidence


def test_sch07_not_checkable_when_schedule_table_unparseable():
    result, evidence, page, confidence = fields._check_SCH07(_SCH07_RULE, _fields("no schedule table at all"))
    assert result == "not_checkable"


# ------------------------------------------------------- item 5: QA-PROB-02 --


def test_prob02_fails_when_evidence_entry_is_a_planted_reviewer_comment():
    """SYNTHETIC fixture with a deliberately planted embedded reviewer
    comment standing in for real clinical evidence -- must fail
    deterministically, not silently pass because the LLM never gets a
    chance to weigh in on the wrong candidate."""
    text = (
        "Problem Area: Communication\n"
        "As evidenced by: Is this goal still relevant given the recent progress update?\n"
        "Problem Area: Social\n"
        "As evidenced by: Client initiates greetings with peers during structured play.\n"
    )
    result, evidence, page, confidence = fields._check_PROB02({}, _fields(text))
    assert result == "fail"
    assert "reviewer comment" in evidence.lower()


# ------------------------------------------------ item 6: QA-GIP-04 broadened


def test_gip04_still_catches_literal_invalid_date_string():
    text = "Anticipated Mastery Date: Invalid Date\n"
    result, evidence, page, confidence = fields._check_GIP04({}, _fields(text))
    assert result == "fail"
    assert "Invalid Date" in evidence


def test_gip04_now_catches_blank_anticipated_mastery_date():
    """SYNTHETIC fixture: no literal 'Invalid Date' string anywhere, but
    the Anticipated Mastery Date field is blank -- must fail, not silently
    pass just because the literal string isn't present."""
    text = (
        "Target Goal: Client will do the thing.\n"
        "Baseline: 10%\nMastery Criteria: 80% over 3 sessions\nSampling Method: Percent Correct\n"
        "Anticipated Mastery Date:\n"
        "Target Goal: Next goal.\n"
    )
    result, evidence, page, confidence = fields._check_GIP04({}, _fields(text))
    assert result == "fail"
    assert "blank" in evidence.lower()


def test_gip04_passes_when_all_mastery_dates_are_filled_in():
    text = (
        "Target Goal: Client will do the thing.\n"
        "Baseline: 10%\nMastery Criteria: 80% over 3 sessions\nSampling Method: Percent Correct\n"
        "Anticipated Mastery Date: 06/01/2026\n"
    )
    result, evidence, page, confidence = fields._check_GIP04({}, _fields(text))
    assert result == "pass"


# --------------------------------------- item 7: QA-GIP-16 vs QA-GIP-10 gap


def test_gip16_now_catches_blank_mastery_criteria_with_no_sampling_method():
    """SYNTHETIC fixture: blank Mastery Criteria AND no Sampling Method
    field in the same block -- the one case QA-GIP-10 structurally can't
    catch (it requires a Sampling Method match first). Must now fail."""
    text = "Target Name: X will reduce tantrums\nBaseline: 7x daily\nMastery Criteria:\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(text))
    assert result == "fail"
    assert "no Sampling Method" in evidence or "Sampling Method" in evidence


def test_gip16_defers_to_gip10_when_sampling_method_is_present():
    """When Sampling Method IS present, GIP-16 must NOT also flag the blank
    Mastery Criteria -- that's QA-GIP-10's job (avoid double-reporting the
    same violation as if it were two separate problems)."""
    text = "Target Goal: X\nBaseline: 10%\nMastery Criteria:\nSampling Method: Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(text))
    assert result == "pass"
    # Confirm QA-GIP-10 IS the one that catches it, so the gap is genuinely closed overall.
    gip10_result, gip10_evidence, _, _ = fields._check_GIP10({}, _fields(text))
    assert gip10_result == "fail"
    assert "blank" in gip10_evidence.lower()


def test_prob02_not_checkable_escalates_when_evidence_is_clean():
    """No reviewer-comment violation present -- must escalate to judgment
    for the real semantic-alignment question, not claim a DET pass it
    can't actually confirm."""
    text = (
        "Problem Area: Communication\n"
        "As evidenced by: Client uses 2-word phrases to request preferred items during snack time.\n"
    )
    result, evidence, page, confidence = fields._check_PROB02({}, _fields(text))
    assert result == "not_checkable"
    assert fields.needs_escalation({"result": result, "evidence": evidence, "confidence": confidence})
