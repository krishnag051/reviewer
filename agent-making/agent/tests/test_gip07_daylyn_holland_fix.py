"""Fix Round (2026-09-11), item 23 -- REAL logic bug confirmed and fixed
against the real Daylyn Holland TP. Ma'am's report: this rule incorrectly
answers "Uncertain" when there are actually no goals open for more than 6
months at all. Confirmed real numbers on this document: goals initiated
05/04/2026-05/18/2026, current report ending 09/08/2026 -- ~4 months,
genuinely under the 6-month threshold for every one of them.
"""
from datetime import datetime

from pipeline import fields


def _fields(full_text: str) -> dict:
    return {"pages": [{"page_number": 1, "text": full_text}], "full_text": full_text}


_REAL_REPORT_HEADER = (
    "Report Information:\n"
    "Date of Initial Assessment: 4/30/2026\n"
    "Date of Current Report: 09/04/2026 to 09/08/2026\n"
    "Authorization Dates Requested: 09/15/2026 to 12/15/2026\n"
)


def test_gip07_not_applicable_when_no_goal_is_old_enough():
    text = _REAL_REPORT_HEADER + (
        "Target Goal: Daylyn will show the BT what whole body listening looks like.\n"
        "Goal Status: In progress\n"
        "Date Initiated: 05/05/2026\n"
        "Mastery Criteria: 3 times per session\n"
    )
    result, evidence, page, confidence = fields._check_GIP07({"rule_id": "QA-GIP-07"}, _fields(text))
    assert result == "not_applicable", evidence


def test_gip07_escalates_to_judgment_when_a_goal_is_genuinely_old():
    text = _REAL_REPORT_HEADER + (
        "Target Goal: Daylyn will show the BT what whole body listening looks like.\n"
        "Goal Status: In progress\n"
        "Date Initiated: 01/01/2026\n"  # ~8 months before 09/08/2026
        "Mastery Criteria: 3 times per session\n"
    )
    result, evidence, page, confidence = fields._check_GIP07({"rule_id": "QA-GIP-07"}, _fields(text))
    assert result == "not_checkable"
    assert "01/01/2026" in evidence


def test_gip07_not_checkable_when_no_report_range_found():
    text = "Target Goal: X\nGoal Status: In progress\nDate Initiated: 01/01/2026\n"
    result, evidence, page, confidence = fields._check_GIP07({"rule_id": "QA-GIP-07"}, _fields(text))
    assert result == "not_checkable"
