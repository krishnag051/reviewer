"""Fix Round 6 (Zaith 9-2026-U1): real regression test for QA-MAST-04 and
HF-05's shared _has_any_parent_training_goal gate. The previous round's
"fixed; domain regex broadened" claim was verified only against a
synthetic case, not the real document -- a real staging run against the
actual Zaith document proved it still failed. Root cause: the per-goal-
block "Skill Domain:" scan only ever finds a domain value that appears
AFTER a goal's own "Target Goal:"/"Target Name:" marker (since
_goal_block_starts splits the document AT that marker); this document's
real structure instead puts "Parent/Caregiver Goals:" as a section HEADER
once, governing a whole group of goals with no per-goal "Skill Domain:"
line at all. These tests mirror that exact real quoted structure: a
"Parent/Caregiver Goals:" header on one page, followed by 4 goal blocks
on the pages after it, each "Goal Status: In progress."
"""

from pipeline import fields


def _zaith_like_fields():
    pages = [
        {"page_number": 45, "text": "Parent/Caregiver Goals:\n"},
        {
            "page_number": 46,
            "text": "Target Goal: Parent will implement token economy at home\nGoal Status: In progress\n",
        },
        {
            "page_number": 47,
            "text": "Target Goal: Parent will use planned ignoring for tantrums\nGoal Status: In progress\n",
        },
        {
            "page_number": 48,
            "text": "Target Goal: Parent will implement DTT drills at home\nGoal Status: In progress\n",
        },
        {
            "page_number": 49,
            "text": "Target Goal: Parent will collect ABC data at home\nGoal Status: In progress\n",
        },
    ]
    full_text = "\n".join(p["text"] for p in pages)
    return {"full_text": full_text, "pages": pages}


def test_mast04_passes_when_header_governs_a_goal_group_with_no_per_goal_skill_domain():
    f = _zaith_like_fields()
    result, evidence, page, confidence = fields._check_MAST04({}, f)
    assert result == "pass"
    assert "4" in evidence
    assert page == 46


def test_mast04_still_not_applicable_with_no_parent_content_at_all():
    f = {"full_text": "Target Goal: unrelated goal\nSkill Domain: Communication\nGoal Status: In progress\n"}
    result, evidence, page, confidence = fields._check_MAST04({}, f)
    assert result == "not_applicable"


def test_has_any_parent_training_goal_true_for_header_governed_goal_group():
    f = _zaith_like_fields()
    assert fields._has_any_parent_training_goal(f) is True


def test_has_any_parent_training_goal_still_true_for_per_block_skill_domain_shape():
    """The pre-existing shape (Skill Domain AFTER the goal marker, within
    the same block) must keep working -- this fix adds a new fallback
    tier, it doesn't touch the tiers above it."""
    f = {
        "full_text": "Target Name: Reduce Tantrum\nSkill Domain: Parent Training\nStatus: In Progress\n",
    }
    assert fields._has_any_parent_training_goal(f) is True


def test_has_any_parent_training_goal_still_false_with_no_parent_content():
    f = {"full_text": "Target Goal: unrelated goal\nSkill Domain: Communication\nGoal Status: In progress\n"}
    assert fields._has_any_parent_training_goal(f) is False


def test_goal_blocks_under_header_stops_at_a_real_section_boundary():
    """The header-governs-a-group scan must not run away past the header's
    own real content into an unrelated later section."""
    text = (
        "Parent/Caregiver Goals:\n"
        "Target Goal: Parent goal one\nGoal Status: In progress\n"
        "Mastered Goals:\n"
        "Target Goal: unrelated mastered goal\nGoal Status: Mastered\n"
    )
    blocks = fields._goal_blocks_under_header(text, "Parent/Caregiver Goals")
    assert len(blocks) == 1
    assert "Parent goal one" in blocks[0][1]
