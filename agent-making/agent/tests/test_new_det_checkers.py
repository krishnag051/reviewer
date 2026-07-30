"""Synthetic-only unit tests for the Tier 1 checkers built this round
(HF-01, RPT-02, RPT-06, SIG-02/03/04, HRS-02/03, COC-04, BIO-02, BIO-13)
plus the two new Straight Medicaid-specific checkers (SM-01/SM-02). Same
style as the existing HF-02 tests in test_fields_checkers.py — plain dicts,
no PDF I/O, no live API.
"""
from pipeline import fields


def _fields(full_text: str):
    return {"pages": [{"page_number": 1, "text": full_text}], "full_text": full_text}


def _rule(rule_id, params=None):
    return {"rule_id": rule_id, "check_type": "deterministic", "params": params or {}}


# --- HF-01: age/date-range math ---

HF01_PARAMS = {"age_threshold": 13, "short_range_months": 3, "long_range_months": 6}


def test_hf01_pass_over_threshold_with_3_month_range():
    text = "Patient Age:  17 Patient Gender: Female\nAuthorization Dates Requested: 07/30/2026  to 10/30/2026"
    result, evidence, page, confidence = fields._check_HF01(_rule("HF-01", HF01_PARAMS), _fields(text))
    assert result == "pass"


def test_hf01_fail_over_threshold_with_6_month_range():
    """This is the exact real-world CD contradiction case: age 17 (>13)
    but a 6-month range instead of the required 3-month range."""
    text = "Patient Age:  17 Patient Gender: Female\nAuthorization Dates Requested: 07/30/2026  to 01/30/2027"
    result, evidence, page, confidence = fields._check_HF01(_rule("HF-01", HF01_PARAMS), _fields(text))
    assert result == "fail"


def test_hf01_pass_under_threshold_with_6_month_range():
    text = "Patient Age:  10 Patient Gender: Male\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, evidence, page, confidence = fields._check_HF01(_rule("HF-01", HF01_PARAMS), _fields(text))
    assert result == "pass"


def test_hf01_fail_under_threshold_with_3_month_range():
    text = "Patient Age:  10 Patient Gender: Male\nAuthorization Dates Requested: 02/21/2026  to 05/21/2026"
    result, evidence, page, confidence = fields._check_HF01(_rule("HF-01", HF01_PARAMS), _fields(text))
    assert result == "fail"


def test_hf01_not_checkable_when_fields_missing():
    result, evidence, page, confidence = fields._check_HF01(_rule("HF-01", HF01_PARAMS), _fields("nothing useful here"))
    assert result == "not_checkable"
    assert confidence == 0.0


# --- RPT-02: Date of Initial Assessment presence (Reassessment only) ---

def test_rpt02_pass_when_present():
    result, *_ = fields._check_RPT02(_rule("QA-RPT-02"), _fields("Date of Initial Assessment: 10/29/2025"))
    assert result == "pass"


def test_rpt02_fail_when_absent():
    result, *_ = fields._check_RPT02(_rule("QA-RPT-02"), _fields("No such field here."))
    assert result == "fail"


# --- RPT-06: report end before auth start ---

def test_rpt06_pass_when_report_ends_before_auth_starts():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, *_ = fields._check_RPT06(_rule("QA-RPT-06"), _fields(text))
    assert result == "pass"


def test_rpt06_fail_when_report_end_after_auth_start():
    text = "Date of Current Report: 01/14/2026  to 03/01/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, *_ = fields._check_RPT06(_rule("QA-RPT-06"), _fields(text))
    assert result == "fail"


def test_rpt06_not_checkable_when_missing():
    result, evidence, page, confidence = fields._check_RPT06(_rule("QA-RPT-06"), _fields("nothing"))
    assert result == "not_checkable"
    assert confidence == 0.0


# --- SIG-02: signature credentials match page-1 provider contact ---

def test_sig02_pass_when_credentials_match():
    text = "Provider Contact:  Karen Kain   Certification: BCBA, LBA\nProvider Credentials: BCBA, LBA"
    result, *_ = fields._check_SIG02(_rule("QA-SIG-02"), _fields(text))
    assert result == "pass"


def test_sig02_fail_when_credentials_differ():
    text = "Provider Contact:  Karen Kain   Certification: BCBA, LBA\nProvider Credentials: LBA"
    result, *_ = fields._check_SIG02(_rule("QA-SIG-02"), _fields(text))
    assert result == "fail"


# --- SIG-03: signature date before auth start ---

