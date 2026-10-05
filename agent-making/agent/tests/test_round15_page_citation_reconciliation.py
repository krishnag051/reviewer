"""Fix Round 15 (2026-10-05): QA-BIO-06 and QA-SCH-06 both cited page 4 on
a real zaith_new.pdf run for content that actually lives on page 5 -- real
page-5 text begins immediately after the document's own printed "Page 4 of
54" footer, right at the page-4/5 boundary. Two distinct, confirmed real
causes, both fixed by pipeline.integrity.reconcile_page_citation without
ever touching `result`:

1. QA-SCH-06's own synthesized disagreement evidence named "(page 5)"
   twice in its free text while its structured `page` field said 4 -- a
   plain internal self-contradiction.
2. QA-BIO-06's evidence quoted real document text verbatim ('He is not
   currently on any prescribed medications...') that is only actually
   found on page 5, not the claimed page 4.

Fixtures below use the exact real evidence strings confirmed against
zaith_new.pdf's own real extracted text (zero model cost -- this is a pure
text-reconciliation function, no real API call anywhere in this file).
"""
from pipeline.integrity import reconcile_page_citation

# The exact real page-5 sentence from zaith_new.pdf (confirmed via direct
# pypdf extraction), split across two fixture "pages" the same way
# fields["pages"] always holds one dict per real PDF page.
_REAL_PAGE_4_TEXT = (
    "He began early intervention services shortly thereafter and achieved "
    "independent walking at 14 months.\nPage 4 of 54"
)
_REAL_PAGE_5_TEXT = (
    "He is not currently on any prescribed medications aside from multivitamins "
    "and takes medication only when ill.\nEducational History:\n"
)


def _fields():
    return {"pages": [
        {"page_number": 4, "text": _REAL_PAGE_4_TEXT},
        {"page_number": 5, "text": _REAL_PAGE_5_TEXT},
    ]}


def test_qa_bio06_real_shape_corrects_page_4_to_5_via_verbatim_quote():
    finding = {
        "result": "not_applicable",
        "evidence": (
            "'He is not currently on any prescribed medications aside from multivitamins "
            "and takes medication only when ill.' - explicit denial of ongoing medication."
        ),
        "page": 4,
        "confidence": 0.8,
    }
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] == 5
    assert corrected["result"] == "not_applicable"  # verdict never touched


def test_qa_sch06_real_shape_corrects_page_4_to_5_via_embedded_page_tags():
    finding = {
        "result": "uncertain",
        "evidence": (
            'This item genuinely came back uncertain: One assessment concluded this is uncertain -- '
            '"Document mentions related therapies (OT/speech/PT/counseling) via the IEP with frequency '
            "'2x 30' but does not state specific days/times for these other therapies anywhere, so no "
            'schedule for them was added to the TP." (page 5); A separate assessment concluded this '
            'doesn\'t apply -- "Document states Emilio\'s IEP mandates OT/speech/PT/counseling but '
            "'these services have not yet begin for the 2026-2027 academic year' [Page 5] -- no active "
            'overlapping related-therapy schedule currently exists to add to..." (page 5). Please '
            "confirm manually."
        ),
        "page": 4,
        "confidence": 0.0,
    }
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] == 5
    assert corrected["result"] == "uncertain"


def test_no_correction_when_claimed_page_already_matches():
    finding = {"result": "pass", "evidence": "Evidence mentions (page 5) and nothing else.", "page": 5, "confidence": 0.8}
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] == 5


def test_no_correction_when_no_quote_and_no_embedded_page_tag():
    finding = {"result": "fail", "evidence": "Plain evidence with no quotes or page tags at all.", "page": 4, "confidence": 0.8}
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] == 4


def test_no_correction_when_embedded_page_tags_disagree_with_each_other():
    """Ambiguous self-contradiction (the embedded tags themselves disagree)
    is left alone rather than guessing which one is right."""
    finding = {"result": "uncertain", "evidence": "One call said (page 4); another said (page 6).", "page": 5, "confidence": 0.0}
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] == 5


def test_no_correction_when_quote_matches_more_than_one_page():
    fields = {"pages": [
        {"page_number": 1, "text": "The quick brown fox jumps over the lazy dog repeatedly today"},
        {"page_number": 2, "text": "The quick brown fox jumps over the lazy dog repeatedly today"},
    ]}
    finding = {"result": "pass", "evidence": "'The quick brown fox jumps over the lazy dog repeatedly today'", "page": 1, "confidence": 0.8}
    corrected = reconcile_page_citation(finding, fields)
    assert corrected["page"] == 1  # ambiguous match -- left unchanged, not guessed


def test_list_shaped_page_is_never_touched():
    """The separate GIP-12-style multi-page merge owns list-shaped `page`
    -- this function must not interfere with it."""
    finding = {"result": "fail", "evidence": "'Some long enough quoted excerpt right here for real'", "page": [1, 2], "confidence": 0.8}
    fields = {"pages": [{"page_number": 9, "text": "Some long enough quoted excerpt right here for real"}]}
    corrected = reconcile_page_citation(finding, fields)
    assert corrected["page"] == [1, 2]


def test_non_string_evidence_is_never_touched():
    finding = {"result": "fail", "evidence": [{"page": 3, "detail": "x"}], "page": None, "confidence": 0.8}
    corrected = reconcile_page_citation(finding, _fields())
    assert corrected["page"] is None


def test_no_fields_still_applies_the_embedded_page_tag_check():
    finding = {"result": "uncertain", "evidence": "Both calls agreed: (page 7).", "page": 4, "confidence": 0.0}
    corrected = reconcile_page_citation(finding, fields=None)
    assert corrected["page"] == 7
