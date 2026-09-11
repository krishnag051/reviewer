"""Fix Round (2026-09-11), item 16 -- REAL false positive confirmed and
fixed against the real Daylyn Holland TP. Ma'am's report: "incorrectly
flagged -- both assessments and their respective dates are present on the
TP." Confirmed directly against the real document text (quoted below,
verbatim from the real PDF) -- BOTH dates genuinely are present; the
checker had three separate, compounding real bugs that each hid one of
them:

1. The multi-tool gap-based date search only looked BEFORE each tool
   mention, never after -- missed "Daylan was previously assessed using
   the Vineland on 4/30/26" (date comes AFTER the tool name).
2. All date regexes only matched 4-digit years -- missed "4/30/26" (a
   2-digit year), used throughout this real document.
3. This document's own PDF text extraction uses a non-breaking space
   (U+00A0) after several labels ("Assessment Date:\xa009/04/2026"),
   which the old [ \\t]*-only whitespace class never matched -- so even
   the correctly-labeled AFLS date was invisible.
4. (Structural, found while fixing #1) A tool mentioned many times in
   plain descriptive prose, with its one real date attached to only ONE
   of those mentions, was marked "undated" as soon as ANY OTHER mention
   of that same tool lacked its own nearby date -- the fix required
   per-mention dating; it should have been per-TOOL (does at least one
   mention have a confirmed date), same shape as the Yisroel Leibowitz
   case this file's own comments already document for the single-tool
   path, never generalized to the multi-tool path.

All four fixed together; verified directly against the real document
text (not a synthetic approximation) below.
"""
from pipeline import fields


# Verbatim (whitespace-preserved) excerpt from the real Daylyn Holland TP's
# Assessment of Current Functioning section -- confirmed via direct PDF
# text extraction, not retyped/cleaned up.
_REAL_ACF_SECTION_TEXT = (
    "Assessment of Current Functioning:\xa0\n"
    "Provider Location During Assessment:\xa0Telehealth\xa0\xa0\n"
    "Patient Location during Assessment:\xa0Home\xa0\xa0\n"
    "Assessment Date:\xa009/04/2026\xa0\xa0\n"
    "Assessor:\xa0Eliana Yachnes\xa0\xa0\n"
    "Assessment Methods/Measures:\n"
    "AFLS\xa0\n"
    "The Assessment of Functional Living Skills (AFLS) is a criterion-referenced skills assessment tool, tracking system, and\n"
    "curriculum guide.\xa0 AFLS is used for teaching children, adolescents, and adults with developmental disabilities the essential skills\n"
    "they need in order to achieve the most independent outcomes. AFLS is the most versatile assessment system available and\n"
    "offers learners a pathway to independence.\xa0The protocol includes Basic Living Skills, Home Skills, Community Participation\n"
    "Skills, School Skills, Independent Living Skills and Vocational Skills.\n"
    "BCBA chose to assess Daylan using the AFLS assessment as opposed to the previously administered Vineland. This was due to\n"
    "an evaluation of the current deficits, BCBA felt this assessment was best for the client's clinical needs.\xa0\n"
    "Daylan was previously assessed using the Vineland on 4/30/26.\xa0\n"
    "Assessment Summary Statement: Daylan continues to make progress.\xa0\n"
    "Goal Progress:\n"
)


def _fields_for(text: str) -> dict:
    return {"pages": [{"page_number": 7, "text": text}], "full_text": text}


def test_acf07_passes_on_the_real_daylyn_holland_document_text():
    """The actual, confirmed-fixed real-document check: both AFLS (labeled
    field, non-breaking-space-separated, 4-digit year) and Vineland (free
    narrative prose, 2-digit year, date AFTER the tool name) must now be
    recognized, and the rule must PASS."""
    result, evidence, page, confidence = fields._check_ACF07(
        {"rule_id": "QA-ACF-07"}, _fields_for(_REAL_ACF_SECTION_TEXT),
    )
    assert result == "pass", evidence
    assert "AFLS" in evidence and "Vineland" in evidence
    assert "09/04/2026" in evidence
    assert "4/30/26" in evidence


def test_acf07_date_after_tool_name_is_found():
    """Isolated regression for bug #1 -- a date stated AFTER the tool name
    in free prose. Uses the same tool (same-tool reassessment shape) with
    one dated mention and one date-after-name mention, isolating just
    this one bug rather than mixing in a second, deliberately-undated tool."""
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Methods/Measures:\n"
        "Vineland administered on 1/1/24.\n"
        "Client was reassessed using the Vineland on 3/1/25.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({"rule_id": "QA-ACF-07"}, _fields_for(text))
    assert result == "pass", evidence


def test_acf07_recognizes_two_digit_years():
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 3/1/25\n"
        "Assessment Methods/Measures:\n"
        "ABLLS-R\n"
        "Total Score on 6/2/25: 79\n"
        "Vineland\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({"rule_id": "QA-ACF-07"}, _fields_for(text))
    assert result == "pass", evidence


def test_acf07_recognizes_non_breaking_space_after_label():
    text = (
        "Assessment of Current Functioning:\xa0\n"
        "Assessment Date:\xa009/04/2026\xa0\xa0\n"
        "Assessment Methods/Measures:\n"
        "AFLS\xa0\n"
        "AFLS is a tool.\n"
        "Vineland was administered on 4/30/26.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({"rule_id": "QA-ACF-07"}, _fields_for(text))
    assert result == "pass", evidence


def test_acf07_a_tool_mentioned_many_times_in_prose_is_dated_by_any_one_mention():
    """Isolated regression for bug #4 -- a tool named 4 times in plain
    descriptive prose, with its real date attached to only the FIRST
    mention, must not be marked undated just because mentions 2-4 have no
    date of their own nearby."""
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 09/04/2026\n"
        "Assessment Methods/Measures:\n"
        "AFLS\n"
        "AFLS is a criterion-referenced tool. AFLS is used for teaching independence. "
        "AFLS covers many domains.\n"
        "Vineland was administered on 4/30/26.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({"rule_id": "QA-ACF-07"}, _fields_for(text))
    assert result == "pass", evidence


def test_acf07_still_fails_when_a_tool_genuinely_has_no_date_anywhere():
    """Confirms the fix didn't loosen this into a false pass -- a tool with
    NO date anywhere near ANY of its mentions is still correctly undated."""
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 09/04/2026\n"
        "Assessment Methods/Measures:\n"
        "AFLS\n"
        "Vineland was also administered, no date given for that one.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({"rule_id": "QA-ACF-07"}, _fields_for(text))
    assert result == "fail"
    assert "Vineland" in evidence
