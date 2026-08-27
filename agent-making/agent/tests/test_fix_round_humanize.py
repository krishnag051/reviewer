"""Fix Round (2026-08-27), Part 4: humanize_evidence -- real before/after
against REAL evidence strings this pipeline's own checker functions
actually produce (called for real here, not hand-typed), plus synthetic
edge cases. Zero model calls -- this whole pass is deterministic Python.
"""
from pipeline import fields
from pipeline.humanize import humanize_evidence
from pipeline.schedule_hours import check_schedule_hours_against_intake
from pipeline.session_note_comparison import check_date_in_current_report_period


def test_strips_trailing_point_zero_off_whole_number_floats():
    assert humanize_evidence("97151 hours requested: 8.0, exceeds the 5-hour cap.") == \
        "97151 hours requested: 8, exceeds the 5-hour cap."


def test_does_not_touch_a_real_decimal_value():
    """8.5 is a real, meaningful fraction -- never strip a genuine decimal,
    only the ".0" artifact a whole-number float leaves behind."""
    assert "8.5" in humanize_evidence("Total hours: 8.5 per week.")


def test_converts_python_list_repr_of_one_item_to_plain_prose():
    assert "1578293197" in humanize_evidence("NPI (['1578293197']) is stated.")
    assert "[" not in humanize_evidence("NPI (['1578293197']) is stated.")


def test_converts_python_list_repr_of_two_items_with_and():
    result = humanize_evidence("Values found: ['a', 'b'].")
    assert result == "Values found: a and b."


def test_converts_python_list_repr_of_three_items_with_oxford_and():
    result = humanize_evidence("Values found: ['a', 'b', 'c'].")
    assert result == "Values found: a, b, and c."


def test_lowercases_midsentence_and_or():
    result = humanize_evidence("This is true, AND this is also true.")
    assert ", and this" in result
    assert "AND" not in result


def test_preserves_and_at_a_real_sentence_start():
    result = humanize_evidence("First sentence. AND this genuinely starts a new sentence.")
    assert result.startswith("First sentence. AND")


def test_drops_redundant_inclusive_parenthetical():
    result = humanize_evidence("Range 2026-07-22 to 2026-07-29 (inclusive).")
    assert "(inclusive)" not in result
    assert result == "Range 2026-07-22 to 2026-07-29."


def test_semicolon_becomes_a_real_sentence_break():
    result = humanize_evidence("Patient age 17; range matches the expected pattern.")
    assert result == "Patient age 17. Range matches the expected pattern."


def test_page_tags_survive_completely_untouched_with_their_surrounding_spaces():
    """The one thing this pass must never do: touch or mangle a [Page N]
    tag, or eat the real space next to one -- these are load-bearing for
    the frontend's clickable page links (judge.py::EXACT_PAGE_TAG_RE)."""
    before = "All correspondence with BCBA removed [Page 4]; nothing found on [Page 9] either."
    after = humanize_evidence(before)
    assert "[Page 4]" in after
    assert "[Page 9]" in after
    assert "removed [Page 4]." in after
    assert "on [Page 9] either" in after


def test_idempotent_running_twice_gives_the_same_result():
    text = "97151 hours requested: 8.0, AND License (['ABC123'])."
    once = humanize_evidence(text)
    twice = humanize_evidence(once)
    assert once == twice


def test_empty_and_none_pass_through_safely():
    assert humanize_evidence("") == ""
    assert humanize_evidence(None) is None


# ---------------------------------------- real before/after against real checker output


def test_real_hf01_evidence_before_and_after():
    text = "Patient Age:  17 Patient Gender: Female\nAuthorization Dates Requested: 07/30/2026  to 10/30/2026"
    rule = {"params": {"age_threshold": 13, "short_range_weeks": 13, "long_range_weeks": 26}}
    _, before, _, _ = fields._check_HF01(rule, {"full_text": text})
    after = humanize_evidence(before)
    assert before == (
        "Patient age 17; authorization range 07/30/2026 to 10/30/2026 (92 days) matches the "
        "expected 13-week range for age > 13."
    )
    assert after == (
        "Patient age 17. Authorization range 07/30/2026 to 10/30/2026 (92 days) matches the "
        "expected 13-week range for age > 13."
    )


def test_real_hf02_evidence_before_and_after():
    rule = {"params": {"cpt_code": "97151", "max_hours": 5}}
    _, before, _, _ = fields._check_HF02(rule, {"full_text": "97151: 8 hrs requested"})
    after = humanize_evidence(before)
    assert before == "97151 hours requested: 8.0, exceeds the 5-hour cap."
    assert after == "97151 hours requested: 8, exceeds the 5-hour cap."


def test_real_ppi05_evidence_before_and_after():
    tp_fields = {
        "full_text": "NPI: 1578293197\n",
        "intake_bcba_name_credentials_npi": "Jane Smith, BCBA-D - NPI 1578293197",
    }
    _, before, _, _ = fields._check_PPI05({}, tp_fields)
    after = humanize_evidence(before)
    assert "['1578293197']" in before
    assert "['1578293197']" not in after
    assert "1578293197" in after
    assert "AND" not in after


def test_real_rpt03_session_note_evidence_before_and_after():
    before = check_date_in_current_report_period("07/29/2026", "07/22/2026 to 07/29/2026")["evidence"]
    after = humanize_evidence(before)
    assert before == "Session date 07/29/2026 falls within the current-report date range 2026-07-22 to 2026-07-29 (inclusive)."
    assert after == "Session date 07/29/2026 falls within the current-report date range 2026-07-22 to 2026-07-29."


def test_real_sch02_not_checkable_evidence_is_already_plain_and_unchanged():
    """Not every real evidence string has something to clean up -- this
    one was already plain going in; confirms the pass doesn't invent
    changes where none are needed."""
    before, _, _ = (
        check_schedule_hours_against_intake("no schedule table here", pos_schedule_text="20 hrs/week", hours_requesting_text=None)[1],
        None, None,
    )
    after = humanize_evidence(before)
    assert before == after
