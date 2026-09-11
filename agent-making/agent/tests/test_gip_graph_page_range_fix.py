"""Fix Round (2026-09-11), items 20/21/24 -- REAL BUG FOUND AND FIXED,
confirmed against the real Daylyn Holland TP: _gip_graph_page_range only
ever found ONE page (15) in a real 45-page document with ~20 goal blocks,
because it only searched for the literal substring "Graph:" -- this
document's "Target Goal:" (skill-acquisition) blocks have no such text
label at all, even though each one has its own embedded graph image.

That single detection gap explained three separate complaints at once:
- item 20: QA-GIP-32 effectively only ever "saw" page 15's graph.
- item 21: QA-GIP-29 false-negatived ("no graph") on every other goal,
  because the judge was never given a rendered image of their page.
- item 24: parent-training goals (goal blocks like any other) were
  equally affected, with no separate fix needed once every goal block's
  own page is covered.
"""
from pipeline import fields


def _fields(full_text: str, n_pages: int) -> dict:
    # One goal per page, matching the real document's own layout.
    lines = full_text.split("\n")
    pages = [{"page_number": i + 1, "text": ""} for i in range(n_pages)]
    return {"pages": pages, "full_text": full_text}


def test_gip_graph_page_range_covers_a_goal_with_no_literal_graph_label():
    """The real, confirmed shape: a 'Target Goal:' block with no 'Graph:'
    text anywhere in it must still have its own page included."""
    text = (
        "Target Goal: goal one with a Graph: label\n"
        + "\n" * 5000  # push the second goal onto a later page via offset math
        + "Target Goal: goal two with NO graph label at all\n"
    )
    pages = [
        {"page_number": 1, "text": "Target Goal: goal one with a Graph: label\n"},
        {"page_number": 2, "text": "Target Goal: goal two with NO graph label at all\n"},
    ]
    full_text = "\n".join(p["text"] for p in pages)
    f = {"pages": pages, "full_text": full_text}
    result = fields._gip_graph_page_range(f)
    assert result == {1, 2}, result


def test_gip_graph_page_range_still_includes_a_literal_graph_label_page():
    pages = [{"page_number": 1, "text": "Some preamble.\nGraph:\nmore text\n"}]
    full_text = pages[0]["text"]
    f = {"pages": pages, "full_text": full_text}
    result = fields._gip_graph_page_range(f)
    assert 1 in result


def test_gip_graph_page_range_covers_every_goal_across_many_pages():
    """Direct regression for the real bug: many goal blocks across many
    pages, none with a 'Graph:' label, must all be covered -- not just
    the first or a hardcoded subset."""
    pages = [
        {"page_number": p, "text": f"Target Goal: goal number {p}\nGoal Status: In progress\n"}
        for p in range(1, 15)
    ]
    full_text = "\n".join(p["text"] for p in pages)
    f = {"pages": pages, "full_text": full_text}
    result = fields._gip_graph_page_range(f)
    assert result == set(range(1, 15)), result


def test_gip_graph_page_range_covers_parent_training_goals_too():
    """Item 24: a parent-training goal is a goal block like any other,
    tagged by its own Skill Domain -- no separate logic needed."""
    pages = [{
        "page_number": 5,
        "text": "Skill Domain: Parent Training\nTarget Goal: Parent will implement the plan\nGoal Status: In progress\n",
    }]
    full_text = pages[0]["text"]
    f = {"pages": pages, "full_text": full_text}
    result = fields._gip_graph_page_range(f)
    assert 5 in result
