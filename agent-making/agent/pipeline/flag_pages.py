"""Step 2 of the pipeline (Section 4): find image-only pages.

Any page under ~100 characters of extracted text is marked "image-only" —
per the design doc, this caught the ABLLS grid, goal graphs, the signature
page, and pages with unresolved reviewer highlights in testing.
"""

LOW_TEXT_CHAR_THRESHOLD = 100


def flag_image_only_pages(pages: list[dict]) -> list[dict]:
    """Takes extract.py's output, returns the same pages with "low_text" added."""
    flagged = []
    for page in pages:
        page = dict(page)
        page["low_text"] = len(page["text"].strip()) < LOW_TEXT_CHAR_THRESHOLD
        flagged.append(page)
    return flagged


def flagged_page_numbers(pages: list[dict]) -> list[int]:
    return [p["page_number"] for p in pages if p["low_text"]]
