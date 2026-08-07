"""Round 63, item 3: deterministic schedule-hours arithmetic. Every
fixture in this file is SYNTHETIC, with deliberately different totals
from any real patient's real hours (not 31 hrs/week, not any value tied
to Yisroel Leibowitz) -- proving the arithmetic is generally correct, not
right for one specific case. Zero model calls anywhere in this file.
"""
from datetime import time

from pipeline.schedule_hours import (
    compute_weekly_total,
    extract_weekly_schedule_day_texts,
    hours_for_day,
    parse_time_range,
)


# ------------------------------------------------------------ parse_time_range


def test_parse_time_range_both_sides_explicit_am_pm():
    start, end = parse_time_range("10:00am-2:30pm")
    assert start == time(10, 0)
    assert end == time(14, 30)


def test_parse_time_range_handles_en_dash_and_spacing():
    start, end = parse_time_range("10:00am – 2:30pm")
    assert (start, end) == (time(10, 0), time(14, 30))


def test_parse_time_range_bare_hour_no_minutes():
    start, end = parse_time_range("4pm-8pm")
    assert (start, end) == (time(16, 0), time(20, 0))


def test_parse_time_range_infers_am_for_morning_hour_without_marker():
    start, end = parse_time_range("10:45-12:45")
    assert start == time(10, 45)  # inferred AM
    assert end == time(12, 45)  # 12 -> inferred PM (noon)


def test_parse_time_range_infers_pm_for_small_hour_without_marker():
    start, end = parse_time_range("1:00-4:00")
    assert (start, end) == (time(13, 0), time(16, 0))


def test_parse_time_range_none_when_unparseable():
    assert parse_time_range("sometime in the afternoon") is None


def test_parse_time_range_none_when_end_not_after_start():
    """Guards against a nonsensical/overnight range being silently
    accepted -- this domain has no overnight ABA sessions."""
    assert parse_time_range("8pm-7am") is None


# ------------------------------------------------------------------ hours_for_day


def test_hours_for_day_single_shift():
    assert hours_for_day("7:30am-3pm") == 7.5


def test_hours_for_day_not_scheduled_is_zero_not_none():
    assert hours_for_day("n/a") == 0.0
    assert hours_for_day("N/A") == 0.0


def test_hours_for_day_two_shifts_joined_by_and():
    assert hours_for_day("10:45-12:45 and 1:00-4:00") == 2.0 + 3.0


def test_hours_for_day_none_when_unparseable_text():
    assert hours_for_day("please confirm with the family") is None


# -------------------------------------------------------------- compute_weekly_total
# SYNTHETIC schedules with hand-verified totals, deliberately different
# from 31 hrs/week (Yisroel's real total) and from each other.


def test_synthetic_schedule_one_single_shift_weekdays_only():
    """5 weekdays x 6 hrs/day = 30 hrs/week, weekend off."""
    day_texts = {
        "Sunday": "n/a", "Monday": "9am-3pm", "Tuesday": "9am-3pm", "Wednesday": "9am-3pm",
        "Thursday": "9am-3pm", "Friday": "9am-3pm", "Saturday": "n/a",
    }
    total, per_day = compute_weekly_total(day_texts)
    assert total == 30.0
    assert per_day["Monday"] == 6.0
    assert per_day["Sunday"] == 0.0


def test_synthetic_schedule_two_split_shift_weekdays_plus_weekend():
    """A deliberately different, higher-total synthetic schedule: 4 split-
    shift weekdays (2 + 2.5 hrs each) plus a single weekend session."""
    day_texts = {
        "Sunday": "10am-1pm", "Monday": "9:00-11:00 and 1:00-3:30", "Tuesday": "9:00-11:00 and 1:00-3:30",
        "Wednesday": "9:00-11:00 and 1:00-3:30", "Thursday": "9:00-11:00 and 1:00-3:30",
        "Friday": "n/a", "Saturday": "n/a",
    }
    total, per_day = compute_weekly_total(day_texts)
    assert per_day["Monday"] == 2.0 + 2.5
    assert total == 3.0 + 4 * 4.5  # Sunday 3 hrs + 4 weekdays x 4.5 hrs each = 21.0
    assert total == 21.0


def test_synthetic_schedule_exactly_six_hours_a_day_not_six_point_five():
    """Directly targets the confirmed real bug shape: a schedule whose
    correct total is exactly 6 hrs/day must compute to exactly 6.0, not
    6.5 -- the arithmetic must be exact, not an LLM approximation."""
    day_texts = {d: "9:00am-3:00pm" for d in
                 ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]}
    total, per_day = compute_weekly_total(day_texts)
    assert all(h == 6.0 for h in per_day.values())
    assert total == 42.0