def test_sig03_pass_when_signature_before_auth_start():
    text = "Provider Signature, Date: 07/27/2026\nAuthorization Dates Requested: 08/23/2026  to 01/24/2027"
    result, *_ = fields._check_SIG03(_rule("QA-SIG-03"), _fields(text))
    assert result == "pass"


def test_sig03_fail_when_signature_after_auth_start():
    text = "Provider Signature, Date: 09/01/2026\nAuthorization Dates Requested: 08/23/2026  to 01/24/2027"
    result, *_ = fields._check_SIG03(_rule("QA-SIG-03"), _fields(text))
    assert result == "fail"


# --- SIG-04: signature date not >2 days after report end ---

def test_sig04_pass_within_two_days():
    text = "Provider Signature, Date: 07/22/2026\nDate of Current Report: 07/19/2026  to 07/20/2026"
    result, *_ = fields._check_SIG04(_rule("QA-SIG-04"), _fields(text))
    assert result == "pass"


def test_sig04_fail_beyond_two_days():
    text = "Provider Signature, Date: 07/25/2026\nDate of Current Report: 07/19/2026  to 07/20/2026"
    result, *_ = fields._check_SIG04(_rule("QA-SIG-04"), _fields(text))
    assert result == "fail"


# --- HRS-02: 97153 hours > 20/week -> flag ---

HRS02_PARAMS = {"cpt_code": "97153", "hours_threshold": 20}


def test_hrs02_pass_under_threshold():
    text = "18  hours per week.\n97153-Direct Care Behavior Technician"
    result, *_ = fields._check_HRS02(_rule("QA-HRS-02", HRS02_PARAMS), _fields(text))
    assert result == "pass"


def test_hrs02_fail_over_threshold():
    text = "25  hours per week.\n97153-Direct Care Behavior Technician"
    result, *_ = fields._check_HRS02(_rule("QA-HRS-02", HRS02_PARAMS), _fields(text))
    assert result == "fail"


def test_hrs02_not_applicable_when_code_absent():
    result, *_ = fields._check_HRS02(_rule("QA-HRS-02", HRS02_PARAMS), _fields("no relevant codes here"))
    assert result == "not_applicable"


# --- HRS-03: supervision/direct-care ratio -- a CEILING, not a floor ---
# (fixed 2026-07-28: a prior round had this backwards; see the checker's
# own docstring in fields.py for the full explanation and the Reeda TP /
# Eliana-manual-review evidence that surfaced the bug.)

HRS03_PARAMS = {"direct_cpt_code": "97153", "supervision_cpt_code": "97155", "supervision_ratio_per_direct_hour": 0.15}


def test_hrs03_pass_using_reedas_real_numbers():
    """Reeda's actual TP: 25 hrs/week direct care, 2.5 hrs/week supervision
    -> ratio 0.10/hr, under the 0.15/hr ceiling. Eliana's manual review
    marked this Pass; the old (floor-direction) checker incorrectly
    returned Fail for this exact case."""
    text = "25  hours per week.\n97153-Direct Care Behavior Technician\n2.5  hours per week.\n97155-Supervision/Behavior Treatment"
    result, evidence, page, confidence = fields._check_HRS03(_rule("QA-HRS-03", HRS03_PARAMS), _fields(text))
    assert result == "pass", evidence


def test_hrs03_uncertain_when_ceiling_exceeded():
    """10 direct hrs -> ceiling 1.5 hrs of supervision. 5 hrs of
    supervision is well over that ceiling -- this needs documented
    director approval, which the checker can't verify from a text pattern
    alone, so it escalates to judgment rather than auto-failing."""
    text = "10  hours per week.\n97153-Direct Care Behavior Technician\n5  hours per week.\n97155-Supervision/Behavior Treatment"
    result, evidence, page, confidence = fields._check_HRS03(_rule("QA-HRS-03", HRS03_PARAMS), _fields(text))
    assert result == "uncertain"
    assert "director approval" in evidence.lower()


def test_hrs03_pass_at_exactly_the_ceiling():
    text = "20  hours per week.\n97153-Direct Care Behavior Technician\n3  hours per week.\n97155-Supervision/Behavior Treatment"
    result, *_ = fields._check_HRS03(_rule("QA-HRS-03", HRS03_PARAMS), _fields(text))
    assert result == "pass"


# --- COC-04: TP faxed within 6 months of report end ---

COC04_PARAMS = {"months_allowed": 6}


