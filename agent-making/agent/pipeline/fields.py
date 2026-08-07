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
import re
from collections import Counter
from datetime import datetime, timedelta

import fitz  # PyMuPDF -- already a pipeline dependency (see render.py)
from pypdf import PdfReader

from .schedule_hours import compute_weekly_total, extract_weekly_schedule_day_texts

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


def _find_blank_labels(text: str) -> list[str]:
    """Heuristic: a label ending in ':' with nothing but whitespace before the
    next line's content, suggesting an unfilled form field.
    """
    blanks = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.endswith(":") and len(stripped) < 60:
            next_nonblank = next((lines[j].strip() for j in range(i + 1, min(i + 2, len(lines)))), "")
            if not next_nonblank:
                blanks.append(stripped)
    return blanks


def _find_labeled_date(text: str, label: str) -> str | None:
    """Finds a single MM/DD/YYYY date following a "Label:" field, e.g.
    "Date of Most Recent Diagnosis: 11/20/2024". Returns the raw matched
    date string, or None if the label or a date after it isn't found."""
    m = re.search(rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})", text, re.IGNORECASE)
    return m.group(1) if m else None


def _find_labeled_date_range(text: str, label: str) -> tuple[str, str] | None:
    """Finds a "Label: MM/DD/YYYY to MM/DD/YYYY" range, e.g. "Authorization
    Dates Requested: 02/21/2026 to 08/21/2026". Returns (start, end) as raw
    matched date strings, or None if not found."""
    m = re.search(
        rf"{re.escape(label)}\s*:?\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})\s*to\s*(\d{{1,2}}/\d{{1,2}}/\d{{4}})",
        text, re.IGNORECASE,
    )
    return (m.group(1), m.group(2)) if m else None


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


_DAYS_IN_MONTH = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


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

# Word/Adobe's standard highlighter palette (yellow/green/pink/cyan,
# roughly full-saturation, at typical highlighter opacity) -- used only to
# scope the FLATTENED-fill fallback below (a colored rectangle baked into
# page content, not a real annotation) so an unrelated colored design
# element (a table row stripe, a header banner) isn't misread as a
# removed-but-still-visible highlight. Real annotation detection (the
# primary path) doesn't need this at all -- it only ever matches an actual
# Highlight-type annotation object, regardless of its color.
_HIGHLIGHTER_COLORS = {
    (1.0, 1.0, 0.0),  # yellow
    (0.0, 1.0, 0.0),  # green
    (1.0, 0.0, 1.0),  # pink/magenta
    (0.0, 1.0, 1.0),  # cyan
}


def _color_is_highlighter_like(color: tuple | None, tolerance: float = 0.15) -> bool:
    if color is None or len(color) != 3:
        return False
    return any(all(abs(c - ref) <= tolerance for c, ref in zip(color, ref_color)) for ref_color in _HIGHLIGHTER_COLORS)


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

    problems = []
    if real_annotation_hits:
        problems.append(f"Real Highlight annotation(s) found on page(s): {sorted(set(real_annotation_hits))}.")
    if flattened_fill_hits:
        problems.append(
            f"Highlighter-colored fill(s) behind text found on page(s): "
            f"{[(p, words) for p, words in flattened_fill_hits]}."
        )
    page = (sorted(set(real_annotation_hits)) or [flattened_fill_hits[0][0]])[0]
    return "fail", " ".join(problems), page, 0.85


def _find_embedded_reviewer_comments(text: str) -> list[str]:
    """Finds embedded reviewer comments/questions left in the document's
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
    """
    comments = []
    for m in re.finditer(r"[^\n]{0,150}\?", text):
        next_char = text[m.end():m.end() + 1]
        if next_char in ('"', "”"):
            continue  # closes a quoted clinical example, not a reviewer question
        comments.append(m.group(0).strip())
    for m in re.finditer(r"[Pp]lease (?!note\b)(?:reword|clarify|specify|update|add)[^\n]{0,80}", text):
        comments.append(m.group(0).strip())
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
    email_headers = re.findall(r"^(?:From|To|Re|Subject|Sent):[^\n]*", text, re.MULTILINE)

    if not comments and not email_headers:
        return (
            "pass",
            "No embedded reviewer comments/questions or email-header-style correspondence "
            "found in the document.",
            None, 0.75,
        )

    problems = []
    if email_headers:
        problems.append(f"{len(email_headers)} email-header-style line(s) found: {email_headers[:5]}.")
    if comments:
        problems.append(
            f"{len(comments)} embedded reviewer comment(s)/question(s) found, e.g.: "
            f"{comments[:3]}."
        )
    return "fail", " ".join(problems), None, 0.75


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
            for comment in comments:
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
                        None, 0.85,
                    )
    return (
        "not_checkable",
        "No embedded-reviewer-comment violation found in any 'As evidenced by:' entry -- the full "
        "semantic alignment against the goals listed still requires judgment.",
        None, 0.0,
    )


def _check_TEMP05(rule: dict, fields: dict) -> tuple:
    hits = _bare_rbt_mentions(fields["full_text"])
    if not hits:
        return "pass", "No bare 'RBT' mentions found; all instances already read 'RBT/BT' or are followed by '/BT'.", None, 0.85
    return "fail", f"Found {len(hits)} bare 'RBT' mention(s) not updated to 'RBT/BT' or 'BT'.", None, 0.8


