"""Fix Round 7: QA-GIP-12's two-pass hybrid (built last round) made real
page coverage WORSE, not better -- real evidence showed 5 pages after the
fix vs. 7 before it, with the 5 a strict subset of the 7. Root cause: the
Pass-1 candidate list was only ever a prompt instruction ("treat this as
a floor"), never enforced in code -- consistent with the model anchoring
on the (incomplete) candidate list and citing fewer pages than it found
unaided. Fixed via _merge_gip12_candidate_pages: after judgment returns,
any Pass-1 page not already in the judgment result gets added back,
in code, so the floor can only grow the final page list, never shrink it
to match Pass 1's own (deliberately partial) candidate set.
"""

from pipeline import _merge_gip12_candidate_pages


def _candidates():
    return [
        (27, "goal a", "mand"), (28, "goal b", "tact"), (29, "goal c", "mand"),
        (30, "goal d", "intraverbal"), (31, "goal e", "echoic"), (32, "goal f", "tact"),
        (33, "goal g", "mand"),
    ]


def test_merge_restores_pages_judgment_dropped_list_of_ints_form():
    """Reproduces the exact reported regression shape: judgment result
    covers only 5 of the 7 real pages Pass 1 found."""
    judgment_result = {
        "result": "pass", "evidence": "Goals cite verbal operants on these pages.",
        "page": [27, 29, 30, 32, 33], "confidence": 0.75,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates())
    assert sorted(merged["page"]) == [27, 28, 29, 30, 31, 32, 33]
    assert "page 28" in merged["evidence"]
    assert "page 31" in merged["evidence"]


def test_merge_restores_pages_judgment_dropped_list_evidence_form():
    judgment_result = {
        "result": "pass",
        "evidence": [{"page": 27, "detail": "x"}, {"page": 29, "detail": "y"}],
        "page": None, "confidence": 0.75,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates())
    pages = {item["page"] for item in merged["evidence"]}
    assert pages == {27, 28, 29, 30, 31, 32, 33}


def test_merge_is_a_pure_no_op_when_judgment_already_covers_everything():
    judgment_result = {
        "result": "pass", "evidence": "x", "page": [27, 28, 29, 30, 31, 32, 33], "confidence": 0.8,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates())
    assert merged == judgment_result


def test_merge_never_removes_a_page_judgment_found_on_its_own():
    """The floor can only add pages -- a page judgment found that Pass 1
    never scanned (e.g. an operant-shaped goal with no literal keyword)
    must survive untouched."""
    judgment_result = {
        "result": "pass", "evidence": "x", "page": [27, 40], "confidence": 0.8,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates())
    assert 40 in merged["page"]


def test_merge_upgrades_a_single_page_finding_when_pass1_has_more_real_pages():
    """Round 13 real fix: a single-page result USED to be left untouched
    here (the original, over-conservative version of this test) -- a
    real live run found that this silently let a clean single-page
    result never receive Pass 1's floor at all. Now upgraded to the
    list[int] shape, since that's already a documented, supported page
    shape elsewhere in this same function -- see
    test_round13_gip12_single_page_upgrade.py for the dedicated coverage.
    """
    judgment_result = {"result": "pass", "evidence": "x", "page": 27, "confidence": 0.8}
    merged = _merge_gip12_candidate_pages(judgment_result, _candidates())
    assert merged["page"] == [27, 28, 29, 30, 31, 32, 33]


def test_merge_no_op_with_no_candidates():
    judgment_result = {"result": "pass", "evidence": "x", "page": [1], "confidence": 0.8}
    assert _merge_gip12_candidate_pages(judgment_result, []) == judgment_result
