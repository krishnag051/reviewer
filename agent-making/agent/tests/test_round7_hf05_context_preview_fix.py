"""Fix Round 7 (mc_current.pdf real bug): HF-05's own Uncertain evidence
was falling through to the generic "no automated context available"
message even on a document that plainly has real Parent/Caregiver
Training goals (confirmed: QA-MAST-04's own checker found 3 of them on
the same document, page 71). Root cause: _goal_context_preview's
parent_training_only branch only ever did the narrower per-block
'Skill Domain:' scan, not the header-governs-a-group fallback
_check_MAST04/_has_any_parent_training_goal already use. Fixed by
routing parent_training_only through the new shared
_find_parent_training_goal_blocks collector instead.
"""

from pipeline import fields
from pipeline import _stabilized_uncertain_finding


def _mc_current_like_fields():
    text = (
        "Parent/Caregiver Involvement:\n"
        "Target Goal: Parent will make eye contact with the client and smile/vocal\n"
        "Goal Status: In progress\n"
        "Target Goal: Parent will label desired items/actions 2 times while modeling\n"
        "Goal Status: In progress\n"
        "Target Goal: Parents will practice using 2 movement cards with the client\n"
        "Goal Status: In progress\n"
    )
    return {"full_text": text, "pages": [{"page_number": 71, "text": text}]}


def test_goal_context_preview_finds_header_governed_parent_training_goals():
    f = _mc_current_like_fields()
    preview = fields._goal_context_preview(f, parent_training_only=True)
    assert "Parent will make eye contact with the client and smile/vocal" in preview
    assert "Parent will label desired items/actions 2 times while modeling" in preview
    assert "Parents will practice using 2 movement cards with the client" in preview
    assert "page 71" in preview


def test_goal_context_preview_states_the_real_hf05_criterion():
    f = _mc_current_like_fields()
    preview = fields._goal_context_preview(f, parent_training_only=True)
    assert "fewer than 3 real data points" in preview
    assert "graph" in preview


def test_hf05_stabilized_finding_is_non_generic_when_real_goals_exist():
    f = _mc_current_like_fields()
    finding = _stabilized_uncertain_finding("HF-05", f)
    assert finding["result"] == "uncertain"
    assert "No additional automated context is available for this item yet." not in finding["evidence"]
    assert "Parent will make eye contact" in finding["evidence"]


def test_goal_context_preview_still_empty_with_no_parent_training_goals():
    text = "Target Goal: unrelated goal\nSkill Domain: Communication\nGoal Status: In progress\n"
    f = {"full_text": text, "pages": [{"page_number": 1, "text": text}]}
    assert fields._goal_context_preview(f, parent_training_only=True) == ""


def test_goal_context_preview_non_parent_training_mode_unaffected():
    """The None/general-purpose mode (used by every OTHER stabilized rule)
    must behave exactly as before -- this fix is additive to the
    parent_training_only branch only."""
    text = "Target Goal: some goal\nBaseline: 5\nStatus: In progress\n"
    f = {"full_text": text, "pages": [{"page_number": 3, "text": text}]}
    preview = fields._goal_context_preview(f)
    assert "some goal" in preview
    assert "Real question for HF-05" not in preview
