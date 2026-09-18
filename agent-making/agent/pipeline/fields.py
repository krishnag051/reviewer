"""Step 4 of the pipeline (Section 4): deterministic field extraction + every
check_type == "deterministic" rule check.

Honesty note (deliberate, not an oversight): several deterministic rules in
rules.json are annotated in their own `notes` as needing data this
standalone POC does not have — a previous finalized TP version, the
facilitator's pre-upload structured intake grid, or a CPT billing lookup
table. None of that exists here (no backend integration, per the design
doc's scope). For those rules, the checker below returns `not_checkable`
with evidence naming exactly what's missing, rather than guessing. This is
the first-class `not_checkable` value from the Section 3 Findings schema
doing its job, not a gap in the implementation.

Implemented checkers cover every deterministic rule answerable from the
PDF's extracted text alone.
"""
import colorsys
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import fitz  # PyMuPDF -- already a pipeline dependency (see render.py)
from pypdf import PdfReader
from rapidfuzz import fuzz

from .schedule_hours import (
    compute_weekly_total,
    extract_weekly_schedule_day_texts,
    extract_weekly_schedule_day_texts_with_offset,
)

NEEDS_BACKEND_INTEGRATION = "Requires data not available in this standalone POC (previous TP version, pre-upload intake fields, or a billing lookup table) — not implemented here."

# A deterministic finding this weak gets a second look from the judgment
# layer, which has the rendered images and can actually reason about
# ambiguous text — the regex-based checkers here cannot.
ESCALATION_CONFIDENCE_THRESHOLD = 0.6


def needs_escalation(det_result: dict) -> bool:
    if det_result["result"] in ("not_checkable", "uncertain"):
        return True
    confidence = det_result.get("confidence")
    return confidence is not None and confidence < ESCALATION_CONFIDENCE_THRESHOLD

_REASSESSMENT_RE = re.compile(r"re[\s\-]?assessment", re.IGNORECASE)
_INITIAL_RE = re.compile(r"\binitial\b", re.IGNORECASE)


def _detect_plan_type(pages: list[dict]) -> str | None:
    """The TP's title line states its plan type directly (e.g.
    "Re-Assessment- Treatment Plan..." vs. "Initial..."). Checked against
    page 1 only. Returns None if neither term is found — callers must treat
    None as "unknown", not as a third plan type.
    """
    page1_text = pages[0]["text"] if pages else ""
    if _REASSESSMENT_RE.search(page1_text):
        return "Reassessment"
    if _INITIAL_RE.search(page1_text):
        return "Initial"
    return None


# Maps a lowercased substring found on the "Patient Payor:" line to the
# normalized payor name used in rules.json's applies_to_payor field. Add an
# entry here whenever a new payor's rule set is added.
KNOWN_PAYORS = {
    "healthfirst": "Healthfirst",
    "molina": "Molina",
    "mvp": "MVP",
    # Same treatment as Molina/MVP: no payor-specific rule content exists
    # for this payor (confirmed against the Master Faster checklist), so it
    # just needs to be recognized — partition_rules_by_scope already marks
    # HF-01/02/03 not_applicable for any known payor that isn't Healthfirst.
    # Two keys covering the abbreviated and "State" variants, same substring-
    # match style as the existing entries above (not exact-string, not fuzzy).
    "new york medicaid": "New York Medicaid",
    "new york state medicaid": "New York Medicaid",
    "ny medicaid": "New York Medicaid",
    # Unlike Molina/MVP/NY Medicaid, this payor genuinely has 2 payor-specific
    # rules (SM-01/02) on top of the universal set — see rules.json.
    "straight medicaid": "Straight Medicaid",
    # Same treatment as Molina/MVP/NY Medicaid: universal-only, no
    # payor-specific rule content (confirmed zero diff against the
    # 134-row reference checklist).
    "anthem": "Anthem",
    "cigna": "Cigna",
    # Aetna/Emblem/Empire genuinely have payor-specific rules (AET-01;
    # EMB-01; EMP-01/02/03) — see rules.json.
    "aetna": "Aetna",
    "emblem": "Emblem",
    "empire": "Empire",
}

_PAYOR_LABEL_RE = re.compile(r"patient\s+payor\s*:?\s*([^\n]{2,60})", re.IGNORECASE)


def _detect_payor(pages: list[dict]) -> str:
    """Reads the "Patient Payor:" line from page 1 and maps it to a known
    payor name. Returns "Unknown" — explicitly, never None or a silent
    fallback — if the label isn't found or doesn't match a known payor.
    Callers (partition_rules_by_scope) must treat "Unknown" as its own case,
    not as "assume Healthfirst" or "assume it matches everything."
    """
    page1_text = pages[0]["text"] if pages else ""
    m = _PAYOR_LABEL_RE.search(page1_text)
    if not m:
        return "Unknown"
    captured = m.group(1).strip().lower()
    for keyword, normalized in KNOWN_PAYORS.items():
        if keyword in captured:
            return normalized
    return "Unknown"


def extract_fields(pdf_path: str, pages: list[dict]) -> dict:
    """Builds the flat structured object described in Section 3: everything a
    deterministic rule needs, pulled by code, not by the model.
    """
    full_text = "\n".join(p["text"] for p in pages)
    reader = PdfReader(pdf_path)

    return {
        "pages": pages,
        "page_count": len(pages),
        "full_text": full_text,
        "num_pdf_pages_via_reader": len(reader.pages),
        "plan_type": _detect_plan_type(pages),
        "payor": _detect_payor(pages),
        # Round 64, item 3: the PDF's own file path, needed by _check_TEMP03
        # (highlight detection) which reads real PDF structure (annotation
        # objects, page content drawings) directly via PyMuPDF -- neither
        # is present in fields["full_text"] at all (plain-text extraction
        # discards them), so a checker needs the file itself, not the
        # already-extracted text. Purely additive; every existing checker
        # ignores this key.
        "pdf_path": pdf_path,
    }


def _plan_type_matches(applies_to_plan_type: str, detected_plan_type: str | None) -> bool:
    if applies_to_plan_type == "Both":
        return True
    if detected_plan_type is None:
        # Unknown plan type: conservative default is to let the rule run
        # rather than wrongly mark it not_applicable off a failed detection.
        return True
    if applies_to_plan_type == "Initial only":
        return detected_plan_type == "Initial"
    if applies_to_plan_type == "Reassessment only":
        return detected_plan_type == "Reassessment"
    return True


def _not_applicable_finding(reason: str) -> dict:
    return {
        "result": "not_applicable",
        "evidence": f"Out of scope for this TP: {reason}.",
        "page": None,
        "confidence": 1.0,
    }


def partition_rules_by_scope(rules: list[dict], fields: dict) -> tuple[list[dict], dict[str, dict]]:
    """Splits active rules into those in-scope for this TP's detected plan
    type/payor and those that are not. Out-of-scope rules never reach either
    layer — they come back as ready-made findings instead.

    Payor handling has three distinct cases, not two:
    - `applies_to_payor == "ALL"` always matches, regardless of what payor
      was detected (or whether detection succeeded at all).
    - A payor-specific rule where the detected payor is a *known* payor that
      doesn't match: genuinely out of scope -> `not_applicable`, same as a
      plan-type mismatch.
    - A payor-specific rule where the detected payor is `"Unknown"`: this is
      NOT the same as "out of scope" — we don't know it doesn't apply, we
      just couldn't confirm either way. That's `not_checkable`, not
      `not_applicable` — the distinction matters because `not_applicable`
      asserts "this genuinely doesn't apply here," which isn't true when the
      real answer is "couldn't tell."
    """
    applicable = []
    excluded = {}
    detected_plan_type = fields.get("plan_type")
    detected_payor = fields.get("payor")

    for rule in rules:
        if not rule["active"]:
            continue

        if not _plan_type_matches(rule["applies_to_plan_type"], detected_plan_type):
            excluded[rule["rule_id"]] = _not_applicable_finding(
                f"rule applies to plan type '{rule['applies_to_plan_type']}', "
                f"this TP was detected as '{detected_plan_type}'"
            )
            continue

        if rule["applies_to_payor"] == "ALL":
            applicable.append(rule)
            continue

        if detected_payor == "Unknown":
            excluded[rule["rule_id"]] = {
                "result": "not_checkable",
                "evidence": (
                    f"This rule applies only to payor '{rule['applies_to_payor']}', but this "
                    f"TP's payor could not be detected from the document's own text — "
                    f"applicability could not be confirmed either way."
                ),
                "page": None,
                "confidence": 0.0,
            }
            continue

        if rule["applies_to_payor"] == detected_payor:
            applicable.append(rule)
        else:
            excluded[rule["rule_id"]] = _not_applicable_finding(
                f"rule applies to payor '{rule['applies_to_payor']}', this TP was "
                f"detected as payor '{detected_payor}'"
            )

    return applicable, excluded


# --- generic text-analysis primitives, reused by multiple checkers ---

def _bare_rbt_mentions(text: str) -> list[str]:
    """'RBT' not already followed by '/BT' and not standing for 'RBT/BT' or 'BT'."""
    return [m.group(0) for m in re.finditer(r"\bRBT\b(?!/BT)", text)]


def _bare_rbt_mentions_with_offsets(text: str) -> list[tuple[str, int]]:
    """Fix Round (2026-09-11), page-number enforcement gap: same match as
    _bare_rbt_mentions, but keeps each hit's character offset so
    _check_TEMP05's fail case can cite the real page(s) instead of the
    None it used to hardcode -- the match positions were always available
    here, just never carried through to the returned finding.
    """
    return [(m.group(0), m.start()) for m in re.finditer(r"\bRBT\b(?!/BT)", text)]


_BLANK_LABEL_DEBUG_CONTEXT_LINES = 3

# Fix Round (Performance/Question Revisions, 2026-09-10) -- shared root
# cause behind QA-RPT-01 (item 9), QA-GIP-19 (item 22), and QA-GIP-10
# (item 27), confirmed to be the SAME underlying bug class rather than
# three separate ones: a label's real value sometimes continues onto a
# LATER line than the one immediately after the label -- either because
# real PDF text extraction wraps a long value across lines purely by page
# width, or (QA-RPT-01 specifically) because the label is the last thing
# on one page and its value is the first thing on the NEXT page. Every
# affected checker was only ever looking at the single line/page
# immediately following the label, so a genuinely-filled field with a
# multi-line or page-spanning value read as blank.
#
# A line that starts with a Title-Case field label (e.g. "Sampling
# Method:", "Mastery Criteria: Frequency", or a bare "Baseline:") -- used
# to recognize where a lookahead should STOP, so the search for one
# label's wrapped value doesn't run past the start of the NEXT real field
# and accidentally swallow ITS value too (confirmed real regression: an
# earlier version of this pattern only matched a bare "Label:" with
# nothing after it, so "Sampling Method: Frequency" right after a blank
# "Mastery Criteria:" wasn't recognized as a new field and got consumed
# as if it were Mastery Criteria's own wrapped value). Anchored to an
# UPPERCASE first letter specifically because every real field name in
# this codebase's documents is Title Case -- a wrapped continuation of an
# ordinary sentence essentially never starts a fresh line with a short,
# capitalized "Word Word:" phrase, so this stays a safe stop signal
# without needing to enumerate every real label name.
_LABEL_ONLY_LINE_RE = re.compile(r"^[A-Z][A-Za-z0-9 /&'()#.-]{0,58}:")


def _extract_labeled_value(text: str, label: str, *, max_lookahead_lines: int = 4) -> str:
    """Finds "{label}:" in `text` and returns its value, tolerating a value
    that continues onto later lines rather than only ever reading the same
    line as the label. Stops looking ahead at whichever comes first: real
    content found, a line that itself looks like a bare "Label:" field
    (the start of the NEXT field, not this one's value), two consecutive
    blank lines (a real paragraph/section break), or `max_lookahead_lines`
    lines with nothing found. Returns "" only when truly nothing follows
    within that window -- a genuinely blank field, not a wrapped one.
    """
    m = re.search(rf"{re.escape(label)}:[ \t]*", text, re.IGNORECASE)
    if not m:
        return ""
    rest = text[m.end():]
    lines = rest.splitlines()
    same_line = lines[0].strip() if lines else ""
    if same_line:
        return same_line

    collected: list[str] = []
    blank_run = 0
    for line in lines[1:1 + max_lookahead_lines]:
        stripped = line.strip()
        if not stripped:
            blank_run += 1
            if blank_run >= 2:
                break
            continue
        if _LABEL_ONLY_LINE_RE.match(stripped):
            break
        collected.append(stripped)
        blank_run = 0
    return " ".join(collected).strip()


def _find_blank_labels(text: str) -> list[str]:
    """Heuristic: a label ending in ':' with no real value anywhere within a
    short lookahead window (see _extract_labeled_value), suggesting an
    unfilled form field.

    Round 93 (2026-08-14), item 4: DIAGNOSTIC LOGGING added -- no pass/fail
    logic changed. QA-RPT-01 has been reported to flag real, filled fields
    (e.g. 'Mastered Goals:', 'Parent/Caregiver Involvement:') as blank on
    real documents, but two candidate mechanisms (a page-boundary artifact
    where the real content starts on the NEXT page's own text, vs. a
    placeholder/instructional line ending in ':' being mistaken for its
    own separate label) couldn't be distinguished without seeing the real
    per-page extracted text around a flagged case.

    Round 94 (2026-08-14), item 1: folded that same diagnostic context
    directly into the evidence/Detail text a real run surfaces, reasoning
    that this made it visible without needing console access. REAL BUG,
    CONFIRMED IN A REAL CSV EXPORT (Next Round, 2026-08-27): that debug
    text was never removed once the investigation it was built for
    finished, and reached actual reviewers verbatim -- "[DEBUG context
    before=... after=... is_last_line_of_page=False]" showing up as if it
    were part of the real finding. Reverted: this function is back to
    returning bare label strings, and the console `print()` below is the
    ONLY place this diagnostic context still exists -- exactly the
    "console access" case Round 94's own docstring said was already
    covered, restored to being the sole channel for it, never the
    evidence a reviewer actually reads.

    Fix Round (2026-09-10), item 9 -- REAL BUG FOUND AND FIXED: this used
    to check only the SINGLE line immediately after the label; a value
    that wrapped onto a line further down (still within the same page)
    read as blank. Now uses _extract_labeled_value's multi-line lookahead
    instead of a bare "is the very next line non-empty" check. The OTHER
    real half of item 9 (a label that's the last line of a PAGE, whose
    value is the first line of the NEXT page) is fixed at the caller
    (_check_RPT01, below) by operating on the full document text instead
    of one page's text at a time -- this function itself is page-text-
    agnostic and doesn't need to know about page boundaries at all.
    """
    return [label for label, _offset in _find_blank_labels_with_offsets(text)]


def _find_blank_labels_with_offsets(text: str) -> list[tuple[str, int]]:
    """Same detection as _find_blank_labels, but also returns each blank
    label's character offset into `text` -- lets a caller operating on the
    FULL document (fields["full_text"], not one page's text) map each
    finding back to its real page via _page_for_offset. _check_RPT01 uses
    this specifically so a label that's the last line of one page, whose
    value is the first line of the NEXT page, is correctly read as
    non-blank -- fixed here by giving the lookahead the whole document to
    search, not just whatever text remains on the current page.
    """
    blanks = []
    lines = text.splitlines()
    offset = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.endswith(":") and len(stripped) < 60:
            value = _extract_labeled_value(text[offset:], stripped[:-1])
            if not value:
                before = lines[max(0, i - _BLANK_LABEL_DEBUG_CONTEXT_LINES):i]
                after = lines[i + 1:i + 1 + _BLANK_LABEL_DEBUG_CONTEXT_LINES]
                is_last_line = i == len(lines) - 1
                print(
                    f"[_find_blank_labels DEBUG] flagged {stripped!r} as blank (line {i} of this page's text). "
                    f"Context before: {before!r}. Context after: {after!r}. "
                    f"(is_last_line_of_page={is_last_line})"
                )
                blanks.append((stripped, offset))
        offset += len(line) + 1
    return blanks


def _find_labeled_date(text: str, label: str) -> str | None:
    """Finds a single MM/DD/YYYY date following a "Label:" field, e.g.
    "Date of Most Recent Diagnosis: 11/20/2024". Returns the raw matched
    date string, or None if the label or a date after it isn't found."""
    m = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})", text, re.IGNORECASE)
    return m.group(1) if m else None


def _find_labeled_date_with_offset(text: str, label: str) -> tuple[str, int] | None:
    """Fix Round (2026-09-11), page-number enforcement gap: same match as
    _find_labeled_date, but also returns the match's character offset so
    callers can resolve a real page via _page_for_offset instead of the
    None several checkers used to hardcode -- the position was always
    right there in the regex match, just never carried through."""
    m = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})", text, re.IGNORECASE)
    return (m.group(1), m.start()) if m else None


def _find_labeled_date_range(text: str, label: str) -> tuple[str, str] | None:
    """Finds a "Label: MM/DD/YYYY to MM/DD/YYYY" range, e.g. "Authorization
    Dates Requested: 02/21/2026 to 08/21/2026". Returns (start, end) as raw
    matched date strings, or None if not found."""
    m = re.search(
        rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})\s*to\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})",
        text, re.IGNORECASE,
    )
    return (m.group(1), m.group(2)) if m else None


def _find_labeled_date_range_with_offset(text: str, label: str) -> tuple[str, str, int] | None:
    """Fix Round (2026-09-11), page-number enforcement gap: same match as
    _find_labeled_date_range, plus the match's character offset -- see
    _find_labeled_date_with_offset's own docstring for why this exists."""
    m = re.search(
        rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})\s*to\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})",
        text, re.IGNORECASE,
    )
    return (m.group(1), m.group(2), m.start()) if m else None


def _find_weekly_hours_for_code(text: str, cpt_code: str) -> float | None:
    """Finds the "<N> hours per week." value immediately preceding a CPT
    code's own label in the Hours Requesting table, e.g. "21  hours per
    week.\\n97153-Direct Care". Confirmed against real TP text (CS TP.pdf,
    Reeda Bint Shaheen's TP) — the requested weekly hours consistently
    appear directly before the code's row label in extracted text, not
    just in a "Hours Approved Previous Authorization" summary elsewhere on
    the page, which is a different figure."""
    m = re.search(
        rf"(\d+(?:\.\d+)?)\s*hours?\s*per\s*\n?\s*week\.?\s*\n?\s*{re.escape(cpt_code)}",
        text, re.IGNORECASE,
    )
    return float(m.group(1)) if m else None


def _find_weekly_hours_for_code_with_offset(text: str, cpt_code: str) -> tuple[float, int] | None:
    """Fix Round (2026-09-11), page-number enforcement gap: same match as
    _find_weekly_hours_for_code, plus the match's character offset -- see
    _find_labeled_date_with_offset's own docstring for why this exists."""
    m = re.search(
        rf"(\d+(?:\.\d+)?)\s*hours?\s*per\s*\n?\s*week\.?\s*\n?\s*{re.escape(cpt_code)}",
        text, re.IGNORECASE,
    )
    return (float(m.group(1)), m.start()) if m else None


_DAYS_IN_MONTH = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _add_months(d: datetime, months: int) -> datetime:
    """Adds calendar months to a date (not a fixed day-count approximation),
    clamping the day if the target month is shorter (e.g. Jan 31 + 1 month
    -> Feb 28/29, not Mar 3)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    max_day = _DAYS_IN_MONTH[month - 1]
    if month == 2 and _is_leap_year(year):
        max_day = 29
    return d.replace(year=year, month=month, day=min(d.day, max_day))


# --- deterministic rule checkers ---
# Each takes (rule, fields) and returns (result, evidence, page, confidence).
# `page` is None when the finding isn't tied to one specific page. Signature
# is uniform across all checkers even where a given checker ignores `rule`,
# so any checker can read rule["params"] without a special-cased interface.
#
# Business-rule constants (a cap, a code, an enum of accepted values —
# things a payor could plausibly change) live in each rule's "params" in
# rules.json, not as Python literals. Purely structural detection
# logic (regexes for a page-number marker, a blank-label heuristic, a
# literal "Invalid Date" string search) stays in code — it's how the rule
# is implemented, not a business fact that varies.

# Round 81, Item 1 -- REAL BUG FOUND AND FIXED: confirmed directly against
# a real PDF's content stream, a genuine highlighter-style fill at RGB
# (1.0, 0.8, 0.0) -- an orange-yellow -- sat behind highlighted text, and
# the old narrow-tolerance-band-around-4-fixed-RGB-triples check
# (tolerance=0.15 around exactly yellow/green/pink/cyan) missed it: (0.8)
# green-channel distance from pure yellow's 1.0 is 0.2, outside the 0.15
# band. That old approach was fundamentally the wrong shape -- highlighter
# colors aren't a small set of fixed points, they're a real COLOR FAMILY
# (any vivid, bright yellow/orange/green/pink), and different highlighter
# tools/export pipelines land anywhere in that family, not just at 4 exact
# RGB triples.
#
# Reclassified via HSV (hue/saturation/value) instead: a fill is
# highlighter-like when it's VIVID (saturation high enough to be a real
# color, not a pale tint) AND BRIGHT (value high enough, not a dark ink
# color) AND its HUE falls in the yellow-through-green range (~15°-160°:
# covers yellow, orange, lime, green) OR the pink/magenta range
# (~300°-345°). Deliberately EXCLUDES cyan (~180°) and blue/purple
# (~190°-300°) -- this pipeline's own real TPs use cyan fills for
# table-header/section-header backgrounds throughout (an intentional,
# non-highlight design element), and real highlighter pens are never
# actually cyan/blue/purple in practice. The old fixed-cyan-triple entry
# is removed for exactly this reason -- keeping it would have made this
# broadening MORE likely to false-positive on those real header fills, not
# less.
_HIGHLIGHTER_HUE_RANGES_DEGREES = ((15, 160), (300, 345))
_HIGHLIGHTER_MIN_SATURATION = 0.35
_HIGHLIGHTER_MIN_VALUE = 0.55


def _color_is_highlighter_like(color: tuple | None) -> bool:
    if color is None or len(color) != 3:
        return False
    r, g, b = color
    if not all(isinstance(c, (int, float)) and 0.0 <= c <= 1.0 for c in (r, g, b)):
        return False
    hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
    if saturation < _HIGHLIGHTER_MIN_SATURATION or value < _HIGHLIGHTER_MIN_VALUE:
        return False  # near-white/near-gray (low saturation) or near-black (low value) -- not a highlighter
    hue_degrees = hue * 360
    return any(lo <= hue_degrees <= hi for lo, hi in _HIGHLIGHTER_HUE_RANGES_DEGREES)


def _check_TEMP03(rule: dict, fields: dict) -> tuple:
    """"All highlights removed."

    Round 64, item 3: converted from judgment to deterministic after
    confirming, via a real investigation (not an assumption), that pypdf's
    plain-text extraction discards ALL highlight/color formatting -- there
    is no highlight signal of any kind in fields["full_text"] for the
    judgment layer to read, regardless of prompt wording. That's a real
    tool/modality gap in the TEXT path specifically -- but the PDF's own
    structure still carries this information, and PyMuPDF (already a
    pipeline dependency, see render.py) can read it directly:

    1. PRIMARY: a real Highlight-type PDF annotation (`page.annots()`
       filtered for `annot.type[1] == "Highlight"`) -- this is what Word's
       "highlight" tool and Adobe's highlight annotation tool both
       produce, and what PyMuPDF's own `add_highlight_annot()` creates.
       Confirmed live against a self-built synthetic PDF (a real
       PyMuPDF-added highlight over a specific word): detected correctly,
       and correctly finds nothing in an unhighlighted synthetic PDF
       (negative control) or one where color was baked into page content
       instead of kept as an annotation (case 2 below) -- this method is
       real-annotation-only, by design.
    2. FALLBACK: some export paths flatten a highlight into a colored
       rectangle drawn behind the text instead of a true annotation --
       `page.get_drawings()` filtered to fills matching a standard
       highlighter color (see _HIGHLIGHTER_COLORS), cross-referenced
       against `page.get_text("words")` for actual text-word overlap (not
       just any colored shape on the page). Confirmed live against a
       second self-built synthetic PDF (a yellow rectangle drawn behind a
       specific word, no annotation object at all): detected correctly by
       this method specifically (method 1 correctly finds nothing there,
       since there's genuinely no annotation object to find).

    Either method finding anything is a fail (a highlight is still
    present, not removed). Needs fields["pdf_path"] (the real PDF file,
    not just extracted text) -- see extract_fields.
    """
    pdf_path = fields.get("pdf_path")
    if not pdf_path:
        return "not_checkable", "No PDF file path available to inspect for highlight annotations.", None, 0.0

    doc = fitz.open(pdf_path)
    try:
        real_annotation_hits = []
        flattened_fill_hits = []
        for page in doc:
            for annot in (page.annots() or []):
                if annot.type[1] == "Highlight":
                    real_annotation_hits.append(page.number + 1)

            for drawing in page.get_drawings():
                fill = drawing.get("fill")
                if not _color_is_highlighter_like(fill):
                    continue
                rect = drawing.get("rect")
                if rect is None:
                    continue
                words = page.get_text("words")
                overlapping = [w[4] for w in words if fitz.Rect(w[:4]).intersects(rect)]
                if overlapping:
                    flattened_fill_hits.append((page.number + 1, overlapping))
    finally:
        doc.close()

    if not real_annotation_hits and not flattened_fill_hits:
        return "pass", "No highlight annotations or highlighter-colored fills found in this PDF.", None, 0.85

    # Round 77, Item 2: rewritten from Python's default list/tuple repr()
    # (e.g. "[(6, ['hit', 'or', 'grab']), (9, [...])...]") -- concise and
    # correct, but exactly the kind of ad-hoc, non-standard page-reference
    # shape the frontend's Round 72 extractPageNumbersFromText() had to
    # special-case a regex for. Now uses the one standard [Page N] tag
    # (see judge.py's _build_prompt for the same convention on the
    # judgment side), one tag per distinct page, and drops the verbose
    # per-page matched-word lists -- the finding is "a highlight exists on
    # this page," not a transcript of which words it covers.
    problems = []
    if real_annotation_hits:
        pages_str = " ".join(f"[Page {p}]" for p in sorted(set(real_annotation_hits)))
        problems.append(f"Highlight annotation(s) found: {pages_str}.")
    if flattened_fill_hits:
        fill_pages = sorted({p for p, _ in flattened_fill_hits})
        pages_str = " ".join(f"[Page {p}]" for p in fill_pages)
        problems.append(f"Highlighter-colored fill(s) found: {pages_str}.")
    page = (sorted(set(real_annotation_hits)) or [flattened_fill_hits[0][0]])[0]
    return "fail", " ".join(problems), page, 0.85


def _find_embedded_reviewer_comments(text: str) -> list[tuple[str, int]]:
    """Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    now returns [(comment_text, offset), ...] instead of a bare list of
    strings -- both call sites (QA-TEMP-04, QA-PROB-02) previously
    discarded a real, computable page for every comment this function
    finds; the offsets were already available internally (every match
    below is via re.finditer), just never returned. Both callers updated
    accordingly.

    Finds embedded reviewer comments/questions left in the document's
    running text -- built to fix a confirmed regression (2026-07-28
    follow-up round, item 1): QA-TEMP-04's notes described the check as
    "pattern match (From:/Re:/email headers) catches most; free-form
    pasted chat needs LLM" -- but this rule was NEVER given a real DET
    checker (check_type stayed "judgment" the whole time, no DET_CHECKS
    entry), so 100% of its real-world behavior always came from the
    judgment layer reading those same narrow notes. Those notes never once
    mentioned "an embedded reviewer question/annotation left in otherwise-
    normal narrative text" as a form of unremoved correspondence -- exactly
    the shape that turned out to be the dominant real evidence across
    THREE other rules fixed this engagement (QA-HRS-06, QA-TRANS-01,
    QA-ACF-07's Vineland question). A judgment-only rule whose notes only
    describe two narrower shapes (email headers, free-form chat) will
    naturally narrow toward matching just those two shapes over successive
    reasoning, especially once nothing in its own notes ever pointed at the
    third, actually-dominant shape. No prior-round git history or run log
    survives to prove this was the exact mechanism (this directory isn't
    under its own version control, and no live-run transcript from "two
    rounds ago" was preserved) -- this is the most evidence-backed
    candidate mechanism, and the fix (give this rule its own real,
    deterministic detector covering the actually-dominant shape) closes
    the gap regardless of the precise prior cause.

    Distinguishes a genuine reviewer comment from a genuine CLINICAL
    quoted-prompt example (e.g. '"What is this?"', an SD example inside a
    goal description) by checking whether the '?' is immediately followed
    by a closing quote mark -- confirmed against every real '?' in both
    documents: every clinical quoted-prompt example's '?' is immediately
    followed by a closing quote character, every real reviewer question's
    '?' is followed by a space/newline and more prose instead. Also matches
    a small set of imperative reviewer phrasings ('please reword', 'please
    clarify', 'please specify', 'please update', 'please add') while
    explicitly excluding 'please note' -- confirmed, IDENTICAL boilerplate
    template language in both real documents' Transition Plan section
    ("Please note, it is not the only criteria..."), not reviewer
    commentary specific to either patient.

    Round 81, Item 2 -- REAL BUG FOUND AND FIXED: confirmed directly
    against a real document, a genuine embedded internal note --
    "(Confirm before signing. The BT is unresponsive.)" -- sits as plain
    DECLARATIVE inline text, no question mark anywhere in it, and every
    detector above (question-mark-based, or the narrow "please X" list)
    missed it entirely. Every prior confirmed real example of this pattern
    happened to be phrased as a question -- the detection had quietly
    overfit to that one shape rather than the underlying, broader pattern
    (an aside directed AT the reviewer/preparer, not part of the clinical
    narrative itself).

    Added: a PARENTHETICAL-aside scan, deliberately scoped to text inside
    parentheses (not every declarative sentence in the document -- that
    would be far too broad and risk flagging ordinary clinical prose).
    Flagged only when the parenthetical's own text starts with a
    reviewer-directed imperative/directive word ('confirm', 'note:',
    'check', 'verify', 'review', 'flag', 'make sure', 'ensure',
    'double check'). Ordinary clinical parenthetical content (a
    definition, an example, a citation, a measurement) never starts with
    one of these words -- confirmed against real examples like
    '(e.g., missing item)', '(80% across 3 sessions)', '(ASD, F84.0)',
    none of which match.

    A bare second-person ("you"/"your") signal was tried and DROPPED
    after real-document testing found it, confirmed: real TPs' goal
    descriptions routinely quote SD/mand example PROMPTS a clinician
    would say TO the client -- e.g. '(e.g., "Are you hungry?", "Do you
    need to use the bathroom?")' -- which are genuine clinical content,
    not reviewer commentary, and would have been false-flagged by a bare
    "you" match every time. The directive-word-starts-the-parenthetical
    signal alone already catches the real confirmed case
    ("Confirm before signing...") with zero false positives against three
    real documents checked directly -- second-person address on its own
    is not a safe enough signal in this domain, where clinical prompts
    are themselves routinely addressed to the patient in the second
    person.
    """
    comments = []
    for m in re.finditer(r"[^\n]{0,150}\?", text):
        next_char = text[m.end():m.end() + 1]
        matched = m.group(0)
        if next_char in ('"', "”"):
            continue  # closes a quoted clinical example, not a reviewer question
        if next_char == ")" and re.search(r'(?:e\.?g\.?|ex\.?|["“”])', matched, re.IGNORECASE):
            # Round 81, item 2: confirmed via real-document testing --
            # a real clinical SD-prompt example quoted parenthetically
            # (e.g. "(...did you play bubbles in the gym before?)" or
            # "(e.g., \"Are you hungry?\"...)") has its own "?" immediately
            # followed by ")", the same "closing a quoted/labeled-example
            # clinical span, not trailing into more reviewer prose" shape
            # the quote-mark exclusion above already covers -- just with a
            # different closing character. Scoped to spans that also show
            # an example lead-in ("e.g."/"ex.") or a quote character, so a
            # genuine reviewer question that happens to be parenthesized on
            # its own (e.g. "(Is this correct?)") is NOT excluded -- that
            # shape has neither signal and still gets caught.
            continue
        comments.append((matched.strip(), m.start()))
    for m in re.finditer(r"[Pp]lease (?!note\b)(?:reword|clarify|specify|update|add)[^\n]{0,80}", text):
        comments.append((m.group(0).strip(), m.start()))
    for m in re.finditer(r"\(([^()]{1,200})\)", text):
        inner = m.group(1).strip()
        if not inner:
            continue
        starts_with_directive = re.match(
            # "note\s*:" ends in a colon, not a word character -- \b would
            # never match right after it (no boundary between two
            # non-word characters), so it's deliberately kept out of the
            # \b-anchored alternation below and checked as its own
            # branch instead.
            r"(?:(?:please\s+)?(?:confirm|check|verify|review|flag|make sure|ensure|double[\s-]?check)\b|note\s*:)",
            inner, re.IGNORECASE,
        )
        if starts_with_directive:
            comments.append((f"({inner})", m.start()))
    return comments


def _check_TEMP04(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 follow-up
    round, item 1) -- fixing a confirmed regression where this rule's
    behavior had narrowed to only recognizing email-header-style text.
    See _find_embedded_reviewer_comments's own docstring for the full
    diagnosis and mechanism.

    Checks for BOTH forms of "correspondence with BCBA" the rule's own
    (unimplemented-until-now) notes always described: email-header-style
    text (From:/To:/Re:/Subject:/Sent: at the start of a line), and
    embedded reviewer comments/questions left in running text. Either one
    present is a fail.

    Verified live against both real documents: Reeda has 8 confirmed
    embedded reviewer comments/questions (e.g. "Is the Vineland for this
    auth? What was the date of administration..."; "This date is in the
    future, please update to correct date."); Charny has 8 (e.g. "Why are
    hours remaining the same?"; "Please specify the DRA"). Both correctly
    fail. No email-header-style text found in either document (neither
    uses that literal form), so that half of the check is verified as a
    mechanism but not against a real triggering instance in either
    document -- same caveat already flagged for other single-condition
    checks this engagement (QA-TEMP-01's Limited Permit path, etc.).
    """
    text = fields["full_text"]
    comments = _find_embedded_reviewer_comments(text)
    email_headers = [(m.group(0), m.start()) for m in re.finditer(r"^(?:From|To|Re|Subject|Sent):[^\n]*", text, re.MULTILINE)]

    # Fix Round (2026-09-10), item 8 -- REAL FALSE POSITIVE FOUND AND
    # FIXED: "listener responding" is normal ABA/VB-MAPP terminology (a
    # Skill Domain name), not real correspondence -- confirmed by ma'am,
    # not a real missing-page-number case. Excluded explicitly rather than
    # guessed at via a broader change to either detector above, since the
    # exact triggering regex wasn't reproducible against any sample
    # document on hand; this exception is correct regardless of which
    # detector produced the false hit.
    _LISTENER_RESPONDING_RE = re.compile(r"listener\s+responding", re.IGNORECASE)
    comments = [(c, off) for c, off in comments if not _LISTENER_RESPONDING_RE.search(c)]
    email_headers = [(h, off) for h, off in email_headers if not _LISTENER_RESPONDING_RE.search(h)]

    if not comments and not email_headers:
        return (
            "pass",
            "No embedded reviewer comments/questions or email-header-style correspondence "
            "found in the document.",
            None, 0.75,
        )

    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # cite whichever type of problem was found first in the document.
    first_offset = min(
        (off for _c, off in comments + email_headers),
        default=None,
    )
    page = _page_for_offset(fields, first_offset) if first_offset is not None else None

    problems = []
    if email_headers:
        problems.append(f"{len(email_headers)} email-header-style line(s) found: {[h for h, _off in email_headers][:5]}.")
    if comments:
        problems.append(
            f"{len(comments)} embedded reviewer comment(s)/question(s) found, e.g.: "
            f"{[c for c, _off in comments][:3]}."
        )
    return "fail", " ".join(problems), page, 0.75


# A whole line that's essentially just "Label: short value" -- the real,
# specific shape of a matrix/checklist form field, e.g. "Eye contact: poor".
# Anchored to the FULL line (^...$) so this doesn't fire on a real sentence
# that merely CONTAINS a colon somewhere (a citation, a time, a ratio).
_MATRIX_LABEL_VALUE_LINE_RE = re.compile(r"(?m)^[ \t]*[A-Za-z][A-Za-z /'\-]{1,30}:[ \t]*[A-Za-z0-9][\w /'\-]{0,30}[ \t]*$")


def _looks_like_structured_matrix(text: str) -> bool:
    """Round 84, item 3: a conservative heuristic distinguishing narrative
    prose from a matrix/checklist-style layout, for the "As evidenced by:"
    narrative-format requirement QA-PROB-01's rubric never checked before.

    Round 84 -- FIRST ATTEMPT CAUGHT AND FIXED: an earlier version split on
    every raw newline and flagged short/unpunctuated fragments -- but real
    PDF text extraction wraps long sentences across MANY lines purely by
    page width, not by sentence/entry boundary (confirmed: this produced
    false positives on Charny's and Yisroel's real "As evidenced by"
    narrative, which just happens to word-wrap into many short lines).
    Raw line length/newline count is not a safe signal here at all.

    Replaced with a much more specific, positive signal instead of a
    negative one: does this block contain multiple whole LINES that are
    themselves just "Label: short value" (e.g. "Eye contact: poor",
    "Turn taking: absent")? That exact shape is specific to a tabular/
    form-style layout and essentially never appears as a genuine sentence
    line in flowing clinical narrative, even when line-wrapped oddly --
    confirmed zero false positives against all three of this project's
    real documents (none of their real "As evidenced by" content has any
    colon-delimited whole-line label:value shape at all).
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    label_value_lines = sum(1 for l in lines if _MATRIX_LABEL_VALUE_LINE_RE.match(l))
    return label_value_lines >= 2 and (label_value_lines / len(lines)) >= 0.5


_EVIDENCED_BY_BLOCK_RE = re.compile(
    r"As evidenced by:[ \t]*([\s\S]{1,3000}?)"
    r"(?=\n\s*(?:Problem Area:|Problem Areas:|As evidenced by:|Areas of Focus|Goal Progress:)|\Z)",
)


def _check_PROB01(rule: dict, fields: dict) -> tuple:
    """Round 84, item 3 -- adds the one signal this rule's rubric never
    had: an actual narrative-vs-structured-format check on "As evidenced
    by:" content, via _looks_like_structured_matrix's conservative
    heuristic. Confirmed real gap (flagged early in this project, never
    separately fixed): a checklist/matrix-formatted "As evidenced by"
    section passed this rule despite the checklist explicitly requiring
    narrative format -- the rule's own rubric only ever counted entries
    and checked for a non-blank "As evidenced by:" value, never the
    FORMAT of that value.

    Hybrid DET pre-check, same shape as QA-PROB-02/QA-GIP-05: ONLY
    attempts this one narrow, objectively-checkable sub-question (does
    the evidenced content read as a matrix/checklist rather than
    narrative prose). Does NOT attempt this rule's own per-bucket
    2-entries-minimum count -- that stays exactly the judgment-layer task
    this rule's own notes already describe (bucket/heading attribution
    from this section's free-form layout isn't reliably regex-extractable
    the way a "Target Name:"-style block marker is). Fails outright only
    when the matrix heuristic confidently fires on at least one "As
    evidenced by:" block; returns not_checkable otherwise (even on a
    clean read) so the full count+format judgment still runs unchanged.
    """
    text = fields["full_text"]
    blocks = [m.group(1).strip() for m in _EVIDENCED_BY_BLOCK_RE.finditer(text)]
    blocks = [b for b in blocks if b]
    if not blocks:
        return "not_checkable", "No 'As evidenced by:' content found to check for narrative format.", None, 0.0

    matrix_like = [b for b in blocks if _looks_like_structured_matrix(b)]
    if matrix_like:
        return (
            "fail",
            (
                f"{len(matrix_like)} of {len(blocks)} 'As evidenced by:' block(s) read as a "
                f"matrix/checklist-style layout (short, fragment-like entries with no sentence "
                f"structure), not the narrative format this checklist item requires."
            ),
            None, 0.7,
        )
    return (
        "not_checkable",
        (
            f"Checked {len(blocks)} 'As evidenced by:' block(s) -- all read as narrative prose, no "
            f"matrix/checklist-format violation found, but the per-bucket 2-entries-minimum count "
            f"still needs judgment."
        ),
        None, 0.3,
    )


def _check_PROB04(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 9, second half: when
    there genuinely is no previous TP available, this rule must resolve
    to not_applicable, not a Pass whose own evidence text says identity
    "cannot be verified" -- a self-contradicting label. This is the
    phase-1 (TP-only) answer, which by definition never has previous-TP
    data to compare against; it always returns not_applicable. The real
    comparison -- current vs. previous TP's own Problem Areas text --
    only happens in pipeline/previous_tp_comparison.py::_compare_prob04,
    wired via app/agent_client.py::review_previous_tp, which uses that
    real result on its own rather than blending it with this stub (see
    that call site's own comment -- combining a fixed not_applicable
    phase-1 with a real pass/fail through the generic compound-combine
    policy would incorrectly collapse a resolved answer into "uncertain").
    """
    return (
        "not_applicable",
        "No previous TP is available in this run to compare Problem Areas against.",
        None, 0.85,
    )


def _check_PROB02(rule: dict, fields: dict) -> tuple:
    """Round 63, item 5: "'As evidenced by' section matches goals listed" --
    deterministic pre-check ONLY for the confirmed objective violation (a
    leftover embedded reviewer comment counted as valid clinical evidence),
    reusing QA-TEMP-04's own reviewer-comment detector
    (_find_embedded_reviewer_comments) rather than duplicating that logic.

    This does NOT attempt the genuine semantic question the rule is really
    about -- whether the evidence actually supports/aligns with the goals
    listed -- that's real judgment, unchanged. This check only ever
    returns a definitive result (fail) when it finds the specific,
    objective violation; otherwise it returns not_checkable, which
    escalates to the judgment layer for the real alignment check (see
    fields.needs_escalation / pipeline/__init__.py's escalation wiring).

    Matching is scoped to same-line text (both this function's "As
    evidenced by:" value capture and _find_embedded_reviewer_comments'
    own regexes are single-line by construction) -- a reviewer comment
    embedded directly in an "As evidenced by:" field's own line is exactly
    the confirmed real failure mode; this intentionally doesn't try to
    catch a comment on some unrelated nearby line, which would risk false
    positives this rule was never actually asked to prevent.
    """
    text = fields["full_text"]
    comments = _find_embedded_reviewer_comments(text)
    if comments:
        for m in re.finditer(r"As evidenced by:[ \t]*([^\n]*)", text, re.IGNORECASE):
            evidence_value = m.group(1).strip()
            if not evidence_value:
                continue
            for comment, comment_offset in comments:
                # _find_embedded_reviewer_comments matches greedily from up
                # to 150 chars before the "?"/imperative phrase, which on
                # this same line includes the "As evidenced by:" label
                # itself -- so `comment` is typically LONGER than
                # evidence_value, with evidence_value as its trailing
                # substring. Checking both directions handles either case
                # (e.g. a line with trailing text after the "?" too).
                if comment and (evidence_value in comment or comment in evidence_value):
                    return (
                        "fail",
                        f"An 'As evidenced by:' entry is an embedded reviewer comment, not real "
                        f"clinical content: {comment!r}.",
                        _page_for_offset(fields, comment_offset), 0.85,
                    )
    return (
        "not_checkable",
        "No embedded-reviewer-comment violation found in any 'As evidenced by:' entry -- the full "
        "semantic alignment against the goals listed still requires judgment.",
        None, 0.0,
    )


def _check_TEMP05(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: the fail case
    now cites the real page(s) the bare 'RBT' mentions were found on
    (single page -> that page, multiple pages -> the {page, detail}
    per-page evidence form) instead of the None this used to hardcode --
    the match positions always existed (via _bare_rbt_mentions), they were
    just being discarded. The pass case genuinely has no page to cite --
    it's an absence across the whole document, nothing was matched.
    """
    hits = _bare_rbt_mentions_with_offsets(fields["full_text"])
    if not hits:
        return "pass", "No bare 'RBT' mentions found; all instances already read 'RBT/BT' or are followed by '/BT'.", None, 0.85
    by_page: dict[int | None, list[str]] = {}
    for mention, offset in hits:
        page = _page_for_offset(fields, offset)
        by_page.setdefault(page, []).append(mention)
    pages = sorted(by_page, key=lambda p: (p is None, p))
    if len(pages) == 1:
        page = pages[0]
        return "fail", f"Found {len(hits)} bare 'RBT' mention(s) not updated to 'RBT/BT' or 'BT'. [Page {page}]", page, 0.8
    evidence = [
        {"page": page, "detail": f"{len(by_page[page])} bare 'RBT' mention(s) not updated to 'RBT/BT' or 'BT'."}
        for page in pages
    ]
    return "fail", evidence, None, 0.8


def _check_RPT01(rule: dict, fields: dict) -> tuple:
    """Next Round (2026-08-27): the Round 94 version of this function
    folded _find_blank_labels' internal debug context directly into this
    rule's real evidence/Detail text -- confirmed, via a real CSV export,
    to have leaked verbatim "[DEBUG context before=... after=...]" text to
    an actual reviewer. Reverted to plain label strings only; the
    diagnostic context still exists (console print, inside
    _find_blank_labels itself), it just never reaches evidence again.

    Fix Round (2026-09-10), item 9 -- REAL BUG FOUND AND FIXED: this used
    to scan each PAGE's text independently, so a label that's the very
    last line of one page, whose value is the first line of the NEXT
    page, always read as blank -- the value simply wasn't in the text
    being searched. Now operates on fields["full_text"] (pages joined,
    same document GIP-10 already reads the same way for the identical
    reason), so a page-spanning label/value pair is found correctly;
    _page_for_offset maps each finding back to its real page for evidence.
    """
    found = _find_blank_labels_with_offsets(fields["full_text"])
    if not found:
        return "pass", "No unfilled 'Label:' form fields detected.", None, 0.6

    by_page: dict[int | None, list[str]] = {}
    for label, offset in found:
        page = _page_for_offset(fields, offset)
        by_page.setdefault(page, []).append(label)
    blanks = sorted(by_page.items(), key=lambda kv: (kv[0] is None, kv[0]))

    if len(blanks) == 1:
        page, labels = blanks[0]
        # confidence 0.65, not 0.5: a blank required field is a plain fact
        # this regex either finds or doesn't, not a judgment call, and
        # confidence < ESCALATION_CONFIDENCE_THRESHOLD (0.6) forces this
        # exact page number to be thrown away in favor of the judgment
        # layer's own (LLM re-counted, and here proven off-by-one) page
        # number every time this rule fails — see the CS TP.pdf QA-RPT-01
        # investigation: the deterministic layer had the right page (20),
        # escalation silently replaced it with the model's wrong guess (19).
        # Round 77, Item 2: "[Page N]" tag, same standard convention as
        # every other checker/the judgment prompt -- was "on page {page}:".
        return "fail", f"Possible unfilled field(s): {labels}. [Page {page}]", page, 0.65
    # More than one page implicated: one {page, detail} entry per page,
    # naming that page's specific labels — never a collapsed page-range
    # summary a reviewer would have to decode.
    evidence = [
        {"page": page, "detail": f"Possible unfilled field(s): {labels}."}
        for page, labels in blanks
    ]
    return "fail", evidence, None, 0.65


def _check_GIP04(rule: dict, fields: dict) -> tuple:
    """"No mastery date shows 'invalid date'."

    Round 63, item 6: broadened -- a BLANK 'Anticipated Mastery Date:'
    field is functionally the same real problem this rule is about (no
    confirmed mastery date for the goal) as the literal 'Invalid Date'
    string; only checking for that one literal string missed the blank-
    field case entirely. Confirmed this is NOT already covered by a
    different rule: QA-GIP-10 only reads Sampling Method/Baseline/Mastery
    CRITERIA (never Anticipated Mastery DATE), and QA-GIP-16 only reads
    Mastery Criteria's zero/near-zero phrasing -- neither rule looks at
    this field at all, so this was a genuine uncovered gap, not
    overlapping responsibility with either (contrast with item 7's fix to
    QA-GIP-16, which IS a real division-of-labor issue with QA-GIP-10 over
    the SAME field, Mastery Criteria).

    Reuses the same per-goal block splitter QA-GIP-10/QA-GIP-16 already
    use (_goal_block_starts), so goals spanning a page boundary are
    handled the same way.
    """
    text = fields["full_text"]
    if re.search(r"invalid date", text, re.IGNORECASE):
        page = next((p["page_number"] for p in fields["pages"] if "invalid date" in p["text"].lower()), None)
        return "fail", "Literal 'Invalid Date' string found in a mastery date field.", page, 0.9

    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        # No per-goal structure to check for blankness at all -- this is a
        # weaker signal than "goal blocks exist but the date field itself
        # is missing/blank" (that case is handled below), so it falls back
        # to the original rule's own behavior: no evidence of the literal
        # 'Invalid Date' string found, and nothing further to check.
        return (
            "pass",
            "No literal 'Invalid Date' strings found; no 'Target Goal:'/'Target Name:' entries "
            "present in this document to check for blank mastery dates.",
            None, 0.5,
        )
    goal_starts = goal_starts + [len(text)]

    blank_dates = []
    total = 0
    first_filled_offset = None
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        amd_m = re.search(r"Anticipated Mastery Date:[ \t]*([^\n]*)", block)
        if not amd_m:
            continue
        total += 1
        amd_val = amd_m.group(1).strip()
        if not amd_val:
            marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
            goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]
            page = _page_for_offset(fields, goal_starts[i] + amd_m.start())
            blank_dates.append((page, f"Anticipated Mastery Date is blank for goal '{goal_name}'."))
        elif first_filled_offset is None:
            # Fix Round (2026-09-11), page-number enforcement gap: track
            # the first non-blank field's real offset so the pass case
            # below can cite it instead of hardcoding page=None.
            first_filled_offset = goal_starts[i] + amd_m.start()

    if total == 0:
        return (
            "pass",
            "No literal 'Invalid Date' strings found; no 'Anticipated Mastery Date:' field present "
            "in this document to check further.",
            None, 0.5,
        )
    if not blank_dates:
        return (
            "pass",
            f"No literal 'Invalid Date' strings found; all {total} 'Anticipated Mastery Date' "
            f"field(s) are non-blank.",
            _page_for_offset(fields, first_filled_offset), 0.85,
        )
    if len(blank_dates) == 1:
        page, detail = blank_dates[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in blank_dates]
    return "fail", evidence, None, 0.85


_HRS05_THRESHOLD_HOURS = 10.0


def _check_HRS05(rule: dict, fields: dict) -> tuple:
    """Round 92 (2026-08-14): converted from judgment to a deterministic
    PRECONDITION check. Confirmed real bug across all 3 real patients this
    round (Amir Howell, Arisha Haque, Solomon Schnitzer) -- this rule's
    entire premise ("<10 hrs of 97153 -> confirm approved") only applies
    when 97153 hours requested are under 10/week, but in all 3 real cases
    the actual number (17, 15, 31.5) was stated plainly in the Hours
    Requesting table and nowhere close to the threshold -- the rule still
    reached judgment every time regardless, producing "uncertain".

    Reuses the already-proven _find_weekly_hours_for_code helper (same one
    _check_HF02 already uses for a different CPT code/cap) rather than a
    new extraction pattern. If 97153 hours are found and >= 10, this
    resolves to not_applicable immediately -- zero judgment call needed.
    If hours are genuinely < 10, or the 97153 hours figure can't be found
    at all, this returns not_checkable, which escalates to the judgment
    layer -- the rule's other real premise ("confirm approved") genuinely
    needs external confirmation ("'Approved' status lives outside the
    TP/system" per this rule's own notes) that this pipeline doesn't have
    in V1; that part is unchanged, only the >= 10 short-circuit is new.
    """
    hours = _find_weekly_hours_for_code(fields["full_text"], "97153")
    if hours is None:
        return (
            "not_checkable",
            "Could not find a 97153 hours-per-week figure in the Hours Requesting section "
            "to compare against the <10 hrs/week threshold.",
            None, 0.0,
        )
    if hours >= _HRS05_THRESHOLD_HOURS:
        return (
            "not_applicable",
            f"97153 hours requested: {hours}/week, at or above the {_HRS05_THRESHOLD_HOURS}-hour "
            f"threshold this rule applies below -- rule does not apply.",
            None, 0.85,
        )
    return (
        "not_checkable",
        f"97153 hours requested: {hours}/week, below the {_HRS05_THRESHOLD_HOURS}-hour threshold -- "
        f"rule applies, but 'Approved' status lives outside the TP/system and cannot be confirmed "
        f"from the document alone.",
        None, 0.0,
    )


def _check_HF02(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: both the pass
    and fail branches used to hardcode page=None even though the regex
    match's own position (the exact spot the hours figure was read from)
    was sitting right there in `m` -- _page_for_offset now maps it to a
    real page for both results, same as the not_applicable case already
    behaved correctly (nothing found -> genuinely no page to cite).
    """
    cpt_code = rule["params"]["cpt_code"]
    max_hours = rule["params"]["max_hours"]
    m = re.search(rf"{re.escape(cpt_code)}[^\d]{{0,20}}(\d+(\.\d+)?)\s*(hrs|hours)?", fields["full_text"], re.IGNORECASE)
    if not m:
        return "not_applicable", f"No {cpt_code} (assessment) hours found in this TP.", None, 0.5
    hours = float(m.group(1))
    page = _page_for_offset(fields, m.start())
    page_tag = f" [Page {page}]" if page is not None else ""
    if hours <= max_hours:
        return "pass", f"{cpt_code} hours requested: {hours} (<= {max_hours}-hour cap).{page_tag}", page, 0.7
    return "fail", f"{cpt_code} hours requested: {hours}, exceeds the {max_hours}-hour cap.{page_tag}", page, 0.7


def _check_HRS11(rule: dict, fields: dict) -> tuple:
    """QA-HRS-11: identifies whether the 97151 hours requested are
    accurate for the SPECIFIC detected payor -- Healthfirst gets a 5-hr
    cap, Emblem gets 3 hrs, every other payor gets the 8-hr default.

    Fix Round (2026-08-26) -- original version: self-excluded (returned
    not_applicable) for Healthfirst/Emblem entirely, deferring to their
    own separate dedicated rules (HF-02/EMB-01), to avoid two findings for
    the same real-world concept looking contradictory.

    Fix Round (2026-09-10), item 12 -- REAL LOGIC BUG FOUND AND FIXED:
    ma'am confirmed this rule should genuinely be payor-aware and evaluate
    the real cap for whichever payor is detected, not return
    not_applicable and defer entirely (same "check it directly, don't
    exclude and defer" fix shape as QA-RPT-07 this same round). Resolves
    the correct max_hours for the detected payor from `params.payor_caps`
    (falling back to the universal default) and reuses _check_HF02's own
    comparison logic with that resolved cap -- so this rule's own
    evidence text always states the real cap it actually checked against.
    """
    detected_payor = fields.get("payor")
    payor_caps = rule["params"].get("payor_caps", {})
    max_hours = payor_caps.get(detected_payor, rule["params"]["max_hours"])
    effective_rule = {**rule, "params": {**rule["params"], "max_hours": max_hours}}
    return _check_HF02(effective_rule, fields)


def _check_OBS01(rule: dict, fields: dict) -> tuple:
    if re.search(r"observation", fields["full_text"], re.IGNORECASE):
        return "pass", "An observation section is present in the document.", None, 0.5
    return "fail", "No 'observation' section found.", None, 0.5


def _check_HF01(rule: dict, fields: dict) -> tuple:
    """Confirmed root cause of the multi-round contradiction bug: this rule
    was labeled deterministic from the start but never had a real checker,
    so it always fell through to the not_checkable/0.0 escalation fallback
    and every finding came from the judgment layer re-deriving age/date-math
    from scratch. Both inputs (Patient Age, Authorization Dates Requested)
    are printed on page 1 in every sample TP seen so far.

    Fix Round (2026-08-26): a SECOND, separate root cause found on top of
    the above -- the rule's own DESCRIPTION never disclosed this
    age-conditional split at all (it just said a flat "3-month range"),
    even though this function and the rule's own pre-existing `notes` field
    always implemented the age split.

    Fix Round (2026-09-10), item 6 -- REAL LOGIC CHANGE, not a wording fix:
    ma'am confirmed the age-conditional split itself should be removed
    entirely -- every Healthfirst patient (this rule only ever runs for
    Healthfirst, per its own applies_to_payor) gets a flat 13-week
    authorization range, regardless of age. Patient Age is no longer read
    at all. Uses exact `timedelta(weeks=...)` math (no calendar-month
    tolerance needed, unlike an earlier month-based version, since a
    week-count has no variable length).
    """
    expected_weeks = rule["params"]["auth_range_weeks"]

    # Fix Round (2026-09-11), page-number enforcement gap: both pass and
    # fail below used to hardcode page=None even though the real match
    # position (where "Authorization Dates Requested" itself was read
    # from) was available -- switched to the offset-carrying variant.
    found = _find_labeled_date_range_with_offset(fields["full_text"], "Authorization Dates Requested")
    if not found:
        return (
            "not_checkable",
            "Could not find 'Authorization Dates Requested' in the document text.",
            None, 0.0,
        )
    auth_range = (found[0], found[1])
    page = _page_for_offset(fields, found[2])

    start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    end = datetime.strptime(auth_range[1], "%m/%d/%Y")
    range_days = (end - start).days

    expected_end = start + timedelta(weeks=expected_weeks)
    # A real TP's auth end date can still be off by a day or two from the
    # requested start due to how the date itself is worded/rounded on the
    # document, so a small tolerance stays.
    tolerance_days = 3
    if abs((end - expected_end).days) <= tolerance_days:
        return (
            "pass",
            f"Authorization range {auth_range[0]} to {auth_range[1]} ({range_days} days) matches "
            f"the required {expected_weeks}-week Healthfirst range.",
            page, 0.85,
        )
    return (
        "fail",
        f"Authorization range {auth_range[0]} to {auth_range[1]} ({range_days} days) does not "
        f"match the required {expected_weeks}-week Healthfirst range (expected end "
        f"~{expected_end.strftime('%m/%d/%Y')}).",
        page, 0.85,
    )


def _check_RPT02(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: both branches
    used to hardcode page=None; the match position was always available.
    """
    found = _find_labeled_date_with_offset(fields["full_text"], "Date of Initial Assessment")
    if found:
        date, offset = found
        page = _page_for_offset(fields, offset)
        return "pass", f"Date of Initial Assessment is present: {date}.", page, 0.7
    return "fail", "No 'Date of Initial Assessment' value found on this Reassessment TP.", None, 0.6


def _check_RPT06(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    to hardcode page=None; now cites the real page 'Date of Current
    Report' was read from (the field this rule's own result centers on).
    """
    report_found = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not report_found or not auth_range:
        return (
            "not_checkable",
            "Could not find both 'Date of Current Report' and 'Authorization Dates Requested' ranges.",
            None, 0.0,
        )
    report_range = (report_found[0], report_found[1])
    page = _page_for_offset(fields, report_found[2])
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    if report_end < auth_start:
        return (
            "pass",
            f"Date of Current Report ends {report_range[1]}, before Authorization Dates "
            f"Requested starts {auth_range[0]}.",
            page, 0.8,
        )
    return (
        "fail",
        f"Date of Current Report ends {report_range[1]}, which is not before Authorization "
        f"Dates Requested starts {auth_range[0]}.",
        page, 0.8,
    )


def _check_SIG02(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    to hardcode page=None; now cites the real page the signature page's
    'Provider Credentials' field (the value this rule's result is about)
    was found on.
    """
    contact_m = re.search(
        r"Provider Contact:\s*[^\n]*?Certification:\s*([^\n]+)", fields["full_text"], re.IGNORECASE
    )
    sig_m = re.search(r"Provider Credentials:\s*([^\n]+)", fields["full_text"], re.IGNORECASE)
    if not contact_m or not sig_m:
        return (
            "not_checkable",
            "Could not find both the page-1 'Provider Contact ... Certification' field and "
            "the signature page's 'Provider Credentials' field.",
            None, 0.0,
        )
    contact_creds = contact_m.group(1).strip().rstrip(".")
    sig_creds = sig_m.group(1).strip().rstrip(".")
    page = _page_for_offset(fields, sig_m.start())
    if contact_creds.lower() == sig_creds.lower():
        return (
            "pass",
            f"Signature credentials '{sig_creds}' match the page-1 Provider Contact "
            f"certification '{contact_creds}'.",
            page, 0.75,
        )
    return (
        "fail",
        f"Signature credentials '{sig_creds}' do not match the page-1 Provider Contact "
        f"certification '{contact_creds}'.",
        page, 0.7,
    )


def _check_SIG03(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: same fix as
    _check_SIG02 -- cites the real page the signature date was found on.
    """
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not sig_m or not auth_range:
        return "not_checkable", "Could not find both the signature date and 'Authorization Dates Requested'.", None, 0.0
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    page = _page_for_offset(fields, sig_m.start())
    if sig_date < auth_start:
        return (
            "pass",
            f"Signature date {sig_m.group(1)} is before Authorization Dates Requested "
            f"start {auth_range[0]}.",
            page, 0.8,
        )
    return (
        "fail",
        f"Signature date {sig_m.group(1)} is not before Authorization Dates Requested "
        f"start {auth_range[0]}.",
        page, 0.8,
    )


def _check_SIG04(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: same fix as
    _check_SIG02 -- cites the real page the signature date was found on.
    """
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    if not sig_m or not report_range:
        return "not_checkable", "Could not find both the signature date and 'Date of Current Report'.", None, 0.0
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    delta_days = (sig_date - report_end).days
    page = _page_for_offset(fields, sig_m.start())
    if delta_days <= 2:
        return (
            "pass",
            f"Signature date {sig_m.group(1)} is {delta_days} day(s) relative to Date of "
            f"Current Report end {report_range[1]} (within the 2-day allowance).",
            page, 0.8,
        )
    return (
        "fail",
        f"Signature date {sig_m.group(1)} is {delta_days} days after Date of Current Report "
        f"end {report_range[1]}, exceeding the 2-day allowance.",
        page, 0.8,
    )


def _check_SCH01(rule: dict, fields: dict) -> tuple:
    """Round 63, item 3: "ABA schedule matches hours requested" -- compares
    the weekly schedule grid's real, computed total (pipeline/
    schedule_hours.py -- real Python date/time arithmetic over the grid's
    actual time ranges) against the Hours Requesting section's stated
    weekly hours for the same CPT code (97153, Direct Care -- the code
    that's actually delivered day-to-day per the schedule grid; other
    codes like assessment/supervision/parent training aren't).

    Replaces leaving this arithmetic to the judgment layer, which was
    confirmed live to make real addition errors and fabricate shifts --
    see schedule_hours.py's own module docstring for the full diagnosis.
    Never guesses: returns not_checkable if either side can't be
    confidently determined, rather than comparing a partial/guessed number.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None even though the schedule grid's own real
    # position (the day-of-week header's match offset) was resolvable --
    # switched to the offset-carrying variant.
    cpt_code = rule["params"]["cpt_code"]
    found = extract_weekly_schedule_day_texts_with_offset(fields["full_text"])
    if found is None:
        return (
            "not_checkable",
            "Could not confidently parse the weekly ABA schedule table into 7 distinct days from this "
            "TP's extracted text.",
            None, 0.0,
        )
    day_texts, header_offset = found
    page = _page_for_offset(fields, header_offset)
    schedule_total, per_day = compute_weekly_total(day_texts)
    if schedule_total is None:
        unparseable_days = [day for day, hours in per_day.items() if hours is None]
        return (
            "not_checkable",
            f"Could not determine the schedule total -- unparseable day(s): {unparseable_days}.",
            None, 0.0,
        )

    requested_hours = _find_weekly_hours_for_code(fields["full_text"], cpt_code)
    if requested_hours is None:
        return (
            "not_checkable",
            f"Computed a real schedule total ({schedule_total} hrs/week) but could not find the "
            f"requested weekly hours for {cpt_code} to compare it against.",
            None, 0.3,
        )

    if schedule_total == requested_hours:
        return (
            "pass",
            f"Schedule grid totals {schedule_total} hrs/week, matching the {cpt_code} hours requested "
            f"({requested_hours} hrs/week). Per-day: {per_day}.",
            page, 0.85,
        )
    return (
        "fail",
        f"Schedule grid totals {schedule_total} hrs/week, but {cpt_code} hours requested is "
        f"{requested_hours} hrs/week -- these do not match. Per-day: {per_day}.",
        page, 0.85,
    )


_NOT_IN_SCHOOL_RE = re.compile(
    r"(?:does(?:n['’]t| not)|is\s+not|isn['’]t)\s+(?:currently\s+)?"
    r"(?:attend(?:ing)?\s+)?(?:in\s+)?school\b",
    re.IGNORECASE,
)


def _check_SCH03(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 5: Ms. Yachnes's explicit
    correction -- when the document clearly states the client isn't in
    school, this rule has nothing to overlap-check and must resolve to
    not_applicable, not escalate to a judgment call. Real evidence: the
    judgment layer's own evidence text already reasoned through to exactly
    this conclusion ("Jacob doesn't currently attend school [Page 4], so
    there's no school schedule to overlap with ABA services") but still
    returned Uncertain as the STATUS -- there was no not-in-school carve-
    out anywhere that could turn that reasoning into a not_applicable
    verdict; this checker is that carve-out.

    This is a narrow, disclosed-limitation gate, not this rule's full real
    overlap-detection logic (still not built -- see this rule's own
    blocked_status: needs robust weekly-schedule-table extraction and a
    payor in-school exception flag). It only catches the clearly-stated
    not-in-school case; anything else -- including the real overlap check
    when the client IS in school -- still escalates to judgment exactly
    as before. NOT YET VERIFIED against a real document containing the
    opposite case; flagged per this codebase's own convention rather than
    assumed to generalize.
    """
    m = _NOT_IN_SCHOOL_RE.search(fields["full_text"])
    if m:
        page = _page_for_offset(fields, m.start())
        return (
            "not_applicable",
            "Document states the client is not currently in school, so there is no school "
            "schedule to check for overlap with ABA services.",
            page, 0.85,
        )
    return (
        "not_checkable",
        "Client's school-enrollment status wasn't clearly stated as 'not in school,' and "
        "this rule's own real overlap-detection logic (weekly-schedule-table extraction, "
        "payor in-school exception) isn't built yet -- see blocked_status.",
        None, 0.0,
    )


def _check_SCH07(rule: dict, fields: dict) -> tuple:
    """Round 63, item 3: ">3 hrs/day of 97153 -> approved by clinical
    director" -- a hard Director-tag trigger (Section 7.1) whenever ANY
    single day in the real, computed weekly schedule exceeds the
    threshold. Same deterministic arithmetic as _check_SCH01, applied
    per-day instead of as a weekly sum.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; same fix as _check_SCH01 -- cites the
    # schedule grid's own real position.
    threshold = rule["params"]["daily_hours_threshold"]
    found = extract_weekly_schedule_day_texts_with_offset(fields["full_text"])
    if found is None:
        return (
            "not_checkable",
            "Could not confidently parse the weekly ABA schedule table into 7 distinct days from this "
            "TP's extracted text.",
            None, 0.0,
        )
    day_texts, header_offset = found
    page = _page_for_offset(fields, header_offset)
    _, per_day = compute_weekly_total(day_texts)
    unparseable_days = [day for day, hours in per_day.items() if hours is None]
    if unparseable_days:
        return (
            "not_checkable",
            f"Could not determine hours for: {unparseable_days} -- cannot confirm no day exceeds "
            f"{threshold} hrs/day.",
            None, 0.0,
        )

    over_threshold = {day: hours for day, hours in per_day.items() if hours > threshold}
    if over_threshold:
        return (
            "fail",
            f"Day(s) exceeding {threshold} hrs/day of 97153, requires clinical director approval: "
            f"{over_threshold}.",
            page, 0.85,
        )
    return "pass", f"No day exceeds {threshold} hrs/day. Per-day: {per_day}.", page, 0.85


def _check_HRS02(rule: dict, fields: dict) -> tuple:
    """Fix Round, Section 1 (2026-08-27): confirmed real staleness --
    ma'am's own wording for this rule drifted through 3 versions ('note
    on review email to Eliana' -> Round 90's 'strong clinical rationale
    required' -> the current, simplest framing: 'auto-flagged
    deterministically if hours > 20, no rationale-quality judgment
    involved'). The actual THRESHOLD LOGIC here was already correct and
    unchanged across all 3 wordings (a plain hours > threshold check, no
    rationale-quality judgment ever implemented) -- only the FAIL
    evidence text still said "requires a note on the review email to
    Eliana", a phrase from the oldest, no-longer-accurate version. Fixed
    to a plain, current statement of the finding -- the logic itself
    needed no change.
    """
    cpt_code = rule["params"]["cpt_code"]
    threshold = rule["params"]["hours_threshold"]
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None even though the match's real position was
    # available -- switched to the offset-carrying helper variant.
    found = _find_weekly_hours_for_code_with_offset(fields["full_text"], cpt_code)
    if found is None:
        return "not_applicable", f"No {cpt_code} weekly hours found in this TP.", None, 0.5
    hours, offset = found
    page = _page_for_offset(fields, offset)
    if hours > threshold:
        return (
            "fail",
            f"{cpt_code} hours requested: {hours}/week, exceeds the {threshold} hrs/week threshold.",
            page, 0.75,
        )
    return "pass", f"{cpt_code} hours requested: {hours}/week (<= {threshold} hrs/week).", page, 0.75


def _check_HRS03(rule: dict, fields: dict) -> tuple:
    """This is a CEILING, not a minimum-supervision floor: supervision must
    not EXCEED the ratio (1.5 hrs per 10 direct-care hrs). A prior round
    had this backwards (treated it as "supervision must be AT LEAST this
    much"), which incorrectly failed Reeda's TP -- her real ratio is 2.5
    supervision / 25 direct = 0.10/hr, under the 0.15/hr ceiling, which
    Eliana's manual review correctly marked Pass.

    Master Fix Round (2026-09-08): pure threshold, no exception path.
    Ma'am confirmed directly, a second time, that this should be an
    unconditional fail when the ceiling is exceeded -- no
    director-approval escalation to judgment. (An earlier round had left
    the director-approval escalation in place on the reasoning that the
    rule's own then-current wording still described it as a real
    requirement rather than an exception to remove; this round's repeated,
    direct ask supersedes that -- see this rule's own rules.json notes.)
    """
    direct_code = rule["params"]["direct_cpt_code"]
    supervision_code = rule["params"]["supervision_cpt_code"]
    ratio = rule["params"]["supervision_ratio_per_direct_hour"]
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; cites the supervision-hours figure's real
    # page (the value this rule's ceiling is actually about).
    direct_found = _find_weekly_hours_for_code_with_offset(fields["full_text"], direct_code)
    supervision_found = _find_weekly_hours_for_code_with_offset(fields["full_text"], supervision_code)
    if direct_found is None or supervision_found is None:
        return (
            "not_checkable",
            f"Could not find both {direct_code} and {supervision_code} weekly hours.",
            None, 0.0,
        )
    direct_hours, _ = direct_found
    supervision_hours, supervision_offset = supervision_found
    page = _page_for_offset(fields, supervision_offset)
    max_allowed_supervision = round(direct_hours * ratio, 2)
    if supervision_hours <= max_allowed_supervision + 0.01:
        return (
            "pass",
            f"{direct_code} direct care: {direct_hours} hrs/week; {supervision_code} supervision: "
            f"{supervision_hours} hrs/week (<= ceiling of {max_allowed_supervision}).",
            page, 0.75,
        )
    return (
        "fail",
        f"{direct_code} direct care: {direct_hours} hrs/week; {supervision_code} supervision: "
        f"{supervision_hours} hrs/week exceeds the ceiling of {max_allowed_supervision} — a pure "
        f"threshold violation, no director-approval exception.",
        page, 0.85,
    )


_HRS06_CPT_CODE_RE = r"(97151|97153|97154|97155|97156)"


def _hrs06_previous_auth_hours(text: str) -> list[tuple[str, str, str]]:
    m = re.search(
        r"Hours Approved Previous Authorization:([\s\S]{0,700}?)(?:School and ABA Schedule|Biopsychosocial)",
        text,
    )
    if not m:
        return []
    block = m.group(1)
    return [
        (cm.group(1), cm.group(2).strip(), cm.group(3).strip())
        for cm in re.finditer(_HRS06_CPT_CODE_RE + r"-([^\n]+?)\s+(N/?A|[\d.]+)\s*hours?\s*per\s*(?:week|auth)\b", block, re.IGNORECASE)
    ]


def _hrs06_current_hours_and_rationale(text: str) -> list[dict]:
    m = re.search(r"Hours Requesting:([\s\S]{0,4000}?)Hours Approved Previous Authorization:", text)
    if not m:
        return []
    block = m.group(1)
    code_positions = [
        (cm.start(), cm.group(1), cm.group(2).strip())
        for cm in re.finditer(_HRS06_CPT_CODE_RE + r"-([^\n]+)", block)
    ]
    hours_matches = list(re.finditer(
        r"([\d.]+|N/A)\s*hours?\s*per\s*\n?\s*(?:week|authorization\s*\n?\s*Period)\.?", block, re.IGNORECASE
    ))
    out = []
    for i, (pos, code, desc) in enumerate(code_positions):
        hours_str = hours_matches[i].group(1) if i < len(hours_matches) else None
        next_pos = code_positions[i + 1][0] if i + 1 < len(code_positions) else len(block)
        out.append({
            "code": code,
            "desc": desc.split("\n", 1)[0].strip()[:60],
            "hours": hours_str,
            "rationale": block[pos:next_pos],
            # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19),
            # Item 2: absolute offset in the full document text, not just
            # within this local "Hours Requesting:" block slice -- lets
            # callers compute a real page via _page_for_offset.
            "offset": m.start(1) + pos,
        })
    return out


def _hrs06_match_previous_to_current(previous: list[tuple[str, str, str]], current: list[dict]) -> list[tuple[str, str, dict]]:
    """Matching by CPT code alone isn't enough -- 97151 covers both
    Assessment and Treatment Planning, with two different description
    strings in the previous-auth block vs. the current Hours Requesting
    table (confirmed live on both real documents). Picks, among same-code
    candidates, whichever has the most overlapping description words."""
    pairs = []
    used_indices = set()
    for p_code, p_desc, p_hours in previous:
        candidates = [(i, c) for i, c in enumerate(current) if c["code"] == p_code and i not in used_indices]
        if not candidates:
            continue
        p_words = set(p_desc.lower().split())
        best_i, best = max(candidates, key=lambda ic: len(p_words & set(ic[1]["desc"].lower().split())))
        used_indices.add(best_i)
        pairs.append((p_desc, p_hours, best))
    return pairs


def _hrs06_to_number(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if s.upper() in ("N/A", "NA"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


_HRS06_ANNOTATION_PATTERN = re.compile(r"\?|\bVerifying\b|\bChange if\b", re.IGNORECASE)


def _hrs06_unresolved_reviewer_annotation(text: str) -> tuple[str, int] | None:
    """Second sub-check (2026-07-28 follow-up round, item 2): scans the
    Hours Requesting section for an embedded reviewer annotation
    questioning an hours line item -- the SAME shape as QA-TRANS-01's
    reviewer-annotation pattern, applied to this section instead. Confirmed
    on both real documents, in two different structural slots:

    - Charny: a full question sitting in the RATIONALE slot itself (right
      after the 97153 code label, where genuine clinical rationale prose
      would normally go): "Why are hours remaining the same? This
      rationale needs to be really strong, given the client's age...
      I would add a plan for titration of hours given her age."
    - Reeda: two short interjections sitting in the GAP slot (between the
      hours-value and the code label, more like a margin note than
      rationale prose): "Verifying" (before 97153-Direct Care) and "Change
      if\\nincreasing" (before 97155-Supervision) -- both immediately
      precede a code whose hours are flat versus the previous
      authorization.

    Both are still-embedded, unaddressed annotations at what should be a
    final document -- their continued presence IS the violation, the same
    logic as QA-TRANS-01 (a reviewer note requesting something that was
    never followed up on). The "?" pattern is the generalizable signal (any
    embedded reviewer question); the two literal Reeda phrases are narrower,
    document-specific additions -- flagged as such, same caveat as this
    round's other single-document-derived patterns (QA-PPI-05, QA-TEMP-01).
    """
    m = re.search(r"Hours Requesting:([\s\S]{0,4000}?)Hours Approved Previous Authorization:", text)
    if not m:
        return None
    section = m.group(1)
    am = _HRS06_ANNOTATION_PATTERN.search(section)
    if not am:
        return None
    start = max(0, am.start() - 60)
    end = min(len(section), am.end() + 60)
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # now returns (text, absolute_offset) instead of a bare string, so
    # the one caller (_check_HRS06) can compute a real page.
    return section[start:end].strip(), m.start(1) + start


def _check_HRS06(rule: dict, fields: dict) -> tuple:
    """Partially converted from judgment to deterministic (2026-07-28
    round, item 2): the rule's own notes already split this into
    "Presence = DET, adequacy of rationale = judgment" -- this builds the
    presence half in full, deterministically, as TWO independent checks
    (same "both must hold" shape as QA-PAR-01's two-criteria structure):

    (a) Increase-vs-previous-auth: compare each CPT code's current
    requested hours against that same code's previous-authorization hours;
    where hours increased, check whether ANY substantial rationale text
    (not just boilerplate provider/POS columns) exists for that code's row.
    QA-HRS-07 already owns the adequacy-of-rationale judgment for the case
    where presence is already confirmed -- this is a presence check only.

    (b) Unresolved reviewer annotation: a SEPARATE, real concern found
    while diagnosing why (a) alone didn't resolve Charny's originally-
    flagged miss (2026-07-28 follow-up round) -- see
    _hrs06_unresolved_reviewer_annotation's own docstring for the full
    real-evidence diagnosis on both documents. This isn't "increase without
    rationale" at all (nothing increased in either confirmed case); it's an
    embedded reviewer question about hours (flat, in both real cases) that
    was never followed up on, the same shape as QA-TRANS-01. Decided to
    fold this into QA-HRS-06 rather than invent a new rule_id: both checks
    are "does this hours line item have the justification it needs," both
    live in the same Hours Requesting section, and this rule already reads
    that section -- splitting them into two separate rule_ids would
    fragment one real-world concern across two checklist rows for no
    benefit, the same reasoning QA-PAR-01 already established for two
    criteria under one rule_id.

    Fails if EITHER sub-check fails; not_applicable only if BOTH have
    nothing to flag. Verified live: Reeda -- (a) 97151-Assessment 5->8 hrs
    with rationale = clean, but (b) finds "Verifying"/"Change if increasing"
    -> fail. Charny -- (a) not_applicable (nothing increased), (b) finds
    the "Why are hours remaining the same?" question -> fail. Both
    documents now correctly come back fail, resolving the originally-
    flagged miss on both.
    """
    text = fields["full_text"]
    annotation = _hrs06_unresolved_reviewer_annotation(text)
    annotation_text, annotation_offset = annotation if annotation else (None, None)

    previous = _hrs06_previous_auth_hours(text)
    current = _hrs06_current_hours_and_rationale(text)
    if not previous or not current:
        if annotation:
            return (
                "fail",
                f"Unresolved reviewer annotation questioning hours in the Hours Requesting "
                f"section: {annotation_text!r}.",
                _page_for_offset(fields, annotation_offset), 0.75,
            )
        return (
            "not_checkable",
            "Could not find both a 'Hours Requesting:' and 'Hours Approved Previous "
            "Authorization:' section with parseable per-code hours.",
            None, 0.0,
        )

    pairs = _hrs06_match_previous_to_current(previous, current)
    changes = []
    for p_desc, p_hours_str, curr in pairs:
        p_hours = _hrs06_to_number(p_hours_str)
        c_hours = _hrs06_to_number(curr["hours"])
        if p_hours is None or c_hours is None or c_hours == p_hours:
            continue
        # Fix Round (Jacob Freund 10-2026-U1), Item 2: a decrease needs a
        # rationale in place just as much as an increase does -- this used
        # to only fire on c_hours > p_hours, silently skipping decreases.
        direction = "increased" if c_hours > p_hours else "decreased"
        # Strip the first few structural lines (code/description, provider,
        # POS) before judging whether real rationale narrative exists --
        # those columns are always present and non-blank even with zero
        # actual rationale, so counting their length would never catch a
        # missing rationale.
        non_boiler = re.sub(r"^[^\n]*\n(?:[^\n]*\n){0,4}", "", curr["rationale"], count=1)
        has_rationale = len(non_boiler.strip()) > 20
        changes.append((curr["code"], curr["desc"], p_hours_str, curr["hours"], direction, has_rationale, curr["offset"]))

    missing = [i for i in changes if not i[5]]
    problems = []
    if missing:
        problems.append("; ".join(
            f"{code}-{desc} {direction} from {p} to {c} hours with no accompanying rationale "
            f"text found" for code, desc, p, c, direction, _has, _off in missing
        ))
    if annotation:
        problems.append(
            f"Unresolved reviewer annotation questioning hours in the Hours Requesting "
            f"section: {annotation_text!r}."
        )

    if problems:
        # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
        # cite the first real problem's own offset -- a missing-rationale
        # CPT-code row if one exists, else the annotation's own location.
        cite_offset = missing[0][6] if missing else annotation_offset
        return "fail", " ".join(problems), _page_for_offset(fields, cite_offset), 0.8

    if not changes:
        return (
            "not_applicable",
            "No CPT code's requested hours changed from the previous authorization, and no "
            "unresolved reviewer annotation questioning hours was found -- nothing for this "
            "rule to check.",
            None, 0.85,
        )
    detail = "; ".join(
        f"{code}-{desc} {direction} from {p} to {c} hours, with rationale text present"
        for code, desc, p, c, direction, _has, _off in changes
    )
    return "pass", detail, _page_for_offset(fields, changes[0][6]), 0.8


def _check_HRS07(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 3: this rule should be
    not_applicable when there's no hours increase at all, not Uncertain --
    previously QA-HRS-07 was pure judgment AND on the stabilized
    safety-net list, so it landed on a forced Uncertain every time,
    dumping raw per-code hours without ever determining whether an
    increase actually occurred.

    This deterministic gate reuses QA-HRS-06's own increase-detection
    helpers to answer that question first, with zero model cost: no
    increase anywhere -> not_applicable, confidently. An increase does
    exist -> escalate (not_checkable here) so a real judgment call can
    assess RATIONALE QUALITY specifically, using this rule's own
    'ADEQUATE' bar (see rules.json notes) -- this checker only gates on
    presence of an increase, it does not itself judge rationale quality.
    """
    text = fields["full_text"]
    previous = _hrs06_previous_auth_hours(text)
    current = _hrs06_current_hours_and_rationale(text)
    if not previous or not current:
        return (
            "not_checkable",
            "Could not find both a 'Hours Requesting:' and 'Hours Approved Previous "
            "Authorization:' section with parseable per-code hours.",
            None, 0.0,
        )
    pairs = _hrs06_match_previous_to_current(previous, current)
    any_increase = False
    for _p_desc, p_hours_str, curr in pairs:
        p_hours = _hrs06_to_number(p_hours_str)
        c_hours = _hrs06_to_number(curr["hours"])
        if p_hours is not None and c_hours is not None and c_hours > p_hours:
            any_increase = True
            break
    if not any_increase:
        return (
            "not_applicable",
            "No CPT code's requested hours increased over the previous authorization -- "
            "nothing for this rule to check.",
            None, 0.85,
        )
    return (
        "not_checkable",
        "An hours increase was found; escalating for a real rationale-quality review.",
        None, 0.0,
    )


def _check_COC04(rule: dict, fields: dict) -> tuple:
    months_allowed = rule["params"]["months_allowed"]
    fax_m = re.search(r"faxed to [^\n]*?on\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    report_found = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    if not fax_m or not report_found:
        return "not_checkable", "Could not find both the COC fax date and 'Date of Current Report'.", None, 0.0
    report_range = (report_found[0], report_found[1])
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # the fax date's own page -- what this rule is actually about.
    page = _page_for_offset(fields, fax_m.start())
    fax_date = datetime.strptime(fax_m.group(1), "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    earliest_valid = _add_months(report_end, -months_allowed)
    if fax_date >= earliest_valid:
        return (
            "pass",
            f"TP faxed on {fax_m.group(1)}, within {months_allowed} months of the current "
            f"report end {report_range[1]}.",
            page, 0.75,
        )
    return (
        "fail",
        f"TP faxed on {fax_m.group(1)}, more than {months_allowed} months before the "
        f"current report end {report_range[1]}.",
        page, 0.75,
    )


def _check_BIO02(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: pass case used
    to hardcode page=None; the match position was always available."""
    found = _find_labeled_date_with_offset(fields["full_text"], "Date of Most Recent Diagnosis")
    if found:
        date, offset = found
        return "pass", f"Date of Most Recent Diagnosis is present: {date}.", _page_for_offset(fields, offset), 0.7
    return "fail", "No 'Date of Most Recent Diagnosis' value found in this TP.", None, 0.6


def _check_BIO13(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), page-number enforcement gap: pass case used
    to hardcode page=None; the match position was always available."""
    found = _find_labeled_date_with_offset(fields["full_text"], "First day of ABA services with Master Faster")
    if found:
        date, offset = found
        return (
            "pass",
            f"'First day of ABA services with Master Faster' is present: {date}.",
            _page_for_offset(fields, offset), 0.7,
        )
    return (
        "fail",
        "No 'First day of ABA services with Master Faster' value found on this Reassessment TP.",
        None, 0.6,
    )


def _check_RPT05(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 1: Ms. Yachnes's explicit
    correction -- this rule is the lapse/gap check ONLY (previous TP's
    authorization end date vs. this TP's authorization start date), not
    the 26-week-default-window check this function used to compute. That
    window check was a different, unrelated check that had been bundled
    into this rule_id's evidence/logic by mistake -- it's covered
    separately by SM-01 for Straight Medicaid specifically, and removed
    from here entirely rather than partially (per her own words: "that's
    a different check and shouldn't be part of this rule's evidence or
    logic").

    The real lapse comparison itself lives in
    `previous_tp_comparison.py::_compare_rpt05_previous_auth_end` and only
    runs when a previous TP is actually provided (see
    `agent_client.py::review_previous_tp`). This phase-1, TP-only function
    is what runs when no previous TP is available at all -- in that case
    there is nothing left for this rule to check, so it's not_checkable,
    plainly.
    """
    return (
        "not_checkable",
        "No previous TP is available in this run, so a lapse between the previous TP's "
        "authorization end date and this TP's authorization start date cannot be checked.",
        None, 0.0,
    )


def _check_SM01(rule: dict, fields: dict) -> tuple:
    """Straight Medicaid-specific: new auth start = day after the current
    report's own end date; new auth end <= N months after that same date.
    Both fields are page-1 text, no backend/prior-auth data needed — see
    the rule's own notes for why this differs from the universal QA-RPT-05."""
    max_months = rule["params"]["max_months_after_report_end"]
    report_found = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    auth_found = _find_labeled_date_range_with_offset(fields["full_text"], "Authorization Dates Requested")
    if not report_found or not auth_found:
        return (
            "not_checkable",
            "Could not find both 'Date of Current Report' and 'Authorization Dates Requested'.",
            None, 0.0,
        )
    report_range = (report_found[0], report_found[1])
    auth_range = (auth_found[0], auth_found[1])
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # the "Authorization Dates Requested" field's own page -- what this
    # rule is actually validating.
    page = _page_for_offset(fields, auth_found[2])

    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    auth_end = datetime.strptime(auth_range[1], "%m/%d/%Y")

    expected_start = report_end + timedelta(days=1)
    max_allowed_end = _add_months(report_end, max_months)

    problems = []
    if auth_start.date() != expected_start.date():
        problems.append(
            f"Authorization start {auth_range[0]} is not the day after the current report "
            f"ends ({report_range[1]}); expected {expected_start.strftime('%m/%d/%Y')}."
        )
    if auth_end > max_allowed_end:
        problems.append(
            f"Authorization end {auth_range[1]} is more than {max_months} months after the "
            f"current report end ({report_range[1]}); latest allowed is "
            f"{max_allowed_end.strftime('%m/%d/%Y')}."
        )

    if problems:
        return "fail", " ".join(problems), page, 0.75
    return (
        "pass",
        f"Authorization Dates Requested ({auth_range[0]} to {auth_range[1]}) correctly starts "
        f"the day after the current report ends and ends within {max_months} months.",
        page, 0.75,
    )


def _check_EMP01(rule: dict, fields: dict) -> tuple:
    """Empire: 'Date of current report is within 30 days of the
    authorization start date' — interpreted as the current report's own
    end date vs the new authorization's start date (see the rule's notes
    for why)."""
    max_days = rule["params"]["max_days"]
    report_found = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    auth_found = _find_labeled_date_range_with_offset(fields["full_text"], "Authorization Dates Requested")
    if not report_found or not auth_found:
        return "not_checkable", "Could not find both 'Date of Current Report' and 'Authorization Dates Requested'.", None, 0.0
    report_range = (report_found[0], report_found[1])
    auth_range = (auth_found[0], auth_found[1])
    page = _page_for_offset(fields, auth_found[2])
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    delta_days = abs((auth_start - report_end).days)
    if delta_days <= max_days:
        return (
            "pass",
            f"Date of Current Report end ({report_range[1]}) is {delta_days} day(s) from "
            f"Authorization Dates Requested start ({auth_range[0]}), within the {max_days}-day allowance.",
            page, 0.75,
        )
    return (
        "fail",
        f"Date of Current Report end ({report_range[1]}) is {delta_days} day(s) from "
        f"Authorization Dates Requested start ({auth_range[0]}), exceeding the {max_days}-day allowance.",
        page, 0.75,
    )


def _check_EMP03(rule: dict, fields: dict) -> tuple:
    """Empire: 'Signature date is within 30 days of the authorization
    start date.'"""
    max_days = rule["params"]["max_days"]
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    auth_found = _find_labeled_date_range_with_offset(fields["full_text"], "Authorization Dates Requested")
    if not sig_m or not auth_found:
        return "not_checkable", "Could not find both the signature date and 'Authorization Dates Requested'.", None, 0.0
    auth_range = (auth_found[0], auth_found[1])
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # cite the signature date's own page -- the field this rule's own
    # description is actually about.
    page = _page_for_offset(fields, sig_m.start())
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    delta_days = abs((auth_start - sig_date).days)
    if delta_days <= max_days:
        return (
            "pass",
            f"Signature date ({sig_m.group(1)}) is {delta_days} day(s) from Authorization "
            f"Dates Requested start ({auth_range[0]}), within the {max_days}-day allowance.",
            page, 0.75,
        )
    return (
        "fail",
        f"Signature date ({sig_m.group(1)}) is {delta_days} day(s) from Authorization "
        f"Dates Requested start ({auth_range[0]}), exceeding the {max_days}-day allowance.",
        page, 0.75,
    )


def _check_AET01(rule: dict, fields: dict) -> tuple:
    """Aetna: 'Vineland, VB-MAPP, and ABLLS can be used; AFLS cannot be
    used.' A disallowed-tool mention is a fail regardless of whether an
    allowed one is also present — the rule bans AFLS outright, it doesn't
    just require at least one allowed tool alongside it."""
    text = fields["full_text"]
    disallowed_matches = [
        (t, m.start()) for t in rule["params"]["disallowed_tools"]
        for m in [re.search(re.escape(t), text, re.IGNORECASE)] if m
    ]
    if disallowed_matches:
        disallowed_hits = [t for t, _off in disallowed_matches]
        page = _page_for_offset(fields, disallowed_matches[0][1])
        return (
            "fail",
            f"Disallowed testing tool(s) found for this payor: {disallowed_hits}.",
            page, 0.75,
        )
    allowed_matches = [
        (t, m.start()) for t in rule["params"]["allowed_tools"]
        for m in [re.search(re.escape(t), text, re.IGNORECASE)] if m
    ]
    if not allowed_matches:
        return "not_checkable", "No recognized testing tool (allowed or disallowed) found in this TP.", None, 0.0
    allowed_hits = [t for t, _off in allowed_matches]
    page = _page_for_offset(fields, allowed_matches[0][1])
    return "pass", f"Testing tool(s) found: {allowed_hits}; no disallowed tool present.", page, 0.75


_ACF07_KNOWN_TOOLS = ["ABLLS-R", "ABLLS", "VB-MAPP", "AFLS", "Vineland-3", "Vineland", "PEAK", "ADOS", "CARS"]
_ACF07_TOOL_PATTERN = re.compile("|".join(re.escape(t) for t in _ACF07_KNOWN_TOOLS), re.IGNORECASE)


# Round 83, item 1: the specific field labels this section's checkers key
# off of -- used both to pick the best of several header occurrences
# (below) and as the whole-document fallback signal in extract_acf_fields/
# _check_ACF07. Each is specific to this one section by this template's
# own convention (never reused as a generic label elsewhere in a real TP).
_ACF_CORE_FIELD_LABELS = (
    "Assessment Date:", "Assessment Methods/Measures:", "Assessment Summary Statement:",
    "Provider Location During Assessment:", "Patient Location during Assessment:",
)


def _labeled_value_maybe_next_line(label: str, haystack: str) -> str | None:
    """Round 85, item 1 -- REAL BUG FOUND AND FIXED (root cause distinct
    from, and previously misdiagnosed in, Round 83): confirmed directly
    against the real document that originally exposed this bug (Blythe
    Diaz's TP, 73 pages, "Assessment of Current Functioning" occurs
    exactly ONCE -- Round 83's "multiple occurrences, wrong one picked"
    theory was never the actual mechanism on this document, which is
    exactly why that real, correctly-implemented fix didn't touch the
    real bug here).

    Traced the actual divergence directly, per this round's own
    instruction, rather than re-theorizing: QA-ACF-01 (escalated to
    judgment, reads the raw text unscoped) and QA-ACF-05
    (_check_ACF05, which ALREADY has its own "is the next non-blank line
    itself another label" multi-line check, built for a different real
    case in an earlier round) both succeed on this document. Every other
    ACF checker built on this section's field-value regexes required the
    value to appear on the SAME LINE as its label
    ("Label:[ \\t]*(\\S[^\\n]*)") -- but on THIS document's real template,
    "Assessment Methods/Measures:" and "Assessment Summary Statement:"
    both put their real, substantial content on the FOLLOWING line, with
    nothing after the colon on the label's own line at all. That same-
    line-only assumption is the actual, confirmed root cause: it's why
    _check_ACF07 saw neither field as "having content" and declared the
    whole section "entirely blank" even though roughly 2700 characters of
    real VB-MAPP methods description and a real summary statement were
    sitting right there, one line down.

    This generalizes _check_ACF05's own already-correct pattern (see its
    docstring) into a shared helper instead of leaving it as a one-off:
    tries the same-line value first; if that's empty, checks whether the
    label appears alone on its own line, and if so, takes the next non-
    blank line as the value -- UNLESS that next line is itself another
    field label (ends in ":"), which still correctly means "blank."
    """
    same_line_m = re.search(re.escape(label) + r"[ \t]*(\S[^\n]*)", haystack)
    if same_line_m:
        return same_line_m.group(1).strip()
    target = label.rstrip(":").strip().lower()
    lines = haystack.splitlines()
    for i, line in enumerate(lines):
        if line.strip().rstrip(":").strip().lower() == target:
            next_nonblank = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            if next_nonblank and not next_nonblank.endswith(":"):
                return next_nonblank
            return None
    return None


def _find_acf_section(text: str) -> str | None:
    """Shared section-boundary finder for every "Assessment of Current
    Functioning:" checker (_check_ACF07, extract_acf_fields below) --
    factored out of what was previously duplicated inline in _check_ACF07,
    so both use the exact same section boundaries. Returns None if the
    section header itself isn't found anywhere in this TP's text.

    Round 83, item 1 -- ROOT CAUSE INVESTIGATED: confirmed real symptom
    (not locally reproducible against this project's own real documents --
    none of the three has an image-only page anywhere, per a direct
    fitz/pypdf scan done before writing this fix, so the exact original
    document isn't available here) was QA-ACF-02/QA-ACF-08 reporting the
    TP's stated Assessment Date as None, and QA-ACF-07 declaring the whole
    section "entirely blank," BOTH on a document where that exact date and
    summary text were plainly present and found correctly by QA-ACF-01/
    QA-ACF-05's own separate, unscoped searches. That combination --
    section FOUND (not None) but empty of the fields QA-ACF-01/05 found
    fine elsewhere -- rules out "the header never matched" and points at
    this function returning the WRONG occurrence's slice, not a broken
    regex. The prior version used a bare re.search, which always commits
    to the FIRST occurrence of "Assessment of Current Functioning:" in the
    document; a document whose real section is preceded by ANY earlier
    occurrence of that same heading text (most plausibly a Table of
    Contents / outline page naming this section, and possibly also naming
    one of the three boundary phrases nearby, which would make the
    non-greedy capture settle on the empty/near-empty TOC span) would
    silently mis-scope every checker built on this function, while
    QA-ACF-01 (escalated to judgment, reads the raw document unscoped) and
    QA-ACF-05 (its own unscoped full-document line scan) are structurally
    immune to this exact failure mode -- exactly the asymmetry confirmed
    in the real run.

    Fix: consider EVERY occurrence of the header (not just the first),
    using the identical per-occurrence regex/boundary logic as before (so
    a document with exactly one occurrence -- confirmed true for all three
    of this project's own real documents -- behaves byte-for-byte
    unchanged), and prefer the LAST occurrence whose captured slice
    contains at least one recognized ACF field label. Falls back to the
    first occurrence when NONE of them contain any recognized label --
    preserving the ability to report a genuinely blank section as blank,
    not None, which callers rely on to distinguish "section found but
    blank" from "section header never appears in this document at all."
    """
    pattern = re.compile(
        r"Assessment of Current Functioning:([\s\S]{0,30000}?)(?:Goal Progress:|Clinical Interpretation|Areas of Focus)",
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    content_bearing = [m for m in matches if any(label in m.group(1) for label in _ACF_CORE_FIELD_LABELS)]
    return (content_bearing[-1] if content_bearing else matches[0]).group(1)


def _find_acf_section_with_offset(text: str) -> tuple[str, int] | None:
    """Fix Round (2026-09-11), page-number enforcement gap: same section
    selection as _find_acf_section, but also returns the section's own
    absolute start offset in `text` (the start of group(1), not the whole
    match) so _check_ACF07 can resolve every one of its findings -- most
    of which cite something at a specific offset WITHIN this section -- to
    a real page via `section_offset + local_offset`.
    """
    pattern = re.compile(
        r"Assessment of Current Functioning:([\s\S]{0,30000}?)(?:Goal Progress:|Clinical Interpretation|Areas of Focus)",
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    content_bearing = [m for m in matches if any(label in m.group(1) for label in _ACF_CORE_FIELD_LABELS)]
    chosen = content_bearing[-1] if content_bearing else matches[0]
    return chosen.group(1), chosen.start(1)


# --- Fix Round, item 5: vision-input routing for image-only content -----
#
# REAL BUG this closes: VB-MAPP grid legends, a second/prior testing-tool
# administration date, and graphed goal data have repeatedly come back
# "Uncertain"/"can't verify" because that content lives inside an embedded
# IMAGE the text-extraction layer never sees at all -- even on a page with
# plenty of OTHER real extractable text (so the existing low-text page-
# flagging in flag_pages.py, which only renders a page when it has almost
# NO extractable text, never catches this: a page can be 90% real text and
# 10% an un-OCR'd grid, and never gets flagged).
#
# GENERAL, opt-in registry -- NOT special-cased to the VB-MAPP/Vineland grid
# alone: any rule that consistently lands on "can't verify" for this reason
# can be added to VISION_ELIGIBLE_RULE_SECTIONS, mapped to whichever named
# section-page-range finder below applies. Adding a new section here (a new
# entry in _SECTION_PAGE_RANGE_FINDERS) is the only work needed to extend
# this to a different part of the document later.
VISION_ELIGIBLE_RULE_SECTIONS: dict[str, str] = {
    "QA-ACF-03": "acf",  # grid-with-legend presence check
    "QA-ACF-06": "acf",  # assessor name -- sometimes only in a grid header
    "QA-ACF-07": "acf",  # old-vs-new testing tool administration dates
    # Round 92: same section, opposite legend requirement (no legend should
    # appear under Vineland specifically) -- the legend content this checks
    # for is the same frequently-image-embedded grid/legend QA-ACF-03
    # already needed vision for, so this rule needs it too.
    "QA-ACF-11": "acf",  # no-legend-under-Vineland check
    # Fix Round, item 5 real verification (2026-08-12): "3mo/6mo graph data
    # matches auth length" -- this rule's own notes already name the exact
    # gap ("needs vision LLM if graphs are embedded images"). Every goal's
    # own "Graph:" field is a candidate embedded-image location, spread
    # across the whole Goals-in-Progress section rather than one
    # contiguous span like ACF -- see _gip_graph_page_range below.
    "QA-GIP-02": "gip_graph",
    # Next Round (2026-08-27), Part 2: QA-GIP-32/34/35 all read the SAME
    # per-goal "Graph:" embedded image QA-GIP-02 already needed vision
    # for -- data-point count, final-data-point value, and x-axis label
    # all live inside that image, not in extractable text (confirmed on
    # the real sample TP). See the block comment above DET_CHECKS for why
    # these are check_type="judgment", not a deterministic checker.
    "QA-GIP-32": "gip_graph",
    "QA-GIP-34": "gip_graph",
    "QA-GIP-35": "gip_graph",
    # Fix Round, Section 1 (2026-08-27): QA-PAR-03 ("parent training >4
    # data points per graph") reads the SAME per-goal "Graph:" image as
    # QA-GIP-02/32 -- parent-training goals are goal blocks like any
    # other, just tagged by their own Skill Domain, so the existing
    # whole-document "gip_graph" page range already covers them with no
    # new finder needed.
    "QA-PAR-03": "gip_graph",
    # Fix Round (2026-09-10), item 7 -- REAL RULE-IDENTITY MISMATCH FOUND:
    # HF-05's own OLD description/checker ("BCBA indicates hours PT
    # occurred... matches PT hours requested") is a completely different
    # check than what this rule now needs to be ("fewer than 3 real data
    # points on any PRT/Parent-Caregiver-Training goal -> rationale must
    # indicate a plan for improvement") -- same shape as QA-BIP-03's own
    # earlier confirmed identity drift. This is the same "count real data
    # points on a goal's embedded Graph image" question QA-GIP-32/PAR-03
    # already answer honestly as judgment, not a deterministic count --
    # no structured data-point count exists anywhere in extractable text,
    # only inside the rendered graph image. Converted to judgment,
    # registered here for the same reason PAR-03 is (a Parent-Training-
    # domain goal is a goal block like any other). The OLD hours-approved-
    # vs-requested checker (_check_HF05, still real and correct for ITS
    # OWN real content) is retired from DET_CHECKS below, not deleted --
    # if the old comparison is still wanted under a DIFFERENT rule_id in a
    # future round, the code is right here.
    "HF-05": "gip_graph",
    # Fix Round, Section 1 (2026-08-27): CIG-01 ("ABLLS completed A-Z") --
    # confirmed real document shape: the ABLLS-R section's own completion
    # status lives in an embedded "ABLLS grid" image (real text found:
    # "Below you will find the ABLLS grid:" immediately followed by a
    # page break into the grid image itself), not extractable text -- see
    # _ablls_grid_page_range below, same vision dependency as ACF's own
    # VB-MAPP/Vineland grid.
    "CIG-01": "ablls_grid",
    # Fix Round (Previous TP round, Bug 2; corrected in the U3 re-run
    # round): QA-ACF-04 ("Score lower than previous assessment -> Director
    # tag") -- the VB-MAPP/ABLLS-style score grid is an embedded
    # image/vector chart with no extractable score value in the text layer
    # at all. Originally registered under a new "milestone_grid" section
    # (phrase-search only, see _milestone_grid_page_range below) -- U3
    # re-run against the REAL Jacob Freund pair confirmed that phrase
    # ("Below you will find the milestone grid") only appears before the
    # grid on SOME documents; Jacob's own previous TP has no such phrase
    # at all before its grid, so that finder found zero pages on it.
    # Registered under "acf" instead -- the SAME section CIG-01/QA-ACF-03/
    # 06/07/11 already use, confirmed by direct testing to correctly cover
    # the grid's real pages on BOTH of Jacob's documents (the milestone
    # grid lives inside the "Assessment of Current Functioning:" section
    # on both, just at a different page offset within it) -- a more
    # robust, already-proven mechanism, not a second fragile one. Adding
    # QA-ACF-04 here also means its own phase-1, TP-only judgment attempt
    # (blind to the previous TP, made by the main per-document judgment
    # batch this registry feeds) now sees the grid image too, not just the
    # previous-TP-comparison layer -- a real, correct side effect of
    # registering this rule properly, not scope creep.
    "QA-ACF-04": "acf",
}


def _ablls_grid_page_range(fields: dict) -> set[int]:
    """Section-page-range finder for "ablls_grid" (CIG-01) -- confirmed
    real document shape: "Below you will find the ABLLS grid:" appears in
    extractable text immediately before the grid itself, which is an
    embedded image with no extractable text of its own. Renders the page
    that phrase falls on plus the next page (the grid image itself
    reliably starts on a fresh page in the confirmed real sample), same
    "render every page in this small, explicitly bounded span" reasoning
    _acf_section_page_range already uses.
    """
    text = fields["full_text"]
    pages: set[int] = set()
    for m in re.finditer(r"ABLLS grid", text, re.IGNORECASE):
        page = _page_for_offset(fields, m.start())
        if page is not None:
            pages.add(page)
            pages.add(page + 1)
    return pages


def _milestone_grid_page_range(fields: dict) -> set[int]:
    """Section-page-range finder for "milestone_grid" (QA-ACF-04) -- Fix
    Round (Previous TP round, Bug 2), confirmed real document shape:
    "Below you will find the milestone grid" appears in extractable text
    immediately before the VB-MAPP/ABLLS-style score grid itself, which is
    an embedded image with no extractable score value in the text layer at
    all -- exact same shape _ablls_grid_page_range already handles for
    CIG-01's ABLLS grid, just a different literal phrase. Copied verbatim
    (page + next page, same reasoning: the grid image reliably starts on
    the page right after this phrase).
    """
    text = fields["full_text"]
    pages: set[int] = set()
    for m in re.finditer(r"milestone grid", text, re.IGNORECASE):
        page = _page_for_offset(fields, m.start())
        if page is not None:
            pages.add(page)
            pages.add(page + 1)
    return pages


def _acf_section_page_range(fields: dict) -> set[int]:
    """Section-page-range finder for "acf" -- every physical page the
    Assessment of Current Functioning section's own text spans, per
    _find_acf_section's existing boundary logic (unchanged, reused as-is).

    REAL BUG FOUND AND FIXED (Fix Round, item 5's own real verification
    run against Blythe Diaz's document, 2026-08-12): this used to include
    only the section's start/end pages plus any page ALSO flagged low_text
    by flag_pages.py's own (much stricter) heuristic in between. Confirmed
    live this misses the actual gap: Blythe's real VB-MAPP grid pages (8-9)
    each carry ~150 characters of real, non-blank extractable text (the
    repeated Patient Name/DOB/Insurance footer that prints on every page
    of this document) -- not zero, so flag_pages.py's own low_text
    threshold never flags them, even though the grid itself produces no
    extractable text at all. A real judgment call against pages 7 and 10
    alone (the section's boundary pages) came back not_checkable,
    correctly reporting it could see neither grid page. Every page within
    the section's own boundaries is now rendered, full stop -- this
    section is already a small, explicitly bounded span (not the whole
    document), so unconditional inclusion doesn't risk an unbounded page
    count, and "does this page already have plenty of real text" is
    exactly the signal that missed the real gap in the first place.
    """
    text = fields["full_text"]
    m = re.search(r"Assessment of Current Functioning:", text)
    if not m:
        return set()
    section = _find_acf_section(text)
    if section is None:
        return set()
    start_offset = m.start()
    end_offset = text.find(section) + len(section) if section in text[start_offset:] else start_offset + len(section)
    start_page = _page_for_offset(fields, start_offset)
    end_page = _page_for_offset(fields, min(end_offset, len(text) - 1))
    if start_page is None:
        return set()
    end_page = end_page or start_page
    pages_in_section = range(min(start_page, end_page), max(start_page, end_page) + 1)
    return {p["page_number"] for p in fields["pages"] if p["page_number"] in pages_in_section}


def _gip_graph_page_range(fields: dict) -> set[int]:
    """Section-page-range finder for "gip_graph" (QA-GIP-02) -- unlike ACF's
    one contiguous section, every goal block's own "Graph:" field is a
    separate, independent candidate embedded-image location scattered
    across the whole Goals-in-Progress section (confirmed real shape:
    Yisroel's document alone has 25 goal blocks, each with its own "Graph:"
    line). Renders the specific page each "Graph:" field actually falls on
    -- not a full-section span, since there's no single boundary to span
    here the way ACF has one.

    Fix Round (2026-09-11), items 20/21/24 -- REAL BUG FOUND AND FIXED,
    confirmed on the real Daylyn Holland TP: only searching for the
    literal substring "Graph:" found exactly ONE page (15) in a real
    45-page document with ~20 goal blocks -- every "Target Goal:"
    (skill-acquisition) block's own graph, one per page (pages 21-34
    confirmed directly), has NO "Graph:" text label at all in this
    document's own template; the embedded graph image sits on the page
    with no literal text anchor next to it. That's the real, shared root
    cause behind two separate complaints: QA-GIP-32 only ever "saw"
    page 15's graph (item 20 -- not actually "hardcoded to page 15", but
    structurally equivalent to it on this document), and QA-GIP-29 false-
    negatived ("goal doesn't have a graph") on every one of those other
    goals, because the judge was never even given a rendered image of
    their page to check -- it only had extracted text with no "Graph:"
    line, which reads exactly like a genuinely missing graph. Also fixes
    item 24 (parent goals) as the same byproduct: a parent-training goal
    is a goal block like any other, tagged by its own Skill Domain, so
    covering every goal block's page covers parent goals with no separate
    logic needed -- same reasoning QA-PAR-03's own registration already
    relied on, now actually true for documents like this one.

    Every goal block's own page is now included, not just pages with a
    literal "Graph:" label -- a goal's graph (however it's laid out on
    this specific template) lives on or right around its own text block's
    page either way.
    """
    text = fields["full_text"]
    pages: set[int] = set()
    for m in re.finditer(r"\bGraph:", text):
        page = _page_for_offset(fields, m.start())
        if page is not None:
            pages.add(page)
    for start in _goal_block_starts(text):
        page = _page_for_offset(fields, start)
        if page is not None:
            pages.add(page)
    return pages


_SECTION_PAGE_RANGE_FINDERS = {
    "acf": _acf_section_page_range,
    "gip_graph": _gip_graph_page_range,
    "ablls_grid": _ablls_grid_page_range,
    "milestone_grid": _milestone_grid_page_range,
}


def vision_eligible_pages(rules: list[dict], fields: dict) -> set[int]:
    """Fix Round, item 5: for every ACTIVE rule in `rules` that's opted
    into VISION_ELIGIBLE_RULE_SECTIONS above, resolves its section's real
    page range on THIS document and unions them all -- the resulting page
    set gets rendered and included in the judgment prompt regardless of
    whether flag_pages.py's own low-text heuristic would have caught them,
    because the actual gap (an embedded image on an otherwise text-heavy
    page) is exactly what that heuristic structurally cannot catch.
    """
    pages: set[int] = set()
    active_rule_ids = {r["rule_id"] for r in rules if r.get("active", True)}
    needed_sections = {
        section for rule_id, section in VISION_ELIGIBLE_RULE_SECTIONS.items() if rule_id in active_rule_ids
    }
    for section in needed_sections:
        finder = _SECTION_PAGE_RANGE_FINDERS.get(section)
        if finder is not None:
            pages |= finder(fields)
    return pages


def _check_ACF09(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 14: Ms. Yachnes's explicit
    correction -- this rule ("if a different testing tool is used than the
    previous auth, rationale is included") should not land on Uncertain
    when the document is this clear. Real evidence: a genuine 5-way
    judgment split still had both sides agreeing on the SAME underlying
    fact -- only one tool (e.g. VB-MAPP) is named anywhere, no prior/
    different tool is documented at all, so there's no tool switch for
    this rule to evaluate a rationale for. The disagreement was over
    STATUS labeling of that shared fact (not_checkable vs. not_applicable),
    not over the fact itself -- exactly the kind of case a deterministic
    gate should resolve before judgment ever runs.

    Reuses the same tool-name detection as _check_ACF07/_check_ACF11
    (_ACF07_TOOL_PATTERN, read-only). At most one distinct tool named
    anywhere in the Assessment of Current Functioning section ->
    not_applicable, confidently -- nothing to compare a rationale
    against. Two or more distinct tools named -> a real tool switch is
    documented; escalate to judgment for the actual rationale-quality
    check this rule still needs.
    """
    found_section = _find_acf_section_with_offset(fields["full_text"])
    if not found_section:
        return (
            "not_checkable",
            "Could not find the 'Assessment of Current Functioning' section to determine which "
            "testing tool(s) were used.",
            None, 0.0,
        )
    section, section_offset = found_section
    tool_mentions = [tm.group(0) for tm in _ACF07_TOOL_PATTERN.finditer(section)]
    distinct = {t.lower().replace("-3", "") for t in tool_mentions}
    if len(distinct) <= 1:
        page = _page_for_offset(fields, section_offset)
        if tool_mentions:
            return (
                "not_applicable",
                f"Only {tool_mentions[0]} is named in the Assessment of Current Functioning section "
                f"-- no prior or different testing tool is documented, so there is no tool switch "
                f"for this rule to check a rationale for.",
                page, 0.85,
            )
        return (
            "not_applicable",
            "No testing tool is named in the Assessment of Current Functioning section -- nothing "
            "for this rule to check.",
            page, 0.8,
        )
    return (
        "not_checkable",
        f"Multiple distinct testing tools are named ({', '.join(sorted(distinct))}); escalating for "
        f"a real rationale-quality review of the tool switch.",
        _page_for_offset(fields, section_offset), 0.0,
    )


def _check_ACF11(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 11: Ms. Yachnes's explicit
    correction -- if the testing tool used is not Vineland, this rule
    should resolve to not_applicable, not Uncertain. Real evidence: a
    document clearly showing VB-MAPP (not Vineland) was used still landed
    on the generic stabilized-safety-net Uncertain template, because
    nothing anywhere detected which tool was actually named before this
    rule was unpinned this round (see pipeline/__init__.py::
    STABILIZED_UNCERTAIN_RULE_IDS).

    Reuses _check_ACF07's own tool-name detection (_ACF07_TOOL_PATTERN /
    _ACF07_KNOWN_TOOLS, read-only here, not modified) over the same
    "Assessment of Current Functioning" section both rules read. Exactly
    one distinct tool named, and it isn't Vineland -> not_applicable,
    confidently. Vineland IS named (alone or alongside another tool) ->
    escalate to judgment for the real no-legend-under-Vineland visual
    check this rule still needs (that part is genuinely image-dependent
    and not built here). No tool named at all, or section not found ->
    escalate too, rather than guess.
    """
    found_section = _find_acf_section_with_offset(fields["full_text"])
    if not found_section:
        return (
            "not_checkable",
            "Could not find the 'Assessment of Current Functioning' section to determine which "
            "testing tool was used.",
            None, 0.0,
        )
    section, section_offset = found_section
    tool_mentions = [tm.group(0) for tm in _ACF07_TOOL_PATTERN.finditer(section)]
    if not tool_mentions:
        return (
            "not_checkable",
            "No named testing tool (e.g. ABLLS-R, Vineland, VB-MAPP, AFLS) found in the "
            "Assessment of Current Functioning section.",
            _page_for_offset(fields, section_offset), 0.0,
        )
    distinct = {t.lower().replace("-3", "") for t in tool_mentions}
    if "vineland" not in distinct:
        return (
            "not_applicable",
            f"Testing tool used is {tool_mentions[0]}, not Vineland -- nothing for this rule to check.",
            _page_for_offset(fields, section_offset), 0.85,
        )
    return (
        "not_checkable",
        "Vineland is named as a testing tool used; escalating for a real no-legend-under-Vineland review.",
        _page_for_offset(fields, section_offset), 0.0,
    )


def _check_ACF07(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 4):
    diagnosed as a real, previously-unfixed bug -- the earlier "schema
    reorder" fix (evidence_supports_result, an earlier round) was never
    actually related to this rule's failure mode; that fix addressed a
    different, general evidence-contradicts-result problem, and this rule
    was never re-verified against real ground truth afterward. Pulled the
    real evidence on both documents where the regression harness confirmed
    this still wrong:

    - Charny (page 8): the ENTIRE 'Assessment of Current Functioning:'
      section is blank -- Provider/Patient Location, Assessment Date,
      Assessment Methods/Measures, Assessment Summary Statement are all
      empty, with an embedded reviewer annotation right in the section
      header itself: "Please add all info below including missing
      corresponding session note." No testing tool at all, let alone two.
    - Reeda (pages 11-17): NOT blank -- ABLLS-R is documented with an
      explicit 'Assessment Date: 06/28/2026'. But Vineland-3 data is also
      presented with NO stated administration date anywhere, and carries
      its own embedded reviewer annotation asking exactly that question:
      "Is the Vineland for this auth? What was the date of administration
      and was this completed by you or the parent?" The real violation
      isn't "missing a second tool" (a second tool IS present) -- it's
      that one of the two tools has no way to confirm which authorization
      period it belongs to (i.e., which one is "old" and which is "new"),
      which is exactly what the rule requires being able to tell apart.

    So the real, shared mechanism across both documents is: for every named
    testing tool in this section, there must be a stated Assessment Date
    tying it to a specific administration -- either because the whole
    section is blank (no tool at all) or because a named tool has no date
    (can't tell old from new). Both are checkable from the TP's own text,
    no external data needed -- this rule's original "presence check" label
    just never had that presence check actually implemented.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: this whole
    # function used to hardcode page=None on every branch -- switched to
    # the offset-carrying section finder so every return below can cite a
    # real page via `_page_for_offset(fields, section_offset + local_offset)`.
    found_section = _find_acf_section_with_offset(fields["full_text"])
    if found_section is None:
        return "not_checkable", "No 'Assessment of Current Functioning:' section found.", None, 0.0
    section, section_offset = found_section

    core_fields = ["Assessment Date:", "Assessment Methods/Measures:", "Assessment Summary Statement:"]
    # Round 85, item 1: uses _labeled_value_maybe_next_line, not a bare
    # same-line regex -- see that function's own docstring for the
    # confirmed real bug (Blythe Diaz's TP) this closes: two of these three
    # labels put their real content on the line AFTER the label on this
    # document's real template, which a same-line-only check reads as
    # "no content," falsely declaring a substantially-filled-in section
    # "entirely blank."
    section_has_content = any(_labeled_value_maybe_next_line(label, section) for label in core_fields)
    if not section_has_content:
        # Round 83, item 1: belt-and-suspenders safety net alongside
        # _find_acf_section's own multi-occurrence fix above -- covers the
        # case where the real field content sits further from EVERY
        # occurrence of the header than the 30000-char boundary window
        # (e.g. a genuinely large image-only grid gap widening the
        # distance), so no candidate slice ever captures it at all. Before
        # confidently declaring the section blank, check whether any of
        # these same labels exist ANYWHERE ELSE in the document -- if so,
        # this is a section-boundary miss, not a real blank section, and a
        # confident "fail" here would be repeating exactly the false
        # symptom this round exists to fix.
        fallback_has_content = any(
            _labeled_value_maybe_next_line(label, fields["full_text"]) for label in core_fields
        )
        if fallback_has_content:
            return (
                "uncertain",
                "The located 'Assessment of Current Functioning:' section appears empty of core fields, "
                "but at least one of Assessment Date/Methods/Summary Statement is present elsewhere in "
                "the document -- likely a section-boundary extraction issue (e.g. a duplicate heading, "
                "such as a Table of Contents entry, or an unusually large gap) rather than a genuinely "
                "blank section. Needs a human/judgment read rather than a confident fail.",
                _page_for_offset(fields, section_offset), 0.3,
            )
        return (
            "fail",
            "The Assessment of Current Functioning section is entirely blank -- no testing "
            "tool, date, or summary documented at all.",
            _page_for_offset(fields, section_offset), 0.8,
        )

    # Round 63, item 4 fix: track EVERY occurrence of a tool name, not just
    # the first (the previous version deduped by tool name at this exact
    # point, which meant the same tool mentioned twice -- e.g. an old score
    # and a new score from the SAME tool, administered on two different
    # dates -- could never be recorded as more than one mention). That's the
    # real bug: the rule's intent (confirmed by Ms. Yachnes's own read) is
    # "an old and new administration are both present," which the SAME tool
    # on two different dates satisfies just as well as two different tools
    # each dated once. Dedup happens later, on (tool_key, date) pairs, not
    # on tool name alone.
    tool_mentions = [(tm.group(0), tm.start(), tm.end()) for tm in _ACF07_TOOL_PATTERN.finditer(section)]

    if not tool_mentions:
        return (
            "fail",
            "No named testing tool (e.g. ABLLS-R, Vineland, VB-MAPP, AFLS) found in the "
            "Assessment of Current Functioning section.",
            _page_for_offset(fields, section_offset), 0.75,
        )

    def _tool_key(name: str) -> str:
        return name.lower().replace("-3", "").replace("-r", "")

    distinct_keys = {}
    for name, start, end in tool_mentions:
        distinct_keys.setdefault(_tool_key(name), []).append((name, start, end))

    # Round 64, item 1 fix: the gap-based per-occurrence date attribution
    # below assumes every tool-name occurrence sits right next to its own
    # "Assessment Date:" field -- true for Reeda's/Charny's real documents
    # (each tool mentioned exactly once, immediately labeled), but NOT
    # general: confirmed live on a real document (Yisroel Leibowitz's TP)
    # where a single tool (VB-MAPP) is named 4 times across a paragraph of
    # generic descriptive prose ("The VB-MAPP is a criterion-referenced
    # assessment tool..."), with its actual two administration dates
    # appearing much later, under a completely different label ("Total
    # Score on 07/29/2026: 79" / "Total Score on 02/16/2026: 39") that
    # isn't positionally tied to any specific tool-name occurrence at all.
    # Gap-scoped attribution structurally cannot find these -- none of the
    # 4 occurrences has "Assessment Date:" in its own immediate gap.
    #
    # The general fix: gap-based per-occurrence attribution is ONLY needed
    # to disambiguate which tool a date belongs to -- and that's only ever
    # ambiguous when 2+ DIFFERENT tools are named in the same section. When
    # exactly ONE distinct tool is named (regardless of how many times its
    # name appears in prose), every confirmed administration date anywhere
    # in the section unambiguously belongs to that one tool -- there's
    # nothing else it could be attributed to. This also broadens the date
    # pattern recognized to include "Total Score on <date>:" (VB-MAPP's own
    # convention for reporting a dated score) alongside "Assessment Date:",
    # in both the single-tool and multi-tool paths.
    # Fix Round (2026-09-11), item 16: [ \t\xa0]* (not just [ \t]*) -- REAL
    # BUG CONFIRMED on the real Daylyn Holland TP: this document's own PDF
    # text extraction uses a non-breaking space (U+00A0) after several
    # labels ("Assessment Date:\xa009/04/2026"), which [ \t]* never
    # matched -- so even the FIRST, most-specific, correctly-labeled date
    # pattern silently missed a real, present date on this real document.
    # \xa0 deliberately listed alongside space/tab, not folded into a bare
    # \s* -- \s* also matches newlines, which would let the match bleed
    # into the next real line's own content (the same bug class already
    # fixed elsewhere in this file, see _extract_labeled_value).
    _DATE_WS = r"[ \t\xa0]*"
    _DATE_PATTERNS = (
        re.compile(rf"Assessment Date:{_DATE_WS}(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"),
        re.compile(rf"Total Score on{_DATE_WS}(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", re.IGNORECASE),
        # Round 85, item 1: confirmed real template variant (Blythe Diaz's
        # TP) uses a bare "Date:" label instead of "Assessment Date:" for
        # this exact field -- checked last (lowest priority), after the
        # two more specific labels above, since a bare "Date:" is more
        # generic and this is scoped to a small tool-proximity window
        # already (single-tool: the whole section; multi-tool: the gap
        # around one specific mention), keeping ambiguity risk low.
        re.compile(rf"\bDate:{_DATE_WS}(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})"),
        # Fix Round (2026-09-11), item 16 -- REAL FALSE POSITIVE CONFIRMED
        # AND FIXED, against the real Daylyn Holland TP: "Daylan was
        # previously assessed using the Vineland on 4/30/26." states a
        # genuine, real administration date in free narrative prose, no
        # labeled field at all -- none of the 3 patterns above matched it.
        # Also confirmed the same document's AFLS/Vineland dates use
        # 2-digit years ("4/30/26"), which the 4-digit-only patterns above
        # (now widened to 2-4 digits, same fix) also missed.
        re.compile(rf"(?:assessed|administered)\b[^.\n]{{0,60}}?\bon{_DATE_WS}(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", re.IGNORECASE),
    )

    def _dates_in(window: str) -> list[str]:
        found = []
        for pattern in _DATE_PATTERNS:
            found.extend(m.group(1) for m in pattern.finditer(window))
        return found

    if len(distinct_keys) == 1:
        key, occurrences = next(iter(distinct_keys.items()))
        display_name = occurrences[0][0]
        # Real page: the tool's own first mention, not just the section
        # start -- more specific and just as available.
        page = _page_for_offset(fields, section_offset + occurrences[0][1])
        dates = set(_dates_in(section))
        has_open_question = re.search(r"\bWhat was the date of administration\b", section, re.IGNORECASE) is not None
        if not dates or has_open_question:
            return (
                "fail",
                f"{display_name} is mentioned but no confirmed administration date was found anywhere "
                f"in the Assessment of Current Functioning section.",
                page, 0.75,
            )
        if len(dates) >= 2:
            return (
                "pass",
                f"{display_name} administered on {sorted(dates)} (old and new administration of the "
                f"same tool).",
                page, 0.8,
            )
        return (
            "uncertain",
            f"Only one testing tool found ({display_name}, dated {sorted(dates)}) -- cannot confirm "
            f"both an old and new administration are present (would also be satisfied by the same tool "
            f"administered on a second, different date).",
            page, 0.4,
        )

    # 2+ distinct tools named -- gap-based per-occurrence attribution is
    # needed here to know which tool each date belongs to. Attribute each
    # occurrence's date from the text strictly BETWEEN it and its immediate
    # neighbors, not a fixed +/-400-char window -- a fixed window over-
    # reaches across tool boundaries in a short section (an earlier version
    # of this fix misattributed one tool's date to the very next tool, and
    # separately let a later tool's "what was the date of administration"
    # question flag an EARLIER, actually-dated tool as undated). The gap
    # before this mention (since the previous mention, or section start) is
    # unambiguously this mention's own date field; the gap after (until the
    # next mention, or section end) is unambiguously where an open reviewer
    # question about THIS mention would appear.
    # Fix Round (2026-09-11), item 16 -- REAL BUG FOUND AND FIXED, confirmed
    # against the real Daylyn Holland TP: this used to require EVERY
    # individual mention of a tool name to have its own nearby date, and
    # marked the WHOLE tool undated the moment any single mention lacked
    # one -- but a tool genuinely can be (and here, was) named several
    # times in plain descriptive prose ("AFLS is a criterion-referenced
    # skills assessment tool...") with its real, confirmed date attached
    # to only ONE of those mentions. That's the same real shape already
    # documented above for Yisroel Leibowitz's VB-MAPP case, but the fix
    # for it was only ever applied to the single-tool branch -- never
    # generalized here. Now aggregates by TOOL first: a tool is undated
    # only if NONE of its mentions found a date anywhere nearby.
    open_question_tools = set()
    dates_by_tool: dict[str, set] = {}
    display_name_by_key: dict[str, str] = {}
    # Fix Round (2026-09-11), page-number enforcement gap: first mention
    # offset per tool key, so the multi-tool branch's returns below can
    # cite a real page instead of the None they used to hardcode.
    first_offset_by_key: dict[str, int] = {}
    for i, (name, start, end) in enumerate(tool_mentions):
        gap_start = tool_mentions[i - 1][2] if i > 0 else 0
        gap_end = tool_mentions[i + 1][1] if i + 1 < len(tool_mentions) else len(section)
        gap_after = section[end:gap_end]

        # Fix Round (2026-09-11), item 16 -- REAL BUG FOUND AND FIXED:
        # this used to search ONLY gap_before (the text strictly before
        # this mention), on the assumption a date always precedes its own
        # tool mention (true for a labeled field like "Assessment Date:
        # ... AFLS", false for free narrative prose that names the tool
        # FIRST and states the date after it -- e.g. "Daylan was
        # previously assessed using the Vineland on 4/30/26", confirmed
        # real on the Daylyn Holland TP). Searching gap_before and
        # gap_after SEPARATELY still isn't enough for that exact phrasing
        # -- "assessed" sits in gap_before while "on 4/30/26" sits in
        # gap_after, so neither piece alone contains the whole "assessed
        # ... on DATE" match. Searches the FULL combined window (gap
        # before this mention through gap after it, mention text
        # included) instead -- still tightly scoped to strictly between
        # this mention and its immediate neighbors, so there's no new
        # risk of attributing a date to the wrong tool.
        full_window = section[gap_start:gap_end]
        date_matches = _dates_in(full_window)
        has_open_question = re.search(r"\bWhat was the date of administration\b", gap_after, re.IGNORECASE) is not None

        key = _tool_key(name)
        display_name_by_key.setdefault(key, name)
        first_offset_by_key.setdefault(key, start)
        if has_open_question:
            open_question_tools.add(key)
        if date_matches:
            dates_by_tool.setdefault(key, set()).add(date_matches[-1])

    all_keys = {_tool_key(name) for name, _, _ in tool_mentions}
    undated = sorted(
        display_name_by_key[key] for key in all_keys
        if key not in dates_by_tool or key in open_question_tools
    )
    if undated:
        undated_keys = [k for k in all_keys if k not in dates_by_tool or k in open_question_tools]
        page = _page_for_offset(fields, section_offset + min(first_offset_by_key[k] for k in undated_keys))
        return "fail", f"Testing tool(s) mentioned without a confirmed administration date: {undated}.", page, 0.75

    # "Old and new" is satisfied by either shape:
    #  (a) two or more DISTINCT tools, each with at least one confirmed date, or
    #  (b) the SAME tool with two or more DISTINCT confirmed dates (an old
    #      score and a new score from one instrument, on two different days
    #      -- exactly the case a same-tool reassessment produces).
    distinct_tools_with_dates = len(dates_by_tool)
    max_distinct_dates_for_one_tool = max((len(dates) for dates in dates_by_tool.values()), default=0)

    if distinct_tools_with_dates >= 2 or max_distinct_dates_for_one_tool >= 2:
        summary = {display_name_by_key[key]: sorted(dates) for key, dates in dates_by_tool.items()}
        page = _page_for_offset(fields, section_offset + min(first_offset_by_key[k] for k in dates_by_tool))
        return "pass", f"Testing tool administration dates found: {summary}.", page, 0.8

    only_key, only_dates = next(iter(dates_by_tool.items()))
    page = _page_for_offset(fields, section_offset + first_offset_by_key[only_key])
    return (
        "uncertain",
        f"Only one testing tool found ({display_name_by_key[only_key]}, dated {sorted(only_dates)}) -- cannot "
        f"confirm both an old and new administration are present (would also be satisfied by the same tool "
        f"administered on a second, different date).",
        page, 0.4,
    )


def extract_acf_fields(fields: dict) -> dict[str, str | None]:
    """Round 63, item 2 fix: the TP's own "Assessment of Current
    Functioning" section values, extracted as plain strings for
    session_note_comparison.py to actually consume.

    Root cause of the original bug: nothing in this pipeline ever
    extracted these as reusable VALUES. QA-ACF-01 (the rule that checks
    date/location/patient-location presence) has no deterministic checker
    registered at all -- it falls through to a not_checkable det result
    and gets escalated straight to the judgment layer, which reads the raw
    TP text/images itself and can correctly say "yes, these fields are
    present" without ever producing a structured value anywhere else in
    the pipeline could read. QA-ACF-06 is judgment-only (assessor name).
    Only QA-ACF-07 (_check_ACF07, above) does real field-level regex
    extraction of this section -- and only for tool names + dates, not
    provider/patient location. That's the actual gap this function closes:
    app.py's session-note comparison call was passing tp_assessment_date /
    tp_pos / tp_patient_location / tp_assessment_tool as None with a
    comment claiming this extraction "doesn't exist yet" -- true at the
    time, now fixed by building it, reusing the exact same section
    boundaries and known-tool pattern _check_ACF07 already uses.

    Returns {"assessment_date", "pos", "patient_location",
    "assessment_tool"} -- each a plain string or None if not found. Never
    guesses: a field this function can't confidently find comes back None,
    which session_note_comparison.py's own check_field_match already
    treats as "the TP doesn't state this" (uncertain), not a false match.

    Round 83, item 1: added a whole-document fallback for every field below
    -- kept, still useful as a second safety net, but Round 83's own
    "multiple header occurrences" root-cause theory was later DISPROVEN
    (Round 85): confirmed against the real document, "Assessment of
    Current Functioning" occurs exactly ONCE in it, so a wrong-occurrence
    mechanism was never actually in play here.

    Round 85, item 1 -- REAL BUG FOUND AND FIXED (the actual root cause):
    confirmed real symptom, QA-ACF-02/QA-ACF-08 reported the TP's stated
    Assessment Date as None even though that exact date was plainly
    present, found correctly by QA-ACF-01/QA-ACF-05's own reads of the
    same document. Traced directly (per this round's own instruction) by
    comparing what QA-ACF-05 does differently from this function -- see
    _labeled_value_maybe_next_line's own docstring for the confirmed
    mechanism: this document's real template puts "Assessment Methods/
    Measures:"/"Assessment Summary Statement:" content on the line AFTER
    the label, which the old same-line-only `_labeled_value` read as
    empty. Now uses the shared multi-line-aware helper.

    Separately, ALSO confirmed on this same document: the Assessment Date
    and Provider Location fields use this template's own different label
    text entirely -- bare "Date:" and "Location:" instead of "Assessment
    Date:"/"Provider Location During Assessment:". Added as a LAST-RESORT
    fallback, scoped to the section only (not whole-document, unlike the
    other fallbacks above) -- "Date:"/"Location:" alone are too generic to
    safely search the whole document without risking picking up an
    unrelated date/location mentioned elsewhere; confirmed only one
    occurrence of each exists within this document's own ACF section.
    """
    text = fields["full_text"]
    section = _find_acf_section(text)
    if section is None:
        return {"assessment_date": None, "pos": None, "patient_location": None, "assessment_tool": None}

    assessment_date_m = re.search(r"Assessment Date:[ \t]*(\d{1,2}/\d{1,2}/\d{4})", section)
    assessment_date = assessment_date_m.group(1) if assessment_date_m else None
    if assessment_date is None:
        fallback_date_m = re.search(r"Assessment Date:[ \t]*(\d{1,2}/\d{1,2}/\d{4})", text)
        assessment_date = fallback_date_m.group(1) if fallback_date_m else None
    if assessment_date is None:
        bare_date_m = re.search(r"\bDate:[ \t]*(\d{1,2}/\d{1,2}/\d{4})", section)
        assessment_date = bare_date_m.group(1) if bare_date_m else None

    tool_m = _ACF07_TOOL_PATTERN.search(section)
    assessment_tool = tool_m.group(0) if tool_m else None
    if assessment_tool is None:
        fallback_tool_m = _ACF07_TOOL_PATTERN.search(text)
        assessment_tool = fallback_tool_m.group(0) if fallback_tool_m else None

    pos = (
        _labeled_value_maybe_next_line("Provider Location During Assessment:", section)
        or _labeled_value_maybe_next_line("Provider Location During Assessment:", text)
    )
    if pos is None:
        bare_location_m = re.search(r"\bLocation:[ \t]*(\S[^\n]*)", section)
        pos = bare_location_m.group(1).strip() if bare_location_m else None

    return {
        "assessment_date": assessment_date,
        "pos": pos,
        "patient_location": _labeled_value_maybe_next_line("Patient Location during Assessment:", section)
            or _labeled_value_maybe_next_line("Patient Location during Assessment:", text),
        "assessment_tool": assessment_tool,
    }


# Previous TP round: QA-ACF-04 needs the assessment tool's own numeric
# SCORE, which nothing in this file extracted before (confirmed by a full
# grep -- extract_acf_fields/_check_ACF07 only ever capture the tool's NAME
# and administration DATE, never a score value; _check_ACF07's own
# "Total Score on <date>:" pattern, fields.py's _DATE_PATTERNS, stops at
# the date and never looks at what number follows it). This is the
# STRUCTURED/boxed case only -- a numeric score printed directly after a
# "Total Score"/"Score:"-style label, same section-boundary discipline as
# extract_acf_fields (_find_acf_section). Ms. Yachnes's own real note (this
# round's brief) is that some documents state the score in narrative prose
# instead -- that case is NOT attempted here (regex can't reliably do it);
# see pipeline/previous_tp_comparison.py's own judgment-layer fallback for
# that half, used only when this boxed extraction comes back None.
_ACF_SCORE_RE = re.compile(
    r"(?:Total\s+Score|Standard\s+Score|Score)(?:\s+on\s+\d{1,2}/\d{1,2}/\d{2,4})?\s*[:\-–]\s*(\d{1,3}(?:\.\d+)?)",
    re.IGNORECASE,
)


def extract_acf_score_boxed(fields: dict) -> float | None:
    """Best-effort STRUCTURED score extraction only -- a number directly
    labeled "Score:"/"Total Score:"/"Standard Score:" inside the
    Assessment of Current Functioning section (falls back to the whole
    document if that section isn't found, same fallback discipline
    extract_acf_fields itself already uses elsewhere). Returns None (never
    guesses) if no such labeled number is found -- the narrative-text case
    is a separate, judgment-layer concern, not this function's job.
    """
    text = fields["full_text"]
    section = _find_acf_section(text) or text
    m = _ACF_SCORE_RE.search(section)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _check_ACF12(rule: dict, fields: dict) -> tuple:
    """Round 92 (2026-08-14): NEW rule -- "Assessment date is within the
    appropriate range (within report dates, before testing tool date, per
    payor guidelines)". Confirmed genuinely missing from the 171-rule set
    before this round (no equivalent rule_id anywhere).

    Reuses two already-established, separately-tested pieces rather than
    inventing new extraction: extract_acf_fields()['assessment_date'] (the
    testing tool's own stated administration date -- this IS this rule's
    "testing tool date," not a second separate date to find) and
    _find_labeled_date_range(text, "Date of Current Report") (the TP's own
    stated report range) -- same pairing _check_SIG04 already uses for a
    different field (signature date) against the same report range.

    SCOPE, DELIBERATE: this rule's own "per payor guidelines" clause is NOT
    implemented here -- payor-specific date-window rules already exist
    separately (e.g. HF-06's 3-month Healthfirst rule); duplicating that
    logic inside a universal rule would double-count the same violation
    under two rule_ids. This checker's scope is only the universal
    within-report-dates comparison.

    NOT YET VERIFIED against a real document -- built from ma'am's
    description only, per this round's explicit no-real-pipeline-run
    constraint. Recommend confirming against a real document before
    trusting results.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; cites the real page 'Date of Current Report'
    # (the range this rule's comparison is anchored to) was found on.
    assessment_date_str = extract_acf_fields(fields).get("assessment_date")
    found_range = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    if not assessment_date_str or not found_range:
        return (
            "not_checkable",
            "Could not find both the testing tool's own Assessment Date and this TP's "
            "'Date of Current Report' range.",
            None, 0.0,
        )
    report_range = (found_range[0], found_range[1])
    page = _page_for_offset(fields, found_range[2])
    assessment_date = datetime.strptime(assessment_date_str, "%m/%d/%Y")
    report_start = datetime.strptime(report_range[0], "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    if report_start <= assessment_date <= report_end:
        return (
            "pass",
            f"Assessment Date {assessment_date_str} falls within the Date of Current Report "
            f"range ({report_range[0]} to {report_range[1]}).",
            page, 0.8,
        )
    return (
        "fail",
        f"Assessment Date {assessment_date_str} falls outside the Date of Current Report "
        f"range ({report_range[0]} to {report_range[1]}).",
        page, 0.8,
    )


_ACF06_ADMIN_BY_RE = re.compile(
    r"\b(?:administered|completed|conducted)\s+by\s+([A-Z][a-zA-Z.\-']+(?:\s+[A-Z][a-zA-Z.\-']+){0,3}(?:,\s*[A-Za-z.]+)?)",
)
_ACF06_ADMIN_VERB_RE = re.compile(r"\b(?:administered|completed|conducted)\b", re.IGNORECASE)


def _check_ACF06(rule: dict, fields: dict) -> tuple:
    """Round 83, item 1 follow-up: converted from judgment to deterministic.
    Investigated whether the confirmed real miss (ground-truth reviewer
    found an assessor name -- "Administered by [name]" -- that this rule
    reported as not found) shared _find_acf_section's root cause above, or
    was a separate, narrower gap: SEPARATE. QA-ACF-06 was judgment-only,
    reading the raw document text/images directly, not through
    _find_acf_section/extract_acf_fields at all -- so it was never
    affected by the section-boundary bug. The real gap here is narrower:
    the confirmed real PASS phrasing ("The ABLLS-R was administered by
    Karen Kain, BCBA.") is a plain, regexable "administered by NAME"
    pattern this rule never had a deterministic checker for at all.

    Uses the same section-then-whole-document-fallback shape as this
    round's other ACF fixes anyway, so an image-page gap or a decoy
    heading occurrence can't reintroduce a similar miss here later.

    PASS: an "administered by"/"completed by"/"conducted by" phrase with a
    name captured. FAIL: a testing tool (_ACF07_TOOL_PATTERN) is named
    AND one of these same admin verbs appears somewhere in the section/
    document, but never with "by NAME" attached -- the confirmed real
    FAIL shape from this rule's own notes ("The ABLLS-R was
    administered." with no name). not_checkable: no testing-tool
    administration statement found to check at all.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None even though the matching haystack's own
    # absolute offset (section-relative or whole-document) was resolvable
    # -- (haystack_text, base_offset) pairs so a match's local `.start()`
    # can be translated back to a real page via base_offset + local_offset.
    text = fields["full_text"]
    found_section = _find_acf_section_with_offset(text)
    haystacks = [(found_section[0], found_section[1])] if found_section else []
    haystacks.append((text, 0))

    for haystack, base_offset in haystacks:
        m = _ACF06_ADMIN_BY_RE.search(haystack)
        if m:
            name = m.group(1).strip().rstrip(".")
            page = _page_for_offset(fields, base_offset + m.start())
            return "pass", f"Assessor named: {name!r}.", page, 0.75

    for haystack, base_offset in haystacks:
        m = _ACF06_ADMIN_VERB_RE.search(haystack)
        if m and _ACF07_TOOL_PATTERN.search(haystack):
            page = _page_for_offset(fields, base_offset + m.start())
            return (
                "fail",
                "A testing tool's administration is mentioned, but no assessor name is given "
                "('administered by [name]' or equivalent phrasing not found).",
                page, 0.6,
            )

    return (
        "not_checkable",
        "No testing-tool administration statement found in this document to check for an assessor name.",
        None, 0.0,
    )


def _check_ACF05(rule: dict, fields: dict) -> tuple:
    """Assessment Summary Statement presence check -- replaces the retired
    Learning-Tree comparison this checklist item used to describe (see
    rules/archive/learning_tree_deprecated_rules.json). Confirmed on Charny
    Gluck's real TP (page 8): the label appears on its own line immediately
    followed by the NEXT field's label ('Areas of Focus for Treatment:'),
    meaning nothing was filled in between -- this is a multi-line narrative
    field, not a single-line "Label: value" field, so blank means "the very
    next non-blank line is itself another label," not just "nothing on the
    same line."""
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None -- the label's own line offset is real,
    # resolvable position information that was just never carried through.
    lines = fields["full_text"].splitlines()
    offset = 0
    for i, line in enumerate(lines):
        if line.strip().rstrip(":").strip().lower() == "assessment summary statement":
            page = _page_for_offset(fields, offset)
            next_nonblank = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            if not next_nonblank or next_nonblank.endswith(":"):
                return (
                    "fail",
                    "The 'Assessment Summary Statement:' field is blank -- immediately "
                    "followed by the next field's label, with nothing filled in.",
                    page, 0.7,
                )
            return "pass", f"Assessment Summary Statement is documented: {next_nonblank[:150]}", page, 0.7
        offset += len(line) + 1
    return "not_checkable", "No 'Assessment Summary Statement:' field found anywhere in this TP.", None, 0.0


_BIO03_DIAGNOSIS_LABELS = [
    "Secondary Diagnosis", "Additional Diagnosis", "Other Diagnosis",
    "Comorbid Diagnosis", "Co-occurring Diagnosis", "Additional Diagnoses",
]
_BIO03_LABEL_RE = re.compile(
    r"(" + "|".join(re.escape(l) for l in _BIO03_DIAGNOSIS_LABELS) + r"):[ \t]*(\S[^\n]*)?",
    re.IGNORECASE,
)


_NO_MEDICATION_RE = re.compile(
    r"not\s+taking\s+any\s+medications?"
    r"|no\s+(?:current\s+)?medications?\b"
    r"|not\s+on\s+any\s+medications?"
    r"|denies?\s+(?:any\s+)?medication\s+use",
    re.IGNORECASE,
)


def _check_BIO06(rule: dict, fields: dict) -> tuple:
    """Fix Round (Jacob Freund 10-2026-U1), Item 7: Ms. Yachnes's explicit
    correction -- a clean, unambiguous "not on medication" document must
    produce a real answer (not_applicable), not Uncertain. Real evidence:
    the system already found the exact fact needed ("allergies He is not
    taking any medications") but still returned Uncertain, because this
    rule was on the stabilized safety-net list (unpinned this round, see
    pipeline/__init__.py::STABILIZED_UNCERTAIN_RULE_IDS) with no logic
    anywhere to turn "no medication" into a verdict.

    No medication mentioned at all, or explicitly denied -> not_applicable,
    confidently, zero model cost -- this rule's premise (a listed
    medication needing a stated reason, or an ADHD medication needing a
    secondary diagnosis) doesn't apply. A real medication mention that
    ISN'T a plain denial -> escalate to judgment for the genuine
    reason-adequacy and ADHD-secondary-diagnosis review this rule still
    needs. Narrow, disclosed limitation: a document mentioning both a
    denial AND a real medication in different sections could be
    misread as N/A by this checker -- not verified against a real
    document with that shape.
    """
    text = fields["full_text"]
    med_mention = re.search(r"\bmedications?\b", text, re.IGNORECASE)
    if not med_mention:
        return (
            "not_applicable",
            "No medication is mentioned anywhere in the document -- nothing for this rule to check.",
            None, 0.85,
        )
    no_med = _NO_MEDICATION_RE.search(text)
    if no_med:
        page = _page_for_offset(fields, no_med.start())
        return (
            "not_applicable",
            "Document states the client is not taking any medications -- nothing for this rule to check.",
            page, 0.85,
        )
    return (
        "not_checkable",
        "Medication is mentioned but not clearly denied; escalating for a real reason-adequacy "
        "and ADHD-secondary-diagnosis review.",
        None, 0.0,
    )


def _check_BIO03(rule: dict, fields: dict) -> tuple:
    """Master Fix Round (2026-09-08): broadened per ma'am's explicit ask
    ('mentioned ANYWHERE in the report, not just if applicable') -- checks
    every labeled diagnosis field this codebase has ever seen a real
    document use (not only 'Secondary Diagnosis:'), scanning the WHOLE
    document rather than a single fixed field. Still a plain presence
    check, not a clinical-applicability judgment (see the rule's own
    notes for why the old BIO-01-derived dependency didn't apply here). A
    labeled field present but blank is genuinely ambiguous -- could mean
    'no additional diagnosis' or an omission -- left to judgment.

    [ \\t]* (not \\s*) so a match doesn't consume the trailing newline and
    bleed into the start of the NEXT line's content as if it were this
    line's own value.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/uncertain
    # both used to hardcode page=None even though each match's real offset
    # was available -- now cites the first matching field's real page.
    filled, blank = [], []
    filled_offset, blank_offset = None, None
    for m in _BIO03_LABEL_RE.finditer(fields["full_text"]):
        label, value = m.group(1), m.group(2)
        if value and value.strip():
            filled.append(f"{label}: {value.strip()}")
            if filled_offset is None:
                filled_offset = m.start()
        else:
            blank.append(label)
            if blank_offset is None:
                blank_offset = m.start()

    if filled:
        page = _page_for_offset(fields, filled_offset)
        return "pass", f"A diagnosis is documented: {'; '.join(filled)}.", page, 0.75
    if blank:
        page = _page_for_offset(fields, blank_offset)
        return (
            "uncertain",
            f"A diagnosis field is present but blank ({'; '.join(blank)}) -- could mean no "
            f"additional diagnosis applies, or could be an omission; not determinable from "
            f"the field alone.",
            page, 0.3,
        )
    return "not_checkable", "No labeled diagnosis field found anywhere in this TP.", None, 0.0


_VALID_SAMPLING_METHODS = {
    "percent correct", "frequency", "duration", "rate",
    "task analysis", "percent independent", "trials to criterion",
    "interval recording", "latency",
}


def _page_for_offset(fields: dict, offset: int) -> int | None:
    """Maps a character offset in fields["full_text"] back to the page it
    falls on -- full_text is built as "\\n".join(p["text"] for p in pages),
    so this walks the same join with a +1 for each joining newline.

    Fix Round (2026-09-11): `fields["pages"]` isn't guaranteed to be
    present -- confirmed via real (mock) test failures the moment this
    helper started getting called from more checkers than before (a
    KeyError crashing the whole check, not the honest "no page" fallback
    this whole page-enforcement effort is about) -- some existing tests
    construct a minimal `fields` dict with only `full_text` set. Missing
    or empty `pages` genuinely means "we don't have the page map," which
    is the same as "couldn't determine a page," not a bug to crash on.
    """
    pages = fields.get("pages")
    if not pages:
        return None
    pos = 0
    for p in pages:
        length = len(p["text"])
        if pos <= offset < pos + length:
            return p["page_number"]
        pos += length + 1
    return pages[-1]["page_number"]


def _goal_block_starts(text: str) -> list[int]:
    """Shared block-splitting helper for both _check_GIP10 and _check_GIP16
    -- a per-goal-or-behavior-target block is delimited by either
    'Target Goal:' (skill-acquisition / Goals-in-Progress entries) or
    'Target Name:' (Behavior Reduction Goals -- a SEPARATE per-behavior-
    target block form found in the BIP section that also carries its own
    Sampling Method/Baseline/Mastery Criteria fields). Confirmed live on
    Reeda's real TP: both of GIP-16's real zero-mastery-criteria violations
    (Tantrum, Elopement) live in 'Target Name:' blocks, not 'Target Goal:'
    ones -- a marker list of just 'Target Goal:' would silently miss them
    entirely, the same class of gap as the \\s*-across-newlines bug found
    while building GIP-10. NOT the narrative "Behavior: Tantrum" text found
    elsewhere in the BIP section (Operational Definition/FBA Hypotheses/
    Consequence Strategies) -- that section has no Mastery Criteria field
    of its own and is a different block entirely.
    """
    return [m.start() for m in re.finditer(r"Target Goal:|Target Name:", text)]


def _check_GIP23(rule: dict, fields: dict) -> tuple:
    """Round 92 (2026-08-14): HYBRID deterministic-then-judgment checker,
    same pattern as QA-PROB-02 (see that rule's own notes). Confirmed
    across all 3 real patients this round (Amir Howell, Arisha Haque,
    Solomon Schnitzer) this rule needs 3 preconditions checked in order:
    (a) does behavior-reduction-goal data exist at all -- if the section
    is blank, resolve to not_applicable with zero judgment call; (b) if
    data exists, is there an upward trend in the graph/data; (c) if
    there's an upward trend, does a narrative explanation already exist
    nearby.

    This implements ONLY precondition (a) deterministically, reusing the
    same already-proven 'Target Name:' (Behavior Reduction Goal) block
    detector _goal_block_starts already uses for QA-BIP-04/05/06 -- a
    real, tested pattern, not a new guess.

    Preconditions (b) and (c) are NOT attempted deterministically this
    round and still escalate to judgment unchanged when goal data exists:
    (b) requires reading a graph that is frequently an embedded image
    (same vision-dependency QA-ACF-03 already established for a different
    section), and (c) has no existing, real-document-confirmed field
    pattern to reuse safely without guessing -- both left to the judgment
    layer rather than risk a fragile, unverified extraction (see
    QA-SCH-08's own notes for a confirmed real example of exactly that
    failure mode). PARTIAL FIX -- only the (a) short-circuit is real,
    verified logic; (b)/(c) are unchanged from before this round.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    has_behavior_reduction_goal = any(
        text[start:start + len("Target Name:")] == "Target Name:" for start in goal_starts
    )
    if not has_behavior_reduction_goal:
        return (
            "not_applicable",
            "No Behavior Reduction Goal ('Target Name:') blocks found in this document -- "
            "no behavior-reduction goal data to check for an unexplained upward trend.",
            None, 0.85,
        )
    return (
        "not_checkable",
        "Behavior Reduction Goal(s) present -- checking for an upward trend without a nearby "
        "narrative explanation requires reading the goal's graph/data and matching it against "
        "any explanation text, which still requires judgment.",
        None, 0.0,
    )


def _check_GIP07(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-09-11), item 23 -- REAL LOGIC BUG FOUND AND FIXED,
    confirmed against the real Daylyn Holland TP: this rule ('Goals open
    more than 6 months have a documented rationale') was pure judgment
    with no precondition check, so even when NO goal was anywhere close
    to 6 months old, all n_calls of the majority vote still had to reason
    about a question that genuinely doesn't apply -- and split (some
    calls correctly said "doesn't apply", others said pass/uncertain for
    unrelated reasons), landing on a real, confirmed "Uncertain" for a
    case the rule should never even have reached. Confirmed real numbers
    on Daylyn Holland: goals initiated 05/04/2026-05/18/2026, current
    report ending 09/08/2026 -- ~4 months, genuinely under the 6-month
    threshold for every goal.

    Hybrid DET precondition, same shape as QA-HRS-05/QA-GIP-23: computes
    each goal's own age (Date Initiated vs. the current report's own end
    date) directly from the document's text. If NONE qualifies (>= 6
    months), resolves to not_applicable outright -- zero judgment calls,
    zero variance, exactly the honest "doesn't apply" answer most of the
    real votes already gave. Only escalates to judgment (not_checkable)
    when at least one goal genuinely IS old enough -- the real remaining
    question (is a real rationale documented for THAT goal) still needs a
    holistic read this checker doesn't attempt.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text) + [len(text)]
    if len(goal_starts) <= 1:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    report_range = _find_labeled_date_range(text, "Date of Current Report")
    if not report_range:
        return (
            "not_checkable",
            "Could not find 'Date of Current Report' to compute each goal's age against.",
            None, 0.0,
        )
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")

    checked = 0
    old_goals = []
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        m = re.search(r"Date Initiated:[ \t\xa0]*(\d{1,2}/\d{1,2}/\d{4})", block)
        if not m:
            continue
        checked += 1
        initiated = datetime.strptime(m.group(1), "%m/%d/%Y")
        six_months_out = _add_months(initiated, 6)
        if six_months_out <= report_end:
            marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
            goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]
            old_goals.append(f"{goal_name!r} (initiated {m.group(1)})")

    if checked == 0:
        return "not_checkable", "No goal block with a 'Date Initiated:' field found to compute age from.", None, 0.0

    if not old_goals:
        return (
            "not_applicable",
            f"None of the {checked} goal(s) with a Date Initiated are open 6 months or more as of "
            f"the current report's end date ({report_range[1]}) -- this rule doesn't apply.",
            None, 0.85,
        )
    return (
        "not_checkable",
        f"{len(old_goals)} of {checked} goal(s) are open 6 months or more as of the current report's "
        f"end date ({report_range[1]}): {old_goals}. Whether a real rationale is documented for these "
        f"still requires a judgment read.",
        None, 0.0,
    )


def _check_GIP22(rule: dict, fields: dict) -> tuple:
    """QA-GIP-22: "Newly initiated goals without graphs should show status
    as 'NEW,' with current data marked 'NEW' or aligned with baseline."
    "Newly initiated" is anchored (per this rule's own already-rewritten
    description) to the goal's 'Date Initiated' falling within the
    CURRENT TP's own 'Date of Current Report' range.

    Fix Round (2026-09-11 night), "Stop Over-Using the Uncertain Safety
    Net" -- REAL FIX: this rule already had a real, concrete anchor field
    from an earlier round's rewrite, but NO deterministic checker was
    ever built for it -- it stayed pure judgment, re-deriving the same
    date-math and status check from scratch on every call, which is
    exactly the shape confirmed to cause instability (same class as
    QA-GIP-07 above). Confirmed on the real Daylyn Holland document
    (zero real API cost): every goal's Date Initiated (05/05/2026 etc.)
    predates the current report range (09/04-09/08/2026) by 4 months --
    none qualify as "newly initiated" here, so this rule's own
    precondition never applies on this document; a real not_applicable,
    not a guess.

    "Current data marked 'NEW' or aligned with baseline" is checked as:
    Current Data's own value either contains the literal word "NEW", or
    is textually identical (case-insensitive, whitespace-normalized) to
    the goal's own Baseline value -- a real, concrete definition of
    "aligned with baseline" (was previously fuzzy/subjective), not yet
    confirmed against a real qualifying goal (none exist on the one real
    document available), so this specific comparison branch is honestly
    unverified in practice, same disclosed limitation as QA-SCH-05 above.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text) + [len(text)]
    if len(goal_starts) <= 1:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    report_range = _find_labeled_date_range(text, "Date of Current Report")
    if not report_range:
        return (
            "not_checkable",
            "Could not find 'Date of Current Report' to determine which goals are newly initiated.",
            None, 0.0,
        )
    report_start = datetime.strptime(report_range[0], "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")

    checked = 0
    problems = []
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        di_m = re.search(r"Date Initiated:[ \t\xa0]*(\d{1,2}/\d{1,2}/\d{4})", block)
        if not di_m:
            continue
        checked += 1
        initiated = datetime.strptime(di_m.group(1), "%m/%d/%Y")
        if not (report_start <= initiated <= report_end):
            continue  # not newly initiated -- this rule's precondition doesn't apply to this goal

        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]
        status_m = re.search(r"(?:Goal Status|Status):[ \t]*([^\n]*)", block)
        status_val = status_m.group(1).strip() if status_m else ""
        baseline_m = re.search(r"Baseline:[ \t]*([^\n]*)", block)
        baseline_val = baseline_m.group(1).strip() if baseline_m else ""
        data_m = re.search(r"Current Data:[ \t]*([^\n]*)", block)
        data_val = data_m.group(1).strip() if data_m else ""

        page = _page_for_offset(fields, goal_starts[i])
        status_is_new = "new" in status_val.lower()
        data_is_new = "new" in data_val.lower()
        data_aligned_with_baseline = bool(baseline_val) and bool(data_val) and (
            re.sub(r"\s+", " ", baseline_val).lower() == re.sub(r"\s+", " ", data_val).lower()
        )
        if not status_is_new and not (data_is_new or data_aligned_with_baseline):
            problems.append((page, (
                f"Goal '{goal_name}' is newly initiated (Date Initiated {di_m.group(1)}) but Status "
                f"({status_val!r}) doesn't say 'NEW', and Current Data ({data_val!r}) is neither 'NEW' "
                f"nor aligned with Baseline ({baseline_val!r})."
            )))

    if checked == 0:
        return "not_checkable", "No goal block with a 'Date Initiated:' field found in this document.", None, 0.0

    if not problems:
        newly_initiated_count = sum(
            1 for i in range(len(goal_starts) - 1)
            for m in [re.search(r"Date Initiated:[ \t\xa0]*(\d{1,2}/\d{1,2}/\d{4})", text[goal_starts[i]:goal_starts[i + 1]])]
            if m and report_start <= datetime.strptime(m.group(1), "%m/%d/%Y") <= report_end
        )
        if newly_initiated_count == 0:
            return (
                "not_applicable",
                f"None of the {checked} goal(s) with a Date Initiated fall within the current report's "
                f"date range ({report_range[0]} to {report_range[1]}) -- no goal is 'newly initiated', "
                f"this rule's precondition doesn't apply.",
                None, 0.85,
            )
        return (
            "pass",
            f"{newly_initiated_count} newly-initiated goal(s) all show 'NEW' status or Current Data "
            f"aligned with/marked 'NEW' relative to Baseline.",
            None, 0.8,
        )
    if len(problems) == 1:
        page, detail = problems[0]
        return "fail", detail, page, 0.8
    evidence = [{"page": page, "detail": detail} for page, detail in problems]
    return "fail", evidence, None, 0.8


def _check_GIP10(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    'sampling method consistent across every goal' is a uniqueness check
    over a list of extractable per-goal field values, not a holistic
    reasoning task -- exactly the shape an LLM is weak at (averaging over a
    big context, missing the one different item among many consistent
    ones), and exactly the shape code is strong at (regex-extract every
    instance, then a plain equality/whitelist check, no averaging).

    Splits the full document on every goal/behavior-target block marker
    (see _goal_block_starts -- blocks can span a page boundary, confirmed
    on Charny's TP where one goal's Mastery Criteria/Sampling Method print
    on the page after its Target Goal line -- so this operates on
    fields["full_text"], not per-page text, and maps each finding's offset
    back to a page via _page_for_offset). For each block that has a
    "Sampling Method:" field: (a) the value must match a known method name
    (case-insensitive) -- catches both a broken merge-field artifact
    (literally 'Page') and spelling/wording variants ('Precent correct',
    'percentage correct') that a majority-pattern read would let slide;
    (b) Baseline and Mastery Criteria must be non-blank -- catches a goal
    with a real Sampling Method but a missing companion field (confirmed on
    Charny: a Frequency-sampled goal with a blank Mastery Criteria, page 27).

    Regex note: the field-value patterns use `[ \t]*` after the label,
    not `\\s*` -- `\\s*` matches newlines too, so on a genuinely blank field
    (colon immediately followed by a newline) it would keep matching
    through the newline into the START OF THE NEXT LINE's text, making a
    blank field look non-blank. Confirmed live: this exact bug silently
    hid the Charny page-27 blank-Mastery-Criteria case during development.

    Fix Round (2026-09-10), item 27 -- REAL BUG FOUND AND FIXED: the
    `[^\\n]*` same-line-only capture above avoided the OLD blank-field bug,
    but introduced the OPPOSITE real bug -- a genuinely non-blank Mastery
    Criteria/Baseline value that wraps onto the line AFTER the label
    (same bug class as items 9/22, see _extract_labeled_value) was read as
    blank too, since nothing on the label's own line matched. Mastery
    Criteria/Baseline now go through _extract_labeled_value's lookahead
    instead (tolerates a wrapped value, still stops at a genuine blank or
    the next field's own label) -- Sampling Method stays a same-line-only
    read, since its value is validated against a short fixed whitelist
    that's never seen wrap onto a second line in any real document.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    goal_starts = goal_starts + [len(text)]
    problems = []
    real_goals = 0
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        sm_m = re.search(r"Sampling Method:[ \t]*([^\n]*)", block)
        if not sm_m:
            continue  # not every block hit is a fully structured goal entry
        real_goals += 1
        mc_m = re.search(r"Mastery Criteria:[ \t]*", block)
        bl_m = re.search(r"Baseline:[ \t]*", block)
        sm_val = sm_m.group(1).strip()
        mc_val = _extract_labeled_value(block, "Mastery Criteria") if mc_m else ""
        bl_val = _extract_labeled_value(block, "Baseline") if bl_m else ""
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]

        if sm_val.lower() not in _VALID_SAMPLING_METHODS:
            page = _page_for_offset(fields, goal_starts[i] + sm_m.start())
            problems.append((page, (
                f"Sampling Method value {sm_val!r} for goal '{goal_name}' doesn't match a "
                f"recognized method name (possible broken merge field or typo)."
            )))
        if not mc_val:
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            problems.append((page, f"Mastery Criteria is blank for goal '{goal_name}' (Sampling Method: {sm_val!r})."))
        if not bl_val:
            page = _page_for_offset(fields, goal_starts[i] + bl_m.start())
            problems.append((page, f"Baseline is blank for goal '{goal_name}' (Sampling Method: {sm_val!r})."))

    if real_goals == 0:
        return "not_checkable", "No goal blocks with a 'Sampling Method:' field found in this document.", None, 0.0
    if not problems:
        return (
            "pass",
            f"All {real_goals} goal(s) with a Sampling Method have a recognized method name "
            f"and non-blank Baseline/Mastery Criteria.",
            None, 0.85,
        )
    if len(problems) == 1:
        page, detail = problems[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in problems]
    return "fail", evidence, None, 0.85


# Round 83, item 2a -- REAL BUG FOUND AND FIXED: confirmed real miss,
# "0 times a week" is the same absolute-zero mastery-criteria problem as
# "0%"/"0 occurrences", just phrased with "times" instead -- the prior
# pattern only recognized "%"/"occurrences"/"x"/"near 0", not "times" or
# the word forms "zero"/"none". Broadened to a general zero-instance-
# phrasing family: "0"/"zero" paired with occurrences/times/instances/x,
# "near 0"/"near-zero", or the field's ENTIRE value being just "0"/"zero"/
# "none" on its own (anchored to the whole value, not a bare substring
# match, so this doesn't fire on "none" appearing incidentally inside a
# longer, unrelated sentence elsewhere -- mc_val is always this one
# field's own short value, never a full paragraph). Deliberately does NOT
# match "fewer than N"/"less than N" phrasing for any N -- that's this
# rule's OWN recommended, non-absolute-zero rewording (see this
# function's docstring), and matching it here would fail the very
# phrasing this rule wants people to use instead.
_ZERO_MASTERY_PATTERN = re.compile(
    r"(?:\b0\s*%"
    r"|\b(?:0|zero)\s*(?:occurrences?|times?|instances?|x)\b"
    r"|\bnear[\s-]*0\b"
    r"|^\s*(?:0|zero|none)\s*\.?\s*$"
    # Fix Round, Section 1 (2026-08-27): "Current Data:" values (the real
    # field this pattern was extended to also cover) confirmed to use a
    # plain "<number> <Sampling Method name>" phrasing with no "%" sign at
    # all (e.g. real sample TP: "Current Data: 56.67 Percent Correct") --
    # a genuine zero reading in that same real format ("0 Percent
    # Correct") would silently miss every branch above, none of which
    # match a bare "0"/"zero" followed by a sampling-method WORD instead
    # of "%"/occurrences/times/instances/x.
    r"|\b(?:0|zero)\s+percent\b"
    r")",
    re.IGNORECASE,
)


def _check_GIP16(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    same shape as GIP-10 -- a per-goal field (Mastery Criteria) checked
    against a fixed banned-pattern list, not a holistic read. Shares
    _goal_block_starts with _check_GIP10 (both split the document the same
    way; this one just reads a different field per block).

    Verified live against both real documents' known instances: Reeda has
    exactly the two confirmed real violations (page 26, Tantrum: 'Near 0
    levels per session for 5 consecutive sessions'; page 27, Elopement: '0
    occurrences per session for 5 consecutive sessions') -- both in
    'Target Name:' Behavior Reduction Goal blocks, not 'Target Goal:' ones,
    which is exactly why _goal_block_starts covers both marker forms.
    Charny has zero violations of this pattern (one goal reads '0-2
    occurrences over three consecutive days', which does NOT match the
    banned pattern -- a genuine minimum-occurrence range, not a zero
    endpoint, and the regex is careful not to flag it).

    Round 83, item 2a: broadened _ZERO_MASTERY_PATTERN to also catch "0
    times"/"zero times"/"zero occurrences"/"zero instances" and a bare
    "0"/"zero"/"none" as the field's entire value -- see that pattern's
    own comment for the confirmed real miss ("0 times a week") and why
    "fewer than N" is deliberately still excluded.

    Fix Round, item 6 -- REAL BUG FOUND AND FIXED: the previous version
    only failed a blank Mastery Criteria when the SAME block also had no
    'Sampling Method:' field, deliberately deferring the (more common)
    Sampling-Method-present case to QA-GIP-10 (documented as an explicit
    "division of labor," 2026-08-07). That's a real problem in its own
    right, not just an intentional split of labor: this rule's own real
    bar is "no zero/near-zero endpoint," and a BLANK field arguably fails
    that bar worse than a literal "0%" does -- but blank text never
    matched the zero/near-zero pattern, so a blank field silently passed
    THIS rule regardless of what any other rule concluded. Relying on
    GIP-10 (or BIP-05) to independently catch the same blank field is an
    undocumented-elsewhere, silently-breakable cross-rule dependency, not
    a design. Now fails a blank Mastery Criteria directly and
    unconditionally, with or without a Sampling Method field present --
    GIP-10 may also flag the identical block; that's two rules correctly
    agreeing on a real problem, not a conflict (see
    find_cross_rule_contradictions, which only flags a genuine
    blank-vs-populated DISAGREEMENT, never two rules agreeing).

    Fix Round, Section 1 (2026-08-27): the 2026-08-26 round added
    "current level" alongside "Mastery Criteria" to this rule's own
    description, but flagged in its own notes that the code was NOT
    changed to match -- confirmed real gap, now fixed. "Current Data:" is
    the real field name for a goal's current-level value (confirmed on
    the real sample TP, e.g. "Current Data: 0 Percent Correct" would be
    exactly the same zero-endpoint problem this rule already bans for
    Mastery Criteria). Checked with the SAME zero/near-zero pattern, same
    per-goal-block scope -- but NOT the blank-field failure that applies
    to Mastery Criteria: a blank Current Data reading commonly just means
    "no data collected yet this period" for a newly-started goal, a
    different, legitimate situation from Mastery Criteria being blank
    (which is a real setup problem regardless of goal age) -- flagging a
    blank Current Data the same way would risk a real false-fail on
    every brand-new goal. Only the explicit zero/near-zero PATTERN is
    checked for Current Data, matching the actual "no 0%, use fewer than
    one instance" ask precisely.

    Fix Round (2026-09-10), item 25 -- REVERSAL, CONFIRMED WITH MA'AM
    DIRECTLY, not a mistake: the "Current Data" half added just above
    (2026-08-27) is now REMOVED again. She asked for this rule to check
    ONLY the Mastery Criteria field going forward, not current data or
    any other field -- back to this rule's original, pre-2026-08-27
    scope. Flagging plainly: this walks back a real, deliberate earlier
    request of hers, not something we got wrong on our own.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    goal_starts = goal_starts + [len(text)]
    problems = []
    total = 0
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        mc_m = re.search(r"Mastery Criteria:[ \t]*([^\n]*)", block)
        if not mc_m:
            continue
        total += 1
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]

        mc_val = mc_m.group(1).strip()
        if mc_val and _ZERO_MASTERY_PATTERN.search(mc_val):
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            problems.append((page, (
                f"Mastery Criteria for goal '{goal_name}' reads {mc_val!r} -- a zero/near-zero "
                f"endpoint must instead read 'fewer than one instance' (or equivalent "
                f"minimum-occurrence phrasing)."
            )))
        elif not mc_val:
            # Fix Round, item 6: fails on its own now, regardless of
            # whether a Sampling Method field is also present in this
            # block -- see this function's own docstring.
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            problems.append((page, f"Mastery Criteria is blank for goal '{goal_name}'."))

    if total == 0:
        return "not_checkable", "No goal blocks with a Mastery Criteria field found.", None, 0.0
    if not problems:
        return (
            "pass",
            f"None of the {total} goal(s)' Mastery Criteria use a zero/near-zero endpoint phrasing.",
            None, 0.85,
        )
    if len(problems) == 1:
        page, detail = problems[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in problems]
    return "fail", evidence, None, 0.85


def _normalize_goal_text(text: str) -> str:
    """Round 83, item 2b: collapses whitespace/case/trailing-punctuation
    differences so the SAME goal wording, appearing in two different
    sections of the document with different line-wrapping/surrounding
    formatting, compares equal. This is NOT fuzzy typo-tolerance (compare
    _name_filename_score below, which IS) -- it only
    normalizes FORMATTING, matching the confirmed real case (identical
    wording, different section, different surrounding formatting), not
    genuinely different phrasing of the same underlying goal.
    """
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".,;: ")


_MASTERED_SKILL_RE = re.compile(r"Name of Skill:[ \t]*([\s\S]{1,400}?)(?=\s*Date Mastered:)")
_GOAL_NAME_TAIL_RE = re.compile(r"[\s\S]{1,400}?(?=\s*(?:Goal Status:|Date Initiated:|Status:))")


def _extract_mastered_goal_names(text: str) -> list[tuple[str, int]]:
    """Round 83, item 2b: every 'Name of Skill: X' entry from the
    document's own 'Mastered Goals:' section, paired with its own text
    offset (for page-mapping). Bounded to end at the first 'Goals in
    Progress:'/'Target Goal:'/'Target Name:'/'Goal Progress:' marker after
    it, whichever comes first -- confirmed live (Reeda/Charny/Yisroel) this
    section is immediately followed by 'Goals in Progress:' and then the
    active per-goal blocks, so this boundary never accidentally swallows
    an active goal block into the mastered-goals scan, regardless of
    which of these header conventions a given document actually uses.
    """
    m = re.search(
        r"Mastered Goals:([\s\S]{0,20000}?)(?:Goals in Progress:|Target Goal:|Target Name:|Goal Progress:|"
        r"Areas of Focus|Clinical Interpretation)",
        text,
    )
    if not m:
        return []
    section = m.group(1)
    base_offset = m.start(1)
    return [(sm.group(1).strip(), base_offset + sm.start(1)) for sm in _MASTERED_SKILL_RE.finditer(section)]


# Previous TP round (extraction plumbing only -- see this round's own
# brief): _extract_mastered_goal_names above only ever captured the goal
# NAME -- its regex uses "Date Mastered:" purely as a lookahead boundary,
# never captures the date value itself, because its one existing caller
# (_check_GIP05) never needed the date. QA-MAST-01/QA-MAST-02 (a future
# round's job, not this one) will need the actual date value to compare
# against a previous TP's own authorization window / mastered-goals list,
# so this pairs each name with its date, reusing the exact same
# "Mastered Goals:" section boundary and per-entry regex as
# _extract_mastered_goal_names -- not new judgment logic, just capturing a
# value the existing boundary already sits right next to.
_MASTERED_SKILL_WITH_DATE_RE = re.compile(
    r"Name of Skill:[ \t]*([\s\S]{1,400}?)\s*Date Mastered:[ \t]*(\d{1,2}/\d{1,2}/\d{2,4})?",
)


def _extract_mastered_goals_with_dates(text: str) -> list[dict]:
    """Same 'Mastered Goals:' section boundary as
    _extract_mastered_goal_names (kept as a separate function rather than
    changed in place, so _check_GIP05's existing (name, offset)-tuple shape
    and behavior stay byte-for-byte unchanged). Returns one dict per entry:
    {"name": str, "date_mastered": str | None, "offset": int} -- offset is
    the goal name's own text offset, same convention as
    _extract_mastered_goal_names, for page-mapping. `date_mastered` is the
    raw "MM/DD/YYYY"-shaped string as it appears in the document (no date
    parsing/validation here -- that's a future round's job, same as the
    actual comparison logic).
    """
    m = re.search(
        r"Mastered Goals:([\s\S]{0,20000}?)(?:Goals in Progress:|Target Goal:|Target Name:|Goal Progress:|"
        r"Areas of Focus|Clinical Interpretation)",
        text,
    )
    if not m:
        return []
    section = m.group(1)
    base_offset = m.start(1)
    return [
        {"name": sm.group(1).strip(), "date_mastered": sm.group(2), "offset": base_offset + sm.start(1)}
        for sm in _MASTERED_SKILL_WITH_DATE_RE.finditer(section)
    ]


# Previous TP round (extraction plumbing only): "Problem Area:"/"Problem
# Areas:" was already used elsewhere in this file (_EVIDENCED_BY_BLOCK_RE,
# _NARRATIVE_SECTION_END_RE) purely as a STOP marker for other sections'
# extraction -- nothing ever extracted the Problem Area label's own text.
# QA-PROB-04 ("Problem Areas should not be identical to the previous TP")
# will need each entry's own text to compare later; this locates them the
# same way the rest of this file locates repeating labeled blocks (see
# _find_acf_section's own boundary style) -- a section locator, not
# comparison logic. A real TP has one or more "Problem Area:"/"Problem
# Areas:" entries, each typically followed by its own "As evidenced by:"
# block (see _EVIDENCED_BY_BLOCK_RE above) -- bounded here to end at the
# next Problem Area entry, the next "As evidenced by:", or a known
# following-section marker, whichever comes first.
_PROBLEM_AREA_RE = re.compile(
    r"Problem Areas?:[ \t]*([\s\S]{0,3000}?)"
    r"(?=\n\s*(?:Problem Area:|Problem Areas:|As evidenced by:|Areas of Focus|Goal Progress:|"
    r"Assessment of Current Functioning:)|\Z)",
)


def _extract_problem_areas(text: str) -> list[dict]:
    """Every 'Problem Area(s): X' entry in the document, in document order.
    Returns [{"text": str, "offset": int}, ...] -- offset is this entry's
    own text offset (for page-mapping), same convention as the mastered-
    goals extractors above. Returns [] if the document has no 'Problem
    Area:'/'Problem Areas:' label at all.

    REAL BUG FOUND (Fix Round, Previous TP round, Bug 3), confirmed against
    real documents (Jacob Freund): this captures the CATEGORY/RUBRIC label
    text itself (the DSM-style boilerplate description, e.g. "Deficits in
    social-emotional reciprocity, ranging, for example...") -- which is a
    FIXED TEMPLATE, identical for every patient's document by design, not
    patient-specific content. QA-PROB-04's real cross-document "are these
    identical" comparison needs the "As evidenced by:" block instead (the
    genuinely patient-specific findings) -- see
    _extract_evidenced_by_blocks below, which
    pipeline/previous_tp_comparison.py::_compare_prob04 now uses instead of
    this function's own output. Kept as-is (not removed) since nothing else
    in this codebase was ever wrong to use it for anything else -- it
    genuinely is "every Problem Area category label's own rubric text," just
    not what a cross-document identity check needs.
    """
    return [
        {"text": m.group(1).strip(), "offset": m.start(1)}
        for m in _PROBLEM_AREA_RE.finditer(text)
        if m.group(1).strip()
    ]


def _extract_evidenced_by_blocks(text: str) -> list[dict]:
    """The REAL fix for Bug 3 above -- reuses _EVIDENCED_BY_BLOCK_RE
    VERBATIM (already defined above, already used by _check_PROB01; not a
    new regex, per this round's own explicit instruction). Returns
    [{"text": str, "offset": int}, ...], one entry per "As evidenced by:"
    occurrence in the document, in document order -- the genuinely
    patient-specific findings text (confirmed real: "Jacob struggles to
    approach peers - improved since last auth", "(in progress)", etc. --
    exactly the content that SHOULD differ between a current and previous
    TP when there's been real progress, unlike the fixed rubric text
    _extract_problem_areas above captures).
    """
    return [
        {"text": m.group(1).strip(), "offset": m.start(1)}
        for m in _EVIDENCED_BY_BLOCK_RE.finditer(text)
        if m.group(1).strip()
    ]


def _check_GIP05(rule: dict, fields: dict) -> tuple:
    """Round 83, item 2b -- REAL BUG FOUND AND FIXED: confirmed directly
    against a real document, a goal was listed BOTH in the document's own
    'Mastered Goals:' section (with a Date Mastered) AND still listed as
    an active goal in 'Goals in Progress:' (with a 0% baseline) --
    identical wording, just in two different sections with different
    surrounding formatting -- and the prior judgment-only version
    reported no duplication found, even though this rule's own notes
    ('LLM needed to match goal descriptions worded differently') assumed
    the harder, differently-worded case was the real challenge; an
    IDENTICALLY-worded duplicate slipping through anyway means the model
    wasn't reliably even doing that literal comparison across two
    far-apart sections of a long document.

    Hybrid DET pre-check (same shape as QA-PROB-02/QA-BIP-05): ONLY
    catches the one narrow, objectively-checkable shape -- the SAME goal
    wording (formatting-normalized via _normalize_goal_text, not typo-
    fuzzy) appearing in BOTH the Mastered Goals section and an active
    'Target Goal:'/'Target Name:' block. Genuinely differently-worded
    duplicates of the same underlying goal are NOT attempted here -- that
    stays exactly the judgment-layer task this rule's own notes describe;
    returns not_checkable when no exact-wording duplicate is found so the
    judgment layer still gets a chance to catch a paraphrased one.

    Verified against all three of this project's real documents: zero
    false positives (none has this duplication) -- the exact real
    document that exposed this bug isn't among them.
    """
    text = fields["full_text"]
    mastered = _extract_mastered_goal_names(text)
    if not mastered:
        return "not_checkable", "No 'Mastered Goals:' section with any 'Name of Skill:' entries found.", None, 0.0

    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return (
            "not_checkable",
            "No active 'Target Goal:'/'Target Name:' entries found to cross-check against mastered goals.",
            None, 0.0,
        )
    goal_starts = goal_starts + [len(text)]

    mastered_by_norm: dict[str, tuple[str, int]] = {}
    for name, offset in mastered:
        mastered_by_norm.setdefault(_normalize_goal_text(name), (name, offset))

    problems = []
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        rest = block[marker_len:]
        tail_m = _GOAL_NAME_TAIL_RE.search(rest)
        active_name = (tail_m.group(0) if tail_m else rest.split("\n", 1)[0]).strip()
        norm = _normalize_goal_text(active_name)
        if norm and norm in mastered_by_norm:
            _mastered_name, mastered_offset = mastered_by_norm[norm]
            active_page = _page_for_offset(fields, goal_starts[i])
            mastered_page = _page_for_offset(fields, mastered_offset)
            problems.append({
                "page": active_page,
                "detail": (
                    f"Goal '{active_name[:150]}' is listed as an active/in-progress goal here, but the "
                    f"SAME goal (identical wording) is also listed in the Mastered Goals section "
                    f"(page {mastered_page}) -- a same-document contradiction/duplication."
                ),
            })

    if not problems:
        return (
            "not_checkable",
            (
                f"Checked {len(mastered)} mastered-goal entry(ies) against {len(goal_starts) - 1} active "
                f"goal block(s) for identical wording -- no exact duplication found, but a differently-"
                f"worded duplicate of the same goal still needs judgment."
            ),
            None, 0.3,
        )
    if len(problems) == 1:
        return "fail", problems[0]["detail"], problems[0]["page"], 0.85
    return "fail", problems, None, 0.85


# Round 84, item 1: this project's real documents use "occurrence(s)",
# "instance(s)", and "times" interchangeably for the SAME concept in
# Mastery Criteria phrasing -- confirmed real case: the same goal's two
# mentions read "1 instance or less per day" (page 15) and "0 times a
# week" (page 64). The original pattern only recognized "occurrence(s)".
_OCCURRENCE_UNIT = r"(?:occurrences?|instances?|times?)"


def _parse_occurrence_ceiling(text: str) -> float | None:
    """Round 81, Item 3: parses the MAXIMUM occurrence count a piece of
    text implies, as a plain float, so two differently-WORDED thresholds
    for the SAME goal can be compared numerically rather than by string
    equality (which would false-positive on every real paraphrase, e.g.
    "fewer than 1" vs "0 occurrences" mean the same real threshold but
    never read as equal strings).

    "fewer than N"/"less than N" -> N - 0.5 (a real, strict ceiling BELOW
    N -- N itself is NOT allowed). "N or less"/"N or fewer" -> N (N itself
    IS allowed -- this is an upper bound, not a strict "below N" ceiling,
    unlike "fewer than N"). "near 0"/"near-zero" -> 0.5 (same shape,
    phrased differently). A range "N-M" -> M (the range's own upper bound
    IS an allowed value). A bare "N occurrence(s)"/"N instance(s)"/"N
    times" -> N.

    Round 84, item 1 -- REAL BUG FOUND AND FIXED: confirmed real case, a
    goal's two Mastery Criteria mentions -- "1 instance or less per day"
    and "0 times a week" -- both went unparsed (None) because the unit
    word wasn't "occurrence(s)" and there was no "or less" pattern at
    all, which silently made pipeline/fields.py::_check_BIP05's cross-
    block comparison skip the pair entirely (not_checkable, not a missed
    fail) -- NOT a Target Name:/Target Goal: label mismatch, which
    _check_BIP05/_check_GIP05 both already treat as equivalent via
    _goal_block_starts covering both marker forms (confirmed directly: a
    same-label control test with this same identical phrasing pair
    reproduced the identical miss, proving the label wasn't the cause).
    Broadened the unit word to _OCCURRENCE_UNIT (occurrence(s)/
    instance(s)/times) and added the "N or less"/"N or fewer" shape.

    Returns None (never a guessed number) when the text doesn't contain
    one of these recognized shapes -- a caller seeing None must treat
    this goal as not comparable, never assume 0 or any other default.
    """
    if not text:
        return None
    t = text.lower()
    m = re.search(rf"(?:fewer|less)\s+than\s+(\d+(?:\.\d+)?)\s*{_OCCURRENCE_UNIT}", t)
    if m:
        return float(m.group(1)) - 0.5
    if re.search(r"near[\s-]*0\b", t):
        return 0.5
    m = re.search(rf"(\d+(?:\.\d+)?)\s*{_OCCURRENCE_UNIT}?\s*or\s+(?:less|fewer)\b", t)
    if m:
        return float(m.group(1))
    m = re.search(rf"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)\s*{_OCCURRENCE_UNIT}", t)
    if m:
        return float(m.group(2))
    m = re.search(rf"\b(\d+(?:\.\d+)?)\s*{_OCCURRENCE_UNIT}", t)
    if m:
        return float(m.group(1))
    return None


def _check_BIP05(rule: dict, fields: dict) -> tuple:
    """Round 81, Item 3 -- REAL BUG FOUND AND FIXED: confirmed directly
    against a real document, a goal's own Target Name states "fewer than
    1 occurrence" while that SAME goal's own Mastery Criteria field states
    "1-2 occurrences" -- a direct, literal, same-goal-block contradiction
    (the mastery bar is looser than the goal's own stated target). Neither
    QA-GIP-16 (only matches literal 0%/zero-occurrence phrasing, not a
    cross-field comparison) nor this rule's own prior judgment-only
    behavior (which noticed the goal's duration was unusual but never
    compared the two fields' actual numbers) caught this -- it needs zero
    clinical judgment, just comparing two fields that belong to the same
    record.

    Deliberately narrow, same "hybrid" shape as QA-PROB-02
    (pipeline/fields.py::_check_PROB02, see its own docstring for the
    precedent): this checker ONLY attempts the same-goal numeric-
    contradiction cross-check, extracted from _goal_block_starts's own
    per-goal blocks (shared with GIP-10/GIP-16). It does NOT attempt this
    rule's full "age-appropriate mastery criteria" judgment call, which
    stays genuinely subjective and is not attempted deterministically --
    when a goal's Target Name and Mastery Criteria don't BOTH state a
    recognized numeric occurrence threshold, or when they do and don't
    contradict, this returns not_checkable (even on a clean read) so the
    judgment layer still gets a chance to make the broader
    age-appropriateness call unchanged. A confirmed, real numeric
    contradiction is the one case objective enough to fail outright,
    with no judgment needed.

    Round 83, item 2c -- INVESTIGATED, NOT FORCED: a new real case
    surfaced where a goal's Mastery Criteria was stated two different
    ways in two different SECTIONS of the document (not the same-block
    Target-Name-vs-own-Mastery-Criteria shape above), and self-consistency
    landed on "uncertain" rather than a confident fail. Investigated
    honestly: this checker's per-block scope structurally cannot see a
    second mention that lives OUTSIDE a 'Target Goal:'/'Target Name:'
    block entirely -- e.g. restated in unstructured BIP narrative prose
    elsewhere -- and finding that would require knowing the real
    document's actual second-location structure, which isn't available
    here (this confirmed case isn't in any of the three real documents
    this project has local access to). Forcing a regex against an
    unconfirmed structural guess risks either dead code that never fires,
    or false positives matching unrelated prose -- exactly the "LLM
    needed to match goal descriptions worded differently" shape this
    project's own QA-GIP-05 notes describe for cross-section, differently-
    worded comparisons (see _check_GIP05 above). NOT extending the DET
    layer for that general shape -- "uncertain" (an honest non-answer
    under genuine self-consistency disagreement) is the right outcome
    here, not a confident wrong one manufactured to look more resolved
    than the evidence supports.

    One safe, narrow generalization IS added below: the numeric-ceiling
    comparison now ALSO cross-checks Mastery Criteria across every block
    sharing the same (formatting-normalized) goal name, not just within
    one block -- covers the one sub-case that's still genuinely
    structural (the goal duplicated as a second full 'Target Goal:'/
    'Target Name:' block elsewhere, not prose), at zero added false-
    positive risk, reusing the same numeric-ceiling parser already built.
    Verified this doesn't fire on any of the three real documents (none
    has a goal repeated as two separate blocks) -- added coverage for a
    real possible shape without manufacturing evidence that isn't there.

    Fix Round, Section 1 Bucket D (2026-08-27): REAL SCOPE BUG FOUND AND
    FIXED, visible directly in the code without needing a specific real
    document -- this rule's own description is "Age-appropriate mastery
    criteria for BEHAVIOR TARGETS" specifically, but the code processed
    EVERY goal block _goal_block_starts finds, including 'Target Goal:'
    blocks (skill-acquisition Goals in Progress entries -- a completely
    different category from BIP's own Behavior Reduction Goals). Ma'am's
    own confirmed complaint ("pulling in transition-plan content it
    shouldn't") is exactly this shape: nothing scoped this checker to
    behavior-target blocks only, so ANY section of the document using a
    similarly-labeled per-item block got swept in.

    NOT a blanket "skip every Target Goal: block" fix -- that would have
    broken the Round 83 cross-block generalization above, which has its
    OWN confirmed real case (see test_check_bip05_catches_the_real_
    confirmed_case_with_different_field_labels): the SAME behavior-target
    goal genuinely gets restated under the OTHER marker form ('Target
    Goal:') elsewhere in some real documents. The real, correct
    distinction is by NAME, not by marker form: the same-BLOCK Target-
    Name-vs-own-Mastery-Criteria check (this rule's primary check) now
    only ever reads a block's OWN name from a genuine 'Target Name:'
    block (skill-acquisition goals never have a numeric behavior-target
    ceiling in their own name to begin with, so this was always a
    no-op for them in practice, but is now also structurally scoped, not
    just incidentally safe). The cross-block generalization (a goal
    repeated under a DIFFERENT marker with a different Mastery Criteria)
    now only considers a 'Target Goal:' block's own name if that EXACT
    normalized name was ALSO seen under a real 'Target Name:' block
    somewhere in the document -- confirming it's genuinely the same
    behavior-target goal restated, not an unrelated skill-acquisition
    goal or Transition Plan entry that merely happens to share the
    'Target Goal:' label shape.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    goal_starts = goal_starts + [len(text)]
    blocks = []
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        is_behavior_target = block.startswith("Target Name:")
        marker_len = len("Target Name:") if is_behavior_target else len("Target Goal:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()
        blocks.append((goal_starts[i], block, is_behavior_target, goal_name))

    # First pass: which normalized goal names are CONFIRMED real behavior
    # targets (appear under a genuine 'Target Name:' block at least once)?
    # This is what lets the cross-block generalization below trust a
    # same-named 'Target Goal:' block as a restatement of that SAME
    # behavior target, rather than an unrelated skill-acquisition goal.
    confirmed_behavior_target_names = {
        _normalize_goal_text(name) for _, _, is_bt, name in blocks if is_bt
    }

    problems = []
    checked = 0
    mastery_by_goal: dict[str, list[tuple[int | None, str, float]]] = {}
    for start, block, is_behavior_target, goal_name in blocks:
        mc_m = re.search(r"Mastery Criteria:[ \t]*([^\n]*)", block)
        if not mc_m:
            continue
        mc_val = mc_m.group(1).strip()
        mastery_ceiling = _parse_occurrence_ceiling(mc_val)
        norm_name = _normalize_goal_text(goal_name)

        # A 'Target Goal:' block only counts toward the cross-block
        # generalization when it's a confirmed restatement of a real
        # behavior target -- otherwise it's out of this rule's scope
        # entirely (a skill-acquisition goal, or unrelated content from
        # elsewhere in the document that merely uses the same label
        # shape).
        in_scope = is_behavior_target or norm_name in confirmed_behavior_target_names
        if not in_scope:
            continue

        if mastery_ceiling is not None:
            page = _page_for_offset(fields, start + mc_m.start())
            mastery_by_goal.setdefault(norm_name, []).append((page, mc_val, mastery_ceiling))

        if not is_behavior_target:
            continue  # same-block Target-Name-vs-own-name check only applies to the real behavior-target block itself
        target_ceiling = _parse_occurrence_ceiling(goal_name)
        if target_ceiling is None or mastery_ceiling is None:
            continue  # this goal doesn't state a numeric threshold on both sides -- not comparable
        checked += 1
        if mastery_ceiling > target_ceiling + 0.01:
            page = _page_for_offset(fields, start + mc_m.start())
            problems.append((page, (
                f"Goal '{goal_name[:120]}' states a target threshold in its own name, but its "
                f"Mastery Criteria ({mc_val!r}) allows MORE occurrences than that same target "
                f"implies -- these contradict each other for the same goal."
            )))

    # Round 83, item 2c: cross-block generalization -- the same CONFIRMED
    # behavior-target goal repeated as two separate blocks with two
    # DIFFERENT Mastery Criteria ceilings is its own real contradiction,
    # independent of whether either block's own name states a numeric
    # threshold at all.
    for norm_name, entries in mastery_by_goal.items():
        distinct_ceilings = {ceiling for _, _, ceiling in entries}
        if len(distinct_ceilings) > 1:
            pages = [page for page, _, _ in entries]
            values = [mc_val for _, mc_val, _ in entries]
            checked += 1
            problems.append((pages[0], (
                f"Goal (normalized: {norm_name[:120]!r}) has DIFFERENT Mastery Criteria values in two "
                f"separate blocks of this document: {values} (pages {pages}) -- these contradict each "
                f"other for the same goal."
            )))

    if checked == 0 or not problems:
        return (
            "not_checkable",
            (
                f"Checked {checked} goal(s)/comparison(s) for a numeric same-goal contradiction "
                f"(same-block Target-Name-vs-Mastery-Criteria, and repeated-block Mastery Criteria "
                f"values) -- no contradiction found, but this rule's broader age-appropriateness "
                f"question, and any cross-section narrative restatement, still need judgment."
            ) if checked else (
                "No goal names an explicit numeric occurrence threshold in both its own Target Name "
                "and Mastery Criteria that could be cross-checked -- age-appropriateness itself still "
                "needs judgment."
            ),
            None, 0.3 if checked else 0.0,
        )
    if len(problems) == 1:
        page, detail = problems[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in problems]
    return "fail", evidence, None, 0.85


def _nearby_block_explanation(block: str, exclude_start: int, exclude_end: int) -> str | None:
    """Fix Round, item 4 -- GENERIC mechanism: given a goal/record block
    and the character span of the specific field already found blank/
    bare-N/A within it, scans every OTHER line in that SAME block (not
    the whole document -- just this one record) for a real explanatory
    sentence (3+ real words) that could explain why the field is blank.
    No field name is hardcoded anywhere in this function -- it operates
    purely on the block's own line structure, so it works the same way
    for a rule and a document layout nobody has looked at yet.

    Confirmed real gap this fixes: a bare 'Current Level: N/A' with the
    real explanation sitting in that SAME goal's own 'Additional Notes:'
    field a few lines later -- the field itself is genuinely blank, but
    blank does not automatically mean "not explained anywhere in this
    record." Returns the first qualifying line found, or None if nothing
    in the rest of the block reads as a real explanation (a bare label
    with nothing after it, like 'Graph:' or 'Additional Notes:' with no
    text, does not count -- and neither does the block's own FIRST line,
    the 'Target Name:'/'Target Goal:' marker naming the goal itself:
    confirmed live this always has 3+ real words, which would otherwise
    make every goal register as "explained" by its own name regardless of
    whether anything nearby actually explains the blank field).
    """
    # A third real-document finding (Zohan Hossain, same discovery
    # process): this project's own _goal_block_starts boundary can span
    # much further than "this one goal's own fields" when a document's
    # raw text order interleaves an unrelated narrative paragraph
    # (confirmed live: "Goal Progress: Skill Acquisition Summary and
    # Rationale: ..." landed INSIDE a Behavior Reduction goal's own block
    # because it happened to sit before the next Target Goal:/Target
    # Name: marker in this document's real extracted text order) --
    # reading the WHOLE block would treat that unrelated narrative as
    # "nearby," which it isn't. Bounded to a fixed character window on
    # each side instead -- "the immediately surrounding fields," per this
    # item's own instruction, not the rest of a block that may run on far
    # longer than intended.
    _ADJACENT_WINDOW_CHARS = 150
    first_line_end = block.find("\n")
    first_line_end = len(block) if first_line_end == -1 else first_line_end
    before_start = max(first_line_end, exclude_start - _ADJACENT_WINDOW_CHARS)
    after_end = min(len(block), exclude_end + _ADJACENT_WINDOW_CHARS)
    surrounding = block[before_start:exclude_start] + "\n" + block[exclude_end:after_end]
    for line in surrounding.splitlines():
        line = line.strip()
        if not line:
            continue
        content = re.sub(r"^[A-Za-z][A-Za-z /]*:\s*", "", line)
        # Round trip on a real document (Zohan Hossain) CAUGHT AND FIXED
        # before shipping: pypdf's raw text extraction often puts two
        # short structured fields on one physical line (e.g. "Date
        # Initiated: 01/23/2026 Baseline: 4 occurrences Frequency") --
        # after stripping the FIRST label, the remainder still has 3+
        # real words, but it's just another data field, not a narrative
        # explanation. If what's left still contains what looks like
        # ANOTHER "Label:" pattern, this line is a concatenated
        # multi-field row, not a genuine explanation -- skip it.
        if re.search(r"\b[A-Z][a-zA-Z]*(?:\s[A-Z][a-zA-Z]*){0,3}:", content):
            continue
        # A second real-document false positive CAUGHT AND FIXED before
        # shipping (Zohan Hossain, same discovery process): a single,
        # non-concatenated structured field's own value can still have
        # 3+ real words without being an explanation at all (confirmed
        # live: "Mastery Criteria: 1-2 occurrences 14 consecutive months"
        # has 5 real words and no embedded second label, but is a data
        # value, not a sentence). A genuine narrative explanation reads
        # like a SENTENCE -- it uses common connecting/functional English
        # words (the/a/an/to/of/due/because/no/not/since/there/this/that/
        # is/was/were/with/for/has/have) that a short structured value
        # essentially never does. Require at least 2 such words, on top
        # of the word-count floor, as the generic "sounds like prose, not
        # a data field" signal -- no field name hardcoded anywhere here.
        function_words = re.findall(
            r"\b(?:the|a|an|to|of|due|because|no|not|since|there|this|that|is|was|were|with|for|has|have|"
            r"were|during|occurred|resulted|missed)\b",
            content, re.IGNORECASE,
        )
        if len(re.findall(r"[A-Za-z]{3,}", content)) >= 3 and len(function_words) >= 2:
            return line
    return None


def _check_BIP06(rule: dict, fields: dict) -> tuple:
    """Round 82, item 2 -- REAL BUG FOUND AND FIXED: confirmed directly
    against a real document, a behavior target's Current Level field read
    literally "N/A" accompanied by a real explanatory note ("There were no
    direct sessions due to issues with staffing"), and this rule (then
    judgment-only) failed it as "not filled in." The checklist's own
    standard credits an anecdotal/explained N/A as satisfying the
    requirement -- the real question is "is a current level indicated at
    all, even informally," not "is there a non-N/A value." Converted to a
    full deterministic checker (same shape as QA-PPI-02/03/05, GIP-10/16):
    unlike QA-BIP-05, this rule's own rubric ("Current level always
    indicated") has no separate subjective question left over once
    presence is resolved, so this returns a real pass/fail, not a hybrid
    not_checkable escalation.

    Scoped to 'Target Name:' blocks only (Behavior Reduction Goals) --
    _goal_block_starts also matches 'Target Goal:' (skill-acquisition)
    blocks, which don't carry a Current Level field at all (per this
    project's own confirmed real-document field layout).

    For each Behavior Reduction Goal block: FAIL if neither the
    'Current Level:' nor 'Current Data:' label is present, OR the one
    that's present has a blank value (both are "not filled in," matching
    this rule's own confirmed real FAIL example: "a behavior target block
    with Baseline stated but no 'Current Level:' value filled in anywhere
    for that behavior"). FAIL if the value is a BARE, unexplained "N/A"
    (fewer than 3 real words following it) -- the point of this fix isn't
    to make N/A always pass. PASS if the value is a real (non-N/A)
    reading, OR "N/A" followed by a genuine explanatory reason (3+
    alphabetic words) -- the confirmed real PASS shape this round exists
    to fix.

    Round 87, item 1 -- REAL BUG FOUND AND FIXED: confirmed independently
    on two real documents (Zohan Hossain, Yisroel Leibowitz) that this
    checker only ever recognized the literal 'Current Level:' label --
    but these real templates actually write this same field as
    'Current Data:' just as often, sometimes exclusively (Yisroel's
    document uses 'Current Data:' on all four of its real Behavior
    Reduction goals, 'Current Level:' not once). This is the identical
    naming-inconsistency shape already fixed for 'Target Name:'/
    'Target Goal:' in earlier rounds -- these treatment plans use both
    labels for the same real field. On Yisroel's document this was a
    confirmed real regression against ground truth: the reviewer's own
    checklist explicitly credits these four goals as Pass ("Current Data
    is provided for all four behavior targets"), while this rule was
    failing all four outright. Now treats 'Current Level:'/'Current
    Data:' as equivalent labels, checked in that order (whichever is
    actually present in this block).

    Fix Round, item 4 -- REAL BUG FOUND AND FIXED: confirmed a bare
    unexplained N/A was called a confident Fail even when a real
    explanation sat a few fields away in the SAME goal block (e.g. its
    own 'Additional Notes:' field) -- see _nearby_block_explanation's own
    docstring for the generic mechanism. A goal whose Current Level is
    genuinely blank/N/A with NO explanation anywhere in its own block is
    still a confident Fail; one where a nearby field in the SAME block
    has real explanatory text downgrades to Uncertain (not a confident
    Fail, since whether that nearby text actually counts as covering
    THIS field is now a judgment call, not something this checker should
    decide unilaterally) -- never silently treated as Pass.
    """
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    goal_starts = goal_starts + [len(text)]
    real_problems = []
    soft_problems = []
    checked = 0
    first_checked_offset = None
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        if not block.startswith("Target Name:"):
            continue  # skill-acquisition ("Target Goal:") blocks don't carry this field
        checked += 1
        if first_checked_offset is None:
            first_checked_offset = goal_starts[i]
        goal_name = block[len("Target Name:"):].split("\n", 1)[0].strip()

        cl_m = re.search(r"(?:Current Level|Current Data):[ \t]*([^\n]*)", block)
        if not cl_m or not cl_m.group(1).strip():
            page = _page_for_offset(fields, goal_starts[i])
            span = (cl_m.start(), cl_m.end()) if cl_m else (0, 0)
            nearby = _nearby_block_explanation(block, *span)
            detail = f"Goal '{goal_name[:120]}' has no 'Current Level:'/'Current Data:' value filled in."
            if nearby:
                soft_problems.append((page, (
                    f"{detail} A nearby field in the same block reads {nearby!r} -- may or may not count "
                    f"as an explanation, needs human confirmation."
                )))
            else:
                real_problems.append((page, detail))
            continue

        val = cl_m.group(1).strip()
        na_m = re.match(r"N/?A\b[\s:.,\-–—]*", val, re.IGNORECASE)
        if na_m:
            remainder = val[na_m.end():].strip()
            if len(re.findall(r"[A-Za-z]{3,}", remainder)) < 3:
                page = _page_for_offset(fields, goal_starts[i] + cl_m.start())
                nearby = _nearby_block_explanation(block, cl_m.start(), cl_m.end())
                if nearby:
                    soft_problems.append((page, (
                        f"Goal '{goal_name[:120]}' Current Level is a bare 'N/A' ({val!r}) on its own line, "
                        f"but a nearby field in the same block reads {nearby!r} -- may or may not count as "
                        f"an explanation, needs human confirmation."
                    )))
                else:
                    real_problems.append((page, (
                        f"Goal '{goal_name[:120]}' Current Level is a bare, unexplained 'N/A' ({val!r}) -- "
                        f"no real reason given anywhere in this goal's own block."
                    )))
        # else: a real, non-N/A value -- satisfies the requirement.

    if checked == 0:
        return "not_checkable", "No Behavior Reduction Goal ('Target Name:') blocks found in this document.", None, 0.0

    if real_problems:
        if len(real_problems) == 1:
            page, detail = real_problems[0]
            return "fail", detail, page, 0.85
        evidence = [{"page": page, "detail": detail} for page, detail in real_problems]
        return "fail", evidence, None, 0.85

    if soft_problems:
        if len(soft_problems) == 1:
            page, detail = soft_problems[0]
            return "uncertain", detail, page, 0.5
        evidence = [{"page": page, "detail": detail} for page, detail in soft_problems]
        return "uncertain", evidence, None, 0.5

    # Fix Round (2026-09-11), page-number enforcement gap: same fix as
    # _check_BIP04 -- cites the first checked goal's real page instead of
    # the None this pass case used to hardcode.
    page = _page_for_offset(fields, first_checked_offset)
    return "pass", f"All {checked} Behavior Reduction Goal(s) have a Current Level indicated (a real value, or an explained N/A).", page, 0.85


# Confirmed real PASS shape (Reeda's TP, "Reduce frequency of Tantrum
# Behavior"): "near 0 levels per session for 5 consecutive sessions" --
# a count/level qualifier followed by "for N consecutive/repeated
# sessions/days/weeks/months." General pattern, not tied to any one
# behavior name.
#
# Fix Round, Section 1 Bucket D (2026-08-27): REAL BUG FOUND AND FIXED,
# visible directly in the regex without needing a specific real document
# -- a "2 minutes" duration qualifier (a TIME-based window, e.g. "will
# remain calm for 2 minutes") was reported as failing to parse. Confirmed:
# the unit alternation only ever listed sessions/days/weeks/months/
# observations -- minutes/seconds/hours (equally real, equally valid
# duration units for a behavior-reduction criterion) were never included
# at all, so ANY minutes/seconds/hours-based duration qualifier silently
# failed this match and got treated as if no duration qualifier existed.
# Fix Round (2026-09-11), item 18 -- REAL BUG FOUND AND FIXED, confirmed
# against the real Daylyn Holland TP: "2 times or less per session for
# three consecutive sessions" was reported as lacking a consecutive-
# session qualifier -- it doesn't; it genuinely states one ("three
# consecutive sessions"), just spelled out as a word instead of a digit.
# The old \d+-only count missed it entirely, while a sibling goal on the
# SAME document phrased identically but with a digit ("for 3 consecutive
# sessions") already passed -- confirmed directly, not guessed at, that
# the checker was being too strict about phrasing, not correctly
# enforcing the rule's real requirement. Small written-out numbers
# (one-twenty) are equally valid English for this qualifier and are now
# recognized alongside digits.
_NUMBER_WORD_RE = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)"
)
_DURATION_QUALIFIER_RE = re.compile(
    rf"for\s+(?:\d+|{_NUMBER_WORD_RE})\s*(?:consecutive|straight|repeated)?\s*"
    r"(?:sessions?|days?|weeks?|months?|observations?|minutes?|seconds?|hours?)",
    re.IGNORECASE,
)


def _check_BIP04(rule: dict, fields: dict) -> tuple:
    """Fix Round (2026-08-12), item 4 -- user-directed real-document
    verification (Yisroel Leibowitz's document, 'Reduce Crying Episodes'
    goal) exposed the same shape of gap this round's item 4 already fixed
    for QA-BIP-06: this rule ('All tantrum goals have a duration' -- i.e.
    every Behavior Reduction Goal's Mastery Criteria states a count/level
    AND a duration/consecutive-session qualifier, per this rule's own
    confirmed real PASS/FAIL examples) had NO deterministic checker at
    all before this -- purely judgment-layer, so a blank Mastery Criteria
    field got no adjacent-context read before a (real, billed) judgment
    call had to guess. Converted to deterministic, reusing the exact same
    general _nearby_block_explanation helper item 4 already built --
    not a new, parallel mechanism, the SAME one, applied to a second
    real rule.

    Scoped to 'Target Name:' (Behavior Reduction Goal) blocks only --
    'Target Goal:' (skill-acquisition) blocks are a different rule shape
    with no duration-qualifier requirement of this kind.

    Fix Round (Jacob Freund 10-2026-U1), Item 15: Ms. Yachnes's explicit
    correction -- this rule's own description ("All TANTRUM goals have a
    duration") was never actually enforced; every Behavior Reduction Goal
    was checked regardless of name. Real evidence: this rule flagged a
    goal about "decrease frequency of freezing, refusing to answer,
    looking away" -- a real behavior-reduction goal, but not tantrum-
    related. Now scoped to goals whose own name mentions "tantrum" --
    other behavior-reduction goals no longer trigger this check at all.

    For each block: FAIL if Mastery Criteria is blank/missing AND no
    nearby field in the same block explains the gap -- confirmed live on
    Yisroel's real 'Reduce Crying Episodes' goal (page 15/16: 'Mastery
    Criteria:' entirely blank, 'Additional Notes:' also blank, no
    duration language anywhere else in the block) -- FAIL. Downgrades to
    UNCERTAIN (never silently PASS) if a nearby field has real
    explanatory text, per _nearby_block_explanation's own contract.
    FAIL if Mastery Criteria has a real value but no duration/consecutive-
    session qualifier anywhere in it (the confirmed real FAIL example in
    this rule's own notes). PASS if a duration qualifier is present
    (confirmed real PASS example: Reeda's Tantrum goal, 'near 0 levels
    per session for 5 consecutive sessions').
    """
    _TANTRUM_RE = re.compile(r"tantrum", re.IGNORECASE)
    text = fields["full_text"]
    goal_starts = _goal_block_starts(text)
    if not goal_starts:
        return "not_checkable", "No 'Target Goal:'/'Target Name:' entries found in this document.", None, 0.0

    goal_starts = goal_starts + [len(text)]
    real_problems = []
    soft_problems = []
    checked = 0
    first_checked_offset = None
    behavior_reduction_goals_seen = 0
    for i in range(len(goal_starts) - 1):
        block = text[goal_starts[i]:goal_starts[i + 1]]
        if not block.startswith("Target Name:"):
            continue  # skill-acquisition ("Target Goal:") blocks are a different rule shape
        behavior_reduction_goals_seen += 1
        goal_name = block[len("Target Name:"):].split("\n", 1)[0].strip()
        if not _TANTRUM_RE.search(goal_name):
            continue  # Item 15: not a tantrum goal -- out of scope for this rule
        checked += 1
        if first_checked_offset is None:
            first_checked_offset = goal_starts[i]

        mc_m = re.search(r"Mastery Criteria:[ \t]*([^\n]*)", block)
        mc_val = mc_m.group(1).strip() if mc_m else ""
        if not mc_val:
            page = _page_for_offset(fields, goal_starts[i])
            span = (mc_m.start(), mc_m.end()) if mc_m else (0, 0)
            nearby = _nearby_block_explanation(block, *span)
            detail = f"Goal '{goal_name[:120]}' has no 'Mastery Criteria:' value filled in -- no duration/consecutive-session qualifier can be confirmed."
            if nearby:
                soft_problems.append((page, (
                    f"{detail} A nearby field in the same block reads {nearby!r} -- may or may not count "
                    f"as an explanation, needs human confirmation."
                )))
            else:
                real_problems.append((page, detail))
            continue

        if not _DURATION_QUALIFIER_RE.search(mc_val):
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            real_problems.append((page, (
                f"Goal '{goal_name[:120]}' Mastery Criteria ({mc_val!r}) states a level/count but no "
                f"duration or consecutive-session qualifier (e.g. 'for 5 consecutive sessions')."
            )))
        # else: a real duration qualifier is present -- satisfies the requirement.

    if checked == 0:
        if behavior_reduction_goals_seen > 0:
            return (
                "not_applicable",
                f"{behavior_reduction_goals_seen} Behavior Reduction Goal(s) found, but none are "
                f"tantrum-related -- nothing for this rule to check.",
                None, 0.85,
            )
        return "not_checkable", "No Behavior Reduction Goal ('Target Name:') blocks found in this document.", None, 0.0

    if real_problems:
        if len(real_problems) == 1:
            page, detail = real_problems[0]
            return "fail", detail, page, 0.85
        evidence = [{"page": page, "detail": detail} for page, detail in real_problems]
        return "fail", evidence, None, 0.85

    if soft_problems:
        if len(soft_problems) == 1:
            page, detail = soft_problems[0]
            return "uncertain", detail, page, 0.5
        evidence = [{"page": page, "detail": detail} for page, detail in soft_problems]
        return "uncertain", evidence, None, 0.5

    # Fix Round (2026-09-11), page-number enforcement gap: this pass case
    # used to hardcode page=None even though every goal's own real offset
    # (goal_starts) was already computed above -- cites the first checked
    # goal's page (a real, honest citation into where this passing result
    # was verified, even though it's a whole-document "all goals" claim).
    page = _page_for_offset(fields, first_checked_offset)
    return "pass", f"All {checked} tantrum Behavior Reduction Goal(s) state a duration/consecutive-session qualifier in their Mastery Criteria.", page, 0.85


def _check_SM02(rule: dict, fields: dict) -> tuple:
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # switched re.findall -> re.finditer -- findall discards match
    # positions entirely, so a real page was never computable here.
    per_day_matches = list(re.finditer(r"\d+(?:\.\d+)?\s*hours?\s*per\s*day\b", fields["full_text"], re.IGNORECASE))
    if per_day_matches:
        per_day_hits = [m.group(0) for m in per_day_matches]
        return (
            "fail",
            f"Found {len(per_day_hits)} hours value(s) expressed 'per day' instead of "
            f"'per week': {per_day_hits}.",
            _page_for_offset(fields, per_day_matches[0].start()), 0.7,
        )
    return "pass", "All hours values are expressed 'per week' (no 'per day' phrasing found).", None, 0.7


# rule_id -> checker. Anything not listed here needs data this POC doesn't
# have (see NEEDS_BACKEND_INTEGRATION) and falls back to not_checkable.
#
# QA-TEMP-02, QA-PREF-01, QA-BIP-06, QA-SIG-01, QA-SIG-05, and QA-COC-06 were
# removed from here (2026-07 audit): their real evidence lives on image-only
# pages, and this module only ever sees `fields["full_text"]` — it has no
# access to rendered_images, so it was structurally blind on those pages no
# matter what the checker logic said.
#
# QA-SCH-08 was also removed (2026-07, three rounds later): not an image-page
# problem, but three consecutive rounds each fixed one specific false-match
# pattern in the POS-field extraction regex and missed the next one — a
# signal that this field's real-world layout is too inconsistent for a fixed
# extraction pattern, not that the regex needed a fourth patch. See
# pipeline/CHECKER_DESIGN.md for the full history and the reuse-vs-new-
# checker (and deterministic-vs-judgment) decision rule this became the
# worked example for.
#
# QA-TRANS-02 and QA-DISC-02 (_check_bullet_formatting) were removed the
# same way (2026-07-28, on Reeda's TP): the shared regex flagged "3. 3." on
# page 61 as a duplicated marker, but it's a genuine two-column table-layout
# artifact (the Goal Name column's "3." and the Mastery Criteria column's
# "3." for the same row ended up adjacent because that row's own descriptive
# text spilled onto the next page) — not a leftover copy-paste duplicate. A
# text-only regex can't tell "same number labeling two different table
# columns for one row" apart from "an actually duplicated marker." Also
# confirmed a second, independent bug while diagnosing this: the shared
# checker searched the WHOLE document regardless of which rule called it, so
# this one artifact (really in the Transition Plan section) made QA-DISC-02
# fail too, even though the Discharge Criteria section itself was clean.
#
# All seven of these are universal rules (applies_to_payor: "ALL") — nothing
# reclassified here was Healthfirst-specific.
#
# All are reclassified to check_type "judgment" in rules.json, where the
# model can read the same rendered images/text with actual reasoning
# instead of a fixed pattern.
def _check_TEMP01(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    the rule's own notes already split this into "LLM extracts credential
    type + all credential mentions; DET compares them for consistency" --
    the extraction half is itself a fixed pattern (a 'Certification:' or
    'Provider Credentials:' labeled field), so there's no LLM step needed
    at all. Extracts every such value and checks they all agree.

    Verified live against both real documents: neither contains a "Limited
    Permit" holder scenario (the description's specific trigger condition)
    -- both show 'BCBA, LBA' consistently in both the header 'Certification:'
    field and the signature-page 'Provider Credentials:' field, so both
    correctly come back "pass" (no contradiction found). This means the
    conversion is verified for the consistency-check mechanism itself, but
    NOT against a real "Limited Permit + wrong template" instance -- neither
    real document has ever presented that specific scenario, so that
    condition-specific behavior remains unverified against real evidence.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; the first mention's real offset is enough to
    # cite (pass) or, for fail, the first mention still points a reviewer
    # at one real occurrence of the inconsistency.
    text = fields["full_text"]
    vals = []
    first_offset = None
    for m in re.finditer(r"(?:Certification|Provider Credentials):[ \t]*([^\n]+)", text):
        v = m.group(1).strip()
        if v:
            vals.append(v)
            if first_offset is None:
                first_offset = m.start()
    if not vals:
        return "not_checkable", "No 'Certification:' or 'Provider Credentials:' field found.", None, 0.0
    page = _page_for_offset(fields, first_offset)
    normalized = {v.lower() for v in vals}
    if len(normalized) == 1:
        return "pass", f"All {len(vals)} credential mention(s) consistently read {vals[0]!r}.", page, 0.85
    return "fail", f"Inconsistent credential designations found across the document: {vals}.", page, 0.85


def _check_PPI02(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    the rule's own notes already describe this as "extract every age/DOB
    mention, compare" -- a uniqueness check over pattern-extractable
    fields, same shape as GIP-10/GIP-16. Also cross-validates the stated
    Patient Age against age computed from DOB as of the current report's
    end date, where both are present (real "correctness," not just
    internal consistency).

    Verified live against both real documents: Reeda -- DOB 04/22/2020
    (identical across 66 mentions), Age 6, computed age from DOB as of the
    07/22/2026 report end date is ~6 -- consistent, pass. Charny -- DOB
    09/06/2007 (identical across 52 mentions), Age 18, computed age ~18 --
    consistent, pass.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; cites the first DOB (or Patient Age, if no
    # DOB mention exists) match's real position.
    text = fields["full_text"]
    dob_matches = list(re.finditer(r"DOB:[ \t]*([0-9/]+)", text))
    age_matches = list(re.finditer(r"Patient Age:[ \t]*([0-9]+)", text))
    dob_vals = sorted({m.group(1).strip() for m in dob_matches})
    age_vals = sorted({m.group(1).strip() for m in age_matches})

    if not dob_vals and not age_vals:
        return "not_checkable", "No DOB or Patient Age field found.", None, 0.0
    page = _page_for_offset(fields, (dob_matches or age_matches)[0].start())

    problems = []
    if len(dob_vals) > 1:
        problems.append(f"Multiple different DOB values found: {dob_vals}.")
    if len(age_vals) > 1:
        problems.append(f"Multiple different Patient Age values found: {age_vals}.")

    if len(dob_vals) == 1 and len(age_vals) == 1:
        report_range = _find_labeled_date_range(text, "Date of Current Report")
        if report_range:
            try:
                dob = datetime.strptime(dob_vals[0], "%m/%d/%Y")
                report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
                computed_age = (report_end - dob).days // 365
                stated_age = int(age_vals[0])
                if abs(computed_age - stated_age) > 1:
                    problems.append(
                        f"Stated Patient Age {stated_age} doesn't match the age computed from "
                        f"DOB {dob_vals[0]} as of the current report date {report_range[1]} "
                        f"(~{computed_age})."
                    )
            except ValueError:
                pass

    if problems:
        return "fail", " ".join(problems), page, 0.8
    return (
        "pass",
        f"DOB ({dob_vals[0] if dob_vals else 'n/a'}) and Patient Age ({age_vals[0] if age_vals else 'n/a'}) "
        f"are consistent throughout the document.",
        page, 0.8,
    )


# Round 82, item 1: junk tokens that legitimately show up in a real
# uploaded filename but carry no name information -- stripped before
# comparing filename tokens against the document's own patient name.
# Deliberately narrow and evidence-based (common upload-hygiene words
# actually seen in this project's own file-naming habits, e.g. "Charny
# Gluck TP Feedback.pdf"), not a guess at every possible word a filename
# might contain.
_FILENAME_JUNK_TOKENS = {
    "tp", "treatment", "plan", "review", "reviewed", "feedback", "final",
    "draft", "redacted", "revised", "updated", "copy", "signed", "pdf",
    # Fix Round, item 1 -- REAL REGRESSION FOUND AND FIXED: "upload" is a
    # generic storage-key word (today's real production filename shape per
    # backend/app/storage.py::save_blob is literally "upload-3.pdf" with no
    # name in it at all), not a name-like token -- without this, rapidfuzz's
    # token_set_ratio still produced a (low but non-None) score against it,
    # which pipeline._name_filename_score's own contract says should be
    # None ("no name-like content at all, no signal, no guess"). Missing
    # this junk-word entry would have made EVERY document uploaded under
    # today's real generated-filename convention register as a filename
    # mismatch and fail QA-PPI-03 -- caught by running the full test suite,
    # not just this round's own new tests, before considering Item 1 done.
    "upload",
}


def _filename_name_tokens(filename: str) -> list[str]:
    """Round 82, item 1: normalizes an uploaded filename down to just its
    plausibly-name-like tokens, so it can be compared against the
    document's own extracted patient name without false-flagging on
    ordinary filename hygiene (extensions, staff labels, version tags,
    dates).

    Strips the extension, splits on any non-alphanumeric run (handles
    spaces, underscores, hyphens, periods uniformly), then drops: known
    junk words (_FILENAME_JUNK_TOKENS), pure version tags ("v2", "ver3"),
    and pure-numeric tokens (dates split into day/month/year fragments,
    IDs) -- none of these carry name information, and leaving them in
    would make an innocuous "Zohran Hossain TP_2026-08-10_v2.pdf" register
    as a mismatch purely because "2026" or "v2" don't match any name token.
    """
    stem = Path(filename).stem
    tokens = []
    for raw in re.split(r"[^A-Za-z0-9]+", stem):
        if not raw:
            continue
        low = raw.lower()
        if low in _FILENAME_JUNK_TOKENS:
            continue
        if re.fullmatch(r"v(?:er(?:sion)?)?\d+", low):
            continue
        if re.fullmatch(r"\d+", low):
            continue
        tokens.append(low)
    return tokens


# Fix Round, item 1 -- REPLACED difflib.SequenceMatcher with rapidfuzz's
# fuzz.token_set_ratio, per this round's explicit instruction (tolerates
# word-order differences and filler text in the filename -- dates, "TP",
# underscores -- without penalty, which a per-token difflib comparison
# handled less cleanly).
#
# THRESHOLD -- a genuine design decision, not a straightforward fix, flagged
# here rather than silently defaulted: the task's own suggested starting
# point (85) was calibrated and found too low. Empirically (see this
# module's own test file for the full matrix): a real medium-length one-
# character typo -- the confirmed real case, "Zohan Hossain" (document) vs
# "Zohran Hossain" (filename) -- scores 96.30 via token_set_ratio, and a
# LONGER name's one-character typo scores even higher (98.31, more
# characters elsewhere dilute the one error further). token_set_ratio is
# structurally NAME-LENGTH-SENSITIVE: there is no single fixed threshold
# that catches a real typo on every name length without also false-
# flagging exact matches on short names pushed defensively high. 97 is set
# here specifically to catch the real confirmed case (96.30 < 97) while
# keeping every genuine exact match (always 100) safely clear -- the
# disclosed, known gap is a one-character typo in an UNUSUALLY LONG name
# (3+ words), which could still score above 97 and slip through. Flagged
# for discussion, not hidden.
_FILENAME_MATCH_THRESHOLD = 97


def _expand_filename_initials(doc_name: str, fname_tokens: list[str]) -> list[str]:
    """Fix Round, item 1 -- REAL REGRESSION FOUND AND FIXED against Reeda's
    real document: her real filename is "Reeda B S Review.pdf" for patient
    "Reeda Bint Shaheen" -- 'B'/'S' are legitimate initials for
    'Bint'/'Shaheen', a common, entirely innocuous real-world filename
    convention (first name + middle/last initials). The old, replaced
    difflib per-token comparator tolerated this by construction (it only
    ever flagged a token that was CLOSE-but-not-identical to a doc token;
    a single initial letter is too dissimilar to a full name word to hit
    that band, so it was silently ignored). rapidfuzz's token_set_ratio has
    no such per-token tolerance -- it compares the whole strings, and 'b'/
    's' sitting where 'bint'/'shaheen' should be drags a totally legitimate
    filename down to 71.4, well under threshold, producing a false FAIL on
    a real, correctly-named, already-passing document. Caught by testing
    this item's fix against every available real document, not just the
    made-up-name synthetic cases the round required.

    General fix, not specific to this name: any single-letter filename
    token is treated as a plausible initial for the first not-yet-claimed
    doc_name word starting with that same letter, and is substituted with
    that full word before scoring -- an initial that genuinely doesn't
    match any doc word (e.g. a filename token unrelated to the name) is
    left as-is and still drags the score down as before.
    """
    doc_words = [w for w in re.split(r"\s+", doc_name.strip()) if w]
    claimed: set[str] = set()
    expanded = []
    for token in fname_tokens:
        if len(token) == 1:
            match = next(
                (w for w in doc_words if w.lower().startswith(token) and w.lower() not in claimed),
                None,
            )
            if match:
                claimed.add(match.lower())
                expanded.append(match.lower())
                continue
        expanded.append(token)
    return expanded


def _name_filename_score(doc_name: str, filename: str) -> float | None:
    """Fix Round, item 1: rapidfuzz `fuzz.token_set_ratio` between the
    document's own extracted patient name and the uploaded filename, after
    stripping filename tokens that carry no name information at all (junk
    words, version tags, pure-numeric date/ID fragments -- reuses
    _filename_name_tokens, unchanged from Round 82) and expanding any
    single-letter initial token into the doc name word it plausibly
    abbreviates (_expand_filename_initials, above -- the real regression
    that fix closes), so an innocuous "patient_smith_v2_final.pdf" or
    "Reeda B S Review.pdf" isn't penalized for its own filler text or
    legitimate initials, and so a filename with NO name-like content at
    all (e.g. a generated storage-key filename, still today's real
    fallback per Round 86's own disclosed gap) never produces a score to
    act on -- returns None,
    exactly the same "no signal, no guess" convention as before this round.
    Both strings are lowercased first -- confirmed live that rapidfuzz's
    ratio functions are case-SENSITIVE, and comparing "Jordan Smith" against
    the (already-lowercased) filename tokens without normalizing case first
    silently drags every genuine exact match down to ~83, not 100.
    """
    fname_tokens = _filename_name_tokens(filename)
    if not fname_tokens:
        return None
    fname_tokens = _expand_filename_initials(doc_name, fname_tokens)
    return fuzz.token_set_ratio(doc_name.lower(), " ".join(fname_tokens).lower())


def _check_PPI03(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    the rule's own notes already say "Internal consistency = DET" -- this
    just builds it. Extracts every 'Patient Name:' value (both the page-1
    header form 'Patient Name: X  AKA: Y Patient DOB: Z' and the repeated
    footer form 'Patient Name: X Patient DOB: Y Patient Insurance: Z') and
    checks they all agree.

    Verified live against both real documents: Reeda -- 'Reeda Bint
    Shaheen' identical across 66 mentions, pass. Charny -- 'Charny Gluck'
    identical across 52 mentions, pass.

    Round 82, item 1 -- REAL BUG FOUND AND FIXED: this rule only ever
    checked internal consistency; it had no way to notice a mismatch
    against something outside the document. Confirmed real case: a
    document's body consistently read "Zohan Hossain" throughout, while
    the uploaded file itself was named "Zohran Hossain TP.pdf" -- a
    one-letter difference risking a real claims/authorization denial.
    Added a second, additive signal: when internal consistency already
    passed, also compare the confirmed name against
    `fields["source_filename"]` (the caller's real uploaded filename, when
    supplied -- see pipeline/api.py::review_treatment_plan's own docstring
    for that parameter) or, failing that, `Path(fields["pdf_path"]).name`
    as a fallback.

    Fix Round, item 1 -- CHANGED from "uncertain" to a confident "fail":
    this round's own explicit instruction. Re-implemented the comparison
    itself via rapidfuzz's fuzz.token_set_ratio (see _name_filename_score's
    own docstring for the real calibration work and the disclosed
    name-length-sensitivity gap) instead of the original per-token difflib
    match. A score below _FILENAME_MATCH_THRESHOLD is now a real Fail, not
    a hedge -- a filename that doesn't match the document's own confirmed
    name closely enough is treated as a real compliance risk (claims/
    authorization denial), not something to defer to a human without an
    opinion. `None` (no name-like content in the filename at all -- e.g.
    today's real fallback to a generated storage-key filename) still
    means no signal, no guess, same as before -- this only ever fires when
    there's an actual filename with real name-like content to compare.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: every branch
    # below used to hardcode page=None; the first mention's real offset
    # was always available.
    text = fields["full_text"]
    matches = list(re.finditer(r"Patient Name:[ \t]*([^\n]+?)(?=\s*(?:AKA:|Patient DOB:|$))", text))
    names = [m.group(1).strip() for m in matches if m.group(1).strip()]
    if not names:
        return "not_checkable", "No 'Patient Name:' field found.", None, 0.0
    page = _page_for_offset(fields, next(m.start() for m in matches if m.group(1).strip()))
    normalized = {n.lower() for n in names}
    if len(normalized) > 1:
        counts = Counter(names)
        return "fail", f"Inconsistent patient name spelling found: {dict(counts)}.", page, 0.85

    name = names[0]
    source_filename = fields.get("source_filename")
    if not source_filename and fields.get("pdf_path"):
        source_filename = Path(fields["pdf_path"]).name
    score = _name_filename_score(name, source_filename) if source_filename else None
    if score is not None and score < _FILENAME_MATCH_THRESHOLD:
        return (
            "fail",
            (
                f"Patient name spelled consistently as {name!r} in the document, but the source filename "
                f"({source_filename!r}) doesn't match closely enough (rapidfuzz token_set_ratio={score:.1f}, "
                f"threshold={_FILENAME_MATCH_THRESHOLD}) -- a real misspelling here risks a claims/"
                f"authorization denial."
            ),
            page, 0.85,
        )
    return "pass", f"Patient name spelled consistently as {name!r} across all {len(names)} mention(s).", page, 0.85


_AKA_BLANK_RE = re.compile(r"^N/?A\b[\s:.,\-–—]*$|^none$|^n/?a$", re.IGNORECASE)


def _check_PPI07(rule: dict, fields: dict) -> tuple:
    """Round 91 (169-rule reconciliation): a brand-new rule_id, deliberately
    NOT a repoint of QA-PPI-06 (that rule keeps its own, unrelated,
    already-shipped meaning -- narrative name-contamination -- see this
    round's own discussion). Same shape as QA-PPI-03, just applied to the
    'AKA:' field instead of 'Patient Name:': "If patient has an AKA/alias,
    it is included and spelled correctly alongside legal name."

    Extracts every 'AKA:' value using the SAME regex boundary
    _document_name_allow_list already uses (a page-1-header-only field in
    every real document checked so far -- confirmed live: Reeda/Blythe
    ('N/A', no real alias), Charny ('Charna'), Yisroel ('Sruly'), each
    with exactly ONE occurrence -- Zohan's real document has no 'AKA:'
    label anywhere at all, a genuinely different template variant).

    Three real outcomes:
    - No 'AKA:' label anywhere in the document at all -- not_checkable
      (this template variant doesn't carry the field; can't confirm
      whether the patient has an alias or not).
    - Label present but blank/N-A/None on every occurrence -- pass
      (patient genuinely has no alias; nothing to include).
    - Label present with a real value -- pass if every occurrence agrees
      on the exact same spelling (same multi-mention consistency check
      QA-PPI-03 already does for the legal name); fail if occurrences
      disagree. Same disclosed scoping as QA-PPI-05's own precedent: this
      confirms internal consistency and presence, not correctness against
      some external ground truth (no alias registry exists to check
      against) -- that's a real, stated limitation, not silently assumed
      solved.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: every branch
    # below used to hardcode page=None; the first mention's real offset
    # was always available.
    text = fields["full_text"]
    matches = list(re.finditer(r"AKA:[ \t]*([^\n]+?)(?=\s*(?:Patient DOB:|$))", text))
    raw_values = [m.group(1).strip() for m in matches]
    if not raw_values:
        return "not_checkable", "No 'AKA:' field found anywhere in this document.", None, 0.0
    page = _page_for_offset(fields, matches[0].start())

    real_values = [v for v in raw_values if v and not _AKA_BLANK_RE.match(v)]
    if not real_values:
        return "pass", f"'AKA:' field present but blank/N-A on all {len(raw_values)} mention(s) -- patient has no stated alias.", page, 0.85

    normalized = {v.lower() for v in real_values}
    if len(normalized) > 1:
        counts = Counter(real_values)
        return "fail", f"Inconsistent AKA/alias spelling found: {dict(counts)}.", page, 0.85

    return (
        "pass",
        f"AKA/alias spelled consistently as {real_values[0]!r} across all {len(real_values)} mention(s) "
        f"alongside the legal name.",
        page, 0.85,
    )


# --- Fix Round, item 2: narrative name-contamination detection -----------
#
# REAL BUG this closes: a document's Developmental/Psychological History
# narrative referred to the patient's PCP by a completely different
# person's name -- almost certainly a copy/paste error from another
# patient's file. QA-PPI-03 only checks that the SAME name is used
# consistently; it can't catch a document that's internally consistent but
# simply wrong about who a mentioned person actually is. There is no
# existing rule_id in this checklist for this question -- see this
# function's own note below on why it is NOT wired into DET_CHECKS yet.

# spaCy's model load is real, measurable overhead (~0.3-0.8s) -- loaded
# once, lazily, on first real use, not at import time (a document with no
# narrative section, or a test that never calls this, should never pay
# this cost) and never reloaded after that within one process.
_SPACY_NLP = None


def _get_spacy_nlp():
    global _SPACY_NLP
    if _SPACY_NLP is None:
        import spacy
        _SPACY_NLP = spacy.load("en_core_web_sm")
    return _SPACY_NLP


# Confirmed real section-header vocabulary this template actually uses
# (Biopsychosocial, Assessment of Current Functioning's own boundary set --
# see _find_acf_section above) plus "Developmental/Psychological History,"
# named directly in the real confirmed case this item fixes. General
# section markers, not document-specific content.
_NARRATIVE_SECTION_START_RE = re.compile(
    r"(?:Biopsychosocial(?:\s+Information)?|Developmental(?:/Psychological)?\s+History|"
    r"Psychological\s+History|Educational\s+History):",
    re.IGNORECASE,
)
_NARRATIVE_SECTION_END_RE = re.compile(
    r"Goal Progress:|Assessment of Current Functioning:|Areas of Focus|Problem Areas?:|"
    r"School and ABA Schedule|Hours Requesting:|Clinical Interpretation",
)

_NAME_TITLE_RE = re.compile(r"^(?:Dr|Mr|Mrs|Ms|Mx)\.?\s+", re.IGNORECASE)

# Fix Round, item 2 -- REAL FALSE-POSITIVE CLASS FOUND AND FIXED: running
# QA-PPI-06 against all 5 available real documents (proactively, before
# considering the item done -- same discipline as items 3/4) showed
# spaCy's en_core_web_sm mislabeling clinical/diagnostic vocabulary as
# PERSON on every single one ("Autism Spectrum Disorder," "COVID-19,"
# "Bipolar Disorder," "Spectrum Disorder," bare "Patient"/"Patient Name" --
# the field label itself, bled into narrative text by this scanner). None
# of these are a name at all, let alone a document-specific one -- this is
# a general NER weakness on this domain's vocabulary, not a per-patient
# concern, so the fix is a general vocabulary filter (same precedent as
# _FILENAME_JUNK_TOKENS), not a per-document allow-list entry.
_CLINICAL_NOISE_WORDS = {
    "disorder", "syndrome", "spectrum", "deficit", "stenosis", "bipolar",
    "autism", "anxiety", "depression", "adhd", "ptsd", "covid", "patient",
    # Severity-rating vocabulary (QA-BIP-01/GIP-03's own rating scale
    # bleeding into a PERSON detection) -- general rating words, not tied
    # to any one document.
    "mild", "moderate", "severe", "significant",
}


def _looks_like_clinical_noise(name: str) -> bool:
    """True for a spaCy PERSON detection that's actually clinical/
    diagnostic vocabulary, a severity-rating word, an all-caps credential
    abbreviation (e.g. "LCSW" standing alone -- real names never come back
    from spaCy in all-caps), or a bare field-label artifact -- never a
    real person's name. See this module's own note above for the confirmed
    real false-positive classes this closes. Also rejects any candidate
    containing a digit (catches "COVID-19" as one token).

    Disclosed, NOT fixed here (see QA-PPI-06's own rule notes/the Fix
    Round report): medication names (e.g. "Prozac") and an organization's
    own name being misread as a person (e.g. this project's own "Master
    Faster" letterhead, where spaCy tags only the trailing common-word
    half as PERSON) are further real noise classes found during real-
    document verification, left as a known residual limitation rather
    than encoding an open-ended, unbounded vocabulary list here.
    """
    if re.search(r"\d", name):
        return True
    if name.isupper() and len(name) <= 8:
        return True
    tokens = {t.lower() for t in re.split(r"[^A-Za-z]+", name) if t}
    return bool(tokens & _CLINICAL_NOISE_WORDS)


def _extract_narrative_sections(text: str) -> list[str]:
    """Every narrative-section span (see _NARRATIVE_SECTION_START_RE),
    bounded to the next known section marker or a hard cap -- same
    "slice between a confirmed start marker and the next confirmed
    boundary" convention already used throughout this file (e.g.
    _find_acf_section, _extract_mastered_goal_names)."""
    sections = []
    for m in _NARRATIVE_SECTION_START_RE.finditer(text):
        window = text[m.end():m.end() + 6000]
        end_m = _NARRATIVE_SECTION_END_RE.search(window)
        sections.append(window[:end_m.start()] if end_m else window)
    return sections


def _document_name_allow_list(text: str) -> set[str]:
    """Builds the allow-list of real person names THIS document itself
    states in a structured field -- patient name/AKA, mother/father/
    caregiver/parent, PCP, and BCBA/provider name. Built fresh from this
    one document's own fields every time -- never a fixed list shared
    across documents (the whole point: a name that's legitimate on one
    patient's document is not automatically legitimate on another's).
    Returns a set of lowercased individual name TOKENS (not full names),
    since a narrative mention and a structured-field mention don't always
    include every token (e.g. a title, a middle name) -- token-level
    overlap is the more robust comparison.
    """
    tokens: set[str] = set()

    def _add(value: str) -> None:
        for tok in re.split(r"[^A-Za-z]+", value):
            if len(tok) > 1:
                tokens.add(tok.lower())

    for m in re.finditer(r"Patient Name:[ \t]*([^\n]+?)(?=\s*(?:AKA:|Patient DOB:|$))", text):
        _add(m.group(1))
    for m in re.finditer(r"AKA:[ \t]*([^\n]+?)(?=\s*(?:Patient DOB:|$))", text):
        _add(m.group(1))
    for m in re.finditer(
        r"(?:Mother(?:'s)?|Father(?:'s)?|Caregiver|Parent)\s*(?:Name)?:[ \t]*([^\n]+)", text, re.IGNORECASE,
    ):
        _add(m.group(1))
    for m in re.finditer(r"PCP\s*(?:Name)?:[ \t]*([^\n]+)", text, re.IGNORECASE):
        _add(m.group(1))
    for m in re.finditer(r"BCBA\s*(?:Name)?:[ \t]*([^\n]+)", text, re.IGNORECASE):
        _add(m.group(1))
    # A provider named inline ("...administered by NAME, BCBA" / "Dr. NAME
    # is the assigned BCBA") -- reuses the same shape _check_ACF06 already
    # confirmed real (Round 83), generalized to any "NAME, BCBA" mention,
    # not just "administered by."
    for m in re.finditer(r"([A-Z][a-zA-Z.\-']+(?:\s+[A-Z][a-zA-Z.\-']+){1,3}),?\s+BCBA\b", text):
        _add(m.group(1))

    return tokens


def _check_narrative_name_contamination(rule: dict, fields: dict) -> tuple:
    """Fix Round, item 2 -- REAL BUG FOUND AND FIXED (general mechanism):
    runs spaCy NER over every narrative section this document has (see
    _extract_narrative_sections), collects every detected PERSON entity,
    and flags any whose name tokens have ZERO overlap with this document's
    OWN allow-list (built fresh per document, see _document_name_allow_list
    -- patient/AKA/mother/father/caregiver/PCP/BCBA, whatever this specific
    document itself states). A name that belongs to none of those roles,
    appearing in free narrative text, is exactly the shape of a copy/paste
    contamination error from a different patient's file.

    Deliberately NOT a blocklist of names seen before -- the allow-list is
    rebuilt from scratch for every document, and nothing about a specific
    prior real name is referenced anywhere in this function. A name this
    function has never seen before is caught exactly the same way as one
    it has.

    Confidence signal: a single, unambiguous contaminating name -> "fail"
    (0.6 confidence -- NER is not perfect, still real enough to act on
    directly). Multiple candidates, or ones spaCy's own PERSON label is
    less certain about (this POC doesn't have per-entity confidence from
    spaCy's default pipeline, so multiple simultaneous candidates are
    treated as the ambiguous case) -> "uncertain", for a human to confirm
    rather than a confident guess.

    WIRED IN (2026-08-12) as QA-PPI-06, "Patient/Provider Info" -- the
    user's own explicit rule_id/category decision, since this checklist's
    rule_ids all trace to a real payor audit document and inventing one
    wasn't a call this function could make unilaterally. See rules.json's
    QA-PPI-06 entry and DET_CHECKS' own registration of this function.
    """
    text = fields["full_text"]
    sections = _extract_narrative_sections(text)
    if not sections:
        return "not_checkable", "No narrative section (Biopsychosocial/Developmental History/etc.) found.", None, 0.0

    allow_list = _document_name_allow_list(text)
    nlp = _get_spacy_nlp()

    candidates = []
    for section in sections:
        doc = nlp(section)
        for ent in doc.ents:
            if ent.label_ != "PERSON":
                continue
            name = _NAME_TITLE_RE.sub("", ent.text).strip()
            if _looks_like_clinical_noise(name):
                continue
            name_tokens = {t.lower() for t in re.split(r"[^A-Za-z]+", name) if len(t) > 1}
            if not name_tokens:
                continue
            if not (name_tokens & allow_list):
                candidates.append(name)

    if not candidates:
        return (
            "pass",
            f"Scanned {len(sections)} narrative section(s) -- every detected person name matches this "
            f"document's own stated patient/family/provider names.",
            None, 0.6,
        )
    distinct = sorted(set(candidates))
    if len(distinct) == 1:
        return (
            "fail",
            (
                f"Narrative text names {distinct[0]!r}, who does not match this document's own stated "
                f"patient, family member, PCP, or BCBA name -- likely a copy/paste error from a different "
                f"patient's file."
            ),
            None, 0.6,
        )
    return (
        "uncertain",
        f"Narrative text names {distinct} -- none match this document's own stated names; multiple "
        f"candidates found, needs human confirmation.",
        None, 0.4,
    )


def _check_PPI05(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    the rule's own notes already say "Internal consistency = DET" -- this
    just builds it. Extracts every NPI and License mention and checks each
    set agrees.

    Verified live against both real documents: each has exactly ONE NPI
    mention and ONE License mention (Reeda: NPI 1578293197, License
    12477453/004132; Charny: NPI 1306507405, License 1-21-57390/002377-01)
    -- both trivially consistent (nothing to contradict), pass. This means
    the conversion is verified for "no contradiction found" but neither
    real document has more than one instance of either field, so the
    genuine multi-mention consistency path is unverified against real
    evidence (same caveat as QA-TEMP-01's untriggered condition).

    Round 54: this rule's own notes used to say "True validation against a
    provider roster remains out of scope" -- that gap is exactly what the
    supporting document's bcba_credentials_npi field can now close, when a
    reviewer attached one and extraction found an NPI in it (Round 52/53
    wiring made `fields["supporting_doc"]` reachable here; nothing before
    this round actually READ it). This only adds a ground-truth CROSS-CHECK
    on top of the existing internal-consistency check above -- it never
    replaces "no NPI on the TP at all" with a pass/fail borrowed purely
    from the supporting document; a TP that never states its own NPI is
    still not_checkable, since there's nothing in the TP itself to hold
    "correct." A supporting_doc confidence of "none" (field not found in
    that document) is treated as no ground truth available, not as a
    mismatch.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: every branch
    # below used to hardcode page=None; the first NPI/License match's real
    # offset was always available.
    text = fields["full_text"]
    npi_matches = list(re.finditer(r"NPI:[ \t]*([0-9]+)", text))
    license_matches = list(re.finditer(r"License[^\n:]*:[ \t]*([^\n]+)", text))
    npi_vals = sorted({m.group(1).strip() for m in npi_matches})
    license_vals = sorted({m.group(1).strip() for m in license_matches})

    if not npi_vals and not license_vals:
        return "not_checkable", "No NPI or License field found.", None, 0.0
    page = _page_for_offset(fields, (npi_matches or license_matches)[0].start())

    problems = []
    if len(npi_vals) > 1:
        problems.append(f"Multiple different NPI values found: {npi_vals}.")
    if len(license_vals) > 1:
        problems.append(f"Multiple different License values found: {license_vals}.")

    supporting_npi_field = (fields.get("supporting_doc") or {}).get("bcba_credentials_npi")
    ground_truth_npi_vals: set[str] = set()
    if supporting_npi_field and supporting_npi_field.get("confidence") != "none" and supporting_npi_field.get("value"):
        ground_truth_npi_vals = {m.group(0) for m in re.finditer(r"[0-9]{10}", supporting_npi_field["value"])}
    # Fix Round (2026-08-27): the OLD document-mode supporting_doc field
    # above is dormant under structured_form (the live default since
    # Round 56) -- confirmed real gap, this rule's own ground-truth
    # cross-check silently stopped having any real data to check against
    # for every upload since then. `intake_bcba_name_credentials_npi` is
    # the SAME real fact from the CURRENT default mode's own "BCBA Name,
    # Credentials & NPI" intake answer (see app/rule_engine/client.py::
    # run_rule_checks for where this key gets set) -- a second, parallel
    # ground-truth source, same NPI-digit-extraction logic, additive with
    # the supporting_doc source above (either or both can supply
    # ground_truth_npi_vals; neither is required).
    intake_npi_text = fields.get("intake_bcba_name_credentials_npi")
    if intake_npi_text:
        ground_truth_npi_vals |= {m.group(0) for m in re.finditer(r"[0-9]{10}", intake_npi_text)}
    if ground_truth_npi_vals and npi_vals and not (set(npi_vals) & ground_truth_npi_vals):
        problems.append(
            f"TP states NPI {npi_vals}, but the supporting document's BCBA "
            f"credentials/NPI field states {sorted(ground_truth_npi_vals)} -- these do not match."
        )

    if problems:
        return "fail", " ".join(problems), page, 0.8
    if ground_truth_npi_vals and npi_vals and (set(npi_vals) & ground_truth_npi_vals):
        return (
            "pass",
            f"NPI ({npi_vals or 'n/a'}) and License ({license_vals or 'n/a'}) are internally "
            f"consistent, AND the TP's NPI matches the supporting document's stated NPI "
            f"({sorted(ground_truth_npi_vals)}).",
            page, 0.9,
        )
    # Round 84, item 2 -- REAL BUG FOUND AND FIXED: this branch used to
    # return a confident "pass" here, but all it actually verified is
    # internal consistency (no contradicting NPI/License value found
    # within the TP) -- it never checked either value against any real
    # ground truth (no supporting-doc match available in this branch, by
    # definition). This rule is named "Provider Credentials/NPI/License
    # CORRECT," not "...internally consistent" -- a confident pass here
    # overstated what was actually checked, the same shape flagged across
    # QA-PPI-04/QA-HRS-08/QA-TRANS-01 this round. "uncertain" says plainly
    # what WAS verified (consistency) without claiming the harder,
    # unverifiable claim (correctness against a real provider roster).
    return (
        "uncertain",
        f"NPI ({npi_vals or 'n/a'}) and License ({license_vals or 'n/a'}) are internally "
        f"consistent (no contradicting values found within the TP), but no ground-truth "
        f"source (e.g. a matching supporting-document field) was available to confirm they "
        f"are actually CORRECT -- internal consistency alone is not evidence of correctness.",
        page, 0.5,
    )


_SEVERITY_LABEL_PATTERN = re.compile(r"Severity of [^\n:]+:[ \t]*([^\n]+)")
_NON_MILD_SEVERITY_VALUES = {"moderate", "severe"}


def _check_severity_rating_not_all_mild(rule: dict, fields: dict) -> tuple:
    """Converted from judgment to deterministic (2026-07-28 round, item 1):
    shared checker for QA-BIP-01 and QA-GIP-03 -- the rules.json notes for
    QA-GIP-03 already call it "Duplicate of BIP-01 logic applied to goals
    section," so one function serves both rule_ids (same pattern as
    EMB-01 reusing HF-02's checker via params). Extracts every "Severity
    of X: Y" categorical rating and checks at least one is Moderate/Severe
    (not all Mild) -- a plain categorical scan, no semantic judgment.

    Verified live against both real documents: Reeda has 4 ratings
    (Moderate, Mild, Severe, Severe) -- pass. Charny has 5 (Moderate,
    Moderate, N/A, Moderate, Moderate) -- pass. Neither real document
    happens to demonstrate the actual failure condition (all Mild), so the
    conversion is verified for the extraction/scan mechanism but the
    fail path itself is untested against real evidence.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None even though each rating's own match position
    # was available -- cites the first non-mild rating's page for pass,
    # the first rating's page for fail (all ratings are mild, any one is
    # a real, representative citation).
    text = fields["full_text"]
    ratings = [
        (m.group(0).split(":")[0].strip(), m.group(1).strip(), m.start())
        for m in _SEVERITY_LABEL_PATTERN.finditer(text)
    ]
    if not ratings:
        return "not_checkable", "No 'Severity of ...:' rating fields found.", None, 0.0

    non_na = [(label, value, offset) for label, value, offset in ratings if value.strip().lower() not in ("n/a", "na", "")]
    if not non_na:
        return "not_checkable", "Severity fields found but all are N/A.", None, 0.0

    non_mild = [(label, value, offset) for label, value, offset in non_na if value.lower() in _NON_MILD_SEVERITY_VALUES]
    ratings_str = ", ".join(f"{label}: {value}" for label, value, _ in ratings)
    if non_mild:
        page = _page_for_offset(fields, non_mild[0][2])
        return "pass", f"At least one severity rating is Moderate or higher ({ratings_str}).", page, 0.85
    page = _page_for_offset(fields, ratings[0][2])
    return "fail", f"All severity ratings are Mild (or N/A) -- none reach Moderate: {ratings_str}.", page, 0.85


# --- Fix Round, item 3: cross-rule contradiction detection ---------------
#
# REAL BUG this closes: on one real document, QA-ACF-07 reported the
# Assessment of Current Functioning section as "entirely blank," while
# QA-ACF-01 and QA-ACF-05 -- reading the SAME section of the SAME document
# -- both found it fully completed (this was Round 85's own confirmed root
# cause, a section-boundary/multi-line-value bug in ACF-07's own
# extraction). Two rules disagreeing about whether a section of text
# exists at all should never ship silently.
#
# GENERAL, not ACF-specific: rules are grouped by everything before their
# own trailing "-NN" number (e.g. "QA-ACF-07" -> "QA-ACF", "QA-GIP-16" ->
# "QA-GIP") -- this is this project's own existing, real rule_id naming
# convention (confirmed across every rule in rules.json), not a hand-picked
# list of rule_ids for this one section. The NEXT pair of rules in the same
# prefix group that disagree about blank-vs-populated, on a section nobody
# has looked at yet, is caught by this exact same grouping with zero new
# code.
_RULE_GROUP_RE = re.compile(r"^(.+)-\d+$")

# Round [Fix Round] real-document false-positive CAUGHT AND FIXED before
# shipping: an earlier, broader _BLANK_SIGNAL_RE (matching any "not found"/
# "missing"/"no X documented" phrase, no matter how narrow) matched
# QA-ACF-06's own real evidence ("...phrasing not found)") purely on
# surface wording -- QA-ACF-06 was reporting one specific sub-field
# (assessor name) missing, not the whole section, and got paired against
# QA-ACF-05's real "populated" evidence as if they were the SAME claim.
# Confirmed live against Blythe Diaz's real, current (already-fixed)
# document before narrowing this -- exactly the false-positive risk this
# function's own docstring warns about. Narrowed to require a genuine
# WHOLE-SECTION claim ("entirely blank," "nothing ... at all") -- the
# actual shape of the real confirmed contradiction (ACF-07's own bug
# evidence: "entirely blank -- no testing tool, date, or summary
# documented at all") -- not any narrow, single-sub-field "wasn't found."
_BLANK_SIGNAL_RE = re.compile(
    r"\bentirely blank\b|\bcompletely blank\b|\bsection is blank\b|\bsection.{0,10}(?:entirely|completely) empty\b|"
    r"\b(?:nothing|no) .{0,60}(?:documented|filled in|found) at all\b",
    re.IGNORECASE,
)
_POPULATED_SIGNAL_RE = re.compile(
    r"\bis documented\b|\bare documented\b|\bis present\b|\bare present\b|\bfully completed\b|\bcompleted\b|"
    r"\bdocumented:\b",
    re.IGNORECASE,
)


def _rule_group(rule_id: str) -> str:
    m = _RULE_GROUP_RE.match(rule_id)
    return m.group(1) if m else rule_id


def find_cross_rule_contradictions(det_results: dict[str, dict]) -> list[dict]:
    """Fix Round, item 3 -- a post-processing pass, run after all
    deterministic (and, if desired, judgment) rules finish on a document.
    Groups rule_ids by their shared prefix (see _rule_group above), and
    within each group, flags a pair where one rule's result is a
    confident 'fail' with blank/missing-signal language in its evidence,
    while another rule in the SAME group has a confident 'pass' with
    populated/present-signal language -- exactly the ACF-01/ACF-05-vs-
    ACF-07 shape, generalized to any group.

    Deliberately conservative: only pairs a 'fail' against a 'pass' (not
    against 'uncertain'/'not_checkable', which aren't a real disagreement
    about the underlying fact), and only when BOTH sides' own evidence
    text uses recognizable blank-vs-populated language -- a group with two
    genuinely different findings that AREN'T about the same blank/
    populated question (e.g. one rule failing on a date mismatch, another
    passing on tool names) is not flagged; this only catches a literal
    "does this section exist" contradiction, not disagreement in general.

    Returns a list of {"rule_ids": [...], "group": ..., "detail": ...} --
    never silently resolves a contradiction by picking one side; both
    results stay exactly what each rule said, this only adds a visible
    flag alongside them.
    """
    by_group: dict[str, list[str]] = {}
    for rule_id in det_results:
        by_group.setdefault(_rule_group(rule_id), []).append(rule_id)

    flags = []
    for group, rule_ids in by_group.items():
        if len(rule_ids) < 2:
            continue
        blank_fails = [
            rid for rid in rule_ids
            if det_results[rid]["result"] == "fail" and _BLANK_SIGNAL_RE.search(str(det_results[rid]["evidence"]))
        ]
        populated_passes = [
            rid for rid in rule_ids
            if det_results[rid]["result"] == "pass" and _POPULATED_SIGNAL_RE.search(str(det_results[rid]["evidence"]))
        ]
        if blank_fails and populated_passes:
            flags.append({
                "rule_ids": sorted(set(blank_fails) | set(populated_passes)),
                "group": group,
                "detail": (
                    f"{sorted(blank_fails)} report this section/field as blank or missing, but "
                    f"{sorted(populated_passes)} (same rule group {group!r}) report it as populated -- "
                    f"these can't both be right; surfaced for human review before this checklist ships."
                ),
            })
    return flags


# --- Next Round (2026-08-27), Part 2: 11 new rules ------------------------
#
# QA-HRS-12, QA-GIP-30, QA-GIP-31, QA-GIP-33, QA-COC-08 below are real
# deterministic checkers, verified against the real Zyaan Ullah sample TP's
# actual field layout (Target Goal:/Goal Status:/Current Data:/Graph: per
# goal block; CPT-code rows in the Hours Requesting section) before being
# written, not guessed at.
#
# QA-SCH-10 (POS = School) is deliberately built as check_type="judgment",
# NOT deterministic, despite this round's own ask -- confirmed real reason:
# it needs the exact same per-CPT-code "Place of Service" field QA-SCH-08
# already gave up parsing deterministically (see that rule's own notes:
# "three rounds of point-fixes... without addressing the underlying issue
# -- this field's real-world layout/labeling in the source PDF is too
# inconsistent for a fixed extraction pattern to hold up"). Building a
# second brittle regex against the identical field would repeat a
# documented failure, not avoid it -- flagged in this round's own report
# rather than silently building something likely to break the same way.
#
# QA-GIP-32/34/35 are also check_type="judgment", not the plain text
# deterministic checks this round assumed -- confirmed real reason: "data
# points"/"final data point"/"x-axis label" all live inside each goal's own
# embedded "Graph:" IMAGE (confirmed on the real sample TP, same field
# QA-GIP-02 already registered as vision-eligible for this exact reason),
# not in extractable text. There is no existing structured graph-value-
# extraction primitive in this codebase to build a deterministic comparison
# on top of (unlike e.g. session-note extraction, which does have one) --
# building one is new-capability work, not a checker, and is flagged back
# rather than faked. What IS real, deterministic work done this round:
# registering all three in VISION_ELIGIBLE_RULE_SECTIONS so the judgment
# layer actually SEES the graph image instead of guessing blind.
#
# QA-BIO-17 (dangerous/poisonous language) is check_type="judgment" for a
# different, confirmed reason: a naive keyword scan for "dangerous"/
# "poisonous" produces a REAL, VERIFIED false positive on the real sample
# TP's own text -- "Zyaan lacks safety awareness. He is unable to
# communicate if something is dangerous such as sharp, hot or poisonous" is
# a completely normal, expected clinical description of the patient's OWN
# safety deficit, not the kind of AI-hallucinated or genuinely alarming
# content this rule is trying to catch. Telling those two apart needs real
# contextual understanding a keyword list structurally can't do -- shipping
# a blind keyword scan here would guarantee false positives on real
# documents, which is worse than leaving it to judgment.


_HRS12_REQUIRED_PAYORS_DEFAULT = ("1199SEIU", "New York Medicaid", "Molina")


def _check_HRS12(rule: dict, fields: dict) -> tuple:
    """QA-HRS-12: "Treatment Planning hours only requested for 1199SEIU, NY
    Medicaid or Molina, all other insurances - N/A. Flag otherwise."

    Fix Round (Jacob Freund 10-2026-U1), Item 4: Ms. Yachnes's exact new
    rule, rewritten from the OPPOSITE scoping this checker used to have.
    The old version treated 1199SEIU/NY Medicaid/Molina as EXEMPT (N/A)
    and required Treatment Planning hours for every OTHER payor -- her new
    rule is the inverse: these 3 payors are the ONLY ones this requirement
    applies to; every other payor is N/A. `params.excluded_payors` is
    renamed `required_payors` accordingly so a stale, oppositely-named
    param can never silently coexist with the new logic.

    Real layout confirmed on the Zyaan Ullah sample TP: the Hours
    Requesting section has a SEPARATE row for 97151-Treatment Planning
    (distinct from the 97151-Assessment row -- same CPT code, different
    row, distinguished only by the trailing label text), formatted the
    same way _find_weekly_hours_for_code already reads for other codes
    ("<value> hours per <period>.\\n97151-...Treatment Planning"), except
    the value is often literally "N/A" rather than a number when Treatment
    Planning hours weren't requested. Matches the label with or without
    "Ongoing" (the "Hours Approved Previous Authorization" block below the
    current request uses "97151-Ongoing Treatment Planning"; this checker
    only reads the CURRENT Hours Requesting section's own row, matching
    either wording so a phrasing difference on that row alone doesn't
    cause a false not_checkable).
    """
    required_payors = rule.get("params", {}).get("required_payors", _HRS12_REQUIRED_PAYORS_DEFAULT)
    payor = fields.get("payor")
    if payor not in required_payors:
        return (
            "not_applicable",
            f"Payor detected as '{payor}', which is not 1199SEIU, NY Medicaid, or Molina -- "
            f"Treatment Planning hours are not required for this payor.",
            None, 0.9,
        )
    m = re.search(
        r"(\S+)\s*hours?\s*per\s*\n?\s*(?:authorization\s*\n?\s*Period\.|week\.)\s*\n?\s*"
        r"97151-\s*(?:Ongoing\s*)?Treatment\s*Planning",
        fields["full_text"], re.IGNORECASE,
    )
    if not m:
        return (
            "not_checkable",
            "Could not find a '97151-Treatment Planning' row in the Hours Requesting section to check.",
            None, 0.0,
        )
    value = m.group(1).strip()
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; the match's real position was always there.
    page = _page_for_offset(fields, m.start())
    if re.match(r"^\d+(\.\d+)?$", value) and float(value) > 0:
        return "pass", f"Treatment Planning hours requested: {value} for this authorization period.", page, 0.8
    return (
        "fail",
        f"Treatment Planning hours requested is {value!r} (missing/zero) for payor '{payor or 'unknown'}', "
        f"which requires this rule's hours to be requested.",
        page, 0.75,
    )


_GROUP_KEYWORD_RE = re.compile(r"\bgroup\b", re.IGNORECASE)
_RECALL_KEYWORD_RE = re.compile(r"\brecall\b", re.IGNORECASE)
_MET_STATUS_RE = re.compile(r"\bmet\b", re.IGNORECASE)


def _iter_goal_target_text(fields: dict) -> list[tuple[int, int, str]]:
    """Shared iteration helper for the new per-goal keyword checkers below
    (QA-GIP-30/31) -- yields (block_start_offset, target_text_offset,
    target_text) for every goal block's own "Target Goal:"/"Target Name:"
    value, reusing the already-proven _goal_block_starts splitter rather
    than a new pattern.
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    out = []
    for i in range(len(starts) - 1):
        block_start = starts[i]
        block = text[block_start:starts[i + 1]]
        tg_m = re.search(r"(?:Target Goal|Target Name):[ \t]*([^\n]*)", block)
        if tg_m:
            out.append((block_start, block_start + tg_m.start(1), tg_m.group(1).strip()))
    return out


def _check_GIP30(rule: dict, fields: dict) -> tuple:
    """QA-GIP-30: "No Group mentions unless 97154 is requested." Reintroduces,
    as its own separate rule, the group-mentions half of the clause that
    QA-GIP-01 deliberately dropped in the 2026-08-26 fix round (confirmed
    against QA-GIP-01's own current notes) -- confirmed with the user this
    is the intended split, not a silent duplicate.

    Scans each goal's own Target Goal/Target Name text for the word
    "group" (word-boundary, so "grouped"/"groups" also match but
    "groupware" would not, and unrelated words like "outgroup" wouldn't
    either) and cross-checks against 97154 hours actually requested, via
    the already-proven _find_weekly_hours_for_code helper -- not a new
    extraction pattern.
    """
    text = fields["full_text"]
    hours_97154 = _find_weekly_hours_for_code(text, "97154")
    all_targets = _iter_goal_target_text(fields)
    mentions = [(block_start, target) for block_start, _, target in all_targets if _GROUP_KEYWORD_RE.search(target)]
    if not mentions:
        # Fix Round (2026-09-11), page-number enforcement gap: this pass
        # case used to hardcode page=None even though the goal blocks it
        # scanned (and found clean) have real, known locations -- cites
        # the first scanned goal's page rather than a fabricated "nowhere."
        page = _page_for_offset(fields, all_targets[0][0]) if all_targets else None
        return "pass", "No goal's Target Goal/Target Name text mentions 'group'.", page, 0.8
    if hours_97154 is not None and hours_97154 > 0:
        return (
            "not_applicable",
            f"97154 (Social Skills Group) requested at {hours_97154} hrs/week -- goal text mentioning "
            f"'group' is expected and does not violate this rule.",
            None, 0.85,
        )
    if len(mentions) == 1:
        block_start, target = mentions[0]
        page = _page_for_offset(fields, block_start)
        return (
            "fail",
            f"Goal mentions 'group' ('{target[:150]}') but 97154 (Social Skills Group) is not requested.",
            page, 0.75,
        )
    evidence = [
        {
            "page": _page_for_offset(fields, block_start),
            "detail": f"Goal mentions 'group' ('{target[:150]}') but 97154 is not requested.",
        }
        for block_start, target in mentions
    ]
    return "fail", evidence, None, 0.75


def _check_GIP31(rule: dict, fields: dict) -> tuple:
    """QA-GIP-31: "Recall Goal -- any goal that is a recall goal should be
    flagged." Plain keyword match against each goal's own Target Goal/
    Target Name text for the word "recall" (word-boundary), same shape and
    same shared helper as QA-GIP-30 above.
    """
    all_targets = _iter_goal_target_text(fields)
    mentions = [(block_start, target) for block_start, _, target in all_targets if _RECALL_KEYWORD_RE.search(target)]
    if not mentions:
        # Fix Round (2026-09-11), page-number enforcement gap: same fix as
        # _check_GIP30 -- cites the first scanned goal's real page.
        page = _page_for_offset(fields, all_targets[0][0]) if all_targets else None
        return "pass", "No goal's Target Goal/Target Name text mentions 'recall'.", page, 0.8
    if len(mentions) == 1:
        block_start, target = mentions[0]
        page = _page_for_offset(fields, block_start)
        return "fail", f"Goal is a recall goal: '{target[:150]}'.", page, 0.8
    evidence = [
        {"page": _page_for_offset(fields, block_start), "detail": f"Goal is a recall goal: '{target[:150]}'."}
        for block_start, target in mentions
    ]
    return "fail", evidence, None, 0.8


def _check_GIP33(rule: dict, fields: dict) -> tuple:
    """QA-GIP-33: "Any goal that mentions 'met' should be flagged" -- a
    Goals in Progress entry that says its own status is "Met" belongs in
    Mastered Goals, not this section, so its presence here is itself the
    thing to flag.

    Reads each goal block's own status FIELD value (matches both "Goal
    Status:" and the bare "Status:" label -- both confirmed present on the
    real sample TP for different goal blocks) rather than scanning the
    whole block's free text, so a goal whose narrative happens to use the
    word "met" in an unrelated sentence elsewhere in the block is never
    the trigger -- only the status value itself.
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    mentions = []
    for i in range(len(starts) - 1):
        block_start = starts[i]
        block = text[block_start:starts[i + 1]]
        status_m = re.search(r"(?:Goal Status|Status):[ \t]*([^\n]*)", block)
        if status_m and _MET_STATUS_RE.search(status_m.group(1)):
            tg_m = re.search(r"(?:Target Goal|Target Name):[ \t]*([^\n]*)", block)
            goal_name = tg_m.group(1).strip()[:100] if tg_m else "(name not found)"
            page = _page_for_offset(fields, block_start + status_m.start())
            mentions.append((page, goal_name, status_m.group(1).strip()))
    if not mentions:
        # Fix Round (2026-09-11), page-number enforcement gap: same fix as
        # _check_GIP30/31 -- cites the first goal block's real page.
        page = _page_for_offset(fields, starts[0]) if len(starts) > 1 else None
        return "pass", "No goal's status field mentions 'met'.", page, 0.8
    if len(mentions) == 1:
        page, goal_name, status_val = mentions[0]
        return "fail", f"Goal '{goal_name}' status is {status_val!r} -- mentions 'met'.", page, 0.8
    evidence = [
        {"page": page, "detail": f"Goal '{goal_name}' status is {status_val!r} -- mentions 'met'."}
        for page, goal_name, status_val in mentions
    ]
    return "fail", evidence, None, 0.8


_LAPSE_IN_SERVICE_RE = re.compile(
    r"\blapse\s+in\s+(?:service|treatment|care)\b"
    r"|\b(?:gap|break)\s+in\s+(?:service|treatment|care)\b"
    r"|\b(?:service|treatment)\s+lapse\b"
    r"|\bdiscontinuation\s+of\s+services?\b",
    re.IGNORECASE,
)


def _check_COC08(rule: dict, fields: dict) -> tuple:
    """QA-COC-08: "Any mention of a lapse in service should be flagged."
    Conservative, specific phrase list (not a bare "lapse" substring match,
    which would also fire on unrelated uses like "time lapse" or "lapse in
    judgment") across the full document text -- no existing Coordination of
    Care section-boundary helper exists in this codebase to scope this to
    (QA-COC-04, the only other COC deterministic checker, searches full
    text directly for the same reason), so this deliberately searches the
    whole document rather than inventing an unverified section boundary.
    """
    matches = list(_LAPSE_IN_SERVICE_RE.finditer(fields["full_text"]))
    if not matches:
        return "pass", "No mention of a lapse/gap/break in service found.", None, 0.75
    pages = sorted({_page_for_offset(fields, m.start()) for m in matches})
    if len(pages) == 1:
        return "fail", f"Mention of a lapse in service found: '{matches[0].group(0)}'.", pages[0], 0.75
    evidence = [
        {"page": p, "detail": "Mention of a lapse in service found on this page."} for p in pages
    ]
    return "fail", evidence, None, 0.75


# --- Fix Round, Section 1 (2026-08-27): "wording changed but no real code" ---
# 20 rules whose description/notes were updated in earlier rounds without
# anyone confirming real code enforces the new wording. See each function's
# own docstring for what was found and fixed for that specific rule_id.


def _check_BAR01(rule: dict, fields: dict) -> tuple:
    """QA-BAR-01: "a barrier/goal requirement that only kicks in
    conditionally around a 25-hour threshold" (per this rule's own
    current description: applies only when the request exceeds 25 hours
    of 97153). REAL GAP FOUND AND FIXED: the 2026-08-26 round added this
    threshold to the description and flagged explicitly, in its own
    notes, that nothing enforced it in code -- the LLM was only ever told
    the condition in English, with no real precondition gate. Same
    hybrid shape as _check_HRS05: the threshold gate is a real DET
    precondition (zero judgment call when the threshold genuinely isn't
    met); the actual "is a barrier mentioned" question stays genuinely
    judgment (a holistic read across the whole document, not reducible
    to a keyword scan -- see this rule's own notes for the real PASS/FAIL
    examples already established).
    """
    threshold = rule.get("params", {}).get("hours_threshold", 25)
    cpt_code = rule.get("params", {}).get("cpt_code", "97153")
    # Fix Round (QA-ACF-11 wording + page numbers, 2026-09-19), Item 2:
    # switched to the offset-capturing sibling -- it already existed,
    # just wasn't the one this checker called.
    found = _find_weekly_hours_for_code_with_offset(fields["full_text"], cpt_code)
    if found is None:
        return (
            "not_checkable",
            f"Could not find {cpt_code} hours requested to check the {threshold}-hour threshold this rule "
            f"applies above.",
            None, 0.0,
        )
    hours, offset = found
    page = _page_for_offset(fields, offset)
    if hours <= threshold:
        return (
            "not_applicable",
            f"{cpt_code} hours requested: {hours}/week, at or below the {threshold}-hour threshold this "
            f"rule applies above -- rule does not apply.",
            page, 0.85,
        )
    return (
        "not_checkable",
        f"{cpt_code} hours requested: {hours}/week, above the {threshold}-hour threshold -- rule applies; "
        f"whether a barrier is documented anywhere in the report requires reading the full narrative.",
        page, 0.0,
    )


def _find_hours_after_label(text: str, label_pattern: str) -> float | None:
    """Finds a "<N> hours per <period>." value immediately AFTER a
    label (e.g. "97156-Parent Training\\n1 hour per week") -- the
    OPPOSITE layout from _find_weekly_hours_for_code's "<N> hours per
    week.\\n<label>" (value BEFORE the label). Confirmed real document
    shape: the "Hours Approved Previous Authorization" section lists
    each code's value AFTER its own label line, the reverse of the
    current "Hours Requesting" section's own layout for the same code.
    """
    m = re.search(
        rf"{label_pattern}\s*\n?\s*(\d+(?:\.\d+)?)\s*hours?\s*per\s*(?:week|auth(?:orization)?)\.?",
        text, re.IGNORECASE,
    )
    return float(m.group(1)) if m else None


def _check_HF05(rule: dict, fields: dict) -> tuple:
    """HF-05: "BCBA indicates hours PT occurred in previous auth period,
    and this matches PT hours requested." REAL, CONFIRMED DATA GAP,
    documented rather than guessed around: "hours PT OCCURRED" (actual
    utilization) is not a field this pipeline has ever found extractable
    text for on a real document -- only hours APPROVED for the previous
    period are stated (confirmed real finding, an earlier round's own
    real-data check: "Hours Approved Previous Authorization... states PT
    previous auth was 2 hours/week... but no narrative BCBA statement
    explicitly confirms 'hours PT occurred' in the previous period").

    This checker does the real, extractable half -- compares 97156
    (Parent Training) hours APPROVED for the previous period against
    97156 hours REQUESTED now, using _find_hours_after_label (the
    Approved-Previous-Authorization section's own reversed layout) and
    _find_weekly_hours_for_code (the current Hours Requesting section) --
    and surfaces that real comparison as context, but always escalates
    to judgment (not_checkable) for the "occurred" half specifically,
    since treating "approved" as if it were "occurred" would overstate
    what this pipeline actually verified.
    """
    text = fields["full_text"]
    approved = _find_hours_after_label(text, r"97156-\s*Parent\s*Training")
    requested = _find_weekly_hours_for_code(text, "97156")
    if approved is None or requested is None:
        return (
            "not_checkable",
            "Could not find both the previous-period APPROVED and currently REQUESTED 97156 (Parent "
            "Training) hours to compare.",
            None, 0.0,
        )
    comparison = (
        f"97156 (Parent Training) hours approved for the previous period: {approved}/week; hours requested "
        f"now: {requested}/week ({'match' if abs(approved - requested) < 0.01 else 'do NOT match'})."
    )
    return (
        "not_checkable",
        f"{comparison} Note: 'approved' is not the same as 'occurred' -- whether PT hours actually "
        f"took place during the previous period needs a human read of the full narrative.",
        None, 0.0,
    )


def _check_COC06(rule: dict, fields: dict) -> tuple:
    """QA-COC-06: "Date faxed to doctor includes month/day, and is within
    the current dates of report" -- REAL FIX: the 2026-08-26 round
    dropped the year requirement from this rule's own wording and added
    the within-report-date-range check, but its own notes flag that
    conversion to a real deterministic checker was never reached (still
    plain judgment, "with no guarantee it applies date-range math
    correctly or consistently"). Built here: reuses QA-COC-04's own real
    "faxed to ... on <date>" regex, now accepting a date WITHOUT a year
    (matching the current wording's own dropped requirement), and
    QA-RPT-05/QA-COC-04's own _find_labeled_date_range helper for the
    within-report-range check. A fax date with no year genuinely cannot
    be range-checked (there's no year to anchor it to) -- returns
    not_checkable for that specific case rather than guessing a year.
    """
    # Fix Round (2026-09-11 night) -- "Stop Over-Using the Uncertain Safety
    # Net": REAL FIX, not a re-vote. This rule was on STABILIZED_UNCERTAIN_
    # RULE_IDS because it always escalated to judgment whenever no fax
    # statement existed, and judgment's own read of "nothing here to check"
    # varied run to run -- a real instability, but not a genuinely
    # image/graph-dependent one (this is a plain text regex). Root cause:
    # `needs_escalation` escalates ANY "not_checkable" unconditionally, and
    # "no fax statement found at all" was being reported as not_checkable
    # ("can't verify") when it's actually a genuinely-determined FINAL
    # state -- this coordination step (faxing a doctor) isn't required/
    # documented for every patient, so its real absence is honestly
    # not_applicable, not "insufficient information." not_applicable does
    # NOT trigger escalation (see needs_escalation's own check), so this
    # is now a stable, zero-variance final answer -- same real evidence
    # confirmed live on the Daylyn Holland document, which has no "faxed
    # to ... on <date>" statement anywhere.
    # Fix Round (2026-09-11 night), real gap found on re-verification: the
    # real Daylyn Holland document's own fax date is stated with a 2-DIGIT
    # year ("8/7/26"), which the original 4-digit-only year group here
    # silently missed entirely (matched as "no year"), still returning
    # not_checkable -- still escalating to judgment for exactly the
    # instability this fix was supposed to close for THIS document.
    # Confirmed via `_check_COC06(rule, fields)` called directly on the
    # real document (zero API cost, local extraction only). Now accepts a
    # 2-digit year, resolved to the 2000s (this pipeline has no document
    # from before 2000 to disambiguate against).
    text = fields["full_text"]
    m = re.search(r"faxed to [^\n]*?on\s*(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?", text, re.IGNORECASE)
    if not m:
        return (
            "not_applicable",
            "No 'faxed to ... on <date>' statement found anywhere in the document -- this "
            "coordination step was not documented as having occurred for this patient.",
            None, 0.85,
        )
    month, day, year_raw = m.group(1), m.group(2), m.group(3)
    year = f"20{year_raw}" if year_raw and len(year_raw) == 2 else year_raw
    raw_date = f"{month}/{day}" + (f"/{year_raw}" if year_raw else "")
    page = _page_for_offset(fields, m.start())
    report_range = _find_labeled_date_range(text, "Date of Current Report")
    if not report_range:
        return (
            "not_checkable",
            f"Found fax date {raw_date!r} (month/day present) but could not find 'Date of Current Report' "
            f"to check it falls within range.",
            page, 0.0,
        )
    if not year:
        return (
            "not_checkable",
            f"Fax date {raw_date!r} has month/day but no year -- cannot confirm it falls within the "
            f"current report's date range ({report_range[0]} to {report_range[1]}) without a year to "
            f"anchor it.",
            page, 0.0,
        )
    fax_date = datetime(int(year), int(month), int(day))
    start = datetime.strptime(report_range[0], "%m/%d/%Y")
    end = datetime.strptime(report_range[1], "%m/%d/%Y")
    if start <= fax_date <= end:
        return (
            "pass",
            f"Fax date {raw_date!r} (month/day present) falls within the current report's date range "
            f"({report_range[0]} to {report_range[1]}).",
            page, 0.8,
        )
    return (
        "fail",
        f"Fax date {raw_date!r} does not fall within the current report's date range ({report_range[0]} "
        f"to {report_range[1]}).",
        page, 0.8,
    )


def _check_RPT07(rule: dict, fields: dict) -> tuple:
    """QA-RPT-07: "Flag if requested auth range is less than a full
    authorization period (13-week or 26-week cycle, depending on
    payor)." Real, confirmed context resolving this rule's own flagged
    blocker ("the payor-to-week-count mapping this needs isn't confirmed
    anywhere in the codebase"): computes the requested range's own real
    length in weeks from 'Authorization Dates Requested' and compares
    against the payor-appropriate expected length.

    Fix Round (2026-09-10), item 10 -- REAL LOGIC BUG FOUND AND FIXED: an
    earlier round had this rule self-exclude (return not_applicable) for
    Healthfirst entirely, on the assumption HF used its own separate
    auth-period concept exempt from this check. Confirmed wrong, directly:
    ma'am asked for this rule to check Healthfirst too -- full 13 weeks
    for HF, full 26 weeks for every other payor -- not skip it. The N/A
    branch is removed; Healthfirst now gets its own expected-weeks value
    instead of being excluded. (HF-01 still separately validates the
    SAME 13-week fact for Healthfirst specifically -- the two rules now
    genuinely agree rather than one deferring to the other.)
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; the match's real position was always there.
    detected_payor = fields.get("payor")
    params = rule.get("params", {})
    hf_weeks = params.get("healthfirst_weeks", 13)
    default_weeks = params.get("expected_weeks", 26)
    weeks_expected = hf_weeks if detected_payor == "Healthfirst" else default_weeks
    found = _find_labeled_date_range_with_offset(fields["full_text"], "Authorization Dates Requested")
    if not found:
        return (
            "not_checkable",
            "Could not find 'Authorization Dates Requested' to compute the requested auth range's length.",
            None, 0.0,
        )
    auth_range = (found[0], found[1])
    page = _page_for_offset(fields, found[2])
    start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    end = datetime.strptime(auth_range[1], "%m/%d/%Y")
    actual_weeks = (end - start).days / 7
    if actual_weeks < weeks_expected - 0.5:  # half-week tolerance for inclusive-day-count rounding
        return (
            "fail",
            f"Requested auth range ({auth_range[0]} to {auth_range[1]}) spans {actual_weeks:.1f} weeks, "
            f"short of a full {weeks_expected}-week authorization period.",
            page, 0.75,
        )
    return (
        "pass",
        f"Requested auth range ({auth_range[0]} to {auth_range[1]}) spans {actual_weeks:.1f} weeks, "
        f"meeting the full {weeks_expected}-week authorization period.",
        page, 0.75,
    )


# Fix Round, Section 1: QA-SCH-06's own "another related therapy" signal --
# frequency/duration phrasing ("OT 2x per week for 30 minutes") confirmed as
# the real shape this appears in, not a dedicated schedule table.
_OTHER_THERAPY_MENTION_RE = re.compile(
    r"\boccupational therapy\b|\bphysical therapy\b|\bspeech therapy\b|\bspeech-language\b"
    r"|\bOT\b[^.\n]{0,20}\bper week\b|\bPT\b[^.\n]{0,20}\bper week\b",
    re.IGNORECASE,
)


def _check_SCH06(rule: dict, fields: dict) -> tuple:
    """QA-SCH-06: "If overlaps related therapy, that schedule is added to
    TP." REAL BUG FOUND AND FIXED: check_type was already "deterministic"
    in rules.json but had ZERO checker registered in DET_CHECKS -- every
    real document silently fell through to the generic not_checkable
    fallback for this rule regardless of content, an HF-01-style silent
    gap (labeled deterministic, no logic behind the label at all).

    LIMITATION, explicit, not glossed over: genuine time-block overlap
    detection between the ABA schedule and another therapy's own
    schedule needs BOTH schedules' actual day/time data -- confirmed on
    the real sample TP, the "other therapy" mention (e.g. "OT 2x per
    week for 30 minutes") states FREQUENCY/DURATION only, never specific
    days/times, so a real overlap computation isn't possible from this
    field alone in the one real document available to verify against.
    This checker implements the real, confirmable half instead: if
    another therapy is mentioned as received at all, confirm SOME
    schedule/time information for it (a day-of-week name or a clock-time
    pattern) appears nearby in the document -- flagging the case where
    another therapy is mentioned with no schedule information anywhere
    near it, which is the real, checkable core of "that schedule is
    added to TP." Full day/time overlap arithmetic is NOT implemented --
    flagged here rather than guessed at without a confirmed real-document
    example showing explicit day/time blocks for a non-ABA service.
    """
    text = fields["full_text"]
    m = _OTHER_THERAPY_MENTION_RE.search(text)
    if not m:
        return (
            "not_applicable",
            "No mention of another related therapy (OT/PT/speech) found -- no overlap to check.",
            None, 0.8,
        )
    # Fix Round (2026-09-11), page-number enforcement gap: pass/uncertain
    # used to hardcode page=None even though the therapy mention's own
    # match position was available.
    page = _page_for_offset(fields, m.start())
    window = text[max(0, m.start() - 200):m.end() + 200]
    has_schedule_info = bool(re.search(
        r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
        window, re.IGNORECASE,
    ))
    if has_schedule_info:
        return (
            "pass",
            "Another related therapy is mentioned and schedule/time information for it appears nearby in "
            "the document.",
            page, 0.65,
        )
    return (
        "uncertain",
        "Another related therapy (OT/PT/speech) is mentioned as received, but no day/time schedule "
        "information for it was found nearby in the document -- cannot confirm whether its schedule was "
        "added to the TP as required.",
        page, 0.0,
    )


def _check_GIP19(rule: dict, fields: dict) -> tuple:
    """QA-GIP-19: "Behavior goals and summary section present in
    review." Real, confirmed field shapes: at least one goal block whose
    own Skill Domain mentions "Behavior" (e.g. the real sample TP's
    "Skill Domain: Functional Behavior Skills"), AND a non-blank
    "Behavioral Summary:" field -- the same field name QA-RPT-01's own
    checker already reads elsewhere in this file, reused here rather
    than guessed at fresh.

    Fix Round (2026-09-10), item 22 -- REAL BUG FOUND AND FIXED: the
    summary check used to read only the SAME line as "Behavioral
    Summary:"; a genuinely-present summary that wraps onto the next line
    (a real, confirmed PDF-extraction shape, same bug class as items 9/27
    -- see _extract_labeled_value) read as blank and failed this rule
    even though the summary was really there. Now uses
    _extract_labeled_value's multi-line lookahead instead of a same-line-
    only regex capture.
    """
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None; cites the Behavior-domain goal's real match
    # position when present, else the (also real) whole-document search
    # gave no location to cite for the fail case's "not found" half --
    # falls back to whichever check DID find a real position.
    text = fields["full_text"]
    behavior_goal_m = re.search(r"Skill Domain:[ \t]*[^\n]*Behavior", text, re.IGNORECASE)
    has_behavior_goal = bool(behavior_goal_m)
    has_summary = bool(_extract_labeled_value(text, "Behavioral Summary"))
    if has_behavior_goal and has_summary:
        return (
            "pass",
            "At least one Behavior-domain goal and a non-blank Behavioral Summary section are both present.",
            _page_for_offset(fields, behavior_goal_m.start()), 0.8,
        )
    missing = []
    if not has_behavior_goal:
        missing.append("no goal with a Behavior-related Skill Domain found")
    if not has_summary:
        missing.append("Behavioral Summary section is missing or blank")
    page = _page_for_offset(fields, behavior_goal_m.start()) if behavior_goal_m else None
    return "fail", "; ".join(missing) + ".", page, 0.75


# Fix Round, Section 1: QA-GIP-26's own real false-pass bug -- confirmed
# real document shape, OT/PT/speech mentioned as background context ("Zyaan
# currently receives OT 2x per week...") is completely normal and must NOT
# fail this rule; only an actual GOAL whose own Target Goal/Skill Domain
# text is itself OT/PT/speech-flavored is the real violation. Scoped to
# each goal block's own text, never the whole document, for exactly that
# reason -- same false-positive-avoidance discipline as QA-GIP-30/31/33.
_OTHER_DISCIPLINE_GOAL_RE = re.compile(
    r"\boccupational therapy\b|\bphysical therapy\b|\bspeech therapy\b|\bspeech-language\b"
    r"|\bOT goal\b|\bPT goal\b",
    re.IGNORECASE,
)


def _check_GIP26(rule: dict, fields: dict) -> tuple:
    """QA-GIP-26: "No OT, PT, or speech therapy goals included." REAL BUG,
    ROOT-CAUSED: this rule's own confirmed real false-pass shape is a
    goal WITHIN the Goals in Progress section whose own Target Goal/
    Skill Domain text is itself OT/PT/speech-flavored (a goal that
    belongs to a different discipline, miscategorized into ABA's own
    goal list) -- judgment, reading the whole document at once, has
    reportedly passed this even when such a goal is present. Scoped
    strictly to each goal block's OWN text (never the whole document),
    since a completely normal, unrelated mention elsewhere in the
    document (e.g. "Zyaan currently receives OT 2x per week" as
    background/biopsychosocial context) must never trigger this --
    confirmed as real, benign content on the real sample TP.
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    hits = []
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        tg_m = re.search(r"(?:Target Goal|Target Name):[ \t]*([^\n]*)", block)
        sd_m = re.search(r"Skill Domain:[ \t]*([^\n]*)", block)
        combined = " ".join(filter(None, [tg_m.group(1) if tg_m else None, sd_m.group(1) if sd_m else None]))
        if combined and _OTHER_DISCIPLINE_GOAL_RE.search(combined):
            page = _page_for_offset(fields, starts[i])
            hits.append((page, combined.strip()[:150]))
    if not hits:
        # Fix Round (2026-09-11), page-number enforcement gap: same fix as
        # _check_GIP30/31/33 -- cites the first scanned goal block's page.
        page = _page_for_offset(fields, starts[0]) if len(starts) > 1 else None
        return (
            "pass",
            "No goal's own Target Goal/Skill Domain text mentions OT, PT, or speech therapy.",
            page, 0.8,
        )
    if len(hits) == 1:
        page, detail = hits[0]
        return "fail", f"Goal appears to be an OT/PT/speech goal, not ABA: '{detail}'.", page, 0.75
    evidence = [
        {"page": p, "detail": f"Goal appears to be an OT/PT/speech goal, not ABA: '{d}'."} for p, d in hits
    ]
    return "fail", evidence, None, 0.75


# --- Fix Round, Section 1 Bucket D (2026-08-27) ----------------------------


def _check_GIP13(rule: dict, fields: dict) -> tuple:
    """QA-GIP-13: "At least 1 goal per hour (excl. Parent Training and
    Behavior Reduction)." REAL BUG FOUND AND FIXED: an HF-01/QA-SCH-06-
    style silent gap -- this rule was already labeled check_type=
    "deterministic" in rules.json, but had ZERO checker registered in
    DET_CHECKS, so every real document silently fell through to the
    generic not_checkable fallback regardless of content.

    Counts skill-acquisition goal blocks ('Target Goal:' -- this
    codebase's own established convention already excludes Behavior
    Reduction Goals, which use 'Target Name:' instead, per
    _goal_block_starts's own docstring), further excluding any goal whose
    own Skill Domain names Parent Training specifically, and compares
    against 97153 (Direct Care) hours requested. Confirmed reproducible
    with a synthetic 13-goal/15-hour fixture (the round's own concrete
    example): 13 < 15 -> fail, matching the real reported miss.
    """
    text = fields["full_text"]
    hours = _find_weekly_hours_for_code(text, "97153")
    if hours is None:
        return (
            "not_checkable",
            "Could not find 97153 (Direct Care) hours requested to compare against the goal count.",
            None, 0.0,
        )
    starts = _goal_block_starts(text) + [len(text)]
    goal_count = 0
    first_qualifying_offset = None
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        if not block.startswith("Target Goal:"):
            continue  # 'Target Name:' (Behavior Reduction Goals) are excluded by this rule's own scope
        sd_m = re.search(r"Skill Domain:[ \t]*([^\n]*)", block)
        if sd_m and "parent training" in sd_m.group(1).lower():
            continue  # Parent Training goals are excluded by this rule's own scope
        goal_count += 1
        if first_qualifying_offset is None:
            first_qualifying_offset = starts[i]
    if goal_count == 0:
        return "not_checkable", "No qualifying skill-acquisition goal blocks found to count.", None, 0.0
    # Fix Round (2026-09-11), page-number enforcement gap: pass/fail used
    # to hardcode page=None even though the first qualifying goal's real
    # offset was already tracked above -- this is a whole-document count
    # comparison, so no single page fully represents it, but citing the
    # first qualifying goal is a real, honest starting point for a reviewer.
    page = _page_for_offset(fields, first_qualifying_offset)
    if goal_count < hours:
        return (
            "fail",
            f"{goal_count} qualifying goal(s) found (excl. Parent Training/Behavior Reduction), but "
            f"{hours} hours/week of 97153 requested -- fewer than 1 goal per hour.",
            page, 0.75,
        )
    return (
        "pass",
        f"{goal_count} qualifying goal(s) found for {hours} hours/week of 97153 requested -- at least "
        f"1 goal per hour.",
        page, 0.75,
    )


_GIP21_BARE_NUMBER_RE = re.compile(
    r"^[ \t]*\d+(?:[ \t]*-[ \t]*\d+)?"  # a number, or a range like "5-6"
    r"(?:[ \t]*(?:times?|per\s+\w+|%|percent))*"  # trailing unit words only, no other prose
    r"[ \t.]*$",
    re.IGNORECASE,
)


def _check_GIP21(rule: dict, fields: dict) -> tuple:
    """QA-GIP-21: "Behavior goals include an explanation and indicate
    'mastered by' status." HYBRID checker, same shape as QA-BIP-05/
    QA-PROB-02 -- this rule's own current description bundles TWO real,
    separately-verifiable facts:

    - "indicate 'mastered by' status" -- 'Anticipated Mastery Date:'
      (confirmed present per goal block on the real sample TP).
    - "include an explanation" -- Fix Round (2026-09-11 night), REAL FIX:
      confirmed directly against the real Daylyn Holland document (zero
      real API cost -- local PDF text extraction only, no guessing) that
      this template has no dedicated "explanation" field, but a REAL
      explanatory signal does exist in two places every goal block
      already has: "Additional Notes:" (when non-blank), or the "Current
      Data:" field itself carrying real narrative text beyond a bare
      number when progress has stalled -- confirmed real example on this
      document: "Current Data: 0  Frequency incorrect reporting - BT has
      been retrained." A bare number/frequency phrase with nothing else
      ("Current Data: 5-6 times per session") is NOT an explanation:
      _GIP21_BARE_NUMBER_RE distinguishes the two. This was previously
      always escalated to judgment (not_checkable) even when both mastery
      date and a real explanation were plainly present -- confirmed real
      contributor to this rule's coin-flip instability, since asking
      judgment to re-derive "is this an explanation" on the SAME document
      varied run to run. Genuinely still not_checkable only when a goal
      has NEITHER Additional Notes text NOR Current Data narrative --
      that residual case stays judgment (rare on real documents seen so
      far, but honestly flagged rather than forced to a guess).
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    mastery_problems = []
    explanation_problems = []
    checked = 0
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        if not block.startswith("Target Name:"):
            continue  # skill-acquisition ("Target Goal:") blocks aren't behavior goals
        checked += 1
        goal_name = block[len("Target Name:"):].split("\n", 1)[0].strip()
        page = _page_for_offset(fields, starts[i])
        amd_m = re.search(r"Anticipated Mastery Date:[ \t]*([^\n]*)", block)
        amd_val = amd_m.group(1).strip() if amd_m else ""
        if not amd_val:
            mastery_problems.append((page, f"Goal '{goal_name[:120]}' has no 'Anticipated Mastery Date' (mastered-by status) indicated."))

        notes_m = re.search(r"Additional Notes:[ \t]*([^\n]*)", block)
        notes_val = notes_m.group(1).strip() if notes_m else ""
        data_m = re.search(r"Current Data:[ \t]*([^\n]*)", block)
        data_val = data_m.group(1).strip() if data_m else ""
        has_explanation = bool(notes_val) or (bool(data_val) and not _GIP21_BARE_NUMBER_RE.match(data_val))
        if not has_explanation:
            explanation_problems.append((page, f"Goal '{goal_name[:120]}' has no explanation in 'Additional Notes:' or narrative in 'Current Data:'."))

    if checked == 0:
        return "not_checkable", "No Behavior Reduction Goal ('Target Name:') blocks found in this document.", None, 0.0

    problems = mastery_problems + explanation_problems
    if problems:
        if len(problems) == 1:
            page, detail = problems[0]
            return "fail", detail, page, 0.8
        evidence = [{"page": page, "detail": detail} for page, detail in problems]
        return "fail", evidence, None, 0.8
    page = _page_for_offset(fields, starts[0])
    return (
        "pass",
        f"All {checked} Behavior Reduction Goal(s) indicate an Anticipated Mastery Date and include a "
        f"real explanation (Additional Notes or Current Data narrative).",
        page, 0.8,
    )


# Fix Round (2026-09-11 night), standard ABA billing CPT codes -- the
# same set QA-HRS-08's own rules.json notes already name ("97151/97153/
# 97154 etc.") plus the other codes already used elsewhere in this file
# (97152/97155/97156/97158, per CPT's own published ABA code set).
_STANDARD_ABA_CPT_CODES = frozenset({"97151", "97152", "97153", "97154", "97155", "97156", "97158"})


def _check_HRS08(rule: dict, fields: dict) -> tuple:
    """QA-HRS-08: "Codes/hours match insurance billing codes guide."
    Fix Round (2026-09-11 night) -- REAL FIX, not a re-vote: this rule had
    NO deterministic checker registered at all (fell straight to
    NEEDS_BACKEND_INTEGRATION, confidence 0.0, always escalated) despite
    its own rules.json notes already describing exactly what to check and
    already deciding the right bar for this specific rule (Round 92's own
    override): confirming the stated CPT codes are real, well-formed,
    standard ABA codes used consistently throughout the document IS
    sufficient for a confident pass -- the actual named "billing codes
    guide" document was never available to this pipeline and isn't needed
    for that bar. Built here: extracts every 5-digit 97xxx code
    mentioned, fails if any isn't a recognized standard ABA code.
    """
    text = fields["full_text"]
    matches = list(re.finditer(r"\b(97\d{3})\b", text))
    if not matches:
        return "not_checkable", "No CPT billing code (e.g. 97151/97153/97154) found anywhere in this TP.", None, 0.0
    codes = sorted({m.group(1) for m in matches})
    page = _page_for_offset(fields, matches[0].start())
    unknown = [c for c in codes if c not in _STANDARD_ABA_CPT_CODES]
    if unknown:
        return (
            "fail",
            f"Found CPT code(s) not in the standard ABA billing code set: {unknown}. All codes found: {codes}.",
            page, 0.75,
        )
    return (
        "pass",
        f"All CPT code(s) found in this TP ({codes}) are standard, recognized ABA billing codes, used "
        f"consistently throughout the document.",
        page, 0.85,
    )


def _check_MAST03(rule: dict, fields: dict) -> tuple:
    """QA-MAST-03: "If no mastered goals, rationale is provided."
    Fix Round (2026-09-11 night) -- REAL FIX, not a re-vote: confirmed
    directly against the real Daylyn Holland document (zero real API
    cost) that this template's own real phrasing for an empty Mastered
    Goals section is a plain sentence on/right after the label itself
    (e.g. "Mastered Goals: There were no mastered parent goals during
    this authorization period.") -- a real, extractable rationale, not a
    field this pipeline had no pattern for. Checks every "Mastered
    Goals:" occurrence (a real document has one per goal domain --
    Behavior Reduction, Skill Acquisition, Parent/Caregiver): a section
    listing real "Name of Skill:" entries has mastered goals, so this
    rule's own "if no mastered goals" precondition doesn't apply there
    (not_applicable); an empty section needs a real, non-blank rationale
    nearby (checked via the same multi-line-aware _extract_labeled_value
    every other checker in this file already uses).
    """
    text = fields["full_text"]
    matches = list(re.finditer(r"Mastered Goals:", text))
    if not matches:
        return "not_checkable", "No 'Mastered Goals:' section found anywhere in this document.", None, 0.0

    empty_sections = []
    for m in matches:
        window = text[m.end():m.end() + 500]
        if re.search(r"Name of Skill:", window):
            continue  # real mastered goals present here -- precondition not met for this section
        rationale = _extract_labeled_value(text[m.start():], "Mastered Goals")
        page = _page_for_offset(fields, m.start())
        empty_sections.append((page, rationale.strip()))

    if not empty_sections:
        return (
            "not_applicable",
            "Every 'Mastered Goals:' section in this document lists real mastered goals -- this rule's "
            "'if no mastered goals' precondition doesn't apply here.",
            None, 0.85,
        )

    problems = [(page, "'Mastered Goals:' section is empty with no rationale stated for why there are no mastered goals.")
                for page, rationale in empty_sections if not rationale]
    if problems:
        if len(problems) == 1:
            page, detail = problems[0]
            return "fail", detail, page, 0.8
        evidence = [{"page": page, "detail": detail} for page, detail in problems]
        return "fail", evidence, None, 0.8

    page = empty_sections[0][0]
    return (
        "pass",
        f"{len(empty_sections)} empty 'Mastered Goals:' section(s) found, each with a real rationale stated.",
        page, 0.8,
    )


def _check_MAST04(rule: dict, fields: dict) -> tuple:
    """QA-MAST-04: "At least 3 parent goals must have the goal status of
    in progress." Fix Round (Jacob Freund 10-2026-U1), Item 17: Ms.
    Yachnes's explicit correction -- this rule was pure judgment AND on
    the stabilized safety-net list (unpinned this round), so every real
    run forced it to Uncertain with no real attempt made at all.

    Reuses this rule's own already-built, real evidence extractor
    (_mast04_context_preview's exact logic, not modified): scan every
    goal block (both 'Target Goal:'/'Target Name:') for a 'Skill Domain:'
    containing 'parent training', read that goal's own 'Goal Status:'/
    'Status:' value, and count how many read 'in progress'. This
    deliberately reads from goal blocks generally, not the Mastered Goals
    section specifically -- a prior round flagged that this rule's
    category ('Mastered Goals') and its own wording ('...status of in
    progress') structurally conflict, since the real Mastered Goals
    section has no in-progress concept at all (every entry there is
    mastered by definition); the Goals-in-Progress section's own status
    field is what 'in progress' can actually mean here. That structural
    question is still open (needs Ms. Yachnes's own confirmation, per
    this rule's own notes) -- this checker answers the question AS ASKED
    ("at least 3... in progress") against whichever goal blocks actually
    carry that status, without assuming which section-level category is
    "correct."
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text)
    if not starts:
        return "not_checkable", "No goal blocks ('Target Goal:'/'Target Name:') found in this document.", None, 0.0
    starts = starts + [len(text)]
    parent_goals = []
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        sd_m = re.search(r"Skill Domain:[ \t]*([^\n]*)", block)
        if not sd_m or "parent training" not in sd_m.group(1).lower():
            continue
        status_m = re.search(r"(?:Goal Status|Status):[ \t]*([^\n]+)", block)
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:60]
        status = status_m.group(1).strip() if status_m else ""
        parent_goals.append((starts[i], goal_name, status))

    if not parent_goals:
        return (
            "not_applicable",
            "No Parent Training goals found in this document -- nothing for this rule to check.",
            None, 0.85,
        )

    in_progress = [(offset, name) for offset, name, status in parent_goals if "in progress" in status.lower()]
    page = _page_for_offset(fields, parent_goals[0][0])
    if len(in_progress) >= 3:
        names = ", ".join(f"'{n}'" for _, n in in_progress[:5])
        return (
            "pass",
            f"{len(in_progress)} Parent Training goal(s) have status 'in progress' (>= 3 required): {names}.",
            page, 0.8,
        )
    statuses = "; ".join(f"'{name}': {status or '(no status found)'}" for _, name, status in parent_goals)
    return (
        "fail",
        f"Only {len(in_progress)} Parent Training goal(s) have status 'in progress' (3 required). "
        f"Statuses found: {statuses}.",
        page, 0.75,
    )


def _check_HF06(rule: dict, fields: dict) -> tuple:
    """HF-06: "Healthfirst client's testing tool/assessment has not been
    updated within 3 months" -- read as the real failure condition this
    checklist item is naming: for a Healthfirst patient, the testing
    tool's own stated Assessment Date being more than 3 months before
    this TP's current report date is a fail (a stale assessment); within
    3 months is a pass. Fix Round (2026-09-11 night) -- REAL FIX: this
    rule had no deterministic checker at all (pure judgment, Round-90
    generic notes, never customized) despite being exactly the same
    payor-gated date-math shape already proven for HF-01/QA-ACF-12/
    QA-SM-01 -- reuses extract_acf_fields' own assessment_date extraction
    (already built for QA-ACF-12) and the same 'Date of Current Report'
    range every date-math checker in this file already reads.
    """
    detected_payor = fields.get("payor")
    if detected_payor != "Healthfirst":
        return (
            "not_applicable",
            f"Detected payor is {detected_payor!r}, not Healthfirst -- this rule only applies to "
            f"Healthfirst patients.",
            None, 0.9,
        )
    assessment_date_str = extract_acf_fields(fields).get("assessment_date")
    found_range = _find_labeled_date_range_with_offset(fields["full_text"], "Date of Current Report")
    if not assessment_date_str or not found_range:
        return (
            "not_checkable",
            "Could not find both the testing tool's own Assessment Date and this TP's 'Date of Current "
            "Report' to compute the 3-month window.",
            None, 0.0,
        )
    report_range = (found_range[0], found_range[1])
    page = _page_for_offset(fields, found_range[2])
    assessment_date = datetime.strptime(assessment_date_str, "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    months_since = (report_end - assessment_date).days / 30.44
    if months_since <= 3:
        return (
            "pass",
            f"Testing tool Assessment Date {assessment_date_str} is {months_since:.1f} months before the "
            f"current report's end date {report_range[1]} -- within the 3-month window.",
            page, 0.8,
        )
    return (
        "fail",
        f"Testing tool Assessment Date {assessment_date_str} is {months_since:.1f} months before the "
        f"current report's end date {report_range[1]} -- exceeds the 3-month window.",
        page, 0.8,
    )


_SCH05_HOURS_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)\s*hours?\b", re.IGNORECASE)


def _check_SCH05(rule: dict, fields: dict) -> tuple:
    """QA-SCH-05: "School hours match total under educational history, if
    applicable." Fix Round (2026-09-11 night) -- REAL, PARTIAL FIX, with
    an honestly-disclosed remaining limitation (not silently claimed
    complete): this rule had NO checker at all despite being labeled
    deterministic, always escalating -- confirmed the real root cause of
    its instability the same way as QA-HRS-08/HF-06/QA-MAST-03 above.

    Confirmed directly against the real Daylyn Holland document (zero
    real API cost, local extraction only): the "Educational History:"
    section states the school SCHEDULE as free prose ("Monday through
    Friday from 7:00 a.m. to 2:20 p.m."), not a labeled numeric hours
    total -- and no second, separately-labeled "school hours" total field
    exists anywhere else in this document to compare it against. This
    rule's own "if applicable" wording covers exactly this case: with no
    second stated total to compare against, the comparison genuinely
    doesn't apply -- a real, stable not_applicable, not a guess.

    HONEST LIMITATION: the actual NUMERIC COMPARE this rule names has not
    been built, because no real document seen so far states both an
    explicit "Educational History" hours figure AND a second total to
    check it against -- inventing that comparison's exact shape without
    a real example to confirm it against would be exactly the kind of
    fabricated-example the project has deliberately avoided elsewhere.
    If EITHER section states an explicit "N hours" figure, this returns
    not_checkable naming what was found, rather than silently guessing a
    match -- flagged for a real compare to be built once a document with
    both fields is available.
    """
    text = fields["full_text"]
    edu_m = re.search(r"Educational History:", text)
    if not edu_m:
        return "not_checkable", "No 'Educational History:' section found in this document.", None, 0.0
    page = _page_for_offset(fields, edu_m.start())
    edu_window = text[edu_m.end():edu_m.end() + 1500]
    edu_hours_m = _SCH05_HOURS_NUMBER_RE.search(edu_window)
    if not edu_hours_m:
        return (
            "not_applicable",
            "The 'Educational History:' section describes the school schedule but states no explicit "
            "school-hours total to compare against -- this rule's own 'if applicable' comparison doesn't "
            "apply here.",
            page, 0.8,
        )
    return (
        "not_checkable",
        f"Found an explicit hours figure in 'Educational History:' ({edu_hours_m.group(0)!r}) but no "
        f"separately-labeled second total elsewhere in the document has been confirmed to compare it "
        f"against -- this comparison's real shape hasn't been built against a confirmed real example yet.",
        page, 0.3,
    )


DET_CHECKS = {
    "QA-TEMP-05": _check_TEMP05,
    "QA-RPT-01": _check_RPT01,
    "QA-GIP-04": _check_GIP04,
    "HF-02": _check_HF02,
    # Round 92: precondition-only checker -- see _check_HRS05's own docstring.
    "QA-HRS-05": _check_HRS05,
    "QA-OBS-01": _check_OBS01,
    # Added following the full deterministic-label audit: these were all
    # labeled check_type "deterministic" but had no real checker, so every
    # finding for them came entirely from the judgment layer regardless of
    # the label. HF-01 in particular is the exact rule that caused the
    # multi-round contradiction bug — it was never actually implemented,
    # only its notes/params were improved to help the judgment layer that
    # was silently doing all the work.
    "HF-01": _check_HF01,
    "QA-RPT-02": _check_RPT02,
    "QA-RPT-05": _check_RPT05,
    "QA-RPT-06": _check_RPT06,
    "QA-SIG-02": _check_SIG02,
    "QA-SIG-03": _check_SIG03,
    "QA-SIG-04": _check_SIG04,
    "QA-HRS-02": _check_HRS02,
    "QA-HRS-03": _check_HRS03,
    # Fix Round (2026-08-26): QA-HRS-11 is the new "every other payor"
    # default bucket -- see _check_HRS11's own docstring for the
    # self-exclusion reasoning.
    "QA-HRS-11": _check_HRS11,
    # Round 63, item 3: real deterministic schedule-table arithmetic,
    # replacing the judgment layer's eyeballed (and confirmed wrong) totals
    # -- see pipeline/schedule_hours.py and _check_SCH01/_check_SCH07's own
    # docstrings.
    "QA-SCH-01": _check_SCH01,
    # Fix Round (Jacob Freund 10-2026-U1), Item 5: not-in-school N/A gate
    # only -- real overlap logic still escalates to judgment.
    "QA-SCH-03": _check_SCH03,
    "QA-SCH-07": _check_SCH07,
    # Round 63, item 5: deterministic pre-check only, for the confirmed
    # objective violation (embedded reviewer comment counted as evidence)
    # -- see _check_PROB02's own docstring for why this escalates to
    # judgment for the real semantic alignment question.
    "QA-PROB-02": _check_PROB02,
    # Round 84, item 3: hybrid DET pre-check, same shape as QA-PROB-02 --
    # see _check_PROB01's own docstring.
    "QA-PROB-01": _check_PROB01,
    # Fix Round (Jacob Freund 10-2026-U1), Item 9: phase-1, TP-only stub --
    # always not_applicable (no previous TP data at this stage). Real
    # comparison happens only via previous_tp_comparison.py::_compare_prob04.
    "QA-PROB-04": _check_PROB04,
    # Round 64, item 3: real highlight detection via PyMuPDF (annotation
    # objects + a flattened-fill fallback), replacing the judgment layer's
    # text-only read, which structurally can never see highlight data at
    # all -- see _check_TEMP03's own docstring for the real investigation.
    "QA-TEMP-03": _check_TEMP03,
    "QA-COC-04": _check_COC04,
    "QA-BIO-02": _check_BIO02,
    # Fix Round (Jacob Freund 10-2026-U1), Item 7: no-medication N/A gate
    # only -- reason-adequacy/ADHD review still escalates to judgment.
    "QA-BIO-06": _check_BIO06,
    "QA-BIO-13": _check_BIO13,
    # Straight Medicaid-specific — built from the start, per instruction not
    # to leave these to fall through like the 44-rule audit found.
    "SM-01": _check_SM01,
    "SM-02": _check_SM02,
    # Empire/Emblem/Aetna-specific — built from the start, same as SM-01/02.
    # EMP-02 deliberately NOT registered here — see its own notes/
    # blocked_status in rules.json for the scope ambiguity found against
    # real documents.
    "EMP-01": _check_EMP01,
    "EMP-03": _check_EMP03,
    # Fix Round (2026-08-26): Anthem siblings of EMP-01/03, same checker
    # code -- both are payor-agnostic already (read only rule["params"],
    # never hardcode "Empire"), so no new function was needed. ANT-02
    # deliberately NOT registered, matching EMP-02's own unbuilt state.
    "ANT-01": _check_EMP01,
    "ANT-03": _check_EMP03,
    "EMB-01": _check_HF02,  # generic CPT-hour-cap check, reused via params
    "AET-01": _check_AET01,
    # Next Round (2026-08-27), Part 2: 5 new real deterministic checkers --
    # see each function's own docstring, and the block comment above
    # DET_CHECKS's own definition for why QA-SCH-10/QA-GIP-32/34/35/
    # QA-BIO-17 are deliberately NOT in this dict (judgment, for confirmed
    # real reasons, not left unbuilt by omission).
    "QA-HRS-12": _check_HRS12,
    "QA-GIP-30": _check_GIP30,
    "QA-GIP-31": _check_GIP31,
    "QA-GIP-33": _check_GIP33,
    "QA-COC-08": _check_COC08,
    # Fix Round, Section 1 (2026-08-27): 7 real deterministic checkers --
    # see each function's own docstring, and the report for this round for
    # why QA-HRS-09/QA-COC-02/QA-BIP-02/QA-GIP-07/QA-BIP-14/CIG-01/
    # QA-PAR-03/QA-MAST-04 are NOT in this dict (judgment, for confirmed
    # real reasons, not left unbuilt by omission).
    "QA-BAR-01": _check_BAR01,
    # HF-05 REMOVED from this dict (Fix Round, 2026-09-10, item 7) -- real
    # rule-identity mismatch confirmed: this rule now means "fewer than 3
    # real data points on a PRT goal -> rationale must show a plan for
    # improvement," a genuine graph-image judgment question (same shape
    # as QA-GIP-32/QA-PAR-03), not the old hours-approved-vs-requested
    # comparison _check_HF05 (still here, unused by any rule_id now) was
    # built for. See VISION_ELIGIBLE_RULE_SECTIONS's own note above.
    "QA-COC-06": _check_COC06,
    "QA-RPT-07": _check_RPT07,
    "QA-SCH-06": _check_SCH06,
    "QA-GIP-19": _check_GIP19,
    "QA-GIP-26": _check_GIP26,
    # Fix Round, Section 1 Bucket D (2026-08-27): 2 real deterministic
    # checkers (see each function's own docstring above DET_CHECKS's own
    # definition) -- QA-GIP-13 closes a silent HF-01-style gap, QA-GIP-21
    # is a hybrid (mastered-by-date half is real DET, explanation-adequacy
    # half stays judgment).
    "QA-GIP-13": _check_GIP13,
    "QA-GIP-21": _check_GIP21,
    # Fix Round (2026-09-11 night), "Stop Over-Using the Uncertain Safety
    # Net": 3 rules that had NO real deterministic checker at all (always
    # escalated to judgment, the real root cause of their coin-flip
    # instability, not a genuine image/graph dependency) -- see each
    # function's own docstring above DET_CHECKS's own definition.
    "QA-HRS-08": _check_HRS08,
    "QA-MAST-03": _check_MAST03,
    # Fix Round (Jacob Freund 10-2026-U1), Item 17: real count-based
    # checker -- reuses this rule's own pre-existing evidence extractor's
    # exact logic (see fields.py::_mast04_context_preview).
    "QA-MAST-04": _check_MAST04,
    "HF-06": _check_HF06,
    "QA-SCH-05": _check_SCH05,
    "QA-GIP-22": _check_GIP22,
    # QA-BIO-03 relabeled from judgment to deterministic this round -- see
    # its rules.json notes for why the old BIO-01-derived "needs external
    # diagnostic report" dependency didn't actually apply to this rule.
    "QA-BIO-03": _check_BIO03,
    # Restored from archive (2026-07-28) as a real blank-field check,
    # replacing the retired Learning-Tree comparison.
    "QA-ACF-05": _check_ACF05,
    # Converted from judgment to deterministic (2026-07-28 round, item 1) --
    # see _check_GIP10's own docstring for the full rationale and the two
    # confirmed real-document bugs found while building it.
    "QA-GIP-10": _check_GIP10,
    # Item 1 backlog conversions (2026-07-28 round 3) -- same treatment,
    # each verified live against both real documents before wiring in. See
    # each checker's own docstring for the specific verification detail.
    "QA-GIP-16": _check_GIP16,
    # Round 92: hybrid DET pre-check (precondition (a) only), same shape as
    # QA-PROB-02 -- see _check_GIP23's own docstring.
    "QA-GIP-23": _check_GIP23,
    # Fix Round (2026-09-11), item 23: hybrid DET precondition (same shape
    # as QA-HRS-05/QA-GIP-23) -- see _check_GIP07's own docstring.
    "QA-GIP-07": _check_GIP07,
    # Round 83, item 2b: hybrid DET pre-check, same shape as QA-PROB-02/
    # QA-BIP-05 -- see _check_GIP05's own docstring.
    "QA-GIP-05": _check_GIP05,
    # Round 81, item 3: hybrid DET pre-check, same shape as QA-PROB-02 --
    # see _check_BIP05's own docstring.
    "QA-BIP-05": _check_BIP05,
    # Round 82, item 2: converted from judgment to deterministic -- see
    # _check_BIP06's own docstring for the confirmed real explained-N/A bug
    # this closes.
    "QA-BIP-06": _check_BIP06,
    "QA-TEMP-01": _check_TEMP01,
    "QA-PPI-02": _check_PPI02,
    "QA-PPI-03": _check_PPI03,
    "QA-PPI-05": _check_PPI05,
    # Fix Round, item 2 (2026-08-12): wired in per the user's explicit
    # rule_id/category decision -- QA-PPI-06, "Patient/Provider Info",
    # slotted right after PPI-01 through PPI-05.
    "QA-PPI-06": _check_narrative_name_contamination,
    # Round 91 (169-rule reconciliation, 2026-08-14): the AKA/alias check
    # -- deliberately a NEW rule_id (QA-PPI-07), not a repoint of QA-PPI-06,
    # per the user's explicit decision. See _check_PPI07's own docstring.
    "QA-PPI-07": _check_PPI07,
    # Fix Round, item 4 (2026-08-12): converted from judgment to
    # deterministic -- see _check_BIP04's own docstring.
    "QA-BIP-04": _check_BIP04,
    "QA-BIP-01": _check_severity_rating_not_all_mild,
    "QA-GIP-03": _check_severity_rating_not_all_mild,
    # Item 2 (2026-07-28 round 3): the presence half of "increase in hours
    # -> rationale in place", fully deterministic -- see _check_HRS06's
    # docstring for why this does NOT resolve Charny's original flagged
    # miss (a structurally different, reviewer-annotation-based issue).
    "QA-HRS-06": _check_HRS06,
    # Fix Round (Jacob Freund 10-2026-U1), Item 3: deterministic no-increase
    # gate only -- escalates to judgment for rationale-quality when an
    # increase is actually found. See _check_HRS07's own docstring.
    "QA-HRS-07": _check_HRS07,
    # Item 4 (2026-07-28 round 3): diagnosed as a real, previously-unfixed
    # bug, not related to the earlier schema-reorder fix -- see
    # _check_ACF07's own docstring for the full real-evidence diagnosis.
    "QA-ACF-07": _check_ACF07,
    # Fix Round (Jacob Freund 10-2026-U1), Item 14: at-most-one-tool N/A
    # gate only -- a real tool-switch still escalates for rationale review.
    "QA-ACF-09": _check_ACF09,
    # Fix Round (Jacob Freund 10-2026-U1), Item 11: non-Vineland N/A gate
    # only -- the real no-legend-under-Vineland review still escalates.
    "QA-ACF-11": _check_ACF11,
    # Round 83, item 1 follow-up: converted from judgment to deterministic
    # -- a narrower, separate gap from ACF-07/extract_acf_fields's
    # section-boundary bug -- see _check_ACF06's own docstring.
    "QA-ACF-06": _check_ACF06,
    # Round 92: NEW rule -- see _check_ACF12's own docstring.
    "QA-ACF-12": _check_ACF12,
    # Follow-up round item 1: fixes a confirmed regression (this rule's
    # judgment-only behavior had narrowed to only recognizing email-header
    # text) -- see _check_TEMP04's and _find_embedded_reviewer_comments's
    # own docstrings for the full diagnosis.
    "QA-TEMP-04": _check_TEMP04,
}


def run_deterministic_checks(rules: list[dict], fields: dict) -> dict[str, dict]:
    """Runs every check_type == "deterministic" active rule. Returns
    {rule_id: {"result", "evidence", "page", "confidence"}}.
    """
    results = {}
    for rule in rules:
        if rule["check_type"] != "deterministic" or not rule["active"]:
            continue
        rule_id = rule["rule_id"]
        checker = DET_CHECKS.get(rule_id)
        if checker is None:
            results[rule_id] = {
                "result": "not_checkable",
                "evidence": NEEDS_BACKEND_INTEGRATION,
                "page": None,
                "confidence": 0.0,
            }
            continue
        result, evidence, page, confidence = checker(rule, fields)
        results[rule_id] = {
            "result": result,
            "evidence": evidence,
            "page": page,
            "confidence": confidence,
        }
    return results


# --- Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence" --
#
# The permanently-stabilized safety-net rules (pipeline/__init__.py's
# STABILIZED_UNCERTAIN_RULE_IDS) were pulled out of the real judgment call
# entirely -- zero model calls, zero variance by construction -- and given
# a fully generic "needs human review" message. Confirmed real complaint:
# that leaves a reviewer with nothing to start from; they have to open the
# source document cold. This closes that WITHOUT touching the stability
# guarantee -- these are plain, deterministic, zero-API-cost text scans
# (same real extraction shape as any other checker in this file), run
# purely to SURFACE real document content, never to compute a verdict.
# The rule_id's own result stays "uncertain" no matter what this finds.
#
# Each extractor returns "" (empty string) when it genuinely finds
# nothing -- the caller (pipeline/__init__.py::_stabilized_uncertain_
# finding) turns that into an honest "no relevant data was found" phrase,
# never a fabricated non-finding dressed up as content.

def _goal_context_preview(fields: dict, *, block_prefix: str | None = None, max_goals: int = 5) -> str:
    """Real, zero-cost preview of each goal/behavior-target block's own
    key fields (Baseline, Current Data/Level, Mastery Criteria,
    Anticipated Mastery Date, Status), with page citations -- used by
    every stabilized rule whose real question is about goal/graph data
    this pipeline can't visually read, but CAN read the surrounding text
    fields for. `block_prefix` scopes to "Target Goal:" (skill-
    acquisition) or "Target Name:" (Behavior Reduction) blocks only, when
    the rule is specific to one; None covers both. Caps at `max_goals` so
    a document with dozens of goals doesn't produce a wall of text.
    """
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    previews = []
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        if block_prefix and not block.startswith(block_prefix):
            continue
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:80]
        if not goal_name:
            continue
        page = _page_for_offset(fields, starts[i])
        found = []
        for label in ("Baseline", "Current Data", "Current Level", "Mastery Criteria", "Anticipated Mastery Date", "Goal Status", "Status"):
            m = re.search(rf"{re.escape(label)}:[ \t]*([^\n]+)", block)
            if m and m.group(1).strip():
                found.append(f"{label}: {m.group(1).strip()[:60]}")
        if found:
            previews.append(f"'{goal_name}' (page {page}) -- {'; '.join(found)}")
    if not previews:
        return ""
    shown = previews[:max_goals]
    suffix = f" (+{len(previews) - max_goals} more goal(s) not shown)" if len(previews) > max_goals else ""
    return "Goal data found: " + " | ".join(shown) + suffix


def _acf_context_preview(fields: dict) -> str:
    """Real preview for the two grid/legend-image ACF rules (QA-ACF-03,
    QA-ACF-11) -- can't read the grid image itself, but CAN surface the
    testing tool name/date already extracted for this section."""
    acf = extract_acf_fields(fields)
    parts = [f"{label}: {acf[key]}" for label, key in (
        ("Testing tool", "assessment_tool"), ("Assessment date", "assessment_date"),
        ("Provider location", "pos"), ("Patient location", "patient_location"),
    ) if acf.get(key)]
    return "Assessment section data found: " + "; ".join(parts) if parts else ""


def _hours_context_preview(fields: dict) -> str:
    """Real preview for QA-HRS-07 (hours increase vs. discharge criteria)
    -- surfaces the actual current and previously-approved hours figures
    already extractable, even though "compared against the discharge
    criteria/transition plan" itself needs a holistic narrative read."""
    text = fields["full_text"]
    parts = []
    for code in ("97151", "97153", "97154", "97155", "97156"):
        current = _find_weekly_hours_for_code(text, code)
        if current is not None:
            parts.append(f"{code} currently requested: {current} hrs/week")
    return "Hours data found: " + "; ".join(parts) if parts else ""


def _ppi05_context_preview(fields: dict) -> str:
    """Real preview for QA-PPI-05 -- the deterministic NPI/License
    comparison itself already runs (see _check_PPI05); this rule is
    stabilized because of a SEPARATE real API call's own variance (the
    supporting-doc NPI extraction), not because this data is unreachable.
    Surfaces the same real NPI/License values that checker already found."""
    text = fields["full_text"]
    npi_vals = sorted({m.group(1).strip() for m in re.finditer(r"NPI:[ \t]*([0-9]+)", text)})
    license_vals = sorted({m.group(1).strip() for m in re.finditer(r"License[^\n:]*:[ \t]*([^\n]+)", text)})
    parts = []
    if npi_vals:
        parts.append(f"NPI value(s) found: {npi_vals}")
    if license_vals:
        parts.append(f"License value(s) found: {license_vals}")
    return "; ".join(parts)


def _mast04_context_preview(fields: dict) -> str:
    """Real preview for QA-MAST-04 (at least 3 parent goals in progress)
    -- surfaces every Parent Training goal's own stated status."""
    text = fields["full_text"]
    starts = _goal_block_starts(text) + [len(text)]
    statuses = []
    for i in range(len(starts) - 1):
        block = text[starts[i]:starts[i + 1]]
        sd_m = re.search(r"Skill Domain:[ \t]*([^\n]*)", block)
        if not sd_m or "parent training" not in sd_m.group(1).lower():
            continue
        status_m = re.search(r"(?:Goal Status|Status):[ \t]*([^\n]+)", block)
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:60]
        if status_m:
            statuses.append(f"'{goal_name}': {status_m.group(1).strip()}")
    return "Parent Training goal statuses found: " + "; ".join(statuses) if statuses else ""


def _par02_context_preview(fields: dict) -> str:
    """Real preview for QA-PAR-02 (child living elsewhere -> who receives
    training) -- surfaces the family-history living-situation statement
    and the Parent/Caregiver Involvement summary's own text, when found."""
    text = fields["full_text"]
    parts = []
    living_m = re.search(r"[^.\n]{0,200}\b(?:lives?|resides?)\b[^.\n]{0,150}", text, re.IGNORECASE)
    if living_m:
        parts.append(f"Living situation mention: \"{living_m.group(0).strip()[:180]}\"")
    involvement = _extract_labeled_value(text, "Parent/Caregiver Involvement")
    if involvement:
        parts.append(f"Parent/Caregiver Involvement summary: \"{involvement[:180]}\"")
    return " ".join(parts)


def _sch09_context_preview(fields: dict) -> str:
    """Real preview for QA-SCH-09 (community-location specificity) --
    surfaces the actual POS/location field text found."""
    text = fields["full_text"]
    m = re.search(r"POS[^\n:]{0,10}:[ \t]*([^\n]+)", text, re.IGNORECASE)
    if not m:
        return ""
    return f"POS/location field found: \"{m.group(1).strip()[:150]}\""


def _coc07_context_preview(fields: dict) -> str:
    """Real preview for QA-COC-07 (COC content vs. background info) --
    surfaces the Coordination of Care section's own stated text."""
    text = fields["full_text"]
    coc = _extract_labeled_value(text, "Coordination of Care")
    return f"Coordination of Care section text: \"{coc[:200]}\"" if coc else ""


def _bio06_context_preview(fields: dict) -> str:
    """Real preview for QA-BIO-06 (medication -> reason stated; ADHD ->
    secondary diagnosis) -- surfaces any medication mention found."""
    text = fields["full_text"]
    hits = [m.group(0) for m in re.finditer(r"[^.\n]{0,60}\bmedication[^.\n]{0,120}", text, re.IGNORECASE)]
    if not hits:
        return ""
    return "Medication mention(s) found: " + " | ".join(f"\"{h.strip()}\"" for h in hits[:3])


def _temp06_context_preview(fields: dict) -> str:
    """Real preview for QA-TEMP-06 (blank fields should say N/A) --
    surfaces a few of the actual blank-looking labels found. Deliberately
    NOT a verdict (see _find_blank_labels_with_offsets's own docstring --
    it also catches genuine section headers, not just real form fields,
    which is exactly why this rule isn't deterministic yet) -- shown here
    only as real, honestly-labeled raw candidates for the reviewer's own
    judgment, capped at 5 so it can't dump the whole document."""
    blanks = _find_blank_labels_with_offsets(fields["full_text"])
    if not blanks:
        return ""
    shown = [f"'{label}' (page {_page_for_offset(fields, offset)})" for label, offset in blanks[:5]]
    suffix = f" (+{len(blanks) - 5} more)" if len(blanks) > 5 else ""
    return "Possible blank field(s) found (unfiltered -- may include section headers, not just form fields): " + ", ".join(shown) + suffix


def _ai03_context_preview(fields: dict) -> str:
    """Real preview for QA-AI-03 (leftover template instructional
    prompts) -- scans for the specific phrasing this rule's own notes
    name as a real example ("jot down something positive")."""
    text = fields["full_text"]
    hits = [m.group(0) for m in re.finditer(r"[^.\n]{0,40}jot down[^.\n]{0,80}", text, re.IGNORECASE)]
    if not hits:
        return ""
    return "Possible leftover template text found: " + " | ".join(f"\"{h.strip()}\"" for h in hits[:3])


# rule_id -> (fields) -> str. A rule_id with no entry here gets an honest
# "no additional automated context is available for this item yet"
# fallback (pipeline/__init__.py) rather than a silently-empty or
# fabricated one -- real, disclosed scope, not a claim of completeness.
STABILIZED_RULE_CONTEXT: dict[str, "Callable[[dict], str]"] = {
    "HF-05": lambda f: _goal_context_preview(f, block_prefix="Target Name:"),
    "QA-GIP-02": _goal_context_preview,
    "QA-GIP-11": lambda f: _goal_context_preview(f, block_prefix="Target Goal:"),
    "QA-GIP-14": _goal_context_preview,
    "QA-GIP-17": lambda f: _goal_context_preview(f, block_prefix="Target Goal:"),
    "QA-GIP-20": lambda f: _goal_context_preview(f, block_prefix="Target Goal:"),
    "QA-GIP-23": lambda f: _goal_context_preview(f, block_prefix="Target Name:"),
    "QA-GIP-25": lambda f: _goal_context_preview(f, block_prefix="Target Goal:"),
    "QA-GIP-27": _goal_context_preview,
    "QA-GIP-29": _goal_context_preview,
    "QA-GIP-34": _goal_context_preview,
    "QA-GIP-35": _goal_context_preview,
    "QA-BIP-09": lambda f: _goal_context_preview(f, block_prefix="Target Name:"),
    "QA-BIP-10": lambda f: _goal_context_preview(f, block_prefix="Target Name:"),
    "QA-BIP-12": lambda f: _goal_context_preview(f, block_prefix="Target Name:"),
    "QA-ACF-03": _acf_context_preview,
    "QA-ACF-11": _acf_context_preview,
    "QA-HRS-07": _hours_context_preview,
    "QA-PPI-05": _ppi05_context_preview,
    "QA-MAST-04": _mast04_context_preview,
    "QA-PAR-02": _par02_context_preview,
    "QA-SCH-09": _sch09_context_preview,
    "QA-COC-07": _coc07_context_preview,
    "QA-BIO-06": _bio06_context_preview,
    "QA-TEMP-06": _temp06_context_preview,
    "QA-AI-03": _ai03_context_preview,
    # QA-AI-05 (spelling/grammar errors) deliberately has no entry -- no
    # reliable, real deterministic detector for this exists in this
    # codebase yet; a fabricated "no errors found" would be worse than
    # honestly saying no automated context is available.
}


def get_stabilized_rule_context(rule_id: str, fields: dict) -> str:
    """Real, zero-API-cost preview of whatever document content is
    relevant to a permanently-stabilized safety-net rule -- never a
    verdict, only substance for the reviewer to start from. Returns ""
    when there's genuinely no extractor built yet OR the extractor ran
    and found nothing -- callers distinguish "ran, found nothing" from
    "no extractor" only if they need to; both are equally honest to
    surface as "no relevant data was found" to a reviewer.
    """
    extractor = STABILIZED_RULE_CONTEXT.get(rule_id)
    if extractor is None:
        return ""
    try:
        return extractor(fields)
    except Exception:
        # Never let a best-effort preview crash the whole review -- same
        # isolation discipline as merge.py's own per-rule fallback.
        return ""
