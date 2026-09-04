"""Previous TP round (comparison logic) -- real comparison logic for
QA-MAST-01, QA-MAST-02, QA-RPT-05 (previous-auth-end half), QA-ACF-04, and
QA-PROB-04. Built against Ms. Yachnes's real worked answers for two real
patients (Mihad Ali, Jacob F/"JF") -- per this round's own explicit
instruction, NONE of their real names/dates/goal text/scores are hardcoded
anywhere in this file. Every fixture below is synthetic, invented purely to
exercise the LOGIC each real example demonstrated (e.g. "a mastered goal
dated outside the previous auth window fails", not Mihad Ali's own actual
4/11/26 date).

Two real-call comparisons (QA-ACF-04's narrative-score fallback, QA-PROB-04)
are tested here with `call_tool_json` MOCKED -- proving the wiring/logic is
correct costs nothing; the round's own real end-to-end spend (a live,
un-mocked run against the real Anthropic API) is a separate, explicitly
budgeted step covered in this round's own report, not repeated on every
test run.
"""
import pipeline.previous_tp_comparison as ptc
from pipeline.model_provider import CallTracker
from pipeline.previous_tp_comparison import (
    _compare_acf04,
    _compare_mast01,
    _compare_mast02,
    _compare_prob04,
    _compare_rpt05_previous_auth_end,
    compare_previous_tp_to_tp,
)


def _goal(name: str, date_mastered: str | None, offset: int = 0) -> dict:
    return {"name": name, "date_mastered": date_mastered, "offset": offset}


# --- QA-MAST-01 --------------------------------------------------------------


def _mast01_fields(current_report_end: str, previous_report_start: str) -> tuple[dict, dict]:
    """Helper: the widened window is [previous report start, current
    report end] -- U3 re-run round's own fix. Callers pass just the two
    ends that matter for a given test; the other two dates are filled
    with plausible bracketing values that never themselves matter."""
    current = {"report_date_range": ("01/01/2000", current_report_end)}
    previous = {"report_date_range": (previous_report_start, "12/31/2099")}
    return current, previous


def test_mast01_fails_when_a_current_goal_date_falls_outside_the_widened_window():
    current, previous = _mast01_fields("05/01/2026", "01/01/2026")
    current["mastered_goals"] = [_goal("Goal A", "06/15/2026")]
    result = _compare_mast01(current, previous)
    assert result["result"] == "fail"
    assert "Goal A" in result["evidence"]


def test_mast01_passes_when_every_current_goal_date_falls_within_the_widened_window():
    current, previous = _mast01_fields("05/01/2026", "01/01/2026")
    current["mastered_goals"] = [_goal("Goal A", "03/01/2026"), _goal("Goal B", "04/15/2026")]
    assert _compare_mast01(current, previous)["result"] == "pass"


def test_mast01_uses_the_widened_elapsed_window_not_the_previous_tps_own_narrow_report_window():
    """Fix Round (U3 re-run) -- REAL BUG FOUND AND FIXED: confirmed on the
    real Jacob Freund pair that the window must span from the PREVIOUS
    TP's own report START through the CURRENT TP's own report END, not
    just the previous TP's own narrow ~2-week report window alone (the
    prior round's fix, which regressed on a real cumulative Mastered
    Goals list spanning many months). A goal dated well after the
    previous TP's own report window ends, but still within the current
    TP's own report window, must PASS."""
    current = {
        "mastered_goals": [_goal("Goal A", "08/10/2026")],  # outside the previous TP's OWN narrow window
        "report_date_range": ("08/10/2026", "08/21/2026"),
    }
    previous = {"report_date_range": ("02/10/2026", "02/26/2026")}  # Goal A's date is OUTSIDE this alone
    result = _compare_mast01(current, previous)
    assert result["result"] == "pass"  # ...but INSIDE the widened [02/10/2026, 08/21/2026] window


def test_mast01_still_does_not_use_authorization_dates_requested():
    """The previous round's own wrong working assumption (comparing
    against 'Authorization Dates Requested' instead of 'Date of Current
    Report') must stay fixed -- a present-but-irrelevant
    auth_dates_requested key must not affect the result."""
    current, previous = _mast01_fields("05/01/2026", "01/01/2026")
    current["mastered_goals"] = [_goal("Goal A", "03/01/2026")]
    previous["auth_dates_requested"] = ("09/01/2026", "03/01/2027")  # would fail Goal A if read by mistake
    result = _compare_mast01(current, previous)
    assert result["result"] == "pass"


