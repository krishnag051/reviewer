"""Step 3 of the pipeline (Section 4): render flagged pages only, via PyMuPDF."""
import fitz  # PyMuPDF

RENDER_DPI = 120


def render_flagged_pages(pdf_path: str, page_numbers: list[int]) -> dict[int, bytes]:
    """Renders the given 1-indexed page numbers to PNG bytes, keyed by page_number."""
    rendered = {}
    doc = fitz.open(pdf_path)
    try:
        for page_number in page_numbers:
            page = doc[page_number - 1]
            pixmap = page.get_pixmap(dpi=RENDER_DPI)
            rendered[page_number] = pixmap.tobytes("png")
    finally:
        doc.close()
    return rendered
