"""Fix Round 13: real gap found via a real, live judgment call against
the real (corrected) mc_current.pdf reconstruction -- a winning
reconciled result can come back with `page` as a single int and
`evidence` as a plain string (a clean pass/fail with one representative
citation). _merge_gip12_candidate_pages used to leave this shape
completely untouched, reasoning that upgrading it would invent an
unsupported shape -- wrong, since list[int] `page` + plain-string
`evidence` is already a documented, supported shape elsewhere in this
same function. Fixed by upgrading a single-page result to the list form
whenever Pass 1 has real pages beyond the one already cited.
"""

from pipeline import _merge_gip12_candidate_pages


def _candidates():
    return [
        (52, "g52", "intraverbal"), (55, "g55", "mand"), (56, "g56", "mand"), (57, "g57", "mand"),
        (58, "g58", "mand"), (59, "g59", "mand"), (60, "g60", "mand"), (61, "g61", "tact"),
        (63, "g63", "tact"), (64, "g64", "tact"), (65, "g65", "tact"), (67, "g67", "tact"),
    ]


def test_single_page_int_result_gets_upgraded_to_the_full_real_candidate_list():
    """Reproduces the exact real shape found this round: a clean
    single-page 'fail' result, Pass 1 has 12 real candidates."""
    judgment_result = {
        "result": "fail", "evidence": "Goal explicitly uses literal term 'intraverbal fill-ins'.",
        "page": 52, "confidence": 0.55,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates(), fields=None)
    assert merged["page"] == [52, 55, 56, 57, 58, 59, 60, 61, 63, 64, 65, 67]
    assert "intraverbal fill-ins" in merged["evidence"]
    assert "additional real pages" in merged["evidence"]


def test_single_page_result_untouched_when_no_candidates_to_add():
    judgment_result = {"result": "pass", "evidence": "real evidence", "page": 5, "confidence": 0.8}
    merged = _merge_gip12_candidate_pages(judgment_result, [(5, "g5", "mand")], fields=None)
    assert merged == judgment_result


def test_single_page_result_untouched_with_no_candidates_at_all():
    judgment_result = {"result": "pass", "evidence": "real evidence", "page": 5, "confidence": 0.8}
    merged = _merge_gip12_candidate_pages(judgment_result, [], fields=None)
    assert merged == judgment_result


def test_page_as_bare_int_alongside_list_shaped_evidence_still_gets_merged():
    """Real shape found on a second live run this round: `evidence` came
    back list-shaped (empty) while `page` was a bare single int (23),
    not a list -- Round 12's own page_only_pages fix only normalized the
    list[int] case, missing this one."""
    judgment_result = {"result": "fail", "evidence": [], "page": 23, "confidence": 0.6}
    candidates = _candidates() + [(23, "g23", "mand")]
    merged = _merge_gip12_candidate_pages(judgment_result, candidates, fields=None)
    covered = {item["page"] for item in merged["evidence"]}
    assert covered == {23, 52, 55, 56, 57, 58, 59, 60, 61, 63, 64, 65, 67}


def test_single_page_that_fails_hallucination_check_is_removed_and_noted():
    pages = [{"page_number": 5, "text": "Cumulative Goal: Listeners response\nGoal Status: In progress\n"}]
    doc_fields = {"full_text": pages[0]["text"], "pages": pages}
    judgment_result = {"result": "pass", "evidence": "single citation", "page": 5, "confidence": 0.8}
    merged = _merge_gip12_candidate_pages(judgment_result, [(9, "g9", "mand")], fields=doc_fields)
    assert 5 not in merged["page"]
    assert merged["page"] == [9]
    assert "removed" in merged["evidence"].lower()