def test_coc04_pass_within_six_months():
    text = "Treatment plan has been faxed to Dr. Smith on 02/01/2026.\nDate of Current Report: 07/19/2026  to 07/22/2026"
    result, *_ = fields._check_COC04(_rule("QA-COC-04", COC04_PARAMS), _fields(text))
    assert result == "pass"


def test_coc04_fail_beyond_six_months():
    text = "Treatment plan has been faxed to Dr. Smith on 01/01/2025.\nDate of Current Report: 07/19/2026  to 07/22/2026"
    result, *_ = fields._check_COC04(_rule("QA-COC-04", COC04_PARAMS), _fields(text))
    assert result == "fail"


# --- BIO-02 / BIO-13: presence checks ---

def test_bio02_pass_when_present():
    result, *_ = fields._check_BIO02(_rule("QA-BIO-02"), _fields("Date of Most Recent Diagnosis: 11/20/2024"))
    assert result == "pass"


def test_bio02_fail_when_absent():
    result, *_ = fields._check_BIO02(_rule("QA-BIO-02"), _fields("no such field"))
    assert result == "fail"


def test_bio13_pass_when_present():
    result, *_ = fields._check_BIO13(_rule("QA-BIO-13"), _fields("First day of ABA services with Master Faster: 12/05/2024"))
    assert result == "pass"


def test_bio13_fail_when_absent():
    result, *_ = fields._check_BIO13(_rule("QA-BIO-13"), _fields("no such field"))
    assert result == "fail"


# --- SM-01: Straight Medicaid auth-date math ---

SM01_PARAMS = {"max_months_after_report_end": 6}


def test_sm01_pass_correct_start_and_within_six_months():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 02/19/2026  to 08/18/2026"
    result, *_ = fields._check_SM01(_rule("SM-01", SM01_PARAMS), _fields(text))
    assert result == "pass"


def test_sm01_fail_wrong_start_date():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, evidence, page, confidence = fields._check_SM01(_rule("SM-01", SM01_PARAMS), _fields(text))
    assert result == "fail"
    assert "day after" in evidence


def test_sm01_fail_end_beyond_six_months():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 02/19/2026  to 12/18/2026"
    result, evidence, page, confidence = fields._check_SM01(_rule("SM-01", SM01_PARAMS), _fields(text))
    assert result == "fail"
    assert "months after" in evidence


def test_sm01_not_checkable_when_dates_missing():
    result, evidence, page, confidence = fields._check_SM01(_rule("SM-01", SM01_PARAMS), _fields("nothing"))
    assert result == "not_checkable"
    assert confidence == 0.0


# --- SM-02: hours per week, not per day ---

def test_sm02_pass_all_per_week():
    text = "21  hours per week.\n97153-Direct Care"
    result, *_ = fields._check_SM02(_rule("SM-02"), _fields(text))
    assert result == "pass"


def test_sm02_fail_when_per_day_found():
    text = "3  hours per day.\n97153-Direct Care"
    result, *_ = fields._check_SM02(_rule("SM-02"), _fields(text))
    assert result == "fail"


# --- EMP-01: report end within N days of auth start ---

EMP01_PARAMS = {"max_days": 30}


def test_emp01_pass_within_window():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, *_ = fields._check_EMP01(_rule("EMP-01", EMP01_PARAMS), _fields(text))
    assert result == "pass"


def test_emp01_fail_beyond_window():
    text = "Date of Current Report: 01/14/2026  to 02/18/2026\nAuthorization Dates Requested: 04/01/2026  to 10/01/2026"
    result, *_ = fields._check_EMP01(_rule("EMP-01", EMP01_PARAMS), _fields(text))
    assert result == "fail"


def test_emp01_not_checkable_when_fields_missing():
    result, evidence, page, confidence = fields._check_EMP01(_rule("EMP-01", EMP01_PARAMS), _fields("nothing"))
    assert result == "not_checkable"
    assert confidence == 0.0


# --- EMP-03: signature date within N days of auth start ---

EMP03_PARAMS = {"max_days": 30}


def test_emp03_pass_within_window():
    text = "Provider Signature, Date: 02/10/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, *_ = fields._check_EMP03(_rule("EMP-03", EMP03_PARAMS), _fields(text))
    assert result == "pass"


def test_emp03_fail_beyond_window():
    text = "Provider Signature, Date: 01/01/2026\nAuthorization Dates Requested: 02/21/2026  to 08/21/2026"
    result, *_ = fields._check_EMP03(_rule("EMP-03", EMP03_PARAMS), _fields(text))
    assert result == "fail"


