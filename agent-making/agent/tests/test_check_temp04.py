"""Coverage for fields._check_TEMP04 -- fixes a confirmed regression
(2026-07-28 follow-up round, item 1): this rule's judgment-only behavior
had narrowed to only recognizing email-header-style text, missing the
actually-dominant real shape (an embedded reviewer comment/question left
in running text) entirely. See _find_embedded_reviewer_comments's own
docstring in pipeline/fields.py for the full diagnosis.
"""
from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def test_pass_when_no_correspondence_or_reviewer_comments():
    text = "Reeda will mand for preferred items using a full sentence. Goal Status: In progress.\n"
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "pass"


def test_fail_on_email_header_style_text():
    text = "From: reviewer@masterfaster.org\nRe: this patient's TP\nSome pasted email content.\n"
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "fail"
    assert "email-header" in evidence


def test_fail_on_embedded_reviewer_question():
    text = "Graph appears to have just one data point at 0 for the entire auth period. When is the above frequency from?\n"
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "fail"
    assert "embedded reviewer comment" in evidence


def test_does_not_false_positive_on_genuine_clinical_quoted_prompt_examples():
    """The exact false-positive risk found live: Reeda's document has many
    genuine clinical SD examples in quotes (e.g. '"What is this?"') that
    must NOT be mistaken for a reviewer question."""
    text = 'Reeda will respond to a verbal prompt when given the SD "What is this?" or "Do you want more?", using an appropriate response.\n'
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "pass"


def test_please_note_boilerplate_is_not_flagged():
    """Confirmed identical template boilerplate in both real documents'
    Transition Plan section -- must not be mistaken for a reviewer
    comment just because it starts with 'Please'."""
    text = "Please note, it is not the only criteria that will determine when and how to titrate and transition ABA services.\n"
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "pass"


def test_fail_on_please_reword_imperative():
    text = "This goal is unclear, please reword before the next authorization period.\n"
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(text))
    assert result == "fail"


def test_temp04_registered_as_deterministic_not_judgment():
    assert "QA-TEMP-04" in fields.DET_CHECKS
    assert fields.DET_CHECKS["QA-TEMP-04"] is fields._check_TEMP04


# --- Locked-in regression case: Charny's real confirmed reviewer comments ---
# (2026-07-28 follow-up round) -- the exact scenario the user reported as
# having silently narrowed. This uses the REAL quoted text found live
# against Charny's document (not a paraphrase), so this can't silently
# narrow again without this test catching it. Live verification against
# the full real document (all pages) lives in test_regression_ground_truth.py.

CHARNY_REVIEWER_COMMENTS_FIXTURE = (
    "Direct Care Behavior\nTechnician\nHome, Office,\nand/or\nCommunity\n \n"
    "Why are hours remaining the same? This\nrationale needs to be really strong, given the\n"
    "client's age. Additionally, I would add a plan\nfor titration of hours given her age.\n"
    "Assessment of Current Functioning: Please add all info below including missing corresponding session note.\n"
    "97153-Direct Care Behavior\nTechnician\nWhy was data not collected for this goal? What is the current data\nas per anecdotal data?\n"
    "To increase DRA client will implement DRA as soon as demand is given Please specify the DRA\n"
    "Current Data: 66.67  Percent Correct Why is there no data for June and July?\n"
    "before  This goal is unclear, please reword\n"
    "Date: 6/14/2026\nName: Raizy Zelcer What is her relationship with the client?\n"
)


def test_charny_real_reviewer_comments_all_caught_and_locked_in():
    result, evidence, page, confidence = fields._check_TEMP04({}, _fields(CHARNY_REVIEWER_COMMENTS_FIXTURE))
    assert result == "fail"
    comments = fields._find_embedded_reviewer_comments(CHARNY_REVIEWER_COMMENTS_FIXTURE)
    # at least the 4 comments the user's report specifically referenced,
    # verbatim, must still be caught -- if a future change to the notes-
    # exclusion list or the quote-detection logic narrows this back down,
    # this assertion fails loudly instead of silently regressing again.
    must_catch = [
        "Why are hours remaining the same?",
        "Why was data not collected for this goal?",
        "Please specify the DRA",
        "please reword",
    ]
    joined = " | ".join(comments)
    for phrase in must_catch:
        assert phrase in joined, f"regression: {phrase!r} no longer detected as a reviewer comment"
    assert len(comments) >= 6, f"expected at least 6 distinct candidate reviewer comments, got {len(comments)}: {comments}"
