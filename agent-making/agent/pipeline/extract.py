"""Step 1 of the pipeline (Section 4): page-by-page text extraction via pypdf.
Free, deterministic, no LLM.
"""
from pypdf import PdfReader


def extract_pdf_text(pdf_path: str) -> list[dict]:
    """Returns one dict per page, in page order: {"page_number": int, "text": str}."""
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages.append({"page_number": i + 1, "text": text})
    return pages
