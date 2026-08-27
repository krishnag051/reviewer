"""Fix Round (2026-08-27): QA-COC-01's real "session note detailed" half --
check_note_detail_level_across_notes -- plus the generic compound-rule
combine policy, combine_compound_rule_result. Synthetic-only, zero model
calls (the extraction step itself is mocked/hand-built here, matching the
project's own standing "mock the boundary in tests" convention -- see
session_note_comparison.py's existing tests for the same pattern).
"""
from pipeline.session_note_comparison import (
    check_note_detail_level_across_notes,
    combine_compound_rule_result,
)


def _extraction(detail_level: str | None, confidence: str = "high") -> dict:
    return {"note_detail_level": {"value": detail_level, "confidence": confidence, "source_quote": None}}


# ---------------------------------------- check_note_detail_level_across_notes


def test_pass_when_at_least_one_note_is_detailed():
    extractions = {
        "note1.pdf": _extraction("minimal"),
        "note2.pdf": _extraction("detailed"),
    }
    result = check_note_detail_level_across_notes(extractions)
    assert result["result"] == "pass"
    assert "note2.pdf" in result["evidence"]


def test_fail_when_every_note_is_minimal():
    extractions = {
        "note1.pdf": _extraction("minimal"),
        "note2.pdf": _extraction("minimal"),
    }
    result = check_note_detail_level_across_notes(extractions)
    assert result["result"] == "fail"


def test_uncertain_when_no_note_extracted_with_confidence():
    extractions = {"note1.pdf": _extraction(None, confidence="none")}
    result = check_note_detail_level_across_notes(extractions)
    assert result["result"] == "uncertain"


def test_uncertain_when_no_notes_at_all():
    result = check_note_detail_level_across_notes({})
    assert result["result"] == "uncertain"


def test_single_detailed_note_passes():
    result = check_note_detail_level_across_notes({"note1.pdf": _extraction("detailed")})
    assert result["result"] == "pass"


# ---------------------------------------- combine_compound_rule_result


def _f(result, evidence="e", confidence=0.8):
    return {"result": result, "evidence": evidence, "confidence": confidence}


def test_either_side_fail_wins():
    assert combine_compound_rule_result(_f("pass"), _f("fail"))["result"] == "fail"
    assert combine_compound_rule_result(_f("fail"), _f("pass"))["result"] == "fail"
    assert combine_compound_rule_result(_f("fail"), _f("fail"))["result"] == "fail"


def test_both_pass_combines_to_pass():
    assert combine_compound_rule_result(_f("pass"), _f("pass"))["result"] == "pass"


def test_real_data_resolves_what_phase1_could_not():
    """Phase 1 was blind to session-note data (uncertain) -- the real
    detail-level check resolving to pass should be trusted."""
    assert combine_compound_rule_result(_f("uncertain"), _f("pass"))["result"] == "pass"
    assert combine_compound_rule_result(_f("not_checkable"), _f("pass"))["result"] == "pass"


def test_phase1_pass_survives_when_real_data_cannot_resolve():
    """The detail-level check itself couldn't confirm anything (no note,
    or none confidently extracted) -- phase 1's own confident TP-only pass
    should not be thrown away."""
    assert combine_compound_rule_result(_f("pass"), _f("uncertain"))["result"] == "pass"
    assert combine_compound_rule_result(_f("pass"), _f("not_checkable"))["result"] == "pass"


def test_both_unresolved_stays_uncertain():
    assert combine_compound_rule_result(_f("uncertain"), _f("not_checkable"))["result"] == "uncertain"


def test_both_not_checkable_stays_not_checkable_not_uncertain():
    """The exact real bug a real backend test caught this round: both
    sides genuinely not_checkable (a real data/infrastructure gap, not
    ambiguous evidence) must stay not_checkable, never quietly become
    uncertain -- these are different, meaningful statuses in this
    project's own vocabulary."""
    assert combine_compound_rule_result(_f("not_checkable"), _f("not_checkable"))["result"] == "not_checkable"


def test_missing_phase1_result_treated_as_uncertain():
    combined = combine_compound_rule_result(None, _f("pass"))
    assert combined["result"] == "pass"  # real data resolves it, same as an explicit uncertain phase1
