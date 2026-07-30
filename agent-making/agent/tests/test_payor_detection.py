"""Synthetic-only coverage for payor detection and payor-scope filtering —
no live document, no live API, per the standing rule. Uses the real
rules.json so counts are checked against the actual rule set, not a
fabricated stand-in.

Four distinct payor-specific groups exist now: Healthfirst's HF-01/02/03,
Straight Medicaid's SM-01/02, Aetna's AET-01, and Empire's EMP-01/02/03
(Emblem's EMB-01 too). A rule scoped to one of them is `not_applicable`
for every OTHER known payor (including each other) — e.g. a Molina-labeled
doc excludes all of them, not just Healthfirst's.
"""
import json
from pathlib import Path

from pipeline.fields import _detect_payor, partition_rules_by_scope

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
ACTIVE_RULES = [r for r in RULES if r.get("active", True)]
N_ACTIVE = len(ACTIVE_RULES)
N_UNIVERSAL = sum(1 for r in ACTIVE_RULES if r["applies_to_payor"] == "ALL")
HEALTHFIRST_ONLY_IDS = {"HF-01", "HF-02", "HF-03"}
STRAIGHT_MEDICAID_ONLY_IDS = {"SM-01", "SM-02"}
AETNA_ONLY_IDS = {"AET-01"}
EMBLEM_ONLY_IDS = {"EMB-01"}
EMPIRE_ONLY_IDS = {"EMP-01", "EMP-02", "EMP-03"}
# Every payor-specific rule id, regardless of which payor it belongs to —
# this is what gets excluded (not_applicable) for any OTHER known payor.
ALL_PAYOR_SPECIFIC_IDS = (
    HEALTHFIRST_ONLY_IDS | STRAIGHT_MEDICAID_ONLY_IDS
    | AETNA_ONLY_IDS | EMBLEM_ONLY_IDS | EMPIRE_ONLY_IDS
)
assert N_ACTIVE == N_UNIVERSAL + len(ALL_PAYOR_SPECIFIC_IDS), (
    "a new payor-specific rule was added without updating this test file's "
    "assumptions about the rule set's shape"
)


def _pages(page1_text: str) -> list[dict]:
    return [{"page_number": 1, "text": page1_text}]


# --- _detect_payor: reading the "Patient Payor:" line ---

def test_detect_payor_healthfirst():
    assert _detect_payor(_pages("Treatment Plan\nPatient Payor: Healthfirst\n...")) == "Healthfirst"


def test_detect_payor_molina_with_trailing_plan_detail():
    assert _detect_payor(_pages("Patient Payor: Molina Healthcare - Medicaid\n...")) == "Molina"


def test_detect_payor_mvp():
    assert _detect_payor(_pages("Patient Payor: MVP Health Care\n...")) == "MVP"


def test_detect_payor_new_york_medicaid():
    assert _detect_payor(_pages("Patient Payor: New York Medicaid\n...")) == "New York Medicaid"


def test_detect_payor_new_york_state_medicaid_variant():
    assert _detect_payor(_pages("Patient Payor: New York State Medicaid\n...")) == "New York Medicaid"


def test_detect_payor_ny_medicaid_abbreviation():
    assert _detect_payor(_pages("Patient Payor: NY Medicaid\n...")) == "New York Medicaid"


def test_detect_payor_straight_medicaid():
    assert _detect_payor(_pages("Patient Payor: Straight Medicaid\n...")) == "Straight Medicaid"


def test_detect_payor_anthem():
    assert _detect_payor(_pages("Patient Payor: Anthem\n...")) == "Anthem"


def test_detect_payor_cigna():
    assert _detect_payor(_pages("Patient Payor: Cigna\n...")) == "Cigna"


def test_detect_payor_aetna():
    assert _detect_payor(_pages("Patient Payor: Aetna\n...")) == "Aetna"


def test_detect_payor_emblem():
    assert _detect_payor(_pages("Patient Payor: Emblem\n...")) == "Emblem"


def test_detect_payor_empire():
    assert _detect_payor(_pages("Patient Payor: Empire\n...")) == "Empire"


