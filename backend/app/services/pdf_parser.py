from pypdf import PdfReader

# Near-zero extracted text heuristic — pages under this land on the
# OCR/vision fallback path. That fallback isn't built yet (step 6 only
# detects and flags candidate pages, per the master doc's pipeline spec).
LOW_TEXT_CHAR_THRESHOLD = 20


def parse_pdf(file_path: str) -> list[dict]:
    """Extracts text page-by-page. Raises on an unreadable/corrupt file —
    the caller (the upload pipeline) treats that as a pipeline failure and
    routes it through the all-or-nothing error path, same as any other
    step-2-4 failure.
    """
    reader = PdfReader(file_path)
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({
            "page_number": page_number,
            "text": text,
            "low_text": len(text) < LOW_TEXT_CHAR_THRESHOLD,
        })
    return pages
