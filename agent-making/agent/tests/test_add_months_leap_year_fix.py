"""Real bug found and fixed via the Streamlit tool (app.py), not a live
document/API issue: `_add_months`'s `_DAYS_IN_MONTH` table hardcoded
February to 29 days, and the leap-year branch only ever set max_day TO 29
(the leap-year case) -- it never corrected back DOWN to 28 for a non-leap
year. So every non-leap February computed max_day=29, and
`d.replace(day=29)` on e.g. Feb 2027 (28 days) raised
`ValueError: day is out of range for month`.

Surfaced live: `_check_HF01` calls `_add_months(start, expected_months)`
on a real document whose authorization start date landed on the 31st of a
month, rolling into a non-leap February -- crashed the whole deterministic
check layer, not just this one rule (run_deterministic_checks has no
per-checker isolation).

Fix: _DAYS_IN_MONTH[1] (February) corrected to 28; the existing leap-year
check still bumps it to 29 when applicable. No live call needed to verify
this -- pure deterministic date arithmetic.
"""
from datetime import datetime

from pipeline.fields import _add_months


def test_non_leap_february_clamps_to_28_not_29():
    """The exact crash shape: Jan 31 + 1 month, landing in a non-leap Feb."""
    assert _add_months(datetime(2027, 1, 31), 1) == datetime(2027, 2, 28)


def test_non_leap_february_clamps_to_28_another_year():
    assert _add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)


def test_leap_february_still_allows_29():
    """The leap-year branch itself was never broken -- confirm it still works."""
    assert _add_months(datetime(2028, 1, 31), 1) == datetime(2028, 2, 29)


def test_plain_month_add_unaffected():
    """Sanity check the fix didn't disturb ordinary month arithmetic."""
    assert _add_months(datetime(2026, 6, 15), 6) == datetime(2026, 12, 15)


def test_multi_month_rollover_into_non_leap_february():
    assert _add_months(datetime(2026, 11, 30), 3) == datetime(2027, 2, 28)
