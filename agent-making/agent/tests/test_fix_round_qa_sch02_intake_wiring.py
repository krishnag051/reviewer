"""Fix Round (2026-08-26): real tests for the confirmed QA-SCH-02 wiring gap
fix -- pipeline/schedule_hours.py::check_schedule_hours_against_intake and
its backend wiring (app/agent_client.py::review_intake_answers,
app/rule_engine/client.py::run_rule_checks). Synthetic-only, zero model
calls anywhere in this file -- this whole comparison is deterministic
Python, same discipline as test_round63_schedule_hours.py.
"""
from pipeline.schedule_hours import check_schedule_hours_against_intake, parse_hours_from_free_text


def _synthetic_tp_text(schedule_row: str) -> str:
    """Same synthetic TP-text shape as test_round63_schedule_hours.py's own
    helper, so this exercises the real extract_weekly_schedule_day_texts
    parser, not a hand-built dict."""
    return (
        "Patient's ABA and school schedule as well as the Place of Service are subject to change.\n"
        "Sunday Monday Tuesday Wednesday Thursday Friday Saturday\n"
        "School Schedule n/a  8am-3pm  8am-3pm  8am-3pm  8am-3pm  8am-3pm  n/a  \n"
        "Patient Schedule\nof ABA Services\n"
        f"{schedule_row}\n"
        "POS Home  n/a  Home  Home  Home  Home  Home  \n"
        "Biopsychosocial Information:\n"
    )


# A real TP schedule totaling exactly 20 hrs/week (2 + 0 + 4*4 + 2), same
# shape/total as test_round63_schedule_hours.py's own single-shift fixture.
_TP_TEXT_20_HRS_WEEK = _synthetic_tp_text("9am-11am  n/a  3pm-7pm  3pm-7pm  3pm-7pm  3pm-7pm  9am-11am  ")


def test_parse_hours_from_free_text_finds_the_number():
    assert parse_hours_from_free_text("Home, Mon-Fri 5-8pm, 15 hrs/week requested") == 15.0


def test_parse_hours_from_free_text_handles_singular_hour_and_no_slash():
    assert parse_hours_from_free_text("20 hours requested weekly") == 20.0


def test_parse_hours_from_free_text_returns_none_when_no_number_present():
    assert parse_hours_from_free_text("Home, telehealth as needed") is None


def test_parse_hours_from_free_text_returns_none_for_empty_or_none():
    assert parse_hours_from_free_text("") is None
    assert parse_hours_from_free_text(None) is None


def test_pass_when_schedule_and_pos_field_hours_match_tp_schedule():
    result, evidence, page, confidence = check_schedule_hours_against_intake(
        _TP_TEXT_20_HRS_WEEK,
        pos_schedule_text="Home, Mon-Fri, 20 hrs/week requested",
        hours_requesting_text="20 hrs/week",
    )
    assert result == "pass"
    assert "20" in evidence
    assert page is None


def test_fail_when_schedule_and_pos_field_hours_disagree_with_tp_schedule():
    result, evidence, page, confidence = check_schedule_hours_against_intake(
        _TP_TEXT_20_HRS_WEEK,
        pos_schedule_text="Home, Mon-Fri, 15 hrs/week requested",
        hours_requesting_text="15 hrs/week",
    )
    assert result == "fail"
    assert "20" in evidence and "15" in evidence


def test_falls_back_to_hours_requesting_field_when_schedule_and_pos_has_no_number():
    """Schedule and POS is the field QA-SCH-02's own description names --
    checked first -- but if it doesn't state a number at all, Hours
    Requesting is a real fallback source, not a second guess."""
    result, evidence, page, confidence = check_schedule_hours_against_intake(
        _TP_TEXT_20_HRS_WEEK,
        pos_schedule_text="Home, Monday through Friday afternoons",
        hours_requesting_text="20 hrs/week",
    )
    assert result == "pass"
    assert "Hours Requesting" in evidence


def test_not_checkable_when_neither_intake_field_states_a_parseable_number():
    result, evidence, page, confidence = check_schedule_hours_against_intake(
        _TP_TEXT_20_HRS_WEEK,
        pos_schedule_text="Home, afternoons",
        hours_requesting_text="as approved",
    )
    assert result == "not_checkable"
    assert confidence < 0.5


def test_not_checkable_when_tp_schedule_table_cannot_be_parsed_at_all():
    result, evidence, page, confidence = check_schedule_hours_against_intake(
        "This document has no schedule table at all.",
        pos_schedule_text="Home, 20 hrs/week",
        hours_requesting_text="20 hrs/week",
    )
    assert result == "not_checkable"
    assert confidence == 0.0
