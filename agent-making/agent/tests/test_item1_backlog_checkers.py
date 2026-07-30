"""Coverage for the item-1 backlog conversions (2026-07-28 round 3):
QA-GIP-16, QA-TEMP-01, QA-PPI-02, QA-PPI-03, QA-PPI-05, QA-BIP-01/QA-GIP-03
(shared checker). Same style as test_check_gip10.py -- minimal stub fields
dicts, no live document, no live API. Live ground truth against Reeda's and
Charny's real documents lives in test_regression_ground_truth.py.
"""
from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- QA-GIP-16: zero/near-zero mastery criteria ban ---

def test_gip16_pass_when_no_zero_endpoints():
    goal = "Target Goal: X\nBaseline: 10%\nMastery Criteria: 85% over three consecutive weeks\nSampling Method: Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(goal))
    assert result == "pass"


def test_gip16_fail_on_target_name_block_not_just_target_goal():
    """The confirmed real-world case: both violations on Reeda's TP live in
    'Target Name:' Behavior Reduction Goal blocks, not 'Target Goal:' ones."""
    behavior_goal = "Target Name: X will reduce tantrums\nBaseline: 7x daily\nMastery Criteria: Near 0 levels per session for 5 consecutive sessions\nSampling Method: Frequency\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(behavior_goal))
    assert result == "fail"
    assert "Near 0 levels" in evidence


def test_gip16_fail_on_zero_occurrences_frequency_form():
    goal = "Target Name: X will reduce elopement\nBaseline: 12x daily\nMastery Criteria: 0 occurrences per session for 5 consecutive sessions\nSampling Method: Frequency\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(goal))
    assert result == "fail"


def test_gip16_does_not_flag_a_minimum_occurrence_range():
    """Confirmed on Charny's real TP: '0-2 occurrences over three
    consecutive days' is a genuine minimum-occurrence RANGE, not a zero
    endpoint -- must not be flagged."""
    goal = "Target Goal: X\nBaseline: 9 Frequency\nMastery Criteria: 0-2 occurrences over three consecutive days\nSampling Method: Frequency\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(goal))
    assert result == "pass"


def test_gip16_not_checkable_with_no_goal_blocks():
    result, evidence, page, confidence = fields._check_GIP16({}, _fields("unrelated text"))
    assert result == "not_checkable"


# --- QA-TEMP-01: credential consistency ---

def test_temp01_pass_when_credentials_consistent():
    text = "Certification: BCBA, LBA\nProvider Credentials: BCBA, LBA\n"
    result, evidence, page, confidence = fields._check_TEMP01({}, _fields(text))
    assert result == "pass"


def test_temp01_fail_on_inconsistent_credentials():
    text = "Certification: BCBA, LBA\nProvider Credentials: Limited Permit\n"
    result, evidence, page, confidence = fields._check_TEMP01({}, _fields(text))
    assert result == "fail"


def test_temp01_not_checkable_with_no_credential_field():
    result, evidence, page, confidence = fields._check_TEMP01({}, _fields("unrelated text"))
    assert result == "not_checkable"


def test_temp01_limited_permit_used_consistently_passes_but_does_not_verify_template():
    """2026-07-28 follow-up round: confirms a real, previously-flagged scope
    gap rather than a logic bug. A document that consistently labels its
    provider 'Limited Permit' everywhere correctly passes the CONSISTENCY
    half of this rule (nothing contradicts) -- but the rule's own
    description has a second half ('correct template used') that is NOT
    implemented here and has no known real-document example to build a
    detector from. This means a document with a Limited Permit provider
    using the WRONG template would still incorrectly pass today. Locked in
    as a documented gap, not silently fixed with a guessed-at pattern."""
    text = "Certification: Limited Permit\nProvider Credentials: Limited Permit\n"
    result, evidence, page, confidence = fields._check_TEMP01({}, _fields(text))
    assert result == "pass"


def test_temp01_limited_permit_at_intake_but_full_credentials_at_signature_fails():
    """The consistency-check mechanism DOES correctly fire on a real
    Limited-Permit-flavored contradiction (credential escalates from
    'Limited Permit' to 'BCBA, LBA' partway through the document)."""
    text = "Certification: Limited Permit\nProvider Credentials: BCBA, LBA\n"
    result, evidence, page, confidence = fields._check_TEMP01({}, _fields(text))
    assert result == "fail"
    assert "Limited Permit" in evidence and "BCBA, LBA" in evidence


# --- QA-PPI-02: age/DOB consistency ---

def test_ppi02_pass_when_dob_and_age_consistent():
    text = "Patient DOB: 04/22/2020\nPatient Age: 6\nDate of Current Report: 07/19/2026 to 07/22/2026\n"
    result, evidence, page, confidence = fields._check_PPI02({}, _fields(text))
    assert result == "pass"


def test_ppi02_fail_on_inconsistent_dob():
    text = "Patient DOB: 04/22/2020\nPatient DOB: 04/23/2020\n"
    result, evidence, page, confidence = fields._check_PPI02({}, _fields(text))
    assert result == "fail"


