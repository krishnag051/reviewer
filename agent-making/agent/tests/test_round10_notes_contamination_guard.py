"""Fix Round 10 structural safeguard: judge.py::_build_prompt sends a
rule's `notes` field verbatim into the judgment prompt on every
escalation (see that function's own `"notes": r.get("notes")` line). This
round's audit found the same failure class QA-BAR-01 hit already
(round-by-round history text repeating a numeric threshold/wording that
was later removed from the rule's own real logic, which the model then
read as if it were still the active criterion) recurring across ~19 more
rules.

This is a permanent guard against the SAME class recurring silently in a
future round: it fails the suite the moment any rule's `notes` field
starts accumulating one of the confirmed-dangerous phrasings again, so
the next round that adds a "Fix Round: found X was stale, removed it"
paragraph gets caught immediately by CI/the test suite, not three rounds
later on a real document.

This does NOT catch every possible contamination shape (that would need
real semantic judgment this test suite can't run) -- it's a real,
zero-cost pattern check on the specific phrasings this engagement has
already confirmed are dangerous, not a claim of completeness.
"""
import json
import re
from pathlib import Path

_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "rules.json"

# Same signal set the Round 10 audit used to find the 45 originally-flagged
# rules, minus the ones confirmed benign (self-consistent history ending in
# a current, accurate statement) -- see this round's own report for the
# full audited list and per-rule verdicts.
_CONTAMINATION_SIGNAL_RE = re.compile(
    r"no longer accurate|no longer applies|no longer matches|doesn.t match the (?:current|actual|real)|"
    r"NEVER actually reverted|genuinely removed(?! entirely per)|"
    r"Old check_type/logic kept as-is|"
    r"THIS NOTE WAS STALE|this note was stale",
    re.IGNORECASE,
)


def _load_rules() -> list[dict]:
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))["rules"]


def test_no_rule_notes_field_contains_a_confirmed_dangerous_phrasing():
    rules = _load_rules()
    offenders = []
    for r in rules:
        notes = r.get("notes") or ""
        if _CONTAMINATION_SIGNAL_RE.search(notes):
            offenders.append(r["rule_id"])
    assert not offenders, (
        f"These rule_ids' notes fields contain a phrasing this engagement has already confirmed can mislead "
        f"a live judgment call (see QA-BAR-01's Round 9 fix and Round 10's full audit): {offenders}. "
        f"Rewrite the notes field to state only the current, real criterion -- do not leave stale history "
        f"describing what USED to be true if it no longer is."
    )


def test_notes_check_type_parenthetical_matches_the_rule_s_actual_check_type():
    """The specific real contradiction Round 10 found (QA-HRS-07): a notes
    field explicitly stating '(judgment)'/'(deterministic)' that no longer
    matches the rule's own current check_type field. Catches this exact
    shape recurring on any rule, not just the one it was found on.
    """
    rules = _load_rules()
    pat = re.compile(r"check_type/logic kept as-is \(([a-z]+)\)", re.IGNORECASE)
    mismatches = []
    for r in rules:
        notes = r.get("notes") or ""
        m = pat.search(notes)
        if m and m.group(1).lower() != r["check_type"].lower():
            mismatches.append((r["rule_id"], m.group(1), r["check_type"]))
    assert not mismatches, f"notes claims a different check_type than the rule's real current one: {mismatches}"
