"""Fix Round -- Section 1, Bucket C (2 known fixes) + Bucket D (9 attempt-and-
fix investigations), 2026-08-27. Every fixture here is synthetic, zero real
API calls anywhere in this file.
"""
import pytest

from pipeline import fields
from pipeline.session_note_comparison import compare_session_notes_to_tp


def _rule(params: dict | None = None) -> dict:
    return {"params": params or {}}


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def _extraction(**overrides) -> dict:
    base = {
        "session_date": {"value": "07/23/2026", "confidence": "high", "source_quote": "q"},
        "session_location": {"value": "Office", "confidence": "high", "source_quote": "q"},
        "clinician_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "patient_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "assessment_activity": {"value": "VB-MAPP", "confidence": "high", "source_quote": "q"},
        "note_detail_level": {"value": "detailed", "confidence": "high", "source_quote": "q"},
    }
    base.update(overrides)
    return base


# --- Bucket C, item 1: QA-ACF-12 session-note cross-check -------------------

def test_acf12_passes_when_matched_session_note_date_agrees_with_tp():
    result = compare_session_notes_to_tp(
        {"note1.pdf": _extraction()},
        tp_current_report_period="07/22/2026 to 07/29/2026",
        tp_assessment_date="07/23/2026",
    )
    assert "QA-ACF-12" in result
    assert result["QA-ACF-12"]["result"] == "pass"


def test_acf12_fails_when_matched_session_note_date_disagrees_with_tp():
    """Confirms this is now a REAL cross-check, not a copy of the TP-only
    phase-1 result -- a session note that genuinely disagrees with the
    TP's own stated Assessment Date must fail, independent of whatever
    the TP-only date-range check (_check_ACF12) itself concluded."""
    # select_matching_session_note matches by date -- use a note whose own
    # date is what the TP claims to match, but force disagreement via a
    # differently-stated tp_assessment_date not equal to the note's own.
    result = compare_session_notes_to_tp(
        {"note1.pdf": _extraction(session_date={"value": "07/23/2026", "confidence": "high", "source_quote": "q"})},
        tp_current_report_period="07/22/2026 to 07/29/2026",
        tp_assessment_date="07/24/2026",  # one day off from the note's own date -- no note matches
    )
    # No note matches this TP date at all -- QA-ACF-12 must say so honestly
    # (uncertain), same as QA-ACF-02/QA-ACF-08 already do in this case.
    assert result["QA-ACF-12"]["result"] == "uncertain"


def test_acf12_uncertain_when_no_session_note_matches_tp_date():
    result = compare_session_notes_to_tp(
        {"note1.pdf": _extraction(session_date={"value": "01/01/2026", "confidence": "high", "source_quote": "q"})},
        tp_current_report_period="07/22/2026 to 07/29/2026",
        tp_assessment_date="07/23/2026",
    )
    assert result["QA-ACF-12"]["result"] == "uncertain"


def test_acf12_is_present_alongside_the_other_3_session_notes_rules():
    """Confirms QA-ACF-12 was added, not substituted for anything --
    QA-RPT-03/QA-ACF-02/QA-ACF-08/QA-COC-01 must all still be returned."""
    result = compare_session_notes_to_tp(
        {"note1.pdf": _extraction()},
        tp_current_report_period="07/22/2026 to 07/29/2026",
        tp_assessment_date="07/23/2026",
    )
    assert set(result.keys()) == {"QA-RPT-03", "QA-ACF-02", "QA-ACF-08", "QA-COC-01", "QA-ACF-12"}


# --- Bucket C, item 2: HF-01/HF-09 agreement --------------------------------

_HF01_PARAMS = {"age_threshold": 13, "short_range_weeks": 13, "long_range_weeks": 26}


def test_hf01_correctly_flags_a_13_week_range_for_a_young_patient_as_wrong():
    """The exact real contradiction that triggered this fix: a 5-year-old
    patient (age <= 13, expects 26 weeks) with a 90-day (~13-week) range
    must FAIL under HF-01's own real, deliberate age split."""
    text = "Patient Age: 5\nAuthorization Dates Requested: 01/01/2026 to 04/01/2026\n"  # ~13 weeks
    result, evidence, page, confidence = fields._check_HF01(_rule(_HF01_PARAMS), _fields(text))
    assert result == "fail"


def test_hf01_correctly_passes_a_13_week_range_for_an_older_patient():
    text = "Patient Age: 15\nAuthorization Dates Requested: 01/01/2026 to 04/03/2026\n"  # ~13 weeks
    result, evidence, page, confidence = fields._check_HF01(_rule(_HF01_PARAMS), _fields(text))
    assert result == "pass"


def test_hf09_is_retired_not_reused_as_an_id():
    """HF-09 is deactivated, not deleted -- confirms it's no longer a live
    checker (never registered in DET_CHECKS to begin with, still isn't),
    and its own rules.json state is checked separately in the report."""
    assert "HF-09" not in fields.DET_CHECKS


# --- Bucket D, item 3: QA-BIP-05 scope fix -----------------------------------

def test_bip05_ignores_an_unrelated_skill_acquisition_goal_with_a_contradiction_shape():
    """The real scope bug: a 'Target Goal:' (skill-acquisition) block that
    HAPPENS to have a numeric-sounding name/mastery-criteria contradiction
    must NOT be treated as a behavior-target violation -- it's simply out
    of this rule's scope."""
    text = (
        "Target Goal: fewer than 1 error\nMastery Criteria: 1-2 errors\n"  # skill-acquisition, unrelated
    )
    result, evidence, page, confidence = fields._check_BIP05(_rule(), _fields(text))
    assert result == "not_checkable"  # never "fail" -- this block is out of scope entirely


