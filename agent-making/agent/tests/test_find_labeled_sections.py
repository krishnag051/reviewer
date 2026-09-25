"""Fix Round (Full Rule-by-Rule Fix List, Part A) -- dedicated test suite
for the shared previous-TP field extractor, fields.py::find_labeled_sections,
independent of any single rule. This is the one primitive QA-RPT-05,
QA-MAST-01/02/03, and QA-PROB-04 now all migrate onto instead of each
maintaining its own hand-written "go find this label" logic -- every real
bug that class of duplicate logic produced (a line-break splitting a label,
a guard that couldn't tell "confirmed empty" from "never found", a table
label covering several entries at once) is covered here explicitly, once,
against synthetic fixtures -- not re-derived per rule.

Zero real API/model calls -- pure regex over synthetic text.
"""
from pipeline.fields import find_labeled_sections


# --- whitespace/line-break tolerance -----------------------------------------


def test_label_split_across_a_line_break_is_found():
    """Real bug shape: 'Authorization Dates\\nRequested:' (old.pdf) and
    'Date of\\nMastery:' (mc_current.pdf) -- a label whose own words land on
    separate lines after PDF text extraction must still be found."""
    text = "Authorization Dates\nRequested: 06/19/2026 to 09/17/2026"
    sections = find_labeled_sections(text, "Authorization Dates Requested")
    assert len(sections) == 1
    assert sections[0]["text"].startswith("06/19/2026")


def test_label_on_one_line_still_matches_identically():
    """Purely additive: a label that already appears on one line,
    single-spaced, must match exactly as before."""
    text = "Authorization Dates Requested: 09/18/2026 to 12/18/2026"
    sections = find_labeled_sections(text, "Authorization Dates Requested")
    assert len(sections) == 1
    assert sections[0]["text"].startswith("09/18/2026")


def test_label_split_by_irregular_whitespace_not_just_a_single_newline():
    text = "Date  of  \n  Mastery:   8/19/2026"
    sections = find_labeled_sections(text, "Date of Mastery")
    assert len(sections) == 1
    assert sections[0]["text"].startswith("8/19/2026")


def test_offset_points_at_real_content_not_the_whitespace_before_it():
    text = "Problem Area:   Aggression toward peers\n"
    sections = find_labeled_sections(text, "Problem Area")
    assert sections[0]["offset"] == text.index("Aggression")


# --- confirmed-empty vs. never-found -----------------------------------------


def test_confirmed_empty_section_returns_a_non_empty_list_with_blank_text():
    """The exact real bug that broke QA-MAST-02: a document whose
    'Mastered Goals:' section is found, but genuinely has nothing under
    it, must be distinguishable from a document where the label never
    appears at all. Both extract to an empty NAME list downstream, but
    only one of them should return [] from this primitive."""
    text = "Mastered Goals:\nAdditonal Notes: No goals were mastered during this reporting period.\nGoals in Progress:\n"
    sections = find_labeled_sections(text, "Mastered Goals")
    assert len(sections) == 1  # found -- not []
    assert sections[0]["text"].strip()  # has real content (the rationale)


def test_section_with_only_whitespace_after_the_label_is_still_found():
    text = "Mastered Goals:\n\nGoals in Progress:\n"
    sections = find_labeled_sections(text, "Mastered Goals")
    assert len(sections) == 1  # found, confirmed empty
    assert sections[0]["text"].strip() == ""


def test_label_never_found_returns_empty_list():
    text = "This document has no such section anywhere in it."
    assert find_labeled_sections(text, "Mastered Goals") == []


def test_never_found_and_confirmed_empty_are_distinguishable_by_callers():
    """The actual real fix QA-MAST-02 needed: a caller checks `bool(sections)`
    to know whether the label was found at all, entirely independent of
    whether any entry's own text has real content."""
    never_found = find_labeled_sections("Nothing relevant here.", "Mastered Goals")
    confirmed_empty = find_labeled_sections("Mastered Goals:\n\nGoals in Progress:\n", "Mastered Goals")
    assert bool(never_found) is False
    assert bool(confirmed_empty) is True


# --- multiple real occurrences of the same label -----------------------------


