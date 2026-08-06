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

from pypdf import PdfReader

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
    if re.search(r"invalid date", fields["full_text"], re.IGNORECASE):
        m = re.search(r"invalid date", fields["full_text"], re.IGNORECASE)
        page = next((p["page_number"] for p in fields["pages"] if "invalid date" in p["text"].lower()), None)
        return "fail", "Literal 'Invalid Date' string found in a mastery date field.", page, 0.9
    return "pass", "No literal 'Invalid Date' strings found.", None, 0.75


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
    text = fields["full_text"]
    m = re.search(
        r"Assessment of Current Functioning:([\s\S]{0,30000}?)(?:Goal Progress:|Clinical Interpretation|Areas of Focus)",
        text,
    )
    if not m:
        return "not_checkable", "No 'Assessment of Current Functioning:' section found.", None, 0.0
    section = m.group(1)

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

    tool_mentions = []
    seen = set()
    for tm in _ACF07_TOOL_PATTERN.finditer(section):
        name = tm.group(0)
        key = name.lower().replace("-3", "").replace("-r", "")
        if key in seen:
            continue
        seen.add(key)
        tool_mentions.append((name, tm.start()))

    if not tool_mentions:
        return (
            "fail",
            "No named testing tool (e.g. ABLLS-R, Vineland, VB-MAPP, AFLS) found in the "
            "Assessment of Current Functioning section.",
            None, 0.75,
        )

    undated = []
    for name, pos in tool_mentions:
        window = section[max(0, pos - 400):pos + 400]
        has_date = re.search(r"Assessment Date:[ \t]*\d{1,2}/\d{1,2}/\d{4}", window) is not None
        has_open_question = re.search(r"\bWhat was the date of administration\b", window, re.IGNORECASE) is not None
        if not has_date or has_open_question:
            undated.append(name)

    if undated:
        return "fail", f"Testing tool(s) mentioned without a confirmed administration date: {undated}.", None, 0.75
    if len(tool_mentions) < 2:
        return (
            "uncertain",
            f"Only one testing tool found ({tool_mentions[0][0]}) -- cannot confirm both an "
            f"old and new testing tool are present.",
            None, 0.4,
        )
    return "pass", f"Testing tools found with dates: {[n for n, _ in tool_mentions]}.", None, 0.8


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
