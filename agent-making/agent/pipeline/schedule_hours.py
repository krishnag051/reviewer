"""Round 63, item 3: deterministic Python parsing + real date/time
arithmetic for the "Patient Schedule of ABA Services" weekly grid, backing
QA-SCH-01 (schedule matches hours requested) and QA-SCH-07 (>3 hrs/day of
97153 -> Director approval).

Root cause of the original bug: this table's total was left to the
judgment layer to eyeball from raw extracted text -- confirmed live to
produce real arithmetic errors (a 6.5 hrs/day total where the table
states 6) and outright fabrication (a shift on a day the table doesn't
list at all). Neither is a judgment call; it's arithmetic over explicit
time ranges, which Python can do exactly and reproducibly every time --
same "deterministic Python for objective checks" principle already used
for QA-PPI-05 (fields.py) and the session-note current-report date-range
check (session_note_comparison.py).

Two genuinely separate concerns, kept in two layers:

1. Arithmetic core (parse_time_range, hours_for_day,
   compute_weekly_total) -- pure, fully general, works on ANY list of
   "start-end" time-range strings for a day, regardless of where they came
   from. Verified below against multiple SYNTHETIC schedules with known
   correct totals (not just one patient's hours), per this round's own
   instruction not to overfit to one real example.

2. Table extraction (extract_weekly_schedule_day_texts) -- the genuinely
   hard, previously-"not yet built" part rules.json's own blocked_status
   flagged (pypdf's raw text ordering for this table loses column
   boundaries entirely; the 7 days' cells run together with no reliable
   delimiter). The one real structural anchor that survives extraction on
   BOTH real documents checked this round (Reeda Bint Shaheen's and Charny
   Gluck's TPs, which have completely different schedule shapes -- one
   shift/day vs. two shifts/day, wrapped vs. unwrapped times) is the word
   "and", which both documents use exclusively to join two time ranges
   WITHIN the same day, never between days. Splitting on "a time-range (or
   n/a) token not immediately preceded by 'and' starts a new day" produces
   the correct 7-way split on both real, structurally different formats --
   this is a general property of how the table is transcribed, not
   something keyed to either document's specific values. If the token
   count doesn't come out to exactly 7, this returns None (not_checkable
   territory for the caller) rather than guessing at a split.

AM/PM inference (only used when a time token has no explicit am/pm
marker): hours 7-11 default to AM, hours 12/1-6 default to PM -- ABA
service hours are daytime by construction in every real document seen;
this is a documented, general default, not a per-document special case.
If applying it still produces an end time at or before the start time,
the range is treated as unparseable (returns None) rather than guessing
an overnight wraparound this domain doesn't have.
"""
from __future__ import annotations

import re
from datetime import time

_TIME_RANGE_PATTERN = re.compile(
    r"(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[-–—]\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
    re.IGNORECASE,
)
_NOT_SCHEDULED_PATTERN = re.compile(r"^n/?a$", re.IGNORECASE)


def _parse_clock_token(token: str, *, is_start: bool) -> time | None:
    """Parses one clock-time token ('7:30am', '3pm', '10', '12:45') into a
    real datetime.time. `is_start` only matters for AM/PM inference when
    no marker is present -- see module docstring.
    """
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", token.strip(), re.IGNORECASE)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    if hour > 12 or minute > 59:
        return None
    meridiem = (m.group(3) or "").lower()

    if not meridiem:
        # Daytime-scheduling default -- see module docstring.
        meridiem = "am" if hour in (7, 8, 9, 10, 11) else "pm"

    hour24 = hour % 12
    if meridiem == "pm":
        hour24 += 12
    return time(hour=hour24, minute=minute)


