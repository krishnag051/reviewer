"""Next Round, Part 3: one fixed, deterministic display/export order for a
rule_results list — used everywhere a rule list is shown or exported (the
review screen, the CSV download, and every Pass/Fail/Uncertain/N-A filtered
view, since those are all built client-side by filtering the SAME already-
sorted array this backend hands back from GET /uploads/:id).

Order, exactly as specified:
  1. This specific TP's payor-specific rules first — ONLY the actual
     detected payor's own rules (rule.payor == version.payor), not every
     payor's rules shown together. Determined from `Version.payor` (set
     at version-creation time for this specific patient/TP), matched
     against `Rule.payor` (rule_payor_enum) — the same field this backend
     already uses everywhere else a rule's payor-specificity matters.
  2. The "Template" category next.
  3. Every remaining category, in the one fixed order given verbatim below.

Sorting is a pure, stable Python sort (`list.sort`/`sorted` are guaranteed
stable) on a tuple key — ties within a bucket keep their prior relative
order (created_at, id, from the DB relationship's own order_by), so nothing
reshuffles between a fresh run and a re-download of the same upload's
results, as required.
"""

# Verbatim, in this exact order — anything not in this list (there
# shouldn't be anything, but a future rules.json category addition that
# forgets to land here first) sorts after everything named, rather than
# raising or silently disappearing.
_FIXED_CATEGORY_ORDER = [
    "Report Information",
    "Patient/Provider Info",
    "Hours Requesting",
    "School & ABA Schedule",
    "Biopsychosocial",
    "Problem Areas",
    "Observations",
    "Assessment of Current Functioning",
    "Clinical Interpretation",
    "Barriers to Treatment",
    "BIP",
    "Results of Preference Assessment",
    "Mastered Goals",
    "Goals in Progress",
    "Parent/Caregiver Involvement",
    "Coordination of Care",
    "Transition Plan",
    "Discharge Criteria",
    "Signatures",
    "Data Sheets",
    "AI-Generated Content & Template Artifacts",
]
_CATEGORY_RANK = {name: i for i, name in enumerate(_FIXED_CATEGORY_ORDER)}
# Anything genuinely unrecognized (shouldn't happen) sorts after every
# named category, never before or silently interleaved.
_UNKNOWN_CATEGORY_RANK = len(_FIXED_CATEGORY_ORDER)
_TEMPLATE_CATEGORY_RANK = -1  # sorts before every entry in _CATEGORY_RANK


def _category_rank(category: str) -> int:
    if category == "Template":
        return _TEMPLATE_CATEGORY_RANK
    return _CATEGORY_RANK.get(category, _UNKNOWN_CATEGORY_RANK)


def rule_result_sort_key(rule_result, payor: str | None) -> tuple:
    """Sort key for one rule_result. `payor` is this upload's version's own
    payor (None/no match means bucket 1 is simply empty — every rule falls
    through to bucket 2/3 as normal, never an error).
    """
    is_payor_specific_match = bool(payor) and rule_result.rule.payor == payor
    return (
        0 if is_payor_specific_match else 1,  # bucket 1: this TP's own payor-specific rules
        _category_rank(rule_result.category),  # bucket 2 (Template) / bucket 3 (fixed order)
    )


def sort_rule_results(rule_results: list, payor: str | None) -> list:
    """Stable sort — see module docstring. `rule_results` is left
    untouched; a new, sorted list is returned."""
    return sorted(rule_results, key=lambda rr: rule_result_sort_key(rr, payor))
