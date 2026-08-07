"""Round 59, Step 2: pure deterministic comparison logic. Zero model
calls anywhere in this file -- these are plain Python function tests.

Round 63, item 1: check_date_in_authorization_period was renamed to
check_date_in_current_report_period, and compare_session_note_to_tp's
tp_authorization_period parameter was renamed to tp_current_report_period
-- QA-RPT-03 must compare a session date against the TP's "Date of
Current Report" range, not its "Authorization Dates Requested" range (a
different field; see session_note_comparison.py's own docstring for the
full diagnosis). This file's existing Yisroel-authorization-period tests
are kept (renamed to match) purely as date-parsing/inclusive-boundary
mechanics tests -- they exercise the SAME generic comparison function
against a real date-range string, regardless of which TP field it
represents. Two NEW test groups below use clearly synthetic, NON-Yisroel
current-report windows specifically, to prove the fix generalizes and
isn't keyed to his dates.

Yisroel Leibowitz is the ONLY real patient fixture used this round (per
Round 59's explicit instruction) -- his real authorization period,
08/17/2026 - 02/17/2027, is used for the date-range mechanics check below,
both a correct-pass case and a deliberately-out-of-range fail case,
proving both directions against his real data. Kendra Djissodey's and
Charny Gluck's data are deliberately NOT referenced anywhere in this file.

Everything else (field-match checks, the full compare_session_note_to_tp
orchestration) is tested against clearly-labeled SYNTHETIC values -- his
real session-note file doesn't exist yet, so there is no real TP
"Assessment of Current Functioning" data or real session-note extraction
to test those specific checks against this round. These tests prove the
MECHANISM is correct and generic (works for any patient), not that it's
been verified against Yisroel's real session note -- that verification
waits for his real file.
"""
from pipeline.session_note_comparison import (
    check_date_in_current_report_period,
    check_field_match,
    compare_session_note_to_tp,
    parse_date_flexible,
    parse_date_range,
)

# Yisroel Leibowitz's REAL authorization period, verbatim from the real
# Q&A data given this round. Reused ONLY for generic date-parsing/
# inclusive-boundary mechanics below -- NOT presented as his real
# current-report date range (that document isn't available), and not
# relied on to prove the item-1 fix generalizes (see the SYNTHETIC_*
# fixtures further down for that).
YISROEL_AUTHORIZATION_PERIOD = "08/17/2026 – 02/17/2027"

# Two clearly synthetic, deliberately different current-report windows --
# neither is Yisroel's authorization period or anyone's real data -- used
# specifically to prove the item-1 fix (compare against current-report
# dates) generalizes across different documents/windows.
SYNTHETIC_CURRENT_REPORT_PERIOD_A = "01/05/2025 to 01/12/2025"
SYNTHETIC_CURRENT_REPORT_PERIOD_B = "11/20/2025 to 11/27/2025"


# ------------------------------------------------------- date parsing (pure)


def test_parse_date_flexible_standard_us_format():
    assert parse_date_flexible("08/17/2026").isoformat() == "2026-08-17"


def test_parse_date_flexible_returns_none_for_ambiguous_no_year_date():
    """"7/29" with no year is genuinely ambiguous -- must not guess a year."""
    assert parse_date_flexible("7/29") is None


def test_parse_date_flexible_returns_none_for_empty_or_missing():
    assert parse_date_flexible(None) is None
    assert parse_date_flexible("") is None
    assert parse_date_flexible("   ") is None


def test_parse_date_range_yisroels_real_authorization_string():
    start, end = parse_date_range(YISROEL_AUTHORIZATION_PERIOD)
    assert start.isoformat() == "2026-08-17"
    assert end.isoformat() == "2027-02-17"


# ------------------- QA-RPT-03 mechanics (date-range parsing, generic) -----
# These exercise check_date_in_current_report_period's parsing/boundary
# logic using Yisroel's real date-range STRING as a convenient real-data
# input -- they are not claims about his real current-report period.


