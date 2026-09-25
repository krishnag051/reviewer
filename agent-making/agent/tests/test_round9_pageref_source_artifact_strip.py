"""Fix Round 9: real evidence from a live document run showed literal
"PAGEREFnn" tokens leaking into reviewer-facing evidence on 4+ rules
(QA-BIP-13, QA-GIP-25, QA-GIP-29, QA-SIG-02). Confirmed this is NOT
humanize.py's own internal "PAGEREF{i}X" rewrite-protection placeholder
(that mechanism is already safety-netted and always ends in "X", never
leaks past humanize_evidence_with_llm's own restore/reject logic) -- it's
a literal Microsoft Word PAGEREF cross-reference field that never
resolved to a real page number before the source .docx was exported to
PDF, so pypdf extracts the field's own broken remnant text verbatim.
Fixed at the earliest possible point: pipeline/extract.py strips it from
every page's raw text right after pypdf's own extraction, before ANY
checker or judgment call ever sees it.
"""

from pipeline.extract import _WORD_FIELD_ARTIFACT_RE


def test_strips_a_single_pageref_artifact():
    text = "Behavioral Summary on PAGEREF20 addresses tantrum progress."
    assert _WORD_FIELD_ARTIFACT_RE.sub("", text) == "Behavioral Summary on  addresses tantrum progress."


def test_strips_multiple_sequential_pageref_artifacts():
    text = "Five goals showing on PAGEREF25, PAGEREF26, PAGEREF27, PAGEREF28, and PAGEREF29 total."
    cleaned = _WORD_FIELD_ARTIFACT_RE.sub("", text)
    assert "PAGEREF" not in cleaned


def test_strips_zero_padded_pageref_artifacts():
    text = "Every reviewed goal across PAGEREF01, PAGEREF02, ..., PAGEREF16 has its graph on the same page."
    cleaned = _WORD_FIELD_ARTIFACT_RE.sub("", text)
    assert "PAGEREF" not in cleaned


def test_does_not_touch_unrelated_text():
    text = "Signature credentials 'BCBA, LBA' match page-1 Provider Contact certification."
    assert _WORD_FIELD_ARTIFACT_RE.sub("", text) == text


def test_extract_pdf_text_strips_pageref_from_real_extraction(tmp_path):
    from pypdf import PdfWriter, PdfReader
    from pypdf.generic import DecodedStreamObject
    import pipeline.extract as extract_module

    # Build a real 1-page PDF and monkeypatch page.extract_text() to
    # return text containing a real PAGEREF artifact, confirming the
    # module-level extract function applies the strip to every page.
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)

    original_reader = PdfReader

    class _FakePage:
        def extract_text(self):
            return "Graph shown on PAGEREF25 for this goal."

    class _FakeReader:
        def __init__(self, path):
            self.pages = [_FakePage()]

    extract_module.PdfReader = _FakeReader
    try:
        pages = extract_module.extract_pdf_text(str(pdf_path))
    finally:
        extract_module.PdfReader = original_reader

    assert "PAGEREF" not in pages[0]["text"]