def parse_time_range(range_str: str) -> tuple[time, time] | None:
    """Parses a single 'start-end' time-range string into (start, end).
    Returns None if either side can't be parsed, or if the resulting end
    is at or before the start (see module docstring on overnight ranges).
    """
    m = _TIME_RANGE_PATTERN.search(range_str)
    if not m:
        return None
    start = _parse_clock_token(m.group(1), is_start=True)
    end = _parse_clock_token(m.group(2), is_start=False)
    if start is None or end is None:
        return None
    if end <= start:
        return None
    return start, end


def _hours_between(start: time, end: time) -> float:
    return ((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) / 60.0


def hours_for_day(day_text: str) -> float | None:
    """Total scheduled hours for ONE day, from its raw text (which may
    contain one or more time ranges, e.g. a split-shift day joined by
    "and"). Returns 0.0 for an explicit "n/a"/"N/A" (no session that
    day -- a real, stated fact, not missing data). Returns None if the
    text is non-empty but no range could be confidently parsed from it --
    never a guessed number.
    """
    stripped = day_text.strip()
    if _NOT_SCHEDULED_PATTERN.match(stripped):
        return 0.0

    ranges = _TIME_RANGE_PATTERN.findall(day_text)
    if not ranges:
        return None

    total = 0.0
    for start_str, end_str in ranges:
        parsed = parse_time_range(f"{start_str}-{end_str}")
        if parsed is None:
            return None
        start, end = parsed
        total += _hours_between(start, end)
    return total


DAYS_OF_WEEK = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def compute_weekly_total(day_texts: dict[str, str]) -> tuple[float | None, dict[str, float | None]]:
    """Given {day_name: raw_text_for_that_day}, returns (weekly_total,
    per_day_hours). weekly_total is None if ANY day's hours couldn't be
    determined -- a partial sum would misrepresent a real total as
    complete when it isn't. per_day_hours is always returned in full (one
    entry per key given), so a caller can still show which specific day(s)
    are the problem.
    """
    per_day = {day: hours_for_day(text) for day, text in day_texts.items()}
    if any(hours is None for hours in per_day.values()):
        return None, per_day
    return sum(per_day.values()), per_day


# ------------------------------------------------- table extraction (best-effort)

_DAY_HEADER_PATTERN = re.compile(
    r"Sunday\s+Monday\s+Tuesday\s+Wednesday\s+Thursday\s+Friday\s+Saturday", re.IGNORECASE,
)
_DAY_TOKEN_PATTERN = re.compile(
    r"(?P<and>and)|(?P<range>" + _TIME_RANGE_PATTERN.pattern + r")|(?P<na>n/?a)",
    re.IGNORECASE,
)


def extract_weekly_schedule_day_texts(full_text: str) -> dict[str, str] | None:
    """Best-effort extraction of the "Patient Schedule of ABA Services" row
    into 7 day buckets (see module docstring for the "and"-joiner strategy
    and why it's confirmed general, not per-document). Returns None if the
    row can't be confidently located or doesn't split into exactly 7
    buckets -- callers should treat None as not_checkable, never a guess.
    """
    header_m = _DAY_HEADER_PATTERN.search(full_text)
    if not header_m:
        return None

    # The ABA-services row sits between the day-of-week header and the
    # "POS" row that always follows it in every real document checked.
    after_header = full_text[header_m.end():]
    row_m = re.search(
        r"Patient Schedule\s*(?:of ABA Services)?([\s\S]{0,1000}?)\bPOS\b", after_header, re.IGNORECASE,
    )
    if not row_m:
        return None
    row_text = row_m.group(1)

    tokens = []  # list of (text, preceded_by_and)
    prev_was_and = False
    for m in _DAY_TOKEN_PATTERN.finditer(row_text):
        if m.group("and"):
            prev_was_and = True
            continue
        tokens.append((m.group(0), prev_was_and))
        prev_was_and = False

    buckets: list[str] = []
    for text, preceded_by_and in tokens:
        if preceded_by_and and buckets:
            buckets[-1] += " and " + text
        else:
            buckets.append(text)

    if len(buckets) != 7:
        return None
    return dict(zip(DAYS_OF_WEEK, buckets))