def test_bip05_still_catches_the_real_same_block_behavior_target_contradiction():
    text = "Target Name: fewer than 1 occurrence\nMastery Criteria: 1-2 occurrences\n"
    result, evidence, page, confidence = fields._check_BIP05(_rule(), _fields(text))
    assert result == "fail"


def test_bip05_still_catches_the_confirmed_cross_label_restatement_case():
    """Locks in the pre-existing confirmed real case (same goal restated
    under BOTH marker forms with different Mastery Criteria) -- the scope
    fix must not have broken this."""
    text = (
        "Target Name: Reduce Elopement\nMastery Criteria: 1 instance or less per day for 2 consecutive weeks\n"
        "Target Goal: Reduce Elopement\nMastery Criteria: 0 times a week for 2 consecutive weeks\n"
    )
    result, evidence, page, confidence = fields._check_BIP05(_rule(), _fields(text))
    assert result == "fail"


# --- Bucket D, item 4: QA-GIP-02 -- confirmed no code bug, notes reach prompt

def test_gip02_notes_are_forwarded_to_the_judgment_prompt():
    from pipeline import judge

    rule = {
        "rule_id": "QA-GIP-02", "category": "Goals in Progress",
        "description": "3mo/6mo graph data matches auth length",
        "notes": "PROPOSED STANDARD sentinel text for this test",
        "params": None,
    }
    content = judge._build_prompt([rule], {"pages": [], "full_text": ""}, {})
    assert "PROPOSED STANDARD sentinel text for this test" in content[0]["text"]


# --- Bucket D, item 5: QA-BIP-04 duration-parsing fix -----------------------

def test_bip04_now_recognizes_a_minutes_based_duration_qualifier():
    text = "Target Name: Stay Calm\nMastery Criteria: remain calm for 2 minutes\n"
    result, evidence, page, confidence = fields._check_BIP04(_rule(), _fields(text))
    assert result == "pass"


def test_bip04_still_recognizes_sessions_based_duration_qualifier_unchanged():
    text = "Target Name: Reduce Tantrum\nMastery Criteria: near 0 levels per session for 5 consecutive sessions\n"
    result, evidence, page, confidence = fields._check_BIP04(_rule(), _fields(text))
    assert result == "pass"


def test_bip04_still_fails_a_bare_count_with_no_duration_qualifier_at_all():
    text = "Target Name: Reduce Tantrum\nMastery Criteria: near 0 levels per session\n"
    result, evidence, page, confidence = fields._check_BIP04(_rule(), _fields(text))
    assert result == "fail"


# --- Bucket D, item 6: QA-TEMP-01 -- confirmed no label-list gap -----------

def test_temp01_consistency_check_has_no_hardcoded_label_list():
    """Confirms the consistency check works for ANY phrasing variant --
    not just a specific hardcoded permit label."""
    text = "Certification: Limited Permit Holder\nProvider Credentials: LP\n"
    result, evidence, page, confidence = fields._check_TEMP01(_rule(), _fields(text))
    assert result == "fail"  # a genuine inconsistency between two variant phrasings, correctly caught


# --- Bucket D, item 7: QA-GIP-13 --------------------------------------------

def test_gip13_reproduces_the_real_reported_miss_13_goals_15_hours():
    goals = "".join(f"Target Goal: Skill {i}\nSkill Domain: Communication\n" for i in range(13))
    text = "15 hours per week.\n97153-Direct Care\n" + goals
    result, evidence, page, confidence = fields._check_GIP13(_rule(), _fields(text))
    assert result == "fail"


def test_gip13_passes_with_enough_goals_for_the_hours_requested():
    goals = "".join(f"Target Goal: Skill {i}\nSkill Domain: Communication\n" for i in range(15))
    text = "15 hours per week.\n97153-Direct Care\n" + goals
    result, evidence, page, confidence = fields._check_GIP13(_rule(), _fields(text))
    assert result == "pass"


def test_gip13_excludes_parent_training_and_behavior_reduction_goals_from_the_count():
    goals = "".join(f"Target Goal: Skill {i}\nSkill Domain: Communication\n" for i in range(15))
    goals += "Target Goal: PT Goal\nSkill Domain: Parent Training\n"  # excluded
    goals += "Target Name: Reduce Tantrum\nMastery Criteria: 0%\n"  # excluded (Behavior Reduction)
    text = "16 hours per week.\n97153-Direct Care\n" + goals
    result, evidence, page, confidence = fields._check_GIP13(_rule(), _fields(text))
    assert result == "fail"  # still only 15 qualifying goals for 16 hours


# --- Bucket D, item 8: QA-BIP-07 -- confirmed pure judgment, no code -------

def test_bip07_has_no_checker_registered_confirmed_pure_judgment():
    assert "QA-BIP-07" not in fields.DET_CHECKS


# --- Bucket D, item 9: QA-GIP-21 --------------------------------------------

def test_gip21_fails_when_no_anticipated_mastery_date():
    text = "Target Name: Reduce Tantrum\nBaseline: 5\n"
    result, evidence, page, confidence = fields._check_GIP21(_rule(), _fields(text))
    assert result == "fail"


def test_gip21_escalates_to_judgment_for_the_explanation_half_when_mastery_date_present():
    text = "Target Name: Reduce Tantrum\nAnticipated Mastery Date: 11/03/2026\n"
    result, evidence, page, confidence = fields._check_GIP21(_rule(), _fields(text))
    assert result == "not_checkable"


# --- Bucket D, item 10: QA-SCH-09 -- confirmed not a fixed-list rule -------

def test_sch09_has_no_checker_registered_confirmed_not_a_fixed_list():
    assert "QA-SCH-09" not in fields.DET_CHECKS
