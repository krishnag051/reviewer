"""Previous TP round -- EXTRACTION PLUMBING ONLY, no comparison logic (see
pipeline/previous_tp_extraction.py's own module docstring for full scope).

Two levels here:
1. Unit tests for the two new fields.py extractors
   (_extract_mastered_goals_with_dates, _extract_problem_areas) against
   synthetic text, same style as the rest of this test suite (e.g.
   test_round83_acf_and_contradictions.py's own `_fields` helper).
2. One real-document integration test: extract_previous_tp_fields against
   `sample_tps/Ullah_Zyaan_Redacted.pdf`, the only real TP PDF locally
   available in this repo. This is NOT the real verification pair this
   round's own brief asks for (the two real Mihad Ali TPs, 5-2026 and
   8-2026) -- those weren't available in this environment when this round
   was built; see this round's own report for that open item. This test
   only proves the plumbing runs end-to-end against a genuine PDF, not that
   its output matches any specific expected values for Mihad Ali.

Zero real API/model calls anywhere in this file -- every function under
test is pure PDF-text-extraction + regex, same as the rest of fields.py.
"""
from pathlib import Path

from pipeline import fields
from pipeline.previous_tp_extraction import extract_previous_tp_fields

_SAMPLE_TP_PATH = Path(__file__).resolve().parents[1] / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"


# --- _extract_mastered_goals_with_dates ------------------------------------


def test_extract_mastered_goals_with_dates_pairs_each_name_with_its_own_date():
    text = (
        "Mastered Goals:\n"
        "Name of Skill: Zyaan will point to a requested item\n"
        "Date Mastered: 03/16/2026,  Last Three Days Average in Maintenance: 0\n"
        "Name of Skill: Zyaan will imitate a two-step motor sequence\n"
        "Date Mastered: 04/02/2026,  Last Three Days Average in Maintenance: 0\n"
        "Goals in Progress:\n"
        "Target Goal: something still active, not mastered\n"
    )
    result = fields._extract_mastered_goals_with_dates(text)
    assert [g["name"] for g in result] == [
        "Zyaan will point to a requested item",
        "Zyaan will imitate a two-step motor sequence",
    ]
    assert [g["date_mastered"] for g in result] == ["03/16/2026", "04/02/2026"]
    # Offsets must point at the goal NAME's own position (same convention
    # as the pre-existing _extract_mastered_goal_names), not the date's.
    assert text[result[0]["offset"]:result[0]["offset"] + len("Zyaan will point")].startswith("Zyaan will point")


def test_extract_mastered_goals_with_dates_never_swallows_an_active_goal():
    """Same boundary-safety guarantee _extract_mastered_goal_names already
    has (Round 83, item 2b's own docstring) -- an active 'Target Goal:'
    block after 'Goals in Progress:' must never be misread as a mastered
    entry, even though this is a different function reusing that boundary."""
    text = (
        "Mastered Goals:\n"
        "Name of Skill: Real mastered goal\n"
        "Date Mastered: 05/01/2026\n"
        "Goals in Progress:\n"
        "Target Goal: An active goal that happens to also mention Date Mastered: 01/01/2020 in passing\n"
    )
    result = fields._extract_mastered_goals_with_dates(text)
    assert len(result) == 1
    assert result[0]["name"] == "Real mastered goal"


def test_extract_mastered_goals_with_dates_returns_empty_list_with_no_section():
    assert fields._extract_mastered_goals_with_dates("No mastered goals section in this text at all.") == []


def test_extract_mastered_goals_with_dates_date_is_none_when_genuinely_missing():
    """A malformed/incomplete entry (name present, date value blank) must
    come back with date_mastered=None, not crash or silently drop the
    entry -- no guessing, same discipline as extract_acf_fields."""
    text = "Mastered Goals:\nName of Skill: A goal with no date filled in\nDate Mastered: \nGoals in Progress:\n"
    result = fields._extract_mastered_goals_with_dates(text)
    assert len(result) == 1
    assert result[0]["name"] == "A goal with no date filled in"
    assert result[0]["date_mastered"] is None


# --- _extract_problem_areas -------------------------------------------------