def test_ppi02_fail_on_age_not_matching_dob():
    text = "Patient DOB: 04/22/2020\nPatient Age: 45\nDate of Current Report: 07/19/2026 to 07/22/2026\n"
    result, evidence, page, confidence = fields._check_PPI02({}, _fields(text))
    assert result == "fail"


def test_ppi02_not_checkable_with_no_fields():
    result, evidence, page, confidence = fields._check_PPI02({}, _fields("unrelated text"))
    assert result == "not_checkable"


# --- QA-PPI-03: patient name consistency ---

def test_ppi03_pass_when_name_consistent_across_forms():
    text = (
        "Patient Name: Reeda Bint Shaheen  AKA: N/A Patient DOB: 04/22/2020\n"
        "Patient Name: Reeda Bint Shaheen Patient DOB: 04/22/2020 Patient Insurance: X\n"
    )
    result, evidence, page, confidence = fields._check_PPI03({}, _fields(text))
    assert result == "pass"


def test_ppi03_fail_on_misspelled_name():
    text = (
        "Patient Name: Reeda Bint Shaheen Patient DOB: 04/22/2020 Patient Insurance: X\n"
        "Patient Name: Reeda Bin Shaheen Patient DOB: 04/22/2020 Patient Insurance: X\n"
    )
    result, evidence, page, confidence = fields._check_PPI03({}, _fields(text))
    assert result == "fail"


# --- QA-PPI-05: NPI/License consistency ---

def test_ppi05_pass_with_single_consistent_npi_and_license():
    text = "NPI: 1578293197\nLicense #: 12477453/004132\n"
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(text))
    assert result == "pass"


def test_ppi05_fail_on_inconsistent_npi():
    text = "NPI: 1578293197\nNPI: 9999999999\n"
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(text))
    assert result == "fail"


def test_ppi05_fail_on_inconsistent_license():
    """2026-07-28 follow-up round: neither real document had more than one
    License mention, so this specific fail path was unverified. Confirmed
    firing correctly on a synthetic multi-mention conflict."""
    text = "License #: 12477453/004132\nLicense #: 99999999/999999\n"
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(text))
    assert result == "fail"
    assert "12477453/004132" in evidence and "99999999/999999" in evidence


def test_ppi05_same_npi_repeated_with_whitespace_differences_still_passes():
    """No false positive from incidental whitespace formatting -- the same
    NPI value appearing twice with different surrounding spaces must still
    read as one consistent value, not two conflicting ones."""
    text = "NPI:  1578293197 \nNPI: 1578293197\n"
    result, evidence, page, confidence = fields._check_PPI05({}, _fields(text))
    assert result == "pass"


def test_ppi05_not_checkable_with_no_fields():
    result, evidence, page, confidence = fields._check_PPI05({}, _fields("unrelated text"))
    assert result == "not_checkable"


# --- QA-BIP-01 / QA-GIP-03: severity rating not all mild (shared checker) ---

def test_severity_pass_when_one_rating_is_moderate():
    text = "Severity of Maladaptive Behavior: Moderate\nSeverity of Aggression: Mild\n"
    result, evidence, page, confidence = fields._check_severity_rating_not_all_mild({}, _fields(text))
    assert result == "pass"


def test_severity_fail_when_all_mild():
    text = "Severity of Maladaptive Behavior: Mild\nSeverity of Aggression: Mild\n"
    result, evidence, page, confidence = fields._check_severity_rating_not_all_mild({}, _fields(text))
    assert result == "fail"


def test_severity_fail_mixed_case_mild_still_caught():
    """Neither real document had genuinely all-Mild ratings, so this fail
    path was unverified. Also confirms case-insensitivity isn't accidentally
    only applied to the Moderate/Severe side."""
    text = "Severity of Maladaptive Behavior: mild\nSeverity of Aggression: MILD\n"
    result, evidence, page, confidence = fields._check_severity_rating_not_all_mild({}, _fields(text))
    assert result == "fail"


def test_severity_fail_when_mild_plus_na_with_no_real_moderate_or_higher():
    """Confirmed real document shape (Charny has one N/A severity rating
    among several real ones) -- an N/A entry must not be misread as
    'clearing the bar,' and must not by itself flip an otherwise-all-Mild
    set to a pass."""
    text = (
        "Severity of Maladaptive Behavior: Mild\n"
        "Severity of Aggression, Self Injury, Property Destruction and/or Elopement: N/A\n"
        "Severity of Communicative/Social Deficits: Mild\n"
    )
    result, evidence, page, confidence = fields._check_severity_rating_not_all_mild({}, _fields(text))
    assert result == "fail"


def test_severity_not_checkable_with_no_ratings():
    result, evidence, page, confidence = fields._check_severity_rating_not_all_mild({}, _fields("unrelated text"))
    assert result == "not_checkable"


def test_bip01_and_gip03_share_the_same_checker_function():
    assert fields.DET_CHECKS["QA-BIP-01"] is fields.DET_CHECKS["QA-GIP-03"]
    assert fields.DET_CHECKS["QA-BIP-01"] is fields._check_severity_rating_not_all_mild