def test_mast01_not_checkable_with_no_current_mastered_goals():
    current, previous = _mast01_fields("05/01/2026", "01/01/2026")
    current["mastered_goals"] = []
    assert _compare_mast01(current, previous)["result"] == "not_checkable"


def test_mast01_not_checkable_with_no_previous_report_range():
    current = {"mastered_goals": [_goal("Goal A", "03/01/2026")], "report_date_range": ("01/01/2026", "05/01/2026")}
    assert _compare_mast01(current, {"report_date_range": None})["result"] == "not_checkable"


def test_mast01_not_checkable_with_no_current_report_range():
    previous = {"report_date_range": ("01/01/2026", "05/01/2026")}
    current = {"mastered_goals": [_goal("Goal A", "03/01/2026")], "report_date_range": None}
    assert _compare_mast01(current, previous)["result"] == "not_checkable"


def test_mast01_ignores_a_goal_with_no_parseable_date_rather_than_crashing():
    current, previous = _mast01_fields("05/01/2026", "01/01/2026")
    current["mastered_goals"] = [_goal("Goal A", None), _goal("Goal B", "03/01/2026")]
    result = _compare_mast01(current, previous)
    assert result["result"] == "pass"  # Goal B is the only checkable one, and it's in range


# --- QA-MAST-02 --------------------------------------------------------------


def test_mast02_fails_on_a_real_exact_duplicate_after_normalization():
    current = {"mastered_goals": [_goal("  Client will mand for a preferred item.  ", "06/01/2026")]}
    previous = {"mastered_goals": [_goal("Client will mand for a preferred item.", "04/01/2026")]}
    result = _compare_mast02(current, previous)
    assert result["result"] == "fail"
    assert "mand for a preferred item" in result["evidence"]


def test_mast02_passes_with_no_overlap():
    current = {"mastered_goals": [_goal("Goal X", "06/01/2026")]}
    previous = {"mastered_goals": [_goal("Goal Y", "04/01/2026")]}
    assert _compare_mast02(current, previous)["result"] == "pass"


def test_mast02_is_not_fuzzy_only_formatting_normalized():
    """_normalize_goal_text collapses whitespace/case/trailing punctuation
    only -- genuinely different wording of the same underlying goal must
    NOT be flagged (that's judgment-layer territory, not this deterministic
    check's job, same discipline QA-GIP-05 already established)."""
    current = {"mastered_goals": [_goal("Client will point to a requested item", "06/01/2026")]}
    previous = {"mastered_goals": [_goal("Client requests items by pointing", "04/01/2026")]}
    assert _compare_mast02(current, previous)["result"] == "pass"


def test_mast02_not_checkable_with_no_previous_mastered_goals():
    current = {"mastered_goals": [_goal("Goal X", "06/01/2026")]}
    assert _compare_mast02(current, {"mastered_goals": []})["result"] == "not_checkable"


# --- QA-RPT-05 (previous-auth-end half) --------------------------------------


def test_rpt05_previous_half_passes_when_directly_adjacent():
    current = {"auth_dates_requested": ("08/06/2026", "02/06/2027")}
    previous = {"auth_dates_requested": ("05/01/2026", "08/05/2026")}
    result = _compare_rpt05_previous_auth_end(current, previous)
    assert result["result"] == "pass"


def test_rpt05_previous_half_fails_on_a_real_gap():
    current = {"auth_dates_requested": ("10/16/2026", "04/16/2027")}
    previous = {"auth_dates_requested": ("07/01/2026", "09/02/2026")}
    result = _compare_rpt05_previous_auth_end(current, previous)
    assert result["result"] == "fail"
    assert "gap" in result["evidence"]


def test_rpt05_previous_half_fails_on_overlap():
    current = {"auth_dates_requested": ("08/01/2026", "02/01/2027")}
    previous = {"auth_dates_requested": ("05/01/2026", "08/10/2026")}  # current starts BEFORE previous ends
    result = _compare_rpt05_previous_auth_end(current, previous)
    assert result["result"] == "fail"
    assert "overlap" in result["evidence"]


def test_rpt05_previous_half_not_checkable_with_missing_dates():
    assert _compare_rpt05_previous_auth_end({"auth_dates_requested": None}, {"auth_dates_requested": None})["result"] == "not_checkable"


# --- QA-ACF-04 ----------------------------------------------------------------