def test_two_occurrences_of_the_same_label_are_both_returned():
    """Real document shape: 'Mastered Goals:' appears once under Skill
    Acquisition and once under Parent/Caregiver -- both must be returned,
    not just the first (the exact bug MAST-01/02 had before this
    extractor existed: a bare re.search only ever found the first). The
    second occurrence's own "text" is whatever real content follows it
    up to the next real boundary this primitive knows about -- deciding
    whether THAT content itself means "confirmed empty" (e.g. it's just
    the next field's own bare label, with nothing real under this one)
    is a caller-side concern (see _check_MAST03's own bare-label check),
    not something this primitive hardcodes.
    """
    text = (
        "Mastered Goals:\nClient will mand for a preferred item. Date of\nMastery: 8/19/2026\n"
        "Goals in Progress:\nSkill Domain: Communication Domain\n"
        "Parent/Caregiver Involvement:\nMastered Goals:\nParent/Caregiver Goals:\n"
    )
    sections = find_labeled_sections(text, "Mastered Goals")
    assert len(sections) == 2
    assert "Client will mand" in sections[0]["text"]
    assert sections[1]["text"].strip() == "Parent/Caregiver Goals:"


def test_three_occurrences_all_returned_in_document_order():
    text = "Mastered Goals:\nA\nGoals in Progress:\nMastered Goals:\nB\nGoals in Progress:\nMastered Goals:\nC\n"
    sections = find_labeled_sections(text, "Mastered Goals")
    assert [s["text"].strip() for s in sections] == ["A", "B", "C"]


# --- table-column-bleed (one label covering several real entries) ----------


def test_one_label_covering_several_concatenated_entries_is_returned_whole():
    """Real bug shape (QA-PROB-04): a two-column PDF table extracts
    column-by-column, not row-by-row, so 'As evidenced by:' appears ONCE
    for an entire table with several entries' content concatenated
    beneath it. This primitive doesn't need to split those entries apart
    -- it just needs to return the real, full text instead of silently
    truncating at the first apparent 'row' boundary."""
    text = (
        "As evidenced by:\n"
        "Engages in Echolalia when spoken to.\n"
        "Repetitive physical movement continues to be a concern.\n"
        "Matthielly continues to experience difficulty with transitions.\n"
        "Problem Area:\n"
    )
    sections = find_labeled_sections(text, "As evidenced by", require_colon=False)
    assert len(sections) == 1
    assert "Echolalia" in sections[0]["text"]
    assert "transitions" in sections[0]["text"]


def test_missing_colon_is_still_tolerated_when_require_colon_is_false():
    text = "As evidenced by\nSome finding text here.\nProblem Area:\n"
    sections = find_labeled_sections(text, "As evidenced by", require_colon=False)
    assert len(sections) == 1
    assert "Some finding text" in sections[0]["text"]


def test_missing_colon_is_not_matched_when_require_colon_is_true_default():
    text = "Mastered Goals\nA real mastered goal here.\n"
    assert find_labeled_sections(text, "Mastered Goals") == []


# --- stop-boundary behavior ---------------------------------------------------


def test_section_stops_at_the_next_different_stop_label():
    text = "Problem Area:\nReal content here.\nAs evidenced by:\nShould not appear in Problem Area's own text.\n"
    sections = find_labeled_sections(text, "Problem Area")
    assert "Should not appear" not in sections[0]["text"]
    assert "Real content here" in sections[0]["text"]


def test_custom_stop_labels_override_the_default_list():
    text = "Some Label:\nContent\nCUSTOM STOP:\nMore content\n"
    sections = find_labeled_sections(text, "Some Label", stop_labels=("CUSTOM STOP",))
    assert "More content" not in sections[0]["text"]
    assert "Content" in sections[0]["text"]


def test_own_label_is_never_treated_as_a_stop_marker_for_itself():
    """A rule_id whose label is ALSO in DEFAULT_SECTION_STOP_LABELS (e.g.
    'Problem Area:') must not have its own next occurrence treated as
    an ADDITIONAL, redundant stop check on top of the normal
    next-occurrence boundary -- it should still correctly stop there
    (via the occurrence loop itself), just not double-counted via the
    stop_labels pattern."""
    text = "Problem Area:\nFirst entry.\nProblem Area:\nSecond entry.\n"
    sections = find_labeled_sections(text, "Problem Area")
    assert len(sections) == 2
    assert sections[0]["text"].strip() == "First entry."
    assert sections[1]["text"].strip() == "Second entry."