def test_detect_payor_unrecognized_string_returns_unknown_explicitly():
    assert _detect_payor(_pages("Patient Payor: Acme Insurance Co.\n...")) == "Unknown"


def test_detect_payor_no_label_at_all_returns_unknown():
    assert _detect_payor(_pages("Treatment Plan\nNo payor field on this page.")) == "Unknown"


def test_detect_payor_no_pages_returns_unknown():
    assert _detect_payor([]) == "Unknown"


def test_detect_payor_never_returns_none():
    """The whole point of "Unknown" as an explicit value: nothing downstream
    should ever have to handle a bare None from this function."""
    for text in ["", "Patient Payor:", "random unrelated text", "Patient Payor: ???"]:
        result = _detect_payor(_pages(text))
        assert result is not None
        assert isinstance(result, str)


# --- partition_rules_by_scope: the three payor cases ---

def test_healthfirst_labeled_doc_gets_universal_plus_its_own_three_rules():
    """Not "all active rules" anymore now that other payors also have their
    own payor-specific rules — a Healthfirst-labeled doc gets universal
    + HF-01/02/03, and correctly excludes every other payor's rules as
    not_applicable."""
    fields = {"plan_type": None, "payor": "Healthfirst"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    applicable_ids = {r["rule_id"] for r in applicable}
    assert HEALTHFIRST_ONLY_IDS <= applicable_ids
    assert len(applicable) == N_UNIVERSAL + len(HEALTHFIRST_ONLY_IDS)
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - HEALTHFIRST_ONLY_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_molina_labeled_doc_gets_universal_rules_and_marks_other_payors_rules_not_applicable():
    fields = {"plan_type": None, "payor": "Molina"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)

    assert len(applicable) == N_UNIVERSAL
    assert all(r["applies_to_payor"] == "ALL" for r in applicable)

    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    for rule_id, finding in excluded.items():
        assert finding["result"] == "not_applicable"
        assert "Molina" in finding["evidence"]


def test_mvp_labeled_doc_same_shape_as_molina():
    fields = {"plan_type": None, "payor": "MVP"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_new_york_medicaid_labeled_doc_same_shape_as_molina():
    """Same treatment as Molina/MVP: universal rules run, every OTHER
    payor's payor-specific rules are not_applicable (not_checkable is
    reserved for a genuinely undetected payor, which this is not)."""
    fields = {"plan_type": None, "payor": "New York Medicaid"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    for finding in excluded.values():
        assert finding["result"] == "not_applicable"
        assert "New York Medicaid" in finding["evidence"]


def test_straight_medicaid_labeled_doc_gets_universal_plus_its_own_two_rules():
    """Unlike Molina/MVP/NY Medicaid, Straight Medicaid genuinely has
    payor-specific content (SM-01/SM-02) — so its applicable set is
    universal + those 2, while Healthfirst's HF-01/02/03 are still
    correctly excluded as not_applicable (this payor isn't Healthfirst)."""
    fields = {"plan_type": None, "payor": "Straight Medicaid"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)

    applicable_ids = {r["rule_id"] for r in applicable}
    assert STRAIGHT_MEDICAID_ONLY_IDS <= applicable_ids
    assert len(applicable) == N_UNIVERSAL + len(STRAIGHT_MEDICAID_ONLY_IDS)

    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - STRAIGHT_MEDICAID_ONLY_IDS
    for finding in excluded.values():
        assert finding["result"] == "not_applicable"
        assert "Straight Medicaid" in finding["evidence"]


def test_anthem_labeled_doc_same_shape_as_molina():
    fields = {"plan_type": None, "payor": "Anthem"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_cigna_labeled_doc_same_shape_as_molina():
    fields = {"plan_type": None, "payor": "Cigna"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_aetna_labeled_doc_gets_universal_plus_its_own_rule():
    fields = {"plan_type": None, "payor": "Aetna"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    applicable_ids = {r["rule_id"] for r in applicable}
    assert AETNA_ONLY_IDS <= applicable_ids
    assert len(applicable) == N_UNIVERSAL + len(AETNA_ONLY_IDS)
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - AETNA_ONLY_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_emblem_labeled_doc_gets_universal_plus_its_own_rule():
    fields = {"plan_type": None, "payor": "Emblem"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    applicable_ids = {r["rule_id"] for r in applicable}
    assert EMBLEM_ONLY_IDS <= applicable_ids
    assert len(applicable) == N_UNIVERSAL + len(EMBLEM_ONLY_IDS)
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - EMBLEM_ONLY_IDS


def test_empire_labeled_doc_gets_universal_plus_its_own_three_rules():
    """Includes EMP-02, which has no real checker yet (flagged, see its own
    blocked_status) — it still belongs in the applicable set for scope
    purposes; it'll just always come back not_checkable via the same
    no-checker fallback as the other flagged rules."""
    fields = {"plan_type": None, "payor": "Empire"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    applicable_ids = {r["rule_id"] for r in applicable}
    assert EMPIRE_ONLY_IDS <= applicable_ids
    assert len(applicable) == N_UNIVERSAL + len(EMPIRE_ONLY_IDS)
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - EMPIRE_ONLY_IDS


def test_unknown_payor_doc_gets_universal_rules_and_marks_payor_specific_not_checkable():
    """The explicit "Unknown" case from item 2: not the same as not_applicable
    — we don't know either payor-specific group's rules don't apply, we
    just couldn't confirm either way."""
    fields = {"plan_type": None, "payor": "Unknown"}
    applicable, excluded = partition_rules_by_scope(RULES, fields)

    assert len(applicable) == N_UNIVERSAL
    assert all(r["applies_to_payor"] == "ALL" for r in applicable)

    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    for rule_id, finding in excluded.items():
        assert finding["result"] == "not_checkable", (
            "an unknown payor must not silently mark a payor-specific rule "
            "not_applicable — that would assert something we don't know"
        )
        assert finding["confidence"] == 0.0
        assert "could not be detected" in finding["evidence"]


def test_unknown_and_healthfirst_produce_different_results_for_the_same_rules():
    """Guards against the two cases collapsing into each other by accident."""
    _, excluded_unknown = partition_rules_by_scope(RULES, {"plan_type": None, "payor": "Unknown"})
    _, excluded_known_mismatch = partition_rules_by_scope(RULES, {"plan_type": None, "payor": "Molina"})

    for rule_id in ALL_PAYOR_SPECIFIC_IDS:
        assert excluded_unknown[rule_id]["result"] == "not_checkable"
        assert excluded_known_mismatch[rule_id]["result"] == "not_applicable"


# --- End-to-end within fields.py: _detect_payor's output feeding partition_rules_by_scope ---

def test_detected_molina_payor_flows_through_to_correct_scoping():
    detected = _detect_payor(_pages("Patient Payor: Molina Healthcare - Medicaid\n..."))
    fields = {"plan_type": None, "payor": detected}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_detected_new_york_medicaid_flows_through_to_correct_scoping():
    detected = _detect_payor(_pages("Patient Payor: New York Medicaid\n..."))
    assert detected == "New York Medicaid"
    fields = {"plan_type": None, "payor": detected}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    assert len(applicable) == N_UNIVERSAL
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_detected_straight_medicaid_flows_through_to_correct_scoping():
    detected = _detect_payor(_pages("Patient Payor: Straight Medicaid\n..."))
    assert detected == "Straight Medicaid"
    fields = {"plan_type": None, "payor": detected}
    applicable, excluded = partition_rules_by_scope(RULES, fields)
    applicable_ids = {r["rule_id"] for r in applicable}
    assert STRAIGHT_MEDICAID_ONLY_IDS <= applicable_ids
    assert set(excluded.keys()) == ALL_PAYOR_SPECIFIC_IDS - STRAIGHT_MEDICAID_ONLY_IDS
    assert all(f["result"] == "not_applicable" for f in excluded.values())


def test_detected_unrecognized_payor_flows_through_to_not_checkable_scoping():
    detected = _detect_payor(_pages("Patient Payor: Some New Payor We've Never Heard Of\n..."))
    assert detected == "Unknown"
    fields = {"plan_type": None, "payor": detected}
    _, excluded = partition_rules_by_scope(RULES, fields)
    assert all(f["result"] == "not_checkable" for f in excluded.values())