def test_acf04_fails_on_a_real_score_drop_using_only_boxed_extraction_zero_model_calls():
    current = {"acf_score_boxed": 53.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "..."}
    previous = {"acf_score_boxed": 55.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "..."}
    tracker = CallTracker(max_calls=0)  # zero calls allowed -- proves no model call is made when both are boxed
    result = _compare_acf04(current, previous, tracker=tracker, model_override=None)
    assert result["result"] == "fail"
    assert tracker.count == 0


def test_acf04_passes_when_score_does_not_drop():
    current = {"acf_score_boxed": 60.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "..."}
    previous = {"acf_score_boxed": 55.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "..."}
    result = _compare_acf04(current, previous, tracker=CallTracker(max_calls=0), model_override=None)
    assert result["result"] == "pass"


def test_acf04_falls_back_to_judgment_when_boxed_extraction_is_missing(monkeypatch):
    """Ms. Yachnes's own real flagged gap: a score stated in narrative
    prose, not a boxed field. Mocked call_tool_json -- proves the fallback
    IS reached and its result IS used, at zero real spend for this test."""
    def fake_call_tool_json(**kwargs):
        assert kwargs["call_reason"] == "acf04_narrative_score"
        return {"found": True, "score": 42.0}

    monkeypatch.setattr(ptc, "call_tool_json", fake_call_tool_json)
    current = {"acf_score_boxed": None, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "scored a 42"}
    previous = {"acf_score_boxed": 40.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "boxed: 40"}
    result = _compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"
    assert "narrative (judgment)" in result["evidence"]
    assert result["confidence"] == 0.7  # lower confidence than a fully-boxed comparison, confirms the bug fix


def test_acf04_not_checkable_when_narrative_fallback_also_finds_nothing(monkeypatch):
    monkeypatch.setattr(ptc, "call_tool_json", lambda **kwargs: {"found": False, "score": None})
    current = {"acf_score_boxed": None, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "no score here"}
    previous = {"acf_score_boxed": 40.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "boxed: 40"}
    result = _compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "not_checkable"


def test_acf04_never_guesses_a_boxed_regex_false_positive_on_an_unrelated_number():
    """Confirms extract_acf_score_boxed's real section-scoping -- a number
    elsewhere in the document (e.g. an hours value) must not be mistaken
    for the assessment score."""
    from pipeline.fields import extract_acf_score_boxed
    text = "Hours Requesting: 15\nAssessment of Current Functioning:\nAssessment Date: 08/01/2026\nGoal Progress:\n"
    assert extract_acf_score_boxed({"full_text": text}) is None


# --- QA-PROB-04 (no confirmed real example yet) ------------------------------


def _tp_text_with_evidenced_by(rubric: str, evidenced_by: str) -> str:
    """Builds real document text shaped like the actual TP grammar --
    'Problem Area(s): <rubric>' followed by 'As evidenced by: <finding>' --
    so these tests exercise the REAL _extract_evidenced_by_blocks path
    (Fix Round, Bug 3), not the old, wrong `problem_areas` field."""
    return f"Problem Area: {rubric}\nAs evidenced by: {evidenced_by}\nGoal Progress:\n"


def test_prob04_reads_evidenced_by_text_not_the_rubric_template(monkeypatch):
    """Fix Round, Bug 3 -- REAL BUG FOUND AND FIXED: confirmed on real
    documents (Jacob Freund) that the fixed rubric/template text (identical
    for every patient by design) was being compared instead of the real,
    patient-specific 'As evidenced by:' findings. This proves the fix:
    IDENTICAL rubric text but DIFFERENT evidenced-by findings must be sent
    to the model as different content (captured via the model's own mocked
    response reflecting that difference), not silently flattened to
    'identical' because the rubric happened to match."""
    captured_prompts = []

    def fake_call_tool_json(**kwargs):
        captured_prompts.append(kwargs["prompt_text"])
        return {
            "new_or_changed_content": "improved since last auth (in progress)",
            "current_explains_limited_services": False, "reasoning": "different progress notes",
        }

    monkeypatch.setattr(ptc, "call_tool_json", fake_call_tool_json)
    same_rubric = "Deficits in social-emotional reciprocity, ranging, for example, from abnormal social approach."
    current = {"full_text": _tp_text_with_evidenced_by(same_rubric, "Jacob struggles to approach peers - improved since last auth (in progress)")}
    previous = {"full_text": _tp_text_with_evidenced_by(same_rubric, "Jacob struggles to approach peers")}
    result = _compare_prob04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"
    # The rubric text (identical on both) must NOT appear in the prompt --
    # only the "As evidenced by:" findings should reach the model.
    assert "improved since last auth" in captured_prompts[0]
    assert same_rubric not in captured_prompts[0]


