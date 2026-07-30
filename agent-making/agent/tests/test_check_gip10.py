"""Coverage for fields._check_GIP10 -- QA-GIP-10 converted from judgment to
deterministic (2026-07-28 round, item 1): "sampling method consistent across
every goal" is a uniqueness check over a code-extractable list of per-goal
field values, not a holistic reasoning task. See _check_GIP10's own
docstring in pipeline/fields.py for the full rationale, and the standing
regression suite (test_regression_ground_truth.py) for the same rule
verified live against Reeda's and Charny's real documents.
"""
from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


GOOD_GOAL = "Target Goal: X will do Y\nBaseline: 10%\nMastery Criteria: 85%\nSampling Method: Percent Correct\n"


def test_pass_when_all_goals_consistent():
    result, evidence, page, confidence = fields._check_GIP10(
        {}, _fields(GOOD_GOAL + GOOD_GOAL)
    )
    assert result == "pass"


def test_fail_on_broken_merge_field_page_value():
    """The confirmed real-world artifact: a Sampling Method field literally
    reading 'Page' instead of an actual method name."""
    bad_goal = "Target Goal: Z will do W\nBaseline: 10%\nMastery Criteria: 85%\nSampling Method: Page\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(GOOD_GOAL, bad_goal))
    assert result == "fail"
    assert page == 2
    assert "'Page'" in evidence


def test_fail_on_spelling_variant_not_caught_by_a_majority_read():
    """A single-character typo ('Precent correct') or a wording variant
    ('percentage correct') would look 'close enough' to a holistic reader
    averaging over many consistent goals -- the exact-match-or-whitelist
    check must not let either slide."""
    typo_goal = "Target Goal: Z will do W\nBaseline: 10%\nMastery Criteria: 85%\nSampling Method: Precent correct\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(GOOD_GOAL, typo_goal))
    assert result == "fail"
    assert "Precent correct" in evidence


def test_fail_on_blank_mastery_criteria_with_otherwise_valid_sampling_method():
    """Confirmed on Charny's real TP: a Frequency-sampled goal with a
    genuinely blank Mastery Criteria field."""
    blank_mc_goal = "Target Goal: Z will do W\nBaseline: 2 occurrences\nMastery Criteria: \nSampling Method: Frequency\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(GOOD_GOAL, blank_mc_goal))
    assert result == "fail"
    assert "Mastery Criteria is blank" in evidence


def test_blank_field_regex_does_not_bleed_into_the_next_line():
    """Regression for the exact bug found live while building this checker:
    `\\s*` after the label matches newlines too, so on a genuinely blank
    field it kept matching through the newline into the next line's own
    text -- making a blank Mastery Criteria look non-blank because it
    'consumed' the following 'Sampling Method: Frequency' line as its own
    value. Must use `[ \\t]*` (same-line only) instead."""
    goal = "Target Goal: Z will do W\nBaseline: 2 occurrences\nMastery Criteria: \nSampling Method: Frequency\nCurrent Data: 3 Frequency\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(goal))
    assert result == "fail"
    assert "Mastery Criteria is blank" in evidence
    # if the bug were present, evidence would instead describe "Sampling
    # Method 'Sampling Method: Frequency'" as the (wrongly non-blank) value
    assert "Sampling Method: Frequency" not in evidence.split("Sampling Method:")[-1]


def test_goal_spanning_a_page_boundary_is_not_a_false_positive():
    """Confirmed on Charny's real TP: a goal's Target Goal line sits at the
    bottom of one page while its Mastery Criteria/Sampling Method print at
    the top of the next page. Splitting on full_text (not per-page text)
    must still see this as one complete, consistent goal."""
    page1 = "Target Goal: Z will do W\nBaseline: 10%\n"
    page2 = "Mastery Criteria: 85%\nSampling Method: Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(page1, page2))
    assert result == "pass"


def test_multiple_problems_return_the_list_form_with_per_page_detail():
    bad1 = "Target Goal: A\nBaseline: 10%\nMastery Criteria: 85%\nSampling Method: Page\n"
    bad2 = "Target Goal: B\nBaseline: 10%\nMastery Criteria: 85%\nSampling Method: percentage correct\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(GOOD_GOAL, bad1, bad2))
    assert result == "fail"
    assert page is None  # top-level page is null when using the {page, detail} list form
    assert isinstance(evidence, list)
    assert {e["page"] for e in evidence} == {2, 3}


def test_not_checkable_when_no_goal_blocks_found():
    result, evidence, page, confidence = fields._check_GIP10({}, _fields("Some unrelated page text."))
    assert result == "not_checkable"


def test_not_checkable_when_target_goal_present_but_no_sampling_method_anywhere():
    result, evidence, page, confidence = fields._check_GIP10(
        {}, _fields("Target Goal: Z will do W\nGoal Status: In progress\n")
    )
    assert result == "not_checkable"


def test_gip10_registered_as_deterministic_not_judgment():
    assert "QA-GIP-10" in fields.DET_CHECKS
    assert fields.DET_CHECKS["QA-GIP-10"] is fields._check_GIP10