def test_session_date_within_a_date_range_passes():
    result = check_date_in_current_report_period("09/15/2026", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "pass"
    assert "09/15/2026" in result["evidence"]
    assert "2026-08-17" in result["evidence"] and "2027-02-17" in result["evidence"]


def test_session_date_before_the_range_fails():
    result = check_date_in_current_report_period("01/01/2026", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "fail"
    assert "OUTSIDE" in result["evidence"]


def test_session_date_after_the_range_fails():
    result = check_date_in_current_report_period("03/01/2027", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "fail"


def test_session_date_exactly_on_range_start_is_inclusive_pass():
    result = check_date_in_current_report_period("08/17/2026", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "pass"


def test_session_date_exactly_on_range_end_is_inclusive_pass():
    result = check_date_in_current_report_period("02/17/2027", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "pass"


def test_session_date_one_day_before_range_start_fails():
    """Boundary check the other direction -- one day outside must still fail
    (proves this isn't accidentally an off-by-one-inclusive bug)."""
    result = check_date_in_current_report_period("08/16/2026", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "fail"


def test_session_date_one_day_after_range_end_fails():
    result = check_date_in_current_report_period("02/18/2027", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "fail"


def test_uncertain_when_session_date_unparseable():
    result = check_date_in_current_report_period("some Tuesday", YISROEL_AUTHORIZATION_PERIOD)
    assert result["result"] == "uncertain"


def test_uncertain_when_current_report_period_unparseable():
    result = check_date_in_current_report_period("09/15/2026", "sometime next year")
    assert result["result"] == "uncertain"


# ---- QA-RPT-03, item-1 fix: SYNTHETIC current-report windows (not Yisroel) -
# Proves the fix generalizes: a session date inside the report window but
# OUTSIDE a hypothetical authorization period (or vice versa) must be
# judged against the report window alone -- this module has no
# authorization-period concept anymore, by construction.


def test_synthetic_window_a_session_date_inside_passes():
    result = check_date_in_current_report_period("01/08/2025", SYNTHETIC_CURRENT_REPORT_PERIOD_A)
    assert result["result"] == "pass"


def test_synthetic_window_a_session_date_outside_fails():
    """This date would fall inside a typical FUTURE authorization period
    for the same fictional case, but the current-report window is what
    matters -- must fail against window A."""
    result = check_date_in_current_report_period("03/01/2025", SYNTHETIC_CURRENT_REPORT_PERIOD_A)
    assert result["result"] == "fail"


def test_synthetic_window_b_is_a_completely_different_range_and_still_works():
    """A second, unrelated synthetic window (different year segment,
    different case) -- confirms the fix isn't keyed to any one window's
    specific dates."""
    result = check_date_in_current_report_period("11/23/2025", SYNTHETIC_CURRENT_REPORT_PERIOD_B)
    assert result["result"] == "pass"
    result_fail = check_date_in_current_report_period("01/08/2025", SYNTHETIC_CURRENT_REPORT_PERIOD_B)
    assert result_fail["result"] == "fail"


# -------------------------------- field match (generic, synthetic values) --


def test_field_match_pass_when_values_agree_case_insensitively():
    result = check_field_match("Home", "home", field_label="Test field")
    assert result["result"] == "pass"


def test_field_match_fail_when_values_disagree():
    result = check_field_match("Home", "Office", field_label="Test field")
    assert result["result"] == "fail"


def test_field_match_uncertain_when_session_side_missing():
    result = check_field_match(None, "Office", field_label="Test field")
    assert result["result"] == "uncertain"


def test_field_match_uncertain_when_tp_side_missing():
    result = check_field_match("Office", None, field_label="Test field")
    assert result["result"] == "uncertain"


def test_field_match_uncertain_when_both_sides_missing():
    result = check_field_match(None, None, field_label="Test field")
    assert result["result"] == "uncertain"


# -------------------------- full orchestration (generic, synthetic values) -


def _synthetic_extraction(**overrides) -> dict:
    base = {
        "session_date": {"value": "09/15/2026", "confidence": "high", "source_quote": "q"},
        "session_location": {"value": "Office", "confidence": "high", "source_quote": "q"},
        "clinician_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "patient_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "assessment_activity": {"value": "Direct observation", "confidence": "high", "source_quote": "q"},
    }
    base.update(overrides)
    return base


def test_compare_session_note_to_tp_all_three_rules_pass_on_matching_synthetic_data():
    result = compare_session_note_to_tp(
        _synthetic_extraction(),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date="09/15/2026",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="Direct observation",
    )
    assert set(result.keys()) == {"QA-RPT-03", "QA-ACF-02", "QA-ACF-08"}
    assert result["QA-RPT-03"]["result"] == "pass"
    assert result["QA-ACF-02"]["result"] == "pass"
    assert result["QA-ACF-08"]["result"] == "pass"


def test_compare_session_note_to_tp_acf02_fails_when_any_one_subcheck_disagrees():
    result = compare_session_note_to_tp(
        _synthetic_extraction(),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date="09/15/2026",
        tp_pos="Home",  # disagrees with the session's "Office"
        tp_patient_location="Office",
        tp_assessment_tool="Direct observation",
    )
    assert result["QA-ACF-02"]["result"] == "fail"
    assert "Office" in result["QA-ACF-02"]["evidence"] and "Home" in result["QA-ACF-02"]["evidence"]


def test_compare_session_note_to_tp_acf08_fails_on_assessment_type_mismatch():
    result = compare_session_note_to_tp(
        _synthetic_extraction(),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date="09/15/2026",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="VB-MAPP",  # disagrees with the session's "Direct observation"
    )
    assert result["QA-ACF-08"]["result"] == "fail"


def test_compare_session_note_to_tp_rpt03_fails_when_session_date_out_of_window():
    """Confirms the FULL orchestration (not just the standalone function)
    also correctly fails an out-of-range date."""
    result = compare_session_note_to_tp(
        _synthetic_extraction(session_date={"value": "01/01/2026", "confidence": "high", "source_quote": "q"}),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date="01/01/2026",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="Direct observation",
    )
    assert result["QA-RPT-03"]["result"] == "fail"


def test_compare_session_note_to_tp_uses_synthetic_current_report_window_not_authorization_period():
    """Round 63, item 1, end-to-end proof: a session date that falls INSIDE
    a synthetic current-report window but would fall OUTSIDE a
    hypothetical future authorization period for the same fictional case
    must still PASS -- proving the full orchestration compares against the
    current-report field, not an authorization period, end to end."""
    result = compare_session_note_to_tp(
        _synthetic_extraction(session_date={"value": "01/08/2025", "confidence": "high", "source_quote": "q"}),
        tp_current_report_period=SYNTHETIC_CURRENT_REPORT_PERIOD_A,
        tp_assessment_date="01/08/2025",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="Direct observation",
    )
    assert result["QA-RPT-03"]["result"] == "pass"


def test_compare_session_note_to_tp_uncertain_when_tp_side_entirely_missing():
    """No TP-side ACF data available at all (exactly Yisroel's real
    situation this round -- no TP document yet) -- must come back
    uncertain, never a guessed pass/fail."""
    result = compare_session_note_to_tp(
        _synthetic_extraction(),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date=None,
        tp_pos=None,
        tp_patient_location=None,
        tp_assessment_tool=None,
    )
    assert result["QA-RPT-03"]["result"] == "pass"  # this one only needs the report period, which IS available
    assert result["QA-ACF-02"]["result"] == "uncertain"
    assert result["QA-ACF-08"]["result"] == "uncertain"


def test_compare_session_note_to_tp_treats_none_confidence_session_field_as_absent():
    """A session-note field extracted with confidence="none" (the honest
    "not stated" outcome) must be treated as absent, not as a literal
    string value to compare."""
    result = compare_session_note_to_tp(
        _synthetic_extraction(assessment_activity={"value": None, "confidence": "none", "source_quote": None}),
        tp_current_report_period=YISROEL_AUTHORIZATION_PERIOD,
        tp_assessment_date="09/15/2026",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="Direct observation",
    )
    assert result["QA-ACF-08"]["result"] == "uncertain"
