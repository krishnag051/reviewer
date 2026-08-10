"""Round 81: three confirmed, reproducible detection-logic gaps, verified
directly against real PDF content before being written up here as
generic, synthetic-both-directions fixes -- not one-off patches for a
single real document.
"""
import fitz
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- Item 1: highlight-color classification ---------------------------


@pytest.mark.parametrize("color,expected", [
    ((1.0, 1.0, 0.0), True),   # standard yellow
    ((1.0, 0.8, 0.0), True),   # REAL confirmed miss: orange-yellow
    ((0.4, 1.0, 0.4), True),   # highlighter green
    ((1.0, 0.4, 0.7), True),   # highlighter pink
    ((0.0, 1.0, 1.0), False),  # cyan -- real table-header fill, must NOT be flagged
    ((0.0, 0.0, 1.0), False),  # blue
    ((0.6, 0.0, 0.9), False),  # purple
    ((0.95, 0.95, 0.95), False),  # near-white background
    ((0.0, 0.0, 0.0), False),  # black body text
    ((1.0, 0.0, 0.0), False),  # pure red -- not a real highlighter color
])
def test_color_is_highlighter_like_covers_the_real_color_family(color, expected):
    assert fields._color_is_highlighter_like(color) is expected


def _pdf_with_fill(tmp_path, name, fill_rgb, opacity=0.4):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), f"This is a test sentence with a {name} word in it.")
    rect = page.search_for(name)[0]
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=None, fill=fill_rgb, fill_opacity=opacity)
    shape.commit()
    path = tmp_path / f"{name.lower()}.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.mark.parametrize("name,fill_rgb", [
    ("YELLOW", (1.0, 1.0, 0.0)),
    ("ORANGE", (1.0, 0.8, 0.0)),  # the exact real confirmed-miss color
    ("GREEN", (0.4, 1.0, 0.4)),
    ("PINK", (1.0, 0.4, 0.7)),
])
def test_check_temp03_catches_every_real_highlighter_color_family(tmp_path, name, fill_rgb):
    pdf_path = _pdf_with_fill(tmp_path, name, fill_rgb)
    result, evidence, page, confidence = fields._check_TEMP03({}, {"pdf_path": pdf_path})
    assert result == "fail"
    assert "[Page 1]" in evidence


def test_check_temp03_does_not_flag_a_cyan_fill_real_header_design_element(tmp_path):
    """The exact real, intentional, non-highlight design element these
    TPs use throughout for table-header/section-header backgrounds --
    must never be misread as a removed-but-still-visible highlight."""
    pdf_path = _pdf_with_fill(tmp_path, "HEADER", (0.0, 1.0, 1.0))
    result, evidence, page, confidence = fields._check_TEMP03({}, {"pdf_path": pdf_path})
    assert result == "pass"


