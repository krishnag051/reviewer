"""Fix Round 19 (2026-10-08): real bugs found and fixed against the real
Raizy Gottesfeld document pair (current TP, previous TP) and its 5 real
session notes. Each test reproduces the exact real text confirmed via
direct pypdf extraction of the real PDFs -- zero real API cost (every rule
touched here is deterministic).
"""
from pipeline import fields as F
from pipeline import previous_tp_comparison as P
from pipeline.session_note_comparison import check_date_in_current_report_period


def _fields(*page_texts: str, start_page: int = 1) -> dict:
    pages = [{"page_number": start_page + i, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- QA-MAST-01 / QA-MAST-02: the "Name of Skill:" no-date-field template ---

def test_mast_extraction_handles_name_only_entries_with_no_date_field_at_all():
    """Real shape: this document's populated Mastered Goals section has
    zero 'Date Mastered:'/'Date of Mastery:' fields at all -- just bare
    'Name of Skill: <sentence>' lines, one per goal, some wrapping onto a
    second physical line. Both prior templates require a date field to
    match anything, so this document used to extract ZERO entries from a
    section that genuinely lists 30+ real mastered goals."""
    text = (
        "Mastered Goals:\n"
        "Name of Skill: Raizy will go to the other room when she is told to do so\n"
        "Name of Skill: Raizy will increase her listener responding skills and respond to a one-step directive given with only two\n"
        "prompts.\n"
        "Goals in Progress:\n"
    )
    entries = F._extract_mastered_goals_with_dates(text)
    assert len(entries) == 2
    assert entries[0]["name"] == "Raizy will go to the other room when she is told to do so"
    assert entries[0]["date_mastered"] is None
    # Line-wrapped entry: joined into one clean sentence, no embedded newline.
    assert entries[1]["name"] == (
        "Raizy will increase her listener responding skills and respond to a one-step directive given with only two prompts."
    )


def test_mast02_real_duplicate_detection_now_works_on_the_name_only_template():
    """Reproduces the real confirmed shape: the current TP's mastered
    goals (name-only template) genuinely duplicate several of the
    previous TP's own mastered goals (dated template) -- MAST-02 must
    catch this as a real fail, not silently conclude 'current TP has no
    named mastered goals at all' (the real, confirmed-wrong prior
    behavior)."""
    current_text = (
        "Mastered Goals:\n"
        "Name of Skill: Raizy will go to the other room when she is told to do so\n"
        "Name of Skill: A brand new goal never mastered before\n"
        "Goals in Progress:\n"
    )
    previous_text = (
        "Mastered Goals:\n"
        "Name of Skill: Raizy will go to the other room when she is told to do so\n"
        "Date Mastered: 02/12/2026, Last Three Days Average in Maintenance: 0\n"
        "Goals in Progress:\n"
    )
    current_fields = _fields(current_text)
    previous_fields = _fields(previous_text)
    current_fields["mastered_goals"] = F._extract_mastered_goals_with_dates(current_text)
    previous_fields["mastered_goals"] = F._extract_mastered_goals_with_dates(previous_text)
    result = P._compare_mast02(current_fields, previous_fields)
    assert result["result"] == "fail"
    assert "go to the other room when she is told to do so" in result["evidence"]


# --- QA-BIO-06: a named drug with a dosage, no literal "medication" word ---

def test_bio06_named_drug_with_dosage_but_no_literal_medication_word_escalates():
    text = "She takes Depakote (250 mg/2x day) as prescribed by her neurologist, Dr. Pearl MD."
    result, evidence, page, confidence = F._check_BIO06({"params": {}}, _fields(text))
    assert result == "not_checkable"
    assert "escalating" in evidence


def test_bio06_genuine_no_medication_denial_still_not_applicable():
    text = "She is not taking any medications."
    result, evidence, page, confidence = F._check_BIO06({"params": {}}, _fields(text))
    assert result == "not_applicable"


# --- QA-BIP-08: "Behavior:" value on the next line + doubled-letter typo ---

def test_bip08_behavior_label_value_on_next_line_and_spelling_variant():
    text = (
        "Current Problem Areas:\n"
        "As evidenced by:\n"
        "Raizy engages in tantrum behavior and aggression.\n"
        "Behavior Intervention Plan:\n"
        "Behavior: \nNon-compliance\nBaseline: 14x per session\n"
        "Behavior: \nAggression\nBaseline: 12x per session\n"
        "Target Name: Noncompliance\nDate Initiated: 03/08/2026\n"
        "Target Name: Agression\nDate Initiated: 02/10/2025\n"
    )
    result, evidence, page, confidence = F._check_BIP08({"params": {}}, _fields(text))
    assert result == "fail"
    assert "tantrum" in evidence
    assert "aggression" not in evidence.lower() or "missing" not in evidence.lower().split("aggression")[0][-20:]


def test_fold_doubled_letters_tolerates_the_real_confirmed_typo():
    assert F._fold_doubled_letters("Aggression") == F._fold_doubled_letters("Agression")
    assert F._fold_doubled_letters("tantrum") != F._fold_doubled_letters("aggression")


# --- QA-BIP-06: multi-page citation when 2+ Behavior Reduction goals pass ---

def test_bip06_cites_every_passing_goals_own_page():
    text = (
        "Target Name: Noncompliance\nCurrent Data: 2 Frequency\n"
    )
    page2_text = "Target Name: Aggression\nCurrent Data: 1.67 Frequency\n"
    fields = _fields(text, page2_text)
    result, evidence, page, confidence = F._check_BIP06({"params": {}}, fields)
    assert result == "pass"
    assert page == [1, 2]


# --- QA-GIP-07: inline rationale on the "Date Initiated:" line itself ---

def test_gip07_reads_real_inline_rationale_and_excludes_a_line_wrapped_next_field():
    text = (
        "Date of Current Report: 09/07/2026 to 09/14/2026\n"
        "Target Goal: Has a real rationale\n"
        "Date Initiated: 01/01/2025 -Modify the prompting and reinforcement\n"
        "Target Name: Agression\n"
        "Date Initiated: 02/10/2025\nBaseline: 12 per session Frequency\n"
        "Target Goal: Genuinely has no rationale anywhere nearby\n"
        "Date Initiated: 02/09/2025\nBaseline: 5%\n"
    )
    result, evidence, page, confidence = F._check_GIP07({"params": {}}, _fields(text))
    assert result == "not_checkable"
    # 1 of the 3 old goals (the one with a real inline rationale) is
    # credited; the line-wrapped "Baseline: 12 per session Frequency"
    # must NOT be mistaken for a rationale on the "Agression" goal.
    assert "1 of these have a real rationale documented inline" in evidence
    assert "2 do not" in evidence


# --- QA-GIP-13: Community Goals restatement must not be double-counted ---

def test_gip13_excludes_community_goals_restatement_and_parent_training():
    text = (
        "30.75 hours per\nweek.\n97153-Direct Care\n"
        "Target Goal: Goal A\nSkill Domain: Communication\n"
        "Target Goal: Goal B\nSkill Domain: Communication\n"
        "Community Goals:\n"
        "Target Goal: Goal A\n"
        "Target Goal: Goal B\n"
        "Parent/Caregiver Involvement:\n"
        "Target Goal: Parent goal, must not count\n"
    )
    result, evidence, page, confidence = F._check_GIP13({"params": {}}, _fields(text))
    assert "2 qualifying goal(s)" in evidence


def test_find_weekly_hours_tolerates_inline_aside_but_not_a_different_codes_row():
    text = "30.75  hours per\nweek.\n15.5  hours will be\ndone in the\ncommunity\n97153-Direct Care"
    assert F._find_weekly_hours_for_code(text, "97153") == 30.75

    # Real regression guard: must not skip past a DIFFERENT code's own
    # complete row to reach the target code.
    text2 = "25  hours per week.\n97153-Direct Care\n2.5  hours per week.\n97155-Supervision"
    assert F._find_weekly_hours_for_code(text2, "97155") == 2.5


# --- QA-ACF-06: "Assessor: NAME" labeled field, not "administered by" prose ---

def test_acf06_recognizes_the_assessor_label_shape():
    text = "Assessment of Current Functioning:\nAssessor: Miriam Fogel\n"
    result, evidence, page, confidence = F._check_ACF06({"params": {}}, _fields(text))
    assert result == "pass"
    assert "Miriam Fogel" in evidence


# --- QA-COC-08: "lapse in services" (plural) ---

def test_coc08_catches_the_plural_services_phrasing():
    text = "Raizy had a lapse in services during the authorization period, from 7/1-7/27."
    result, evidence, page, confidence = F._check_COC08({"params": {}}, _fields(text))
    assert result == "fail"


# --- QA-RPT-03: date format consistency ---

def test_rpt03_evidence_uses_mm_dd_yyyy_throughout_not_isoformat():
    result = check_date_in_current_report_period("07/29/2026", "07/22/2026 to 07/29/2026")
    assert result["result"] == "pass"
    assert "2026-07-22" not in result["evidence"] and "2026-07-29" not in result["evidence"]
    assert "07/22/2026" in result["evidence"] and "07/29/2026" in result["evidence"]