def test_extract_problem_areas_finds_every_entry_in_document_order():
    text = (
        "Problem Area: Difficulty with transitions between activities\n"
        "As evidenced by: Client engages in tantrum behavior during transitions.\n"
        "Problem Area: Limited functional communication\n"
        "As evidenced by: Client uses gestures instead of vocal requests.\n"
        "Goal Progress:\n"
    )
    result = fields._extract_problem_areas(text)
    assert [p["text"] for p in result] == [
        "Difficulty with transitions between activities",
        "Limited functional communication",
    ]


def test_extract_problem_areas_also_matches_plural_label():
    text = "Problem Areas: Aggression toward peers\nAs evidenced by: hitting during group activities.\n"
    result = fields._extract_problem_areas(text)
    assert result == [{"text": "Aggression toward peers", "offset": text.index("Aggression")}]


def test_extract_problem_areas_returns_empty_list_with_no_label():
    assert fields._extract_problem_areas("No such section anywhere in this document.") == []


def test_extract_problem_areas_skips_a_blank_entry():
    text = "Problem Area: \nProblem Area: Real content here\nGoal Progress:\n"
    result = fields._extract_problem_areas(text)
    assert len(result) == 1
    assert result[0]["text"] == "Real content here"


# --- extract_previous_tp_fields (integration, real PDF) --------------------


def test_extract_previous_tp_fields_runs_end_to_end_against_a_real_pdf():
    """Proves the plumbing (extract_pdf_text -> extract_fields -> the 4
    field extractors) runs cleanly end-to-end against a genuine PDF, not
    just synthetic text -- using this repo's one locally-available real TP.
    Not a substitute for this round's own real Mihad Ali verification
    requirement (see this round's report for that open item); this only
    proves the mechanism works and returns the documented shape."""
    result = extract_previous_tp_fields(str(_SAMPLE_TP_PATH))

    # "acf_score_boxed"/"full_text" added in the comparison-logic round;
    # "report_date_range"/"milestone_grid_images" added in the bugfix round
    # (Fix Round, Previous TP: 3 Real Bugs, Jacob F) -- see this function's
    # own docstring for both. The plumbing round's original 5 keys are
    # otherwise unchanged.
    assert set(result.keys()) == {
        "mastered_goals", "problem_areas", "acf_fields", "acf_score_boxed",
        "auth_dates_requested", "report_date_range", "milestone_grid_images",
        "page_count", "full_text",
    }
    assert result["page_count"] > 0
    assert result["full_text"]  # non-empty real extracted text
    # Fix Round (U3 re-run): page selection is now the ACF section's own
    # page range (union'd with the phrase-search finder) -- this real
    # sample document DOES have an "Assessment of Current Functioning:"
    # section, so this is non-empty even though it has no literal
    # "milestone grid" phrase -- confirms the more robust "acf"-section-
    # based selection is what's actually running, not the old fragile
    # phrase-only finder (which alone would have found nothing here).
    assert result["milestone_grid_images"] != {}
    # Real, confirmed-correct values from this actual document (checked
    # directly against the PDF this round) -- not placeholder assertions.
    assert len(result["mastered_goals"]) == 12
    assert all(g["date_mastered"] is not None for g in result["mastered_goals"])
    assert len(result["problem_areas"]) >= 1
    assert result["acf_fields"]["assessment_date"] == "07/07/2026"
    assert result["acf_fields"]["assessment_tool"] == "ABLLS-R"
    assert result["auth_dates_requested"] == ("08/04/2026", "11/02/2026")


def test_extract_previous_tp_fields_is_identical_whether_called_on_current_or_previous_tp_path():
    """This function has no 'previous TP'-specific logic anywhere in it --
    it's the exact same extraction the CURRENT TP already gets (see its own
    module docstring). Confirms calling it twice on the SAME file (standing
    in for "current TP path" and "previous TP path") returns identical
    results -- i.e. this round's change genuinely didn't alter how the
    CURRENT TP's own fields get extracted anywhere in the pipeline."""
    result_a = extract_previous_tp_fields(str(_SAMPLE_TP_PATH))
    result_b = extract_previous_tp_fields(str(_SAMPLE_TP_PATH))
    assert result_a == result_b