def _check_RPT01(rule: dict, fields: dict) -> tuple:
    blanks = []
    for p in fields["pages"]:
        found = _find_blank_labels(p["text"])
        if found:
            blanks.append((p["page_number"], found))
    if not blanks:
        return "pass", "No unfilled 'Label:' form fields detected.", None, 0.6
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
        return "fail", f"Possible unfilled field(s) on page {page}: {labels}.", page, 0.65
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
            None, 0.85,
        )
    if len(blank_dates) == 1:
        page, detail = blank_dates[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in blank_dates]
    return "fail", evidence, None, 0.85


def _check_HF02(rule: dict, fields: dict) -> tuple:
    cpt_code = rule["params"]["cpt_code"]
    max_hours = rule["params"]["max_hours"]
    m = re.search(rf"{re.escape(cpt_code)}[^\d]{{0,20}}(\d+(\.\d+)?)\s*(hrs|hours)?", fields["full_text"], re.IGNORECASE)
    if not m:
        return "not_applicable", f"No {cpt_code} (assessment) hours found in this TP.", None, 0.5
    hours = float(m.group(1))
    if hours <= max_hours:
        return "pass", f"{cpt_code} hours requested: {hours} (<= {max_hours}-hour cap).", None, 0.7
    return "fail", f"{cpt_code} hours requested: {hours}, exceeds the {max_hours}-hour cap.", None, 0.7


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
    are printed on page 1 in every sample TP seen so far."""
    age_threshold = rule["params"]["age_threshold"]
    short_months = rule["params"]["short_range_months"]
    long_months = rule["params"]["long_range_months"]

    age_m = re.search(r"Patient Age:\s*(\d+)", fields["full_text"], re.IGNORECASE)
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not age_m or not auth_range:
        return (
            "not_checkable",
            "Could not find both 'Patient Age' and 'Authorization Dates Requested' in the document text.",
            None, 0.0,
        )

    age = int(age_m.group(1))
    start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    end = datetime.strptime(auth_range[1], "%m/%d/%Y")
    range_days = (end - start).days

    expected_months = short_months if age > age_threshold else long_months
    expected_end = _add_months(start, expected_months)
    # +/- 10 days tolerance for month-length variation and "approximately"
    # wording in the rule itself — not a precise calendar-day requirement.
    tolerance_days = 10
    if abs((end - expected_end).days) <= tolerance_days:
        return (
            "pass",
            f"Patient age {age}; authorization range {auth_range[0]} to {auth_range[1]} "
            f"({range_days} days) matches the expected ~{expected_months}-month range "
            f"for age {'>' if age > age_threshold else '<='} {age_threshold}.",
            None, 0.85,
        )
    return (
        "fail",
        f"Patient age {age}; authorization range {auth_range[0]} to {auth_range[1]} "
        f"({range_days} days) does not match the expected ~{expected_months}-month range "
        f"for age {'>' if age > age_threshold else '<='} {age_threshold} "
        f"(expected end ~{expected_end.strftime('%m/%d/%Y')}).",
        None, 0.85,
    )


def _check_RPT02(rule: dict, fields: dict) -> tuple:
    date = _find_labeled_date(fields["full_text"], "Date of Initial Assessment")
    if date:
        return "pass", f"Date of Initial Assessment is present: {date}.", None, 0.7
    return "fail", "No 'Date of Initial Assessment' value found on this Reassessment TP.", None, 0.6


def _check_RPT06(rule: dict, fields: dict) -> tuple:
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not report_range or not auth_range:
        return (
            "not_checkable",
            "Could not find both 'Date of Current Report' and 'Authorization Dates Requested' ranges.",
            None, 0.0,
        )
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    if report_end < auth_start:
        return (
            "pass",
            f"Date of Current Report ends {report_range[1]}, before Authorization Dates "
            f"Requested starts {auth_range[0]}.",
            None, 0.8,
        )
    return (
        "fail",
        f"Date of Current Report ends {report_range[1]}, which is not before Authorization "
        f"Dates Requested starts {auth_range[0]}.",
        None, 0.8,
    )


def _check_SIG02(rule: dict, fields: dict) -> tuple:
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
    if contact_creds.lower() == sig_creds.lower():
        return (
            "pass",
            f"Signature credentials '{sig_creds}' match the page-1 Provider Contact "
            f"certification '{contact_creds}'.",
            None, 0.75,
        )
    return (
        "fail",
        f"Signature credentials '{sig_creds}' do not match the page-1 Provider Contact "
        f"certification '{contact_creds}'.",
        None, 0.7,
    )


def _check_SIG03(rule: dict, fields: dict) -> tuple:
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not sig_m or not auth_range:
        return "not_checkable", "Could not find both the signature date and 'Authorization Dates Requested'.", None, 0.0
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    if sig_date < auth_start:
        return (
            "pass",
            f"Signature date {sig_m.group(1)} is before Authorization Dates Requested "
            f"start {auth_range[0]}.",
            None, 0.8,
        )
    return (
        "fail",
        f"Signature date {sig_m.group(1)} is not before Authorization Dates Requested "
        f"start {auth_range[0]}.",
        None, 0.8,
    )


def _check_SIG04(rule: dict, fields: dict) -> tuple:
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    if not sig_m or not report_range:
        return "not_checkable", "Could not find both the signature date and 'Date of Current Report'.", None, 0.0
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    delta_days = (sig_date - report_end).days
    if delta_days <= 2:
        return (
            "pass",
            f"Signature date {sig_m.group(1)} is {delta_days} day(s) relative to Date of "
            f"Current Report end {report_range[1]} (within the 2-day allowance).",
            None, 0.8,
        )
    return (
        "fail",
        f"Signature date {sig_m.group(1)} is {delta_days} days after Date of Current Report "
        f"end {report_range[1]}, exceeding the 2-day allowance.",
        None, 0.8,
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
    cpt_code = rule["params"]["cpt_code"]
    day_texts = extract_weekly_schedule_day_texts(fields["full_text"])
    if day_texts is None:
        return (
            "not_checkable",
            "Could not confidently parse the weekly ABA schedule table into 7 distinct days from this "
            "TP's extracted text.",
            None, 0.0,
        )
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
            None, 0.85,
        )
    return (
        "fail",
        f"Schedule grid totals {schedule_total} hrs/week, but {cpt_code} hours requested is "
        f"{requested_hours} hrs/week -- these do not match. Per-day: {per_day}.",
        None, 0.85,
    )


def _check_SCH07(rule: dict, fields: dict) -> tuple:
    """Round 63, item 3: ">3 hrs/day of 97153 -> approved by clinical
    director" -- a hard Director-tag trigger (Section 7.1) whenever ANY
    single day in the real, computed weekly schedule exceeds the
    threshold. Same deterministic arithmetic as _check_SCH01, applied
    per-day instead of as a weekly sum.
    """
    threshold = rule["params"]["daily_hours_threshold"]
    day_texts = extract_weekly_schedule_day_texts(fields["full_text"])
    if day_texts is None:
        return (
            "not_checkable",
            "Could not confidently parse the weekly ABA schedule table into 7 distinct days from this "
            "TP's extracted text.",
            None, 0.0,
        )
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
            None, 0.85,
        )
    return "pass", f"No day exceeds {threshold} hrs/day. Per-day: {per_day}.", None, 0.85


def _check_HRS02(rule: dict, fields: dict) -> tuple:
    cpt_code = rule["params"]["cpt_code"]
    threshold = rule["params"]["hours_threshold"]
    hours = _find_weekly_hours_for_code(fields["full_text"], cpt_code)
    if hours is None:
        return "not_applicable", f"No {cpt_code} weekly hours found in this TP.", None, 0.5
    if hours > threshold:
        return (
            "fail",
            f"{cpt_code} hours requested: {hours}/week, exceeds {threshold} hrs/week — "
            f"requires a note on the review email to Eliana.",
            None, 0.75,
        )
    return "pass", f"{cpt_code} hours requested: {hours}/week (<= {threshold} hrs/week).", None, 0.75


def _check_HRS03(rule: dict, fields: dict) -> tuple:
    """This is a CEILING, not a minimum-supervision floor: the checklist
    says supervision must not EXCEED the ratio (1.5 hrs per 10 direct-care
    hrs), and if it does, needs documented clinical director approval. A
    prior round had this backwards (treated it as "supervision must be AT
    LEAST this much"), which incorrectly failed Reeda's TP -- her real
    ratio is 2.5 supervision / 25 direct = 0.10/hr, under the 0.15/hr
    ceiling, which Eliana's manual review correctly marked Pass.

    When the ceiling IS exceeded, this returns "uncertain" rather than an
    automatic fail: whether director approval was documented requires
    reading the actual document, and there's no confirmed real-sample text
    pattern for what that approval note looks like to search for -- so
    this escalates to judgment (which has full page context) instead of
    guessing at a regex for something never yet seen in a real document.
    """
    direct_code = rule["params"]["direct_cpt_code"]
    supervision_code = rule["params"]["supervision_cpt_code"]
    ratio = rule["params"]["supervision_ratio_per_direct_hour"]
    direct_hours = _find_weekly_hours_for_code(fields["full_text"], direct_code)
    supervision_hours = _find_weekly_hours_for_code(fields["full_text"], supervision_code)
    if direct_hours is None or supervision_hours is None:
        return (
            "not_checkable",
            f"Could not find both {direct_code} and {supervision_code} weekly hours.",
            None, 0.0,
        )
    max_allowed_supervision = round(direct_hours * ratio, 2)
    if supervision_hours <= max_allowed_supervision + 0.01:
        return (
            "pass",
            f"{direct_code} direct care: {direct_hours} hrs/week; {supervision_code} supervision: "
            f"{supervision_hours} hrs/week (<= ceiling of {max_allowed_supervision}).",
            None, 0.75,
        )
    return (
        "uncertain",
        f"{direct_code} direct care: {direct_hours} hrs/week; {supervision_code} supervision: "
        f"{supervision_hours} hrs/week exceeds the ceiling of {max_allowed_supervision} — this "
        f"needs documented clinical director approval, which requires reading the actual "
        f"document rather than a text-pattern check.",
        None, 0.3,
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


def _hrs06_unresolved_reviewer_annotation(text: str) -> str | None:
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
    return section[start:end].strip()


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

    previous = _hrs06_previous_auth_hours(text)
    current = _hrs06_current_hours_and_rationale(text)
    if not previous or not current:
        if annotation:
            return (
                "fail",
                f"Unresolved reviewer annotation questioning hours in the Hours Requesting "
                f"section: {annotation!r}.",
                None, 0.75,
            )
        return (
            "not_checkable",
            "Could not find both a 'Hours Requesting:' and 'Hours Approved Previous "
            "Authorization:' section with parseable per-code hours.",
            None, 0.0,
        )

    pairs = _hrs06_match_previous_to_current(previous, current)
    increases = []
    for p_desc, p_hours_str, curr in pairs:
        p_hours = _hrs06_to_number(p_hours_str)
        c_hours = _hrs06_to_number(curr["hours"])
        if p_hours is None or c_hours is None or c_hours <= p_hours:
            continue
        # Strip the first few structural lines (code/description, provider,
        # POS) before judging whether real rationale narrative exists --
        # those columns are always present and non-blank even with zero
        # actual rationale, so counting their length would never catch a
        # missing rationale.
        non_boiler = re.sub(r"^[^\n]*\n(?:[^\n]*\n){0,4}", "", curr["rationale"], count=1)
        has_rationale = len(non_boiler.strip()) > 20
        increases.append((curr["code"], curr["desc"], p_hours_str, curr["hours"], has_rationale))

    missing = [i for i in increases if not i[4]]
    problems = []
    if missing:
        problems.append("; ".join(
            f"{code}-{desc} increased from {p} to {c} hours with no accompanying rationale "
            f"text found" for code, desc, p, c, _ in missing
        ))
    if annotation:
        problems.append(
            f"Unresolved reviewer annotation questioning hours in the Hours Requesting "
            f"section: {annotation!r}."
        )

    if problems:
        return "fail", " ".join(problems), None, 0.8

    if not increases:
        return (
            "not_applicable",
            "No CPT code's requested hours increased over the previous authorization, and no "
            "unresolved reviewer annotation questioning hours was found -- nothing for this "
            "rule to check.",
            None, 0.85,
        )
    detail = "; ".join(
        f"{code}-{desc} increased from {p} to {c} hours, with rationale text present"
        for code, desc, p, c, _ in increases
    )
    return "pass", detail, None, 0.8


def _check_COC04(rule: dict, fields: dict) -> tuple:
    months_allowed = rule["params"]["months_allowed"]
    fax_m = re.search(r"faxed to [^\n]*?on\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    if not fax_m or not report_range:
        return "not_checkable", "Could not find both the COC fax date and 'Date of Current Report'.", None, 0.0
    fax_date = datetime.strptime(fax_m.group(1), "%m/%d/%Y")
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    earliest_valid = _add_months(report_end, -months_allowed)
    if fax_date >= earliest_valid:
        return (
            "pass",
            f"TP faxed on {fax_m.group(1)}, within {months_allowed} months of the current "
            f"report end {report_range[1]}.",
            None, 0.75,
        )
    return (
        "fail",
        f"TP faxed on {fax_m.group(1)}, more than {months_allowed} months before the "
        f"current report end {report_range[1]}.",
        None, 0.75,
    )


def _check_BIO02(rule: dict, fields: dict) -> tuple:
    date = _find_labeled_date(fields["full_text"], "Date of Most Recent Diagnosis")
    if date:
        return "pass", f"Date of Most Recent Diagnosis is present: {date}.", None, 0.7
    return "fail", "No 'Date of Most Recent Diagnosis' value found in this TP.", None, 0.6


def _check_BIO13(rule: dict, fields: dict) -> tuple:
    date = _find_labeled_date(fields["full_text"], "First day of ABA services with Master Faster")
    if date:
        return "pass", f"'First day of ABA services with Master Faster' is present: {date}.", None, 0.7
    return (
        "fail",
        "No 'First day of ABA services with Master Faster' value found on this Reassessment TP.",
        None, 0.6,
    )


def _check_SM01(rule: dict, fields: dict) -> tuple:
    """Straight Medicaid-specific: new auth start = day after the current
    report's own end date; new auth end <= N months after that same date.
    Both fields are page-1 text, no backend/prior-auth data needed — see
    the rule's own notes for why this differs from the universal QA-RPT-05."""
    max_months = rule["params"]["max_months_after_report_end"]
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not report_range or not auth_range:
        return (
            "not_checkable",
            "Could not find both 'Date of Current Report' and 'Authorization Dates Requested'.",
            None, 0.0,
        )

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
        return "fail", " ".join(problems), None, 0.75
    return (
        "pass",
        f"Authorization Dates Requested ({auth_range[0]} to {auth_range[1]}) correctly starts "
        f"the day after the current report ends and ends within {max_months} months.",
        None, 0.75,
    )


def _check_EMP01(rule: dict, fields: dict) -> tuple:
    """Empire: 'Date of current report is within 30 days of the
    authorization start date' — interpreted as the current report's own
    end date vs the new authorization's start date (see the rule's notes
    for why)."""
    max_days = rule["params"]["max_days"]
    report_range = _find_labeled_date_range(fields["full_text"], "Date of Current Report")
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not report_range or not auth_range:
        return "not_checkable", "Could not find both 'Date of Current Report' and 'Authorization Dates Requested'.", None, 0.0
    report_end = datetime.strptime(report_range[1], "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    delta_days = abs((auth_start - report_end).days)
    if delta_days <= max_days:
        return (
            "pass",
            f"Date of Current Report end ({report_range[1]}) is {delta_days} day(s) from "
            f"Authorization Dates Requested start ({auth_range[0]}), within the {max_days}-day allowance.",
            None, 0.75,
        )
    return (
        "fail",
        f"Date of Current Report end ({report_range[1]}) is {delta_days} day(s) from "
        f"Authorization Dates Requested start ({auth_range[0]}), exceeding the {max_days}-day allowance.",
        None, 0.75,
    )


def _check_EMP03(rule: dict, fields: dict) -> tuple:
    """Empire: 'Signature date is within 30 days of the authorization
    start date.'"""
    max_days = rule["params"]["max_days"]
    sig_m = re.search(r"Provider Signature,\s*Date:\s*(\d{1,2}/\d{1,2}/\d{4})", fields["full_text"], re.IGNORECASE)
    auth_range = _find_labeled_date_range(fields["full_text"], "Authorization Dates Requested")
    if not sig_m or not auth_range:
        return "not_checkable", "Could not find both the signature date and 'Authorization Dates Requested'.", None, 0.0
    sig_date = datetime.strptime(sig_m.group(1), "%m/%d/%Y")
    auth_start = datetime.strptime(auth_range[0], "%m/%d/%Y")
    delta_days = abs((auth_start - sig_date).days)
    if delta_days <= max_days:
        return (
            "pass",
            f"Signature date ({sig_m.group(1)}) is {delta_days} day(s) from Authorization "
            f"Dates Requested start ({auth_range[0]}), within the {max_days}-day allowance.",
            None, 0.75,
        )
    return (
        "fail",
        f"Signature date ({sig_m.group(1)}) is {delta_days} day(s) from Authorization "
        f"Dates Requested start ({auth_range[0]}), exceeding the {max_days}-day allowance.",
        None, 0.75,
    )


def _check_AET01(rule: dict, fields: dict) -> tuple:
    """Aetna: 'Vineland, VB-MAPP, and ABLLS can be used; AFLS cannot be
    used.' A disallowed-tool mention is a fail regardless of whether an
    allowed one is also present — the rule bans AFLS outright, it doesn't
    just require at least one allowed tool alongside it."""
    text = fields["full_text"]
    disallowed_hits = [t for t in rule["params"]["disallowed_tools"] if re.search(re.escape(t), text, re.IGNORECASE)]
    if disallowed_hits:
        return (
            "fail",
            f"Disallowed testing tool(s) found for this payor: {disallowed_hits}.",
            None, 0.75,
        )
    allowed_hits = [t for t in rule["params"]["allowed_tools"] if re.search(re.escape(t), text, re.IGNORECASE)]
    if not allowed_hits:
        return "not_checkable", "No recognized testing tool (allowed or disallowed) found in this TP.", None, 0.0
    return "pass", f"Testing tool(s) found: {allowed_hits}; no disallowed tool present.", None, 0.75


_ACF07_KNOWN_TOOLS = ["ABLLS-R", "ABLLS", "VB-MAPP", "AFLS", "Vineland-3", "Vineland", "PEAK", "ADOS", "CARS"]
_ACF07_TOOL_PATTERN = re.compile("|".join(re.escape(t) for t in _ACF07_KNOWN_TOOLS), re.IGNORECASE)


def _find_acf_section(text: str) -> str | None:
    """Shared section-boundary finder for every "Assessment of Current
    Functioning:" checker (_check_ACF07, extract_acf_fields below) --
    factored out of what was previously duplicated inline in _check_ACF07,
    so both use the exact same section boundaries. Returns None if the
    section header itself isn't found anywhere in this TP's text.
    """
    m = re.search(
        r"Assessment of Current Functioning:([\s\S]{0,30000}?)(?:Goal Progress:|Clinical Interpretation|Areas of Focus)",
        text,
    )
    return m.group(1) if m else None


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
    section = _find_acf_section(fields["full_text"])
    if section is None:
        return "not_checkable", "No 'Assessment of Current Functioning:' section found.", None, 0.0

    core_fields = ["Assessment Date:", "Assessment Methods/Measures:", "Assessment Summary Statement:"]
    section_has_content = any(
        re.search(re.escape(label) + r"[ \t]*(\S[^\n]*)", section) for label in core_fields
    )
    if not section_has_content:
        return (
            "fail",
            "The Assessment of Current Functioning section is entirely blank -- no testing "
            "tool, date, or summary documented at all.",
            None, 0.8,
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
            None, 0.75,
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
    _DATE_PATTERNS = (
        re.compile(r"Assessment Date:[ \t]*(\d{1,2}/\d{1,2}/\d{4})"),
        re.compile(r"Total Score on[ \t]*(\d{1,2}/\d{1,2}/\d{4})", re.IGNORECASE),
    )

    def _dates_in(window: str) -> list[str]:
        found = []
        for pattern in _DATE_PATTERNS:
            found.extend(m.group(1) for m in pattern.finditer(window))
        return found

    if len(distinct_keys) == 1:
        key, occurrences = next(iter(distinct_keys.items()))
        display_name = occurrences[0][0]
        dates = set(_dates_in(section))
        has_open_question = re.search(r"\bWhat was the date of administration\b", section, re.IGNORECASE) is not None
        if not dates or has_open_question:
            return (
                "fail",
                f"{display_name} is mentioned but no confirmed administration date was found anywhere "
                f"in the Assessment of Current Functioning section.",
                None, 0.75,
            )
        if len(dates) >= 2:
            return (
                "pass",
                f"{display_name} administered on {sorted(dates)} (old and new administration of the "
                f"same tool).",
                None, 0.8,
            )
        return (
            "uncertain",
            f"Only one testing tool found ({display_name}, dated {sorted(dates)}) -- cannot confirm "
            f"both an old and new administration are present (would also be satisfied by the same tool "
            f"administered on a second, different date).",
            None, 0.4,
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
    undated = []
    dates_by_tool: dict[str, set] = {}
    display_name_by_key: dict[str, str] = {}
    for i, (name, start, end) in enumerate(tool_mentions):
        gap_start = tool_mentions[i - 1][2] if i > 0 else 0
        gap_end = tool_mentions[i + 1][1] if i + 1 < len(tool_mentions) else len(section)
        gap_before = section[gap_start:start]
        gap_after = section[end:gap_end]

        date_matches = _dates_in(gap_before)
        has_open_question = re.search(r"\bWhat was the date of administration\b", gap_after, re.IGNORECASE) is not None

        if not date_matches or has_open_question:
            undated.append(name)
            continue
        key = _tool_key(name)
        display_name_by_key.setdefault(key, name)
        dates_by_tool.setdefault(key, set()).add(date_matches[-1])

    if undated:
        return "fail", f"Testing tool(s) mentioned without a confirmed administration date: {undated}.", None, 0.75

    # "Old and new" is satisfied by either shape:
    #  (a) two or more DISTINCT tools, each with at least one confirmed date, or
    #  (b) the SAME tool with two or more DISTINCT confirmed dates (an old
    #      score and a new score from one instrument, on two different days
    #      -- exactly the case a same-tool reassessment produces).
    distinct_tools_with_dates = len(dates_by_tool)
    max_distinct_dates_for_one_tool = max((len(dates) for dates in dates_by_tool.values()), default=0)

    if distinct_tools_with_dates >= 2 or max_distinct_dates_for_one_tool >= 2:
        summary = {display_name_by_key[key]: sorted(dates) for key, dates in dates_by_tool.items()}
        return "pass", f"Testing tool administration dates found: {summary}.", None, 0.8

    only_key, only_dates = next(iter(dates_by_tool.items()))
    return (
        "uncertain",
        f"Only one testing tool found ({display_name_by_key[only_key]}, dated {sorted(only_dates)}) -- cannot "
        f"confirm both an old and new administration are present (would also be satisfied by the same tool "
        f"administered on a second, different date).",
        None, 0.4,
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
    """
    section = _find_acf_section(fields["full_text"])
    if section is None:
        return {"assessment_date": None, "pos": None, "patient_location": None, "assessment_tool": None}

    def _labeled_value(label: str) -> str | None:
        m = re.search(re.escape(label) + r"[ \t]*(\S[^\n]*)", section)
        if not m:
            return None
        value = m.group(1).strip()
        return value or None

    assessment_date_m = re.search(r"Assessment Date:[ \t]*(\d{1,2}/\d{1,2}/\d{4})", section)
    tool_m = _ACF07_TOOL_PATTERN.search(section)

    return {
        "assessment_date": assessment_date_m.group(1) if assessment_date_m else None,
        "pos": _labeled_value("Provider Location During Assessment:"),
        "patient_location": _labeled_value("Patient Location during Assessment:"),
        "assessment_tool": tool_m.group(0) if tool_m else None,
    }


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
    lines = fields["full_text"].splitlines()
    for i, line in enumerate(lines):
        if line.strip().rstrip(":").strip().lower() == "assessment summary statement":
            next_nonblank = next((lines[j].strip() for j in range(i + 1, len(lines)) if lines[j].strip()), "")
            if not next_nonblank or next_nonblank.endswith(":"):
                return (
                    "fail",
                    "The 'Assessment Summary Statement:' field is blank -- immediately "
                    "followed by the next field's label, with nothing filled in.",
                    None, 0.7,
                )
            return "pass", f"Assessment Summary Statement is documented: {next_nonblank[:150]}", None, 0.7
    return "not_checkable", "No 'Assessment Summary Statement:' field found anywhere in this TP.", None, 0.0


def _check_BIO03(rule: dict, fields: dict) -> tuple:
    """'Includes any other diagnosis if applicable' -- confirmed against real
    documents this is a plain presence check on the 'Secondary Diagnosis:'
    field, not a clinical-applicability judgment (see the rule's own notes
    for why the old BIO-01-derived dependency didn't actually apply here).
    A blank field is genuinely ambiguous -- could mean 'no secondary
    diagnosis' or an omission -- so that case is left to judgment rather
    than guessed at here."""
    # [ \t]* (not \s*) so this doesn't consume the trailing newline and bleed
    # into matching the start of the NEXT line's content as if it were the
    # value on this line.
    m = re.search(r"Secondary Diagnosis:[ \t]*(\S[^\n]*)", fields["full_text"], re.IGNORECASE)
    if m:
        return "pass", f"Secondary Diagnosis is documented: {m.group(1).strip()}.", None, 0.75
    if re.search(r"Secondary Diagnosis:", fields["full_text"], re.IGNORECASE):
        return (
            "uncertain",
            "The 'Secondary Diagnosis:' field is present but blank -- could mean no "
            "secondary diagnosis applies, or could be an omission; not determinable "
            "from the field alone.",
            None, 0.3,
        )
    return "not_checkable", "No 'Secondary Diagnosis:' field found anywhere in this TP.", None, 0.0


_VALID_SAMPLING_METHODS = {
    "percent correct", "frequency", "duration", "rate",
    "task analysis", "percent independent", "trials to criterion",
    "interval recording", "latency",
}


def _page_for_offset(fields: dict, offset: int) -> int | None:
    """Maps a character offset in fields["full_text"] back to the page it
    falls on -- full_text is built as "\\n".join(p["text"] for p in pages),
    so this walks the same join with a +1 for each joining newline."""
    pos = 0
    for p in fields["pages"]:
        length = len(p["text"])
        if pos <= offset < pos + length:
            return p["page_number"]
        pos += length + 1
    return fields["pages"][-1]["page_number"] if fields["pages"] else None


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
        mc_m = re.search(r"Mastery Criteria:[ \t]*([^\n]*)", block)
        bl_m = re.search(r"Baseline:[ \t]*([^\n]*)", block)
        sm_val = sm_m.group(1).strip()
        mc_val = mc_m.group(1).strip() if mc_m else ""
        bl_val = bl_m.group(1).strip() if bl_m else ""
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


_ZERO_MASTERY_PATTERN = re.compile(r"(?:\b0\s*%|\b0\s*occurrences?\b|\b0\s*x\b|near\s*0)", re.IGNORECASE)


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

    EXPLICIT DIVISION OF LABOR WITH QA-GIP-10 (2026-08-07, Round 63, item
    7 -- documented, not just implemented, so results don't look
    contradictory when read together): a BLANK Mastery Criteria is a real
    problem, but this rule's own narrow zero/near-zero pattern never
    matches an empty string, so on its own it would silently pass a blank
    field. QA-GIP-10 ALREADY flags a blank Mastery Criteria -- but only
    for a block that also has a 'Sampling Method:' field (GIP-10 skips
    any block without one entirely). So there's a genuine, narrow gap
    neither rule closes on its own: a block with a blank Mastery Criteria
    AND no Sampling Method field. This function fails that specific
    combination; when Sampling Method IS present, it deliberately defers
    to GIP-10 (does not also flag it here) to avoid two rules reporting
    the identical blank-field violation as if it were two separate
    problems.
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
        mc_val = mc_m.group(1).strip()
        marker_len = len("Target Goal:") if block.startswith("Target Goal:") else len("Target Name:")
        goal_name = block[marker_len:].split("\n", 1)[0].strip()[:100]
        if mc_val and _ZERO_MASTERY_PATTERN.search(mc_val):
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            problems.append((page, (
                f"Mastery Criteria for goal '{goal_name}' reads {mc_val!r} -- a zero/near-zero "
                f"endpoint must instead read 'fewer than one instance' (or equivalent "
                f"minimum-occurrence phrasing)."
            )))
        elif not mc_val and not re.search(r"Sampling Method:[ \t]*[^\n]", block):
            # Blank Mastery Criteria with no Sampling Method field either --
            # the one case QA-GIP-10 structurally cannot catch (it requires
            # a Sampling Method match before it even looks at this block).
            page = _page_for_offset(fields, goal_starts[i] + mc_m.start())
            problems.append((page, (
                f"Mastery Criteria is blank for goal '{goal_name}', and this block also has no "
                f"Sampling Method field -- not caught by QA-GIP-10 (which requires a Sampling "
                f"Method match first)."
            )))

    if total == 0:
        return "not_checkable", "No goal blocks with a Mastery Criteria field found.", None, 0.0
    if not problems:
        return "pass", f"None of the {total} goal(s)' Mastery Criteria use a zero/near-zero endpoint phrasing.", None, 0.85
    if len(problems) == 1:
        page, detail = problems[0]
        return "fail", detail, page, 0.85
    evidence = [{"page": page, "detail": detail} for page, detail in problems]
    return "fail", evidence, None, 0.85


def _check_SM02(rule: dict, fields: dict) -> tuple:
    per_day_hits = re.findall(r"\d+(?:\.\d+)?\s*hours?\s*per\s*day\b", fields["full_text"], re.IGNORECASE)
    if per_day_hits:
        return (
            "fail",
            f"Found {len(per_day_hits)} hours value(s) expressed 'per day' instead of "
            f"'per week': {per_day_hits}.",
            None, 0.7,
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
    text = fields["full_text"]
    vals = []
    for m in re.finditer(r"(?:Certification|Provider Credentials):[ \t]*([^\n]+)", text):
        v = m.group(1).strip()
        if v:
            vals.append(v)
    if not vals:
        return "not_checkable", "No 'Certification:' or 'Provider Credentials:' field found.", None, 0.0
    normalized = {v.lower() for v in vals}
    if len(normalized) == 1:
        return "pass", f"All {len(vals)} credential mention(s) consistently read {vals[0]!r}.", None, 0.85
    return "fail", f"Inconsistent credential designations found across the document: {vals}.", None, 0.85


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
    text = fields["full_text"]
    dob_vals = sorted({m.group(1).strip() for m in re.finditer(r"DOB:[ \t]*([0-9/]+)", text)})
    age_vals = sorted({m.group(1).strip() for m in re.finditer(r"Patient Age:[ \t]*([0-9]+)", text)})

    if not dob_vals and not age_vals:
        return "not_checkable", "No DOB or Patient Age field found.", None, 0.0

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
        return "fail", " ".join(problems), None, 0.8
    return (
        "pass",
        f"DOB ({dob_vals[0] if dob_vals else 'n/a'}) and Patient Age ({age_vals[0] if age_vals else 'n/a'}) "
        f"are consistent throughout the document.",
        None, 0.8,
    )


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
    """
    text = fields["full_text"]
    names = [
        m.group(1).strip()
        for m in re.finditer(r"Patient Name:[ \t]*([^\n]+?)(?=\s*(?:AKA:|Patient DOB:|$))", text)
    ]
    names = [n for n in names if n]
    if not names:
        return "not_checkable", "No 'Patient Name:' field found.", None, 0.0
    normalized = {n.lower() for n in names}
    if len(normalized) == 1:
        return "pass", f"Patient name spelled consistently as {names[0]!r} across all {len(names)} mention(s).", None, 0.85
    counts = Counter(names)
    return "fail", f"Inconsistent patient name spelling found: {dict(counts)}.", None, 0.85


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
    text = fields["full_text"]
    npi_vals = sorted({m.group(1).strip() for m in re.finditer(r"NPI:[ \t]*([0-9]+)", text)})
    license_vals = sorted({m.group(1).strip() for m in re.finditer(r"License[^\n:]*:[ \t]*([^\n]+)", text)})

    if not npi_vals and not license_vals:
        return "not_checkable", "No NPI or License field found.", None, 0.0

    problems = []
    if len(npi_vals) > 1:
        problems.append(f"Multiple different NPI values found: {npi_vals}.")
    if len(license_vals) > 1:
        problems.append(f"Multiple different License values found: {license_vals}.")

    supporting_npi_field = (fields.get("supporting_doc") or {}).get("bcba_credentials_npi")
    ground_truth_npi_vals: set[str] = set()
    if supporting_npi_field and supporting_npi_field.get("confidence") != "none" and supporting_npi_field.get("value"):
        ground_truth_npi_vals = {m.group(0) for m in re.finditer(r"[0-9]{10}", supporting_npi_field["value"])}
    if ground_truth_npi_vals and npi_vals and not (set(npi_vals) & ground_truth_npi_vals):
        problems.append(
            f"TP states NPI {npi_vals}, but the supporting document's BCBA "
            f"credentials/NPI field states {sorted(ground_truth_npi_vals)} -- these do not match."
        )

    if problems:
        return "fail", " ".join(problems), None, 0.8
    if ground_truth_npi_vals and npi_vals and (set(npi_vals) & ground_truth_npi_vals):
        return (
            "pass",
            f"NPI ({npi_vals or 'n/a'}) and License ({license_vals or 'n/a'}) are internally "
            f"consistent, AND the TP's NPI matches the supporting document's stated NPI "
            f"({sorted(ground_truth_npi_vals)}).",
            None, 0.9,
        )
    return (
        "pass",
        f"NPI ({npi_vals or 'n/a'}) and License ({license_vals or 'n/a'}) are consistent "
        f"(no contradicting values found).",
        None, 0.8,
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
    text = fields["full_text"]
    ratings = [(m.group(0).split(":")[0].strip(), m.group(1).strip()) for m in _SEVERITY_LABEL_PATTERN.finditer(text)]
    if not ratings:
        return "not_checkable", "No 'Severity of ...:' rating fields found.", None, 0.0

    non_na_values = [v for _, v in ratings if v.strip().lower() not in ("n/a", "na", "")]
    if not non_na_values:
        return "not_checkable", "Severity fields found but all are N/A.", None, 0.0

    has_non_mild = any(v.lower() in _NON_MILD_SEVERITY_VALUES for v in non_na_values)
    ratings_str = ", ".join(f"{label}: {value}" for label, value in ratings)
    if has_non_mild:
        return "pass", f"At least one severity rating is Moderate or higher ({ratings_str}).", None, 0.85
    return "fail", f"All severity ratings are Mild (or N/A) -- none reach Moderate: {ratings_str}.", None, 0.85

DET_CHECKS = {
    "QA-TEMP-05": _check_TEMP05,
    "QA-RPT-01": _check_RPT01,
    "QA-GIP-04": _check_GIP04,
    "HF-02": _check_HF02,
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
    "QA-RPT-06": _check_RPT06,
    "QA-SIG-02": _check_SIG02,
    "QA-SIG-03": _check_SIG03,
    "QA-SIG-04": _check_SIG04,
    "QA-HRS-02": _check_HRS02,
    "QA-HRS-03": _check_HRS03,
    # Round 63, item 3: real deterministic schedule-table arithmetic,
    # replacing the judgment layer's eyeballed (and confirmed wrong) totals
    # -- see pipeline/schedule_hours.py and _check_SCH01/_check_SCH07's own
    # docstrings.
    "QA-SCH-01": _check_SCH01,
    "QA-SCH-07": _check_SCH07,
    # Round 63, item 5: deterministic pre-check only, for the confirmed
    # objective violation (embedded reviewer comment counted as evidence)
    # -- see _check_PROB02's own docstring for why this escalates to
    # judgment for the real semantic alignment question.
    "QA-PROB-02": _check_PROB02,
    # Round 64, item 3: real highlight detection via PyMuPDF (annotation
    # objects + a flattened-fill fallback), replacing the judgment layer's
    # text-only read, which structurally can never see highlight data at
    # all -- see _check_TEMP03's own docstring for the real investigation.
    "QA-TEMP-03": _check_TEMP03,
    "QA-COC-04": _check_COC04,
    "QA-BIO-02": _check_BIO02,
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
    "EMB-01": _check_HF02,  # generic CPT-hour-cap check, reused via params
    "AET-01": _check_AET01,
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
    "QA-TEMP-01": _check_TEMP01,
    "QA-PPI-02": _check_PPI02,
    "QA-PPI-03": _check_PPI03,
    "QA-PPI-05": _check_PPI05,
    "QA-BIP-01": _check_severity_rating_not_all_mild,
    "QA-GIP-03": _check_severity_rating_not_all_mild,
    # Item 2 (2026-07-28 round 3): the presence half of "increase in hours
    # -> rationale in place", fully deterministic -- see _check_HRS06's
    # docstring for why this does NOT resolve Charny's original flagged
    # miss (a structurally different, reviewer-annotation-based issue).
    "QA-HRS-06": _check_HRS06,
    # Item 4 (2026-07-28 round 3): diagnosed as a real, previously-unfixed
    # bug, not related to the earlier schema-reorder fix -- see
    # _check_ACF07's own docstring for the full real-evidence diagnosis.
    "QA-ACF-07": _check_ACF07,
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