def test_synthetic_schedule_weekly_total_is_none_when_any_day_unparseable():
    """A partial sum would misrepresent an incomplete total as complete --
    must come back None (not_checkable territory), not a guessed partial."""
    day_texts = {
        "Sunday": "n/a", "Monday": "9am-3pm", "Tuesday": "please confirm", "Wednesday": "9am-3pm",
        "Thursday": "9am-3pm", "Friday": "9am-3pm", "Saturday": "n/a",
    }
    total, per_day = compute_weekly_total(day_texts)
    assert total is None
    assert per_day["Tuesday"] is None
    assert per_day["Monday"] == 6.0  # other days still individually visible


# ---------------------------------------- extract_weekly_schedule_day_texts
# SYNTHETIC full-document text blobs, shaped like the real table layout
# but with values that are not any real patient's real hours.


def _synthetic_tp_text(schedule_row: str) -> str:
    return (
        "Patient's ABA and school schedule as well as the Place of Service are subject to change.\n"
        "Sunday Monday Tuesday Wednesday Thursday Friday Saturday\n"
        "School Schedule n/a  8am-3pm  8am-3pm  8am-3pm  8am-3pm  8am-3pm  n/a  \n"
        "Patient Schedule\nof ABA Services\n"
        f"{schedule_row}\n"
        "POS Home  n/a  Home  Home  Home  Home  Home  \n"
        "Biopsychosocial Information:\n"
    )


def test_extract_single_shift_per_day_shape_splits_into_seven_days():
    text = _synthetic_tp_text("9am-11am  n/a  3pm-7pm  3pm-7pm  3pm-7pm  3pm-7pm  9am-11am  ")
    days = extract_weekly_schedule_day_texts(text)
    assert days is not None
    assert set(days.keys()) == set(
        ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    )
    total, per_day = compute_weekly_total(days)
    assert per_day["Sunday"] == 2.0
    assert per_day["Monday"] == 0.0
    assert total == 2.0 + 0.0 + 4.0 * 4 + 2.0


def test_extract_two_shift_per_day_shape_with_and_joiner_splits_into_seven_days():
    """Mirrors the OTHER real structural shape confirmed this round (split
    shifts joined by 'and') -- with entirely different, synthetic hours."""
    schedule_row = (
        "n/a  \n"
        "9:00-11:00\nand 1:00-\n3:00  \n"
        "9:00-11:00 and 1:00-3:00  \n"
        "9:00-11:00\nand 1:00-3:00  \n"
        "9:00-11:00 and\n1:00-3:00  \n"
        "n/a  n/a  "
    )
    text = _synthetic_tp_text(schedule_row)
    days = extract_weekly_schedule_day_texts(text)
    assert days is not None
    total, per_day = compute_weekly_total(days)
    assert per_day["Monday"] == 2.0 + 2.0
    assert per_day["Sunday"] == 0.0
    assert per_day["Friday"] == 0.0
    assert total == 4 * 4.0  # Mon-Thu, 4 hrs each


def test_extract_returns_none_when_day_header_missing():
    assert extract_weekly_schedule_day_texts("no schedule table here at all") is None


def test_extract_returns_none_when_token_count_is_not_seven():
    """A row that clearly doesn't split into exactly 7 day-tokens must come
    back None (not_checkable) rather than a wrong guessed split."""
    text = _synthetic_tp_text("9am-11am  3pm-7pm  3pm-7pm  ")  # only 3 tokens, not 7
    assert extract_weekly_schedule_day_texts(text) is None


# ------------------------------------------- real-document generality check
# Uses conftest.py's skip-if-absent reeda_tp_pdf/charny_tp_pdf fixtures --
# no PHI appears anywhere in THIS file's source; the fixture reads real
# bytes from disk only if present on the machine running the suite. Reeda's
# and Charny's schedules are two structurally DIFFERENT real shapes (one
# shift/day, unwrapped vs. two shifts/day, wrapped across lines) -- this is
# the strongest available proof the extraction generalizes beyond synthetic
# fixtures, without hardcoding either patient's real hours into source.


def test_extraction_and_arithmetic_agree_on_reedas_real_schedule_shape(reeda_tp_pdf):
    from pipeline.extract import extract_pdf_text

    full_text = "\n".join(p["text"] for p in extract_pdf_text(reeda_tp_pdf))
    days = extract_weekly_schedule_day_texts(full_text)
    assert days is not None, "expected a clean 7-day split on this real document's schedule table"
    total, per_day = compute_weekly_total(days)
    assert total is not None, f"expected every day to parse cleanly; got {per_day}"
    assert all(hours is not None for hours in per_day.values())


def test_extraction_and_arithmetic_agree_on_charnys_real_schedule_shape(charny_tp_pdf):
    from pipeline.extract import extract_pdf_text

    full_text = "\n".join(p["text"] for p in extract_pdf_text(charny_tp_pdf))
    days = extract_weekly_schedule_day_texts(full_text)
    assert days is not None, "expected a clean 7-day split on this real document's schedule table"
    total, per_day = compute_weekly_total(days)
    assert total is not None, f"expected every day to parse cleanly; got {per_day}"
    assert all(hours is not None for hours in per_day.values())
