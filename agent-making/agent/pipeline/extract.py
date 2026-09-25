"""Step 1 of the pipeline (Section 4): page-by-page text extraction via pypdf.
Free, deterministic, no LLM.
"""
import re

from pypdf import PdfReader

# Fix Round (Round 9, real bug found): confirmed real evidence from four
# different rules (QA-BIP-13, QA-GIP-25, QA-GIP-29, QA-SIG-02) quoting a
# literal "PAGEREFnn" token into reviewer-facing evidence. This is a
# Microsoft Word cross-reference field code (PAGEREF <bookmark> \h) that
# never resolved to an actual page number before the source .docx was
# exported to PDF -- the field's own internal bookmark/switch text is what
# pypdf extracts verbatim in that case, not a real page number, and never
# was. This has nothing to do with this tool's OWN internal humanize.py
# placeholder mechanism (a similarly-named but unrelated, already-fixed
# "PAGEREF{i}X" template used only transiently during an LLM rewrite call,
# never in checker/judgment input) -- confirmed by the leaked text's own
# shape (no trailing "X", no "PAGEREF{i}X" round-trip involved; this text
# is already present in fields["full_text"] before ANY checker or
# judgment call ever sees it, source-side). Stripped here, at the
# earliest possible point (page-by-page, right after pypdf's own
# extraction), so every downstream consumer -- every deterministic
# checker, every judgment prompt, every page-lookup helper -- only ever
# sees real document text, never a broken source field artifact. No
# resolution is attempted (there is no real page number recoverable from
# a field that never resolved in the source document itself); real page
# citations always come from this tool's OWN computed page numbers
# (_page_for_offset et al.), never from quoting the source text.
_WORD_FIELD_ARTIFACT_RE = re.compile(r"PAGEREF\d+")


def extract_pdf_text(pdf_path: str) -> list[dict]:
    """Returns one dict per page, in page order: {"page_number": int, "text": str}."""
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        text = _WORD_FIELD_ARTIFACT_RE.sub("", text)
        pages.append({"page_number": i + 1, "text": text})
    return pages
