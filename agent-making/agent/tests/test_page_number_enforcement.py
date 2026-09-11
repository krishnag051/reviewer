"""Fix Round (2026-09-11), item 3 -- REAL, structural enforcement of page
numbers on every finding with real evidence behind it, replacing what was
previously only a prompt-text convention the model could (and confirmed
live, sometimes did) skip by returning page=null "as a last resort."

The one legitimate exception, per ma'am's own clarification: "Not
checkable" (or "Not applicable") when the underlying data genuinely
doesn't exist anywhere in the document -- nothing real to cite a page
for. That's now a real, checkable claim (`nothing_relevant_found_anywhere`
in FINDINGS_TOOL's schema), not an inferred default -- a model reaching
for null out of convenience can no longer satisfy the gate silently; it
has to explicitly claim nothing relevant exists, which is itself a
specific, false-if-wrong statement.

Fix Round (2026-09-11 evening) -- REAL REGRESSION FOUND AND FIXED, this
file rewritten accordingly: a missing-page finding used to be DROPPED
entirely from the returned dict, which made it look identical to a
rule_id the model never answered at all -- integrity.py's retry-then-
not_checkable exhaustion path couldn't tell the two apart, so a rule that
kept reaffirming a real Pass/Fail/Uncertain answer, just never with a
page, eventually got its real judgment thrown away and replaced with a
guessed "not_checkable". Confirmed live on a real document run (see
integrity.py's own module docstring for the exact rule_ids). Fixed:
`_findings_dict_from_list` now KEEPS a missing-page-but-otherwise-valid
finding in the dict (page=None), flagged `page_unresolved: True` so
integrity.py's separate page-recovery pass can still try for a real page
without ever risking the answer itself being discarded. Every test below
now asserts "kept, page=None, flagged" instead of the old "dropped".

Zero real API spend -- tests the pure parsing/validation function directly.
"""
from pipeline import judge


def _finding(rule_id, result, page=None, nothing_relevant_found_anywhere=None, evidence_supports_result=True):
    f = {
        "rule_id": rule_id,
        "result": result,
        "evidence": "some evidence",
        "page": page,
        "confidence": 0.8,
        "evidence_supports_result": evidence_supports_result,
    }
    if nothing_relevant_found_anywhere is not None:
        f["nothing_relevant_found_anywhere"] = nothing_relevant_found_anywhere
    return f


def test_pass_with_no_page_is_kept_and_flagged_for_page_recovery():
    """pass/fail/uncertain always came from real evidence -- the answer
    itself is never discarded for lacking a page; it's kept and flagged
    for integrity.py's separate page-recovery retry instead."""
    findings = judge._findings_dict_from_list([_finding("A-1", "pass", page=None)])
    assert "A-1" in findings
    assert findings["A-1"]["result"] == "pass"
    assert findings["A-1"]["page"] is None
    assert findings["A-1"]["page_unresolved"] is True


def test_fail_with_no_page_is_kept_and_flagged_for_page_recovery():
    findings = judge._findings_dict_from_list([_finding("A-1", "fail", page=None)])
    assert "A-1" in findings
    assert findings["A-1"]["result"] == "fail"
    assert findings["A-1"]["page_unresolved"] is True


def test_uncertain_with_no_page_is_kept_and_flagged_for_page_recovery():
    findings = judge._findings_dict_from_list([_finding("A-1", "uncertain", page=None)])
    assert "A-1" in findings
    assert findings["A-1"]["result"] == "uncertain"
    assert findings["A-1"]["page_unresolved"] is True


def test_pass_fail_uncertain_with_a_real_page_are_accepted_unflagged():
    findings = judge._findings_dict_from_list([
        _finding("A-1", "pass", page=3),
        _finding("A-2", "fail", page=7),
        _finding("A-3", "uncertain", page=[2, 4]),
    ])
    assert set(findings) == {"A-1", "A-2", "A-3"}
    for rid in findings:
        assert "page_unresolved" not in findings[rid]


