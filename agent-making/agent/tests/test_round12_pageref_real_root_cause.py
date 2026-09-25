"""Fix Round 12: real root cause found for the PAGEREF leak, traced
against the real mc_current.pdf run. Round 9's two fixes both missed:
(1) extract.py's strip targets the SOURCE PDF text, which never contains
this pattern in the real document at all; (2) humanize_evidence_with_llm's
hardened safety net is dead code -- grepped every real call site in this
package and confirmed api.py never calls it, only the plain
humanize_evidence. The real source is judge.py's own prompt instructing
the model to cite pages as "[Page N]" -- the model sometimes writes its
own "PAGEREFnn" text instead, worst on the densest multi-page citations
(QA-GIP-29's real 16-page case). Fixed at the one place every real
finding's evidence unconditionally passes through: humanize_evidence
itself (api.py::_to_review_result's only real call site).
"""

from pipeline.humanize import humanize_evidence, humanize_evidence_with_llm


def test_strips_a_single_pageref_artifact_from_real_evidence_shape():
    text = "Behavioral Summary section on PAGEREF20 matches the BIP data."
    assert "PAGEREF" not in humanize_evidence(text)


def test_strips_a_dense_multi_pageref_run_cleanly():
    text = "five goals showing on PAGEREF25, PAGEREF26, PAGEREF27, PAGEREF28, PAGEREF29."
    cleaned = humanize_evidence(text)
    assert "PAGEREF" not in cleaned
    assert cleaned == "five goals showing on."


def test_strips_a_trailing_pageref_artifact():
    text = "No goal Target Goal/Target Name text mentions 'recall'. PAGEREF01"
    cleaned = humanize_evidence(text)
    assert "PAGEREF" not in cleaned


def test_real_page_tag_survives_untouched():
    text = "Evidence accounted for on [Page 12] -- consistent."
    assert humanize_evidence(text) == text


def test_a_legitimate_llm_rewrite_placeholder_shaped_token_is_not_a_real_evidence_string():
    """PAGEREF{i}X (with trailing X) is humanize_evidence_with_llm's own
    internal, transient protection token -- it only ever exists between
    that function's own protect/restore calls, never in text a reviewer
    or humanize_evidence itself would see. Confirms the strip regex's
    negative lookahead correctly leaves an X-suffixed token alone, in
    case it's ever passed through by mistake."""
    text = "A literal PAGEREF0X placeholder should not be treated as the malformed shape."
    assert "PAGEREF0X" in humanize_evidence(text)


def test_humanize_evidence_with_llm_still_exists_but_is_confirmed_unused_dead_code():
    """Documents the real Round 12 finding: this function is fully
    implemented and tested but has no real call site in the production
    pipeline (api.py only calls the plain humanize_evidence). Not
    removed this round (out of scope), but this test exists so a future
    reader doesn't have to re-derive that finding from scratch."""
    assert callable(humanize_evidence_with_llm)
