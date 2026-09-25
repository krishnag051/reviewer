"""Fix Round 12: real bug found via a real, live judgment call against
mc_current.pdf's real text (approved one-time $5 real-API budget, this
round only -- see the round's own report for actual spend). The
reconciled majority-vote result for QA-GIP-12 came back with `evidence`
as an EMPTY list while `page` separately cited 3 real pages -- a genuine
inconsistency in the model's own reconciled output shape, not something
_merge_gip12_candidate_pages was built to expect. merge.py's own export
dispatch (_explode_to_rows) reads a page-level entry's page from
`evidence` ONLY when evidence is list-shaped, never falling back to the
top-level `page` field -- so those 3 real pages would have silently
vanished from the final CSV without ever being wrong, just never
exported. Fixed by tracking pages cited only via the `page` field
separately from pages that already have a real evidence entry, and
synthesizing a real entry for any of them that survive the hallucination
check.
"""

from pipeline import _merge_gip12_candidate_pages


def test_page_field_pages_with_no_evidence_entry_are_not_silently_lost():
    """Reproduces the exact real shape found this round."""
    judgment_result = {"result": "pass", "evidence": [], "page": [23, 66, 73], "confidence": 0.55}
    candidates = [(23, "Elopement goal", "mand"), (76, "Parents will practice using 2 movement cards", "mand")]
    merged = _merge_gip12_candidate_pages(judgment_result, candidates, fields=None)
    covered = {item["page"] for item in merged["evidence"]}
    assert covered == {23, 66, 73, 76}


def test_page_field_page_gets_a_real_entry_not_a_pass1_mislabel():
    """A page that's only in the `page` field (not one of Pass 1's own
    real candidates) must be labeled honestly as carried over from the
    page field -- never mislabeled as a deterministic keyword hit it
    never was."""
    judgment_result = {"result": "pass", "evidence": [], "page": [66], "confidence": 0.55}
    merged = _merge_gip12_candidate_pages(judgment_result, [], fields=None)
    assert merged["evidence"] == [
        {
            "page": 66,
            "detail": "Judgment cited this page separately (in its own page field) without a matching "
                      "evidence entry -- carried over here so it isn't silently lost from the export.",
        }
    ]


def test_page_that_is_both_a_pass1_candidate_and_page_field_only_gets_the_real_detail():
    """When a page is in BOTH the page field (no evidence entry) and
    Pass 1's own real candidates, prefer the more informative,
    deterministic-keyword-scan detail over the generic carry-over one."""
    judgment_result = {"result": "pass", "evidence": [], "page": [23], "confidence": 0.55}
    candidates = [(23, "Elopement goal", "mand")]
    merged = _merge_gip12_candidate_pages(judgment_result, candidates, fields=None)
    assert len(merged["evidence"]) == 1
    assert "Deterministic keyword scan" in merged["evidence"][0]["detail"]


def test_evidence_list_with_matching_page_field_is_a_true_no_op():
    judgment_result = {
        "result": "pass",
        "evidence": [{"page": 23, "detail": "real"}, {"page": 66, "detail": "real"}],
        "page": [23, 66],
        "confidence": 0.55,
    }
    merged = _merge_gip12_candidate_pages(judgment_result, [], fields=None)
    assert merged == judgment_result