# --- QA-HRS-06: hours-increase-needs-rationale (presence half only) ---

def test_hrs06_pass_when_increase_has_rationale():
    text = (
        "Hours Requesting:\n"
        "8  hours per\nauthorization\nPeriod.\n97151-Assessment\nBCBA/LBA\nTelehealth,\nHome, Office,\nand/or\nCommunity.\n"
        "Some real detailed clinical rationale narrative here explaining the increase in depth.\n"
        "Hours Approved Previous Authorization:\n97151-Assessment 5 hours per auth\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "pass"


def test_hrs06_not_applicable_when_nothing_increased():
    text = (
        "Hours Requesting:\n"
        "20  hours per\nweek.\n97153-Direct Care Behavior\nTechnician\nSome rationale text here.\n"
        "Hours Approved Previous Authorization:\n97153-Direct Care by Behavior Technician 20 hours per week\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "not_applicable"


def test_hrs06_fail_when_increase_has_no_rationale():
    text = (
        "Hours Requesting:\n"
        "8  hours per\nweek.\n97153-Direct Care Behavior\nTechnician\n"
        "Hours Approved Previous Authorization:\n97153-Direct Care by Behavior Technician 5 hours per week\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "fail"


def test_hrs06_not_checkable_with_no_sections():
    result, evidence, page, confidence = fields._check_HRS06({}, _fields("unrelated text"))
    assert result == "not_checkable"


# --- QA-HRS-06 sub-check (b): unresolved reviewer annotation questioning hours ---
# (2026-07-28 follow-up round -- the real mechanism behind Charny's and
# Reeda's originally-flagged misses; see _hrs06_unresolved_reviewer_
# annotation's own docstring for the full real-evidence diagnosis)

def test_hrs06_fail_on_embedded_question_even_with_no_hours_increase():
    """Confirmed Charny shape: a full reviewer question sitting in the
    RATIONALE slot itself, with no CPT code actually increased."""
    text = (
        "Hours Requesting:\n"
        "20  hours per\nweek.\n97153-Direct Care Behavior\nTechnician\nHome, Office,\n"
        "Why are hours remaining the same? This rationale needs to be really strong, given the client's age.\n"
        "Hours Approved Previous Authorization:\n97153-Direct Care by Behavior Technician 20 hours per week\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "fail"
    assert "remaining the same" in evidence


def test_hrs06_fail_on_short_margin_annotation_even_with_no_hours_increase():
    """Confirmed Reeda shape: a short interjection ('Verifying') sitting in
    the gap between an hours-value and its code label, not inside a full
    sentence."""
    text = (
        "Hours Requesting:\n"
        "25  hours per\nweek.\nVerifying\n97153-Direct Care Behavior\nTechnician\nSome rationale text here that is long enough.\n"
        "Hours Approved Previous Authorization:\n97153-Direct Care by Behavior Technician 25 hours per week\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "fail"
    assert "Verifying" in evidence


def test_hrs06_pass_when_no_increase_and_no_annotation():
    """Confirms the annotation sub-check doesn't over-fire on ordinary
    clean rationale text with no question mark or marker phrase."""
    text = (
        "Hours Requesting:\n"
        "20  hours per\nweek.\n97153-Direct Care Behavior\nTechnician\nSupervision hours are required to ensure treatment fidelity.\n"
        "Hours Approved Previous Authorization:\n97153-Direct Care by Behavior Technician 20 hours per week\nSchool and ABA Schedule:\n"
    )
    result, evidence, page, confidence = fields._check_HRS06({}, _fields(text))
    assert result == "not_applicable"


# --- QA-ACF-07: both old and new testing tool ---

def test_acf07_fail_when_section_entirely_blank():
    text = (
        "Assessment of Current Functioning: Please add all info below.\n"
        "Provider Location During Assessment:   \nPatient Location during Assessment:   \n"
        "Assessment Date:   \nAssessment Methods/Measures:\nAssessment Summary Statement:\n"
        "Areas of Focus for Treatment:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "fail"
    assert "entirely blank" in evidence


def test_acf07_fail_when_a_named_tool_has_no_administration_date():
    text = (
        "Assessment of Current Functioning:\nAssessment Date: 06/28/2026\n"
        "The ABLLS-R was administered by the BCBA.\n"
        "Is the Vineland for this auth? What was the date of administration and was this completed by you or the parent?\n"
        "Vineland Assessment is a standardized measure of adaptive behavior.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "fail"
    assert "Vineland" in evidence


def test_acf07_pass_when_two_tools_both_dated():
    text = (
        "Assessment of Current Functioning:\nAssessment Date: 06/28/2026\n"
        "The ABLLS-R was administered.\n"
        "Assessment Date: 06/29/2026\n"
        "The Vineland-3 was also administered on this date.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "pass"


def test_acf07_not_checkable_with_no_section():
    result, evidence, page, confidence = fields._check_ACF07({}, _fields("unrelated text"))
    assert result == "not_checkable"
