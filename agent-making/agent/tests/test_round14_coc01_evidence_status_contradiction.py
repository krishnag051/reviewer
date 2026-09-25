"""Fix Round 14: real evidence from mc_current.pdf showed QA-COC-01's
status as Pass while its own evidence text opened with "This item
genuinely came back uncertain: One assessment concluded pass -- ...".
Root cause: combine_compound_rule_result unconditionally concatenated
both sides' raw evidence text regardless of which side actually decided
the combined result. When phase 1 (the TP-only judgment call) landed on
"uncertain" via the disagreement-synthesis path (judge.py::
_short_uncertain_summary) but the real-data side resolved a confident
"pass", that uncertain-phrased text got glued into the final Pass
result's evidence at face value -- reading as a direct contradiction of
the status sitting right next to it. Fixed by having the resolving
side's own evidence lead, with the non-resolving side folded in as
clearly-labeled context.
"""

from pipeline.session_note_comparison import combine_compound_rule_result


def _disagreement_text():
    return (
        'This item genuinely came back uncertain: One assessment concluded pass -- "some real evidence"; '
        'A separate assessment concluded fail -- "other real evidence". Please confirm manually.'
    )


def test_real_data_resolves_pass_leads_with_that_evidence_not_phase1s_uncertain_text():
    p1 = {"result": "uncertain", "evidence": _disagreement_text(), "confidence": 0.0}
    real_data = {"result": "pass", "evidence": "Session note explicitly documents coordination of care.", "confidence": 0.8}
    combined = combine_compound_rule_result(p1, real_data)
    assert combined["result"] == "pass"
    assert combined["evidence"].startswith("Session note explicitly documents coordination of care.")
    assert not combined["evidence"].startswith("This item genuinely came back uncertain")
    # Real information from both sides must still be present -- nothing lost.
    assert "genuinely came back uncertain" in combined["evidence"]


def test_phase1_resolves_pass_leads_with_that_evidence_not_real_datas_uncertain_text():
    p1 = {"result": "pass", "evidence": "TP itself confirms coordination of care is documented.", "confidence": 0.8}
    real_data = {"result": "uncertain", "evidence": _disagreement_text(), "confidence": 0.0}
    combined = combine_compound_rule_result(p1, real_data)
    assert combined["result"] == "pass"
    assert combined["evidence"].startswith("TP itself confirms coordination of care is documented.")
    assert not combined["evidence"].startswith("This item genuinely came back uncertain")
    assert "genuinely came back uncertain" in combined["evidence"]


def test_not_checkable_resolving_to_pass_also_leads_with_the_resolving_side():
    p1 = {"result": "not_checkable", "evidence": "Could not find the field in this document.", "confidence": 0.0}
    real_data = {"result": "pass", "evidence": "Real data confirms it.", "confidence": 0.8}
    combined = combine_compound_rule_result(p1, real_data)
    assert combined["result"] == "pass"
    assert combined["evidence"].startswith("Real data confirms it.")


def test_both_pass_keeps_the_original_unlabeled_concatenation():
    """Unaffected branch -- no status/evidence contradiction risk when
    both sides already agree, so the original simple join is untouched."""
    p1 = {"result": "pass", "evidence": "A", "confidence": 0.8}
    real_data = {"result": "pass", "evidence": "B", "confidence": 0.9}
    combined = combine_compound_rule_result(p1, real_data)
    assert combined["evidence"] == "A | B"