def test_check_temp03_does_not_flag_ordinary_body_text(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This is an ordinary sentence with no highlighting at all.")
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()
    result, evidence, page_num, confidence = fields._check_TEMP03({}, {"pdf_path": str(path)})
    assert result == "pass"


# --- Item 2: embedded reviewer-comment detection -----------------------


def test_finds_a_declarative_parenthetical_reviewer_aside_no_question_mark():
    """REAL confirmed miss: a declarative internal note with no question
    mark, sitting as a plain parenthetical inside an otherwise normal
    clinical paragraph."""
    text = (
        "The BT worked with the client on manding goals today. "
        "(Confirm before signing. The BT is unresponsive.) "
        "Goals were addressed per the treatment plan."
    )
    comments = fields._find_embedded_reviewer_comments(text)
    assert any("Confirm before signing" in c for c in comments)


@pytest.mark.parametrize("directive", [
    "Note: this needs review", "Check with BCBA", "Verify this is correct",
    "Please make sure this is accurate", "double check this date",
])
def test_finds_various_declarative_directive_parentheticals(directive):
    text = f"The client attended the session. ({directive}) The plan continues as written."
    comments = fields._find_embedded_reviewer_comments(text)
    assert comments, f"expected a match for {directive!r}"


def test_finds_a_please_prefixed_directive_parenthetical():
    text = "The rationale is documented below. (Please review this section before signing.) Continuing."
    comments = fields._find_embedded_reviewer_comments(text)
    assert comments


@pytest.mark.parametrize("real_clinical_example", [
    # Real, verbatim (redaction-safe generic form) examples found while
    # testing this fix against real documents: SD/mand example prompts a
    # clinician would say TO the client, quoted inside parentheses in a
    # goal description -- second-person ("you") throughout, but genuine
    # clinical content, not reviewer commentary. An earlier version of
    # this fix bare-matched "you"/"your" anywhere in the parenthetical and
    # would have false-flagged every one of these -- that signal was
    # dropped for exactly this reason.
    '(e.g., "Are you hungry?", "Do you need to use the bathroom?", "Do you want more?")',
    '(e.g., "What do you want?", "Where is ___?", "Who is that?")',
    "(can you hold the door open while I bring it)",
    "(ex. did you play bubbles in the gym before?)",
])
def test_does_not_false_positive_on_real_second_person_clinical_examples(real_clinical_example):
    """Confirmed via direct testing against 3 real documents: these are
    the actual shape of real second-person clinical content this fix
    must NOT flag."""
    comments = fields._find_embedded_reviewer_comments(f"The BT will use SD prompts {real_clinical_example} during sessions.")
    assert comments == [], f"false positive on real clinical SD-prompt example: {comments}"


def test_a_question_mark_closing_a_labeled_example_is_not_flagged_but_a_real_parenthetical_question_still_is():
    """Real-document regression (Yisroel's TP): a "?" immediately before
    ")" that closes an example/quoted clinical span (signaled by "ex."/
    "e.g."/a quote mark nearby) must NOT be flagged -- but a genuine
    reviewer question that happens to be parenthesized on its own, with
    neither signal, still must be."""
    clinical = "The BT will ask (ex. did you play bubbles in the gym before?) during the session."
    assert fields._find_embedded_reviewer_comments(clinical) == []

    reviewer = "The goal was addressed this period. (Is this correct?) Continuing with the plan."
    assert fields._find_embedded_reviewer_comments(reviewer) != []


@pytest.mark.parametrize("clinical_text", [
    "The client scored 79 on the VB-MAPP (80% across 3 sessions).",
    "Diagnosis confirmed (ASD, F84.0) per the diagnostic report.",
    "Client demonstrated the skill (e.g., missing item) independently.",
    "Sessions occur twice weekly (Monday and Thursday) in the home setting.",
    "The client's mother reports improvement (per parent report, 07/2026).",
])
def test_does_not_false_positive_on_legitimate_clinical_parentheticals(clinical_text):
    """Avoid overcorrecting: ordinary parenthetical clinical content
    (a percentage, a diagnosis code, an example, a schedule note, a
    citation) must never be flagged just because it's in parentheses."""
    comments = fields._find_embedded_reviewer_comments(clinical_text)
    assert comments == [], f"false positive on legitimate clinical text: {comments}"


def test_check_temp04_end_to_end_catches_the_declarative_parenthetical():
    text = (
        "Clinical Interpretation: The client has made progress. "
        "(Confirm before signing. The BT is unresponsive.) "
        "Treatment will continue as planned.\n"
    )
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "fail"
    assert "Confirm before signing" in str(evidence)


def test_check_temp04_still_passes_a_clean_document_with_normal_parens():
    text = (
        "Clinical Interpretation: The client scored 79 on the VB-MAPP (80% across 3 sessions), "
        "showing progress consistent with the diagnosis (ASD, F84.0). Treatment will continue.\n"
    )
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "pass"


# --- Item 3: mastery-criteria vs. Target Name contradiction -------------


@pytest.mark.parametrize("target_phrase,mastery_phrase,expected_ceiling_target,expected_ceiling_mastery", [
    ("fewer than 1 occurrence", "1-2 occurrences", 0.5, 2.0),
    ("fewer than 2 occurrences", "0-1 occurrences", 1.5, 1.0),
    ("near 0", "0 occurrences", 0.5, 0.0),
    ("3 occurrences", "3 occurrences", 3.0, 3.0),
])
def test_parse_occurrence_ceiling(target_phrase, mastery_phrase, expected_ceiling_target, expected_ceiling_mastery):
    assert fields._parse_occurrence_ceiling(target_phrase) == expected_ceiling_target
    assert fields._parse_occurrence_ceiling(mastery_phrase) == expected_ceiling_mastery


def test_parse_occurrence_ceiling_returns_none_for_unrecognized_phrasing():
    assert fields._parse_occurrence_ceiling("shows good progress") is None
    assert fields._parse_occurrence_ceiling("") is None
    assert fields._parse_occurrence_ceiling(None) is None


def _goal_block(marker: str, name: str, mastery: str) -> str:
    return f"{marker} {name}\nBaseline: 5\nSampling Method: Frequency\nMastery Criteria: {mastery}\n"


def test_check_bip05_catches_the_real_confirmed_contradiction():
    """REAL confirmed case: Target Name says 'fewer than 1 occurrence',
    Mastery Criteria says '1-2 occurrences' for the SAME goal."""
    text = _goal_block(
        "Target Name:", "Reduce Elopement (fewer than 1 occurrence per week)", "1-2 occurrences per week",
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "fail"
    assert "contradict" in str(evidence).lower()


def test_check_bip05_passes_a_consistent_pair_with_compatible_but_different_phrasing():
    """Generality check: target 'fewer than 2' and criteria '0-1
    occurrences' are DIFFERENT phrasing but NOT a contradiction (mastery
    is at least as strict) -- must not false-positive on paraphrasing."""
    text = _goal_block(
        "Target Name:", "Reduce Bolting (fewer than 2 occurrences per week)", "0-1 occurrences per week",
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result != "fail"


def test_check_bip05_passes_a_paraphrased_equivalent_pair():
    """'fewer than 1' and '0 occurrences' mean the same real threshold,
    phrased differently -- must not be flagged as a contradiction."""
    text = _goal_block(
        "Target Name:", "Reduce Crying (fewer than 1 occurrence per week)", "0 occurrences per week",
    )
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result != "fail"


def test_check_bip05_not_checkable_when_no_numeric_threshold_stated():
    text = _goal_block("Target Goal:", "Increase Manding", "80% across 3 consecutive sessions")
    result, evidence, page, confidence = fields._check_BIP05({}, _fields(text))
    assert result == "not_checkable"


def test_check_bip05_not_checkable_with_no_goal_blocks_at_all():
    result, evidence, page, confidence = fields._check_BIP05({}, _fields("No goals mentioned anywhere."))
    assert result == "not_checkable"