def test_prob04_passes_when_genuinely_different(monkeypatch):
    monkeypatch.setattr(
        ptc, "call_tool_json",
        lambda **kwargs: {"new_or_changed_content": "different findings entirely", "current_explains_limited_services": False, "reasoning": "different"},
    )
    current = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers")}
    previous = {"full_text": _tp_text_with_evidenced_by("rubric", "Difficulty with transitions")}
    result = _compare_prob04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"


def test_prob04_fails_when_identical_and_unexplained(monkeypatch):
    monkeypatch.setattr(
        ptc, "call_tool_json",
        lambda **kwargs: {"new_or_changed_content": "", "current_explains_limited_services": False, "reasoning": "same"},
    )
    current = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers")}
    previous = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers")}
    result = _compare_prob04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "fail"
    assert "still awaiting Ms. Yachnes's confirmed real answer" in result["evidence"]


def test_prob04_passes_when_identical_but_explained(monkeypatch):
    monkeypatch.setattr(
        ptc, "call_tool_json",
        lambda **kwargs: {"new_or_changed_content": "", "current_explains_limited_services": True, "reasoning": "limited services"},
    )
    current = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers -- unchanged, very limited services this period.")}
    previous = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers")}
    result = _compare_prob04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"


def test_prob04_cannot_self_contradict_reasoning_naming_new_content_while_claiming_identical(monkeypatch):
    """Fix Round (U3 re-run) -- REAL BUG FOUND AND FIXED: confirmed live,
    the model's own free-text reasoning named real added content while a
    separate boolean still claimed 'identical' -- this is the actual
    contradiction from the real U3 run, reproduced directly: even if the
    model's `reasoning` prose mentions progress notes, the result must
    still be NOT identical whenever `new_or_changed_content` is non-empty,
    because that field -- not reasoning text -- is what the code branches
    on now."""
    monkeypatch.setattr(
        ptc, "call_tool_json",
        lambda **kwargs: {
            "new_or_changed_content": "progress notes added",
            "current_explains_limited_services": False,
            "reasoning": "Findings are largely the same overall category, with progress notes added.",
        },
    )
    current = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers, improved, in progress")}
    previous = {"full_text": _tp_text_with_evidenced_by("rubric", "Aggression toward peers")}
    result = _compare_prob04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"  # NOT identical -> passes, consistent with its own evidence now


def test_prob04_not_checkable_with_no_evidenced_by_on_either_document():
    assert _compare_prob04({"full_text": "nothing here"}, {"full_text": "nothing here"}, tracker=CallTracker(max_calls=5), model_override=None)["result"] == "not_checkable"


# --- top-level entry point ----------------------------------------------------


def test_compare_previous_tp_to_tp_returns_all_5_rule_ids(monkeypatch):
    monkeypatch.setattr(
        ptc, "call_tool_json",
        lambda **kwargs: (
            {"found": True, "score": 50.0} if kwargs["call_reason"] == "acf04_narrative_score"
            else {"new_or_changed_content": "different", "current_explains_limited_services": False, "reasoning": "x"}
        ),
    )
    current = {
        "mastered_goals": [_goal("Goal A", "03/01/2026")],
        "acf_score_boxed": None, "acf_fields": {"assessment_tool": "ABLLS-R"},
        "full_text": _tp_text_with_evidenced_by("rubric", "A"),
        "milestone_grid_images": {},
        "auth_dates_requested": ("08/06/2026", "02/06/2027"),
        "report_date_range": ("01/01/2026", "03/01/2026"),
    }
    previous = {
        "mastered_goals": [_goal("Goal B", "04/01/2026")],
        "acf_score_boxed": 48.0, "acf_fields": {"assessment_tool": "ABLLS-R"},
        "full_text": _tp_text_with_evidenced_by("rubric", "B"),
        "milestone_grid_images": {},
        "auth_dates_requested": ("01/01/2026", "08/05/2026"),
        "report_date_range": ("01/01/2026", "03/01/2026"),
    }
    result = compare_previous_tp_to_tp(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert set(result.keys()) == {"QA-MAST-01", "QA-MAST-02", "QA-RPT-05", "QA-ACF-04", "QA-PROB-04"}
