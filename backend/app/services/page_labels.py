"""Round 70, Item 2 — the logical (printed) vs. physical (actual position
in the file) page-number mapping.

Ground truth confirmed before building this: agent-making's own
`pipeline/extract.py::extract_pdf_text` assigns `page_number = i + 1` —
purely by physical position in the file, via pypdf's own page iteration
order (`app/services/pdf_parser.py::parse_pdf` here in the backend does the
exact same thing). That's also what's fed into judge.py's own prompt, so
`model_pages`/`final_pages` are populated as real physical page indices
today, not something already translated from a printed label.

What this module adds: many real TPs print their OWN page number in a
footer/header ("Page 4 of 43", "- 4 -", a bare trailing number) that can
legitimately diverge from the physical index — a cover page, an inserted
blank, or a multi-document PDF all shift the two out of sync. This scans
each page's own extracted text for that printed label, page by page, so
the review UI can show a reviewer the number they'd actually recognize
from looking at the page, and flag the (real, occasional) case where it
disagrees with the physical index everything else in this system already
uses for navigation. Page-JUMP navigation always targets the physical
index (that's what a PDF viewer can actually jump to) — this mapping is
for cross-checking/display, not a translation step jump navigation needs.

Best-effort, not a guess dressed up as certainty: a page with no
confidently-matched printed label is simply omitted from the returned map
(not defaulted to str(physical_index)), so "no entry" always means
"couldn't find one," never "found one that happens to match."
"""
import re

# Ordered by specificity — checked in order, first match wins per page.
# All anchored near the END of the page's text (the last ~200 chars), since
# a printed page number is a footer convention; a number pattern anywhere
# else on the page (e.g. mid-narrative, "we discussed 43 hours") is exactly
# the kind of false match this ordering + tail-anchoring avoids.
_PATTERNS = [
    re.compile(r"[Pp]age\s+(\d{1,4})\s+of\s+\d{1,4}\b"),
    re.compile(r"[Pp]age\s+(\d{1,4})\b"),
    re.compile(r"^\s*-\s*(\d{1,4})\s*-\s*$", re.MULTILINE),
]

_TAIL_CHARS = 200


def extract_page_labels(parsed_pages: list[dict]) -> dict[int, str]:
    """`parsed_pages`: the same list `parse_pdf`/`extract_pdf_text` already
    produce (`[{"page_number": int, "text": str, ...}, ...]`). Returns
    {physical_page_number: printed_label_str}, one entry per page where a
    printed label was confidently found -- pages with none are omitted.
    """
    labels: dict[int, str] = {}
    for page in parsed_pages:
        tail = page["text"][-_TAIL_CHARS:]
        for pattern in _PATTERNS:
            match = pattern.search(tail)
            if match:
                labels[page["page_number"]] = match.group(1)
                break
    return labels
