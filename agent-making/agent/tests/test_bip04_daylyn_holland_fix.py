"""Fix Round (2026-09-11), item 18 -- REAL false positive confirmed and
fixed against the real Daylyn Holland TP. Ma'am's report: "Goal states
count criteria but lacks the consecutive-session qualifier -- needs to
specify how many consecutive sessions the 2-or-less standard applies to,
not just that it applies three times total."

Confirmed directly against the real document text: the goal's own
Mastery Criteria field reads "2 times or less per session for three
consecutive sessions" -- it DOES specify the consecutive-session count
(three), just spelled out as a word instead of a digit. The checker's
_DURATION_QUALIFIER_RE only ever matched digit counts ("for 3
consecutive..."), confirmed directly by a sibling goal on the SAME real
document phrased identically but with a digit, which already passed.
"""
from pipeline import fields


def _fields_for(text: str) -> dict:
    return {"pages": [{"page_number": 14, "text": text}], "full_text": text}


# Verbatim (whitespace-preserved) excerpt from the real Daylyn Holland TP.
_REAL_BLOCK = (
    "Target Name:\xa0count of instances that Daylyn lines up items\n"
    "Date Initiated:\xa005/18/2026\xa0\n"
    "Baseline:\xa05-6 times per session\xa0Frequency\n"
    "Mastery Criteria:\xa02 times or less per session for three consecutive sessions\xa0\n"
    "Sampling Method:\xa0Frequency\xa0\n"
    "Anticipated Mastery Date:\xa003/01/2027\xa0\n"
    "Status:\xa0In Progress\xa0\xa0\xa0\n"
)


def test_bip04_passes_on_the_real_daylyn_holland_goal_text():
    result, evidence, page, confidence = fields._check_BIP04({"rule_id": "QA-BIP-04"}, _fields_for(_REAL_BLOCK))
    assert result == "pass", evidence


def test_duration_qualifier_recognizes_written_out_numbers():
    assert fields._DURATION_QUALIFIER_RE.search("2 times or less per session for three consecutive sessions")
    assert fields._DURATION_QUALIFIER_RE.search("one time or less per session, for 3 consecutive sessions")
    assert fields._DURATION_QUALIFIER_RE.search("for five consecutive days")


def test_duration_qualifier_still_fails_when_genuinely_no_qualifier_present():
    """Confirms the fix didn't loosen this into matching everything --
    a Mastery Criteria with no count/duration qualifier at all is still
    correctly unmatched."""
    assert fields._DURATION_QUALIFIER_RE.search("85% accuracy") is None
