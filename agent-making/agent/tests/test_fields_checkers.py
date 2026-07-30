"""Locked-in regression coverage for every checker in fields.DET_CHECKS —
written and run green against the implementation before any further changes
touched this file's logic (see the accompanying request: "lock that in
before touching anything else"). Checker signature was then refactored from
checker(fields) to checker(rule, fields) (business constants moved out of
Python into rule["params"]) — call sites below were updated to match that
mechanical change, but every assertion is untouched from the original
locked-in baseline.

Note on scope: fields.py currently has 7 deterministic rule_ids / 6 unique
checker functions (TEMP-05, RPT-01, GIP-04, HF-02, TRANS-02+DISC-02 sharing
one function, OBS-01) — not 14. Seven originally-implemented checkers were
reclassified to check_type "judgment" and removed from this module across
two rounds: TEMP-02, PREF-01, BIP-06, SIG-01, SIG-05, COC-06 (their real
evidence lives on image-only pages this module has no access to), and SCH-08
(not an image-page problem — three rounds of point-fixes each closed one
false-match pattern in the POS-field regex and missed the next one, which is
itself the signal the extraction approach was unreliable; see
pipeline/CHECKER_DESIGN.md for the full history). There is no deterministic
checker left to test for any of these seven — they're judgment-layer now,
tested against the live model instead. Flagging this rather than fabricating
tests for code that no longer exists. Every rule_id in rules.json now
carries a scope-accurate namespace prefix — "QA-" for the 111 universal
rules (e.g. "QA-TEMP-05"), a payor's own prefix ("HF-01"/"HF-02"/"HF-03")
for the 3 genuinely Healthfirst-specific ones. These tests call the checker
functions directly with minimal stub rule dicts, so they're unaffected by
that rename and don't reference real rule_id strings.
"""
from pipeline import fields


def _fields(*page_texts: str) -> dict:
    """Minimal fields dict shaped like extract_fields()'s output — just the
    two keys every checker actually reads (pages, full_text)."""
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def _rule(params: dict | None = None) -> dict:
    """Minimal rule dict — only params is ever read by a checker."""
    return {"params": params or {}}


HF02_RULE = _rule({"max_hours": 5, "cpt_code": "97151"})


# --- TEMP-05: 'RBT' must read 'RBT/BT' or 'BT' ---

def test_temp05_pass_when_already_rbt_bt():
    result, evidence, page, confidence = fields._check_TEMP05(_rule(), _fields("Services provided by RBT/BT staff."))
    assert result == "pass"


def test_temp05_fail_on_bare_rbt():
    result, evidence, page, confidence = fields._check_TEMP05(_rule(), _fields("An RBT will provide services."))
    assert result == "fail"
    assert "RBT" in evidence


# --- RPT-01: blank-field heuristic ---

def test_rpt01_pass_when_labels_filled():
    result, evidence, page, confidence = fields._check_RPT01(_rule(), _fields("Diagnosis:\nAutism Spectrum Disorder"))
    assert result == "pass"


def test_rpt01_fail_on_blank_label():
    result, evidence, page, confidence = fields._check_RPT01(_rule(), _fields("Diagnosis:\n\nNext Section:"))
    assert result == "fail"
    assert page == 1
    assert isinstance(evidence, str), "single blank page must stay a plain string, not the list form"


def test_rpt01_fail_on_multiple_blank_pages_uses_list_form():
    result, evidence, page, confidence = fields._check_RPT01(
        _rule(),
        _fields("Diagnosis:\n\nNext:", "Goals:\n\nNext:"),
    )
    assert result == "fail"
    assert page is None, "page must be null when evidence is the multi-page list form"
    assert isinstance(evidence, list)
    assert {item["page"] for item in evidence} == {1, 2}


# --- GIP-04: literal 'Invalid Date' string ---

def test_gip04_pass_when_no_invalid_date_string():
    result, evidence, page, confidence = fields._check_GIP04(_rule(), _fields("Mastery date: 01/02/2026."))
    assert result == "pass"


def test_gip04_fail_on_invalid_date_string():
    result, evidence, page, confidence = fields._check_GIP04(_rule(), _fields("Mastery date: Invalid Date"))
    assert result == "fail"


# SCH-08's deterministic checker (and its regex-fix history: mid-word
# matches -> a blank field bleeding into the next label -> a third
# unresolved case) is gone — reclassified to judgment. No test here; see
# the module docstring and pipeline/CHECKER_DESIGN.md.


# --- HF-02: CPT hours must not exceed the rule's configured cap ---
# Bug regression: boundary must be inclusive (<=cap passes, cap+1 fails).

def test_hf02_boundary_five_hours_passes():
    result, evidence, page, confidence = fields._check_HF02(HF02_RULE, _fields("97151: 5 hrs requested."))
    assert result == "pass", evidence


def test_hf02_boundary_six_hours_fails():
    result, evidence, page, confidence = fields._check_HF02(HF02_RULE, _fields("97151: 6 hrs requested."))
    assert result == "fail", evidence


def test_hf02_not_applicable_when_no_97151_mention():
    result, evidence, page, confidence = fields._check_HF02(HF02_RULE, _fields("No assessment hours requested."))
    assert result == "not_applicable"


def test_hf02_reads_cap_from_rule_params_not_a_python_literal():
    """A different cap/CPT code in rule["params"] must change the outcome —
    proving the 5-hour cap and '97151' are no longer hardcoded in Python."""
    custom_rule = _rule({"max_hours": 10, "cpt_code": "97155"})
    result, evidence, page, confidence = fields._check_HF02(custom_rule, _fields("97155: 8 hrs requested."))
    assert result == "pass", evidence
    result, evidence, page, confidence = fields._check_HF02(custom_rule, _fields("97155: 11 hrs requested."))
    assert result == "fail", evidence


# --- OBS-01: observation section present ---

def test_obs01_pass_when_observation_section_present():
    result, evidence, page, confidence = fields._check_OBS01(_rule(), _fields("Patient Observation: completed 01/02/2026."))
    assert result == "pass"


def test_obs01_fail_when_no_observation_section():
    result, evidence, page, confidence = fields._check_OBS01(_rule(), _fields("No relevant section here."))
    assert result == "fail"


# --- needs_escalation: confidence/uncertain/not_checkable routing ---

def test_needs_escalation_true_for_uncertain():
    assert fields.needs_escalation({"result": "uncertain", "confidence": 0.9}) is True


def test_needs_escalation_true_for_not_checkable():
    assert fields.needs_escalation({"result": "not_checkable", "confidence": None}) is True


def test_needs_escalation_true_for_low_confidence():
    assert fields.needs_escalation({"result": "pass", "confidence": 0.5}) is True


def test_needs_escalation_false_for_confident_pass():
    assert fields.needs_escalation({"result": "pass", "confidence": 0.9}) is False


def test_needs_escalation_boundary_not_less_than_threshold_does_not_escalate():
    assert fields.needs_escalation({"result": "pass", "confidence": 0.6}) is False