# --- EMB-01: reuses fields._check_HF02 with its own params (max_hours=3) ---

EMB01_PARAMS = {"max_hours": 3, "cpt_code": "97151"}


def test_emb01_pass_at_or_under_cap():
    text = "97151 3 hrs"
    result, *_ = fields._check_HF02(_rule("EMB-01", EMB01_PARAMS), _fields(text))
    assert result == "pass"


def test_emb01_fail_over_cap():
    text = "97151 6 hrs"
    result, *_ = fields._check_HF02(_rule("EMB-01", EMB01_PARAMS), _fields(text))
    assert result == "fail"


# --- AET-01: testing tool restriction ---

AET01_PARAMS = {"allowed_tools": ["Vineland", "VB-MAPP", "ABLLS"], "disallowed_tools": ["AFLS"]}


def test_aet01_pass_when_allowed_tool_used():
    result, *_ = fields._check_AET01(_rule("AET-01", AET01_PARAMS), _fields("Assessment tool: Vineland-3"))
    assert result == "pass"


def test_aet01_fail_when_afls_used():
    result, evidence, page, confidence = fields._check_AET01(_rule("AET-01", AET01_PARAMS), _fields("Assessment tool: AFLS"))
    assert result == "fail"
    assert "AFLS" in evidence


def test_aet01_fail_when_afls_used_alongside_an_allowed_tool():
    """AFLS is banned outright for this payor — its presence is a fail even
    if an allowed tool is also mentioned, not just when AFLS is the only
    tool present."""
    result, *_ = fields._check_AET01(_rule("AET-01", AET01_PARAMS), _fields("Tools used: Vineland-3 and AFLS"))
    assert result == "fail"


def test_aet01_not_checkable_when_no_recognized_tool_mentioned():
    result, *_ = fields._check_AET01(_rule("AET-01", AET01_PARAMS), _fields("no testing tool mentioned at all"))
    assert result == "not_checkable"


# --- BIO-03: Secondary Diagnosis presence (relabeled from judgment this round) ---

def test_bio03_pass_when_secondary_diagnosis_documented():
    result, evidence, page, confidence = fields._check_BIO03(_rule("QA-BIO-03"), _fields("Diagnosis: F84.0\nSecondary Diagnosis: ADHD\nDiagnosed By: Dr. Smith"))
    assert result == "pass"
    assert "ADHD" in evidence


def test_bio03_uncertain_when_field_present_but_blank():
    result, evidence, page, confidence = fields._check_BIO03(_rule("QA-BIO-03"), _fields("Diagnosis: F84.0\nSecondary Diagnosis: \nDiagnosed By: Dr. Smith"))
    assert result == "uncertain"
    assert confidence == 0.3


def test_bio03_not_checkable_when_field_absent_entirely():
    result, evidence, page, confidence = fields._check_BIO03(_rule("QA-BIO-03"), _fields("Diagnosis: F84.0\nDiagnosed By: Dr. Smith"))
    assert result == "not_checkable"
    assert confidence == 0.0


# --- ACF-05: Assessment Summary Statement presence (restored from archive) ---

def test_acf05_fail_on_charny_glucks_real_blank_case():
    """Real text pattern confirmed on Charny Gluck's TP, page 8: the label
    is immediately followed by the NEXT field's label, nothing filled in."""
    text = (
        "Assessment Methods/Measures:\n"
        "Assessment Summary Statement:\n"
        "Areas of Focus for Treatment:\n"
        "☑ Challenging Behavior ☑ Language and Communication"
    )
    result, evidence, page, confidence = fields._check_ACF05(_rule("QA-ACF-05"), _fields(text))
    assert result == "fail"
    assert "blank" in evidence.lower()


def test_acf05_pass_when_field_has_real_content():
    text = (
        "Assessment Summary Statement:\n"
        "Reeda demonstrates significant delays across communication, social, and adaptive domains.\n"
        "Areas of Focus for Treatment:\n"
    )
    result, evidence, page, confidence = fields._check_ACF05(_rule("QA-ACF-05"), _fields(text))
    assert result == "pass"
    assert "Reeda demonstrates" in evidence


def test_acf05_not_checkable_when_field_absent_entirely():
    result, evidence, page, confidence = fields._check_ACF05(_rule("QA-ACF-05"), _fields("no such field here"))
    assert result == "not_checkable"
    assert confidence == 0.0