def test_evidence_as_page_detail_list_is_exempt_even_with_a_null_top_level_page():
    """Fix Round (2026-09-11 evening) -- REAL LATENT BUG FOUND AND FIXED:
    FINDINGS_TOOL's own schema requires a null top-level `page` when
    evidence is the {page, detail} multi-page list form (each item
    already carries its own page) -- the original page-enforcement never
    accounted for this and would have wrongly flagged a legitimate
    multi-page finding as unresolved."""
    raw = _finding("A-1", "fail", page=None)
    raw["evidence"] = [{"page": 4, "detail": "x"}, {"page": 6, "detail": "y"}]
    findings = judge._findings_dict_from_list([raw])
    assert "A-1" in findings
    assert "page_unresolved" not in findings["A-1"]


def test_not_checkable_with_no_page_and_nothing_relevant_found_is_accepted_unflagged():
    """The one legitimate exception: genuinely nothing to cite."""
    findings = judge._findings_dict_from_list([
        _finding("A-1", "not_checkable", page=None, nothing_relevant_found_anywhere=True),
    ])
    assert "A-1" in findings
    assert findings["A-1"]["result"] == "not_checkable"
    assert "page_unresolved" not in findings["A-1"]


def test_not_applicable_with_no_page_and_nothing_relevant_found_is_accepted_unflagged():
    findings = judge._findings_dict_from_list([
        _finding("A-1", "not_applicable", page=None, nothing_relevant_found_anywhere=True),
    ])
    assert "A-1" in findings
    assert "page_unresolved" not in findings["A-1"]


def test_not_checkable_with_no_page_and_relevant_data_partially_found_is_flagged():
    """The real, confirmed distinction: "not_checkable" for a reason OTHER
    than "no data exists" (something was found but not fully resolved)
    still needs a page if a real location was referenced -- kept, but
    flagged for page-recovery, same as pass/fail/uncertain."""
    findings = judge._findings_dict_from_list([
        _finding("A-1", "not_checkable", page=None, nothing_relevant_found_anywhere=False),
    ])
    assert "A-1" in findings
    assert findings["A-1"]["page_unresolved"] is True


def test_not_checkable_missing_the_new_field_entirely_is_flagged():
    """A model that omits the new field altogether (rather than explicitly
    setting it) must not get the exception by default -- the absence of
    an affirmative claim is not itself a claim of 'nothing found'."""
    findings = judge._findings_dict_from_list([
        _finding("A-1", "not_checkable", page=None, nothing_relevant_found_anywhere=None),
    ])
    assert "A-1" in findings
    assert findings["A-1"]["page_unresolved"] is True


def test_not_checkable_with_a_real_page_is_accepted_regardless_of_the_flag():
    findings = judge._findings_dict_from_list([
        _finding("A-1", "not_checkable", page=5, nothing_relevant_found_anywhere=False),
    ])
    assert "A-1" in findings
    assert "page_unresolved" not in findings["A-1"]


def test_mixed_batch_keeps_everything_but_only_flags_the_ones_missing_a_page():
    findings = judge._findings_dict_from_list([
        _finding("GOOD-1", "pass", page=3),
        _finding("BAD-1", "fail", page=None),
        _finding("GOOD-2", "not_applicable", page=None, nothing_relevant_found_anywhere=True),
    ])
    assert set(findings) == {"GOOD-1", "BAD-1", "GOOD-2"}
    assert "page_unresolved" not in findings["GOOD-1"]
    assert findings["BAD-1"]["page_unresolved"] is True
    assert "page_unresolved" not in findings["GOOD-2"]


def test_evidence_supports_result_false_is_still_dropped_entirely():
    """The OTHER rejection mechanism -- a finding the model itself disowns
    -- is unrelated to page enforcement and still drops the finding
    entirely (retried as if missing, unchanged by this round's fix)."""
    findings = judge._findings_dict_from_list([
        _finding("A-1", "fail", page=3, evidence_supports_result=False),
    ])
    assert "A-1" not in findings
