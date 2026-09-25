"""Fix Round 11: real, literal pypdf-extracted text for mc_current.pdf's
12 confirmed target pages (52, 55, 56, 57, 58, 59, 60, 61, 63, 64, 65, 67
-- each a real goal block naming mand/tact/intraverbal), pasted directly
from the actual document for the first time (prior rounds only had page
numbers and a couple of quoted goal names). This closes the honest gap
Round 10 disclosed: it could reason about Pass 1's mechanism but not
byte-verify it against this document's real text.

Result: Pass 1 (gip12_verbal_operant_candidate_pages) finds all 12 pages
correctly, with ZERO code changes needed. Specifically confirmed against
the three real shapes this round's own report called out as risks:

1. Pages 55/60: the operant term is on a trailing 'Cumulative Goal:'
   line, not in the 'Target Goal:' sentence itself. Already handled --
   Pass 1 scans a goal block's FULL text (from one 'Target Goal:'/
   'Target Name:' marker to the next), not just the first line, so the
   trailing line is inside the same block and gets scanned too.
2. Page 63: a real multi-page goal block whose own 'Target Goal:' starts
   on page 62, with page 63's own extracted text starting mid-sentence
   as the TAIL of that page-62 goal, followed by a SECOND, separate
   'Target Goal:' that starts fresh on page 63. Already handled --
   matches are attributed by each match's own real offset
   (_page_for_offset(fields, starts[i] + m.start())), not the block's
   start, so page 62's own "mand" mentions resolve to page 62 and page
   63's own "tact" goal resolves to page 63, correctly.
3. Confirmed real fact: none of these 12 pages actually use a
   'Program Goal:' marker (Round 8 added recognition for that marker
   expecting it to matter here; it doesn't, on this document -- harmless
   since it's additive, but the real gap these 12 pages needed was #1/#2
   above, not that marker).
"""

from pipeline import fields


def _mc_current_pages():
    return [
        {"page_number": 52, "text": (
            "Target Goal:By 12/10/2026, Matthielly, when presented with familiar songs, animal sounds, routine phrases, or common fill-in\n"
            "statements, will complete 10 different intraverbal fill-ins without visual cues with 80% accuracy across 3 consecutive sessions.\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 55, "text": (
            "Target Goal:Client will respond to hearing her own name by turning toward the adult when an adult sitting next to and infront of\n"
            "of her to increase communication skills through shaping.\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/02/2025 - Prompt will be added to ensure mastery\n"
            "...\n"
            "Cumulative Goal: Mand\n"
        )},
        {"page_number": 56, "text": (
            "Target Goal:Client will mand using a single word mand training to increase communication skills.\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/02/2025- Prompt will be added to ensure mastery\n"
        )},
        {"page_number": 57, "text": (
            "Target Goal:Matthielly, when presented with a nonpreferred task, transition, or difficult demand, will mand for help, break, or all\n"
            "done instead of engaging in problem behavior\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 58, "text": (
            "Target Goal:Matthielly, when the MO for continuation or assistance is present during preferred activities, will independently mand\n"
            "for 5 different actions, such as open, push, help, go, or turn on\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 59, "text": (
            "Target Goal:Matthielly, when engaged with a preferred activity and a needed item is missing, will independently mand for the\n"
            "missing item using her current communication modality for 10 different missing items\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 60, "text": (
            "Target Goal:Matthielly, when preferred items or activities are present and motivation is observed, will emit 10 different two-word\n"
            "or longer mands\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
            "...\n"
            "Cumulative Goal: Tact\n"
        )},
        {"page_number": 61, "text": (
            "Target Goal:Client will tact 4 family members in her home when asked \"who is that?\" in order to increase communication skills\n"
            "using prompt fading.\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/02/2025\n"
        )},
        {"page_number": 62, "text": (
            "Target Goal:Matthielly will independently mand across settings and people, using her current modality, when a preferred item "
            "or activity is present or when help is needed. The BT will\n"
            "fade prompts, and reinforce independent mands immediately. Practice will also be programmed across different items, people, and\n"
        )},
        {"page_number": 63, "text": (
            "settings so mastery reflects generalized functional communication rather than responding only under specific treatment conditions.\n"
            "\n"
            "Target Goal:Matthielly, when presented with live actions, pictures, or short videos and asked \"What is he/she doing?\", will\n"
            "independently tact 10 actions\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 64, "text": (
            "Target Goal:Matthielly, when presented with common 2D or 3D items from her natural environment and the tact frame \"What is\n"
            "it?\" or \"This is…,\" will independently tact 25 common items\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/11/2026\n"
        )},
        {"page_number": 65, "text": (
            "Target Goal:Client will tact 10 common objects/items and people from a book when asked by a behavior therapist in order to\n"
            "increase communication skills using prompt fading.\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/02/2025\n"
        )},
        {"page_number": 67, "text": (
            "Target Goal:Matthielly, when presented with pictures or live scenes containing an item and action, will emit 25 two-component\n"
            "noun-verb or verb-noun tacts\n"
            "Goal Status: In progress\n"
            "Date Initiated: 06/10/2026\n"
        )},
    ]


def _fields():
    pages = _mc_current_pages()
    return {"full_text": "\n".join(p["text"] for p in pages), "pages": pages}


def test_pass1_finds_all_12_real_confirmed_target_pages():
    hits = fields.gip12_verbal_operant_candidate_pages(_fields())
    found = {h[0] for h in hits}
    target = {52, 55, 56, 57, 58, 59, 60, 61, 63, 64, 65, 67}
    assert target <= found, f"missing: {sorted(target - found)}"


def test_pass1_matches_the_trailing_cumulative_goal_line_on_page_55():
    """Page 55's 'Target Goal:' sentence itself has no literal operant
    word -- only the trailing 'Cumulative Goal: Mand' line does."""
    hits = fields.gip12_verbal_operant_candidate_pages(_fields())
    page_55_terms = {h[2] for h in hits if h[0] == 55}
    assert "mand" in page_55_terms


def test_pass1_matches_the_trailing_cumulative_goal_line_on_page_60():
    hits = fields.gip12_verbal_operant_candidate_pages(_fields())
    page_60_terms = {h[2] for h in hits if h[0] == 60}
    assert "tact" in page_60_terms


def test_pass1_attributes_page_63s_own_goal_to_page_63_not_62():
    """The real multi-page block case: page 62's own 'Target Goal:'
    (mand) mentions must resolve to page 62, and page 63's own separate
    'Target Goal:' (tact) must resolve to page 63 -- not both collapsed
    onto whichever page the enclosing block happens to start on."""
    hits = fields.gip12_verbal_operant_candidate_pages(_fields())
    assert any(h[0] == 62 and h[2] == "mand" for h in hits)
    assert any(h[0] == 63 and h[2] == "tact" for h in hits)
