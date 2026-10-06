"""Fix Round 18 (2026-10-06): a real staging run against zaith_new.pdf
showed QA-SCH-06 still citing page 4 even after Round 17's merge-order
fix -- this time with no embedded page mention in the judgment evidence
at all, so reconcile_page_citation had nothing to correct from. The real
root cause was never in the merge path: `_check_SCH06`'s own regex
matched the FIRST "therapy"-adjacent phrase anywhere in the document --
"...leading to a referral for speech-language pathology services," an
unrelated early-childhood history sentence on page 4 -- rather than the
real, relevant Educational History content ("occupational and physical
therapies (2x 30)... IEP that mandates occupational, speech and physical
therapies (2x 30)") on page 5. Fixed at the source: a "mention" now
requires a nearby frequency/schedule anchor ("(Nx NN)" or "Nx per
week/weekly"), not just a bare keyword, so a one-time historical aside
with no frequency information nearby no longer counts as a real mention.

Synthetic-only (zero real API cost) -- reproduces the confirmed real text
shapes directly as fixtures, same convention as every other DET_CHECKS
test in this suite.
"""
from pipeline import fields


def _fields(*page_texts: str, start_page: int = 1) -> dict:
    pages = [{"page_number": start_page + i, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def test_unrelated_historical_referral_with_no_frequency_is_not_a_mention():
    """The exact real zaith_new.pdf page-4 sentence -- a one-time early-
    childhood history note, no frequency/schedule anchor anywhere near it.
    Must no longer be treated as "another related therapy" at all."""
    page4 = (
        "By 18 months, his mother noted a regression in eye contact and communication, "
        "leading to a referral for speech-language pathology services. He began early "
        "intervention services shortly thereafter."
    )
    result, evidence, page, confidence = fields._check_SCH06(
        {"params": {}}, _fields(page4),
    )
    assert result == "not_applicable"
    assert page is None


def test_real_educational_history_parenthetical_frequency_format_is_found_on_its_own_real_page():
    """The exact real zaith_new.pdf page-5 content: '(Nx NN)' parenthetical
    shorthand, not the 'Nx per week' phrasing the original regex only
    covered. Must now be found, and cited on its OWN real page -- not
    page 4's unrelated historical mention."""
    page4 = (
        "leading to a referral for speech-language pathology services. He began early "
        "intervention services shortly thereafter."
    )
    page5 = (
        "He received speech, occupational and physical therapies (2x 30), as well as "
        "counseling services 1x weekly for social skills development. He has an IEP that "
        "mandates occupational, speech and physical therapies (2x 30), as well as "
        "counseling (1x 30) for ongoing social skills development. His mother reports "
        "that these services have not yet begin for the 2026-2027 academic year."
    )
    result, evidence, page, confidence = fields._check_SCH06(
        {"params": {}}, _fields(page4, page5, start_page=4),
    )
    assert page == 5, f"expected the real, relevant page (5), got {page!r}"
    assert result == "uncertain"  # no day/time schedule info nearby in this fixture -- real, correct answer


def test_existing_nx_per_week_shape_still_matches_unchanged():
    """No regression on the originally-documented real shape (Zyaan Ullah
    sample TP) -- 'OT 2x per week for 30 minutes' must still match."""
    text = "Zyaan currently receives OT 2x per week for 30 minutes."
    result, evidence, page, confidence = fields._check_SCH06({"params": {}}, _fields(text))
    assert result == "uncertain"
    assert page == 1


def test_existing_pass_shape_with_nearby_schedule_info_still_works():
    text = "Zyaan receives OT 2x per week for 30 minutes on Monday 10am-11am."
    result, evidence, page, confidence = fields._check_SCH06({"params": {}}, _fields(text))
    assert result == "pass"
    assert page == 1


def test_no_mention_at_all_stays_not_applicable():
    result, evidence, page, confidence = fields._check_SCH06(
        {"params": {}}, _fields("Nothing relevant here."),
    )
    assert result == "not_applicable"


def test_bare_whole_phrase_with_no_frequency_anchor_no_longer_matches():
    """Direct regression guard for the Round 18 bug class itself: a bare
    'speech therapy'/'physical therapy'/'speech-language' mention with
    nothing resembling a frequency nearby must not count as a real
    mention -- this is exactly the gap the old, removed whole-phrase
    alternatives left open."""
    text = "He was referred for speech therapy evaluation due to a regression noted by his mother."
    result, evidence, page, confidence = fields._check_SCH06({"params": {}}, _fields(text))
    assert result == "not_applicable"
