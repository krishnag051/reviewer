"""Fix Round 12: real evidence showed Round 9's fix to _short_uncertain_
summary didn't actually close the complaint -- it removed the literal
"Some reviews found.../Others found..." template, but the replacement
("N of 5 reviews concluded X") still describes raw vote mechanics. A
fresh real run surfaced the SAME complaint in different wording
("Reviewers split three ways... two said uncertain, two said pass, one
said fail"). This rewrite drops every vote-count/reviewer-tally word
entirely -- no number of reviewers, no fraction, no "split" -- and
describes only the real substantive disagreement.
"""
import re

from pipeline.judge import _short_uncertain_summary

_VOTE_MECHANICS_RE = re.compile(
    r"\breviewers?\b|\bsplit\b|\d+\s+of\s+\d+|\bvotes?\b|\bcalls?\s+said\b", re.IGNORECASE,
)


def test_no_vote_mechanics_language_in_a_three_way_split():
    entries = [
        {"result": "uncertain", "evidence": "no explicit plan documented anywhere", "page": 15},
        {"result": "uncertain", "evidence": "no explicit plan documented anywhere", "page": 15},
        {"result": "pass", "evidence": "goal covers disagreement appropriately", "page": 18},
        {"result": "pass", "evidence": "goal covers disagreement appropriately", "page": 18},
        {"result": "fail", "evidence": "no such goal exists in this document", "page": None},
    ]
    summary = _short_uncertain_summary(entries, split_desc="5-way, no majority")
    assert not _VOTE_MECHANICS_RE.search(summary)
    assert "no explicit plan documented anywhere" in summary
    assert "goal covers disagreement appropriately" in summary
    assert "no such goal exists in this document" in summary
    assert "confirm manually" in summary.lower()


def test_no_vote_mechanics_language_in_a_two_way_split():
    entries = [
        {"result": "pass", "evidence": "real pass reasoning", "page": 10},
        {"result": "fail", "evidence": "real fail reasoning", "page": 12},
    ]
    summary = _short_uncertain_summary(entries, split_desc="2-call disagreement")
    assert not _VOTE_MECHANICS_RE.search(summary)


def test_each_distinct_position_gets_its_own_named_assessment_label():
    entries = [
        {"result": "pass", "evidence": "A", "page": 1},
        {"result": "fail", "evidence": "B", "page": 2},
        {"result": "uncertain", "evidence": "C", "page": 3},
    ]
    summary = _short_uncertain_summary(entries, split_desc="3-way")
    assert "One assessment" in summary
    assert "A separate assessment" in summary
    assert "Another assessment" in summary
