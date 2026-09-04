"""Fix Round: REAL production crash, confirmed live -- QA-PROB-01, a 2-of-3
tie-break majority vote (Round 93's own best-of-3 tie-breaker), returned one
of the three raw per-call finding dicts completely unvalidated. That call's
own `evidence` value was a dict, not the FINDINGS_TOOL schema's advertised
string -- crashed downstream in humanize.py's `_PAGE_TAG_RE.split(text)`
("TypeError: expected string or bytes-like object, got 'dict'"), discarding
the whole review's results after ~$1.17 of real spend already made on that
run.

Root cause: the schema is advisory to the model, not runtime-enforced on
the response side -- the exact same class of gap merge.py::
_format_page_display already found and fixed for the `page` field in an
earlier round. Three call sites in judge.py had this exposure (only one of
which actually crashed this time); merge.py::_explode_to_rows gets the same
defense-in-depth fix as its own `page` handling, as the last centralized
chokepoint for every check_type, not just judgment-layer ones.

No live document, no live API -- same convention as
test_judge_self_consistency.py.
"""
from pipeline import judge, merge


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


# --- judge.py::_coerce_evidence_to_string ------------------------------------


def test_coerce_evidence_to_string_passes_through_a_real_string():
    assert judge._coerce_evidence_to_string("a normal finding") == "a normal finding"


def test_coerce_evidence_to_string_extracts_detail_key_from_a_dict():
    assert judge._coerce_evidence_to_string({"page": 3, "detail": "the real finding text"}) == "the real finding text"


def test_coerce_evidence_to_string_falls_back_to_json_for_anything_else():
    result = judge._coerce_evidence_to_string({"weird": "shape", "no_detail_key": True})
    assert isinstance(result, str)
    assert "weird" in result  # a real, inspectable fallback, not a swallowed crash


# --- the exact crash site: _three_way_majority_finding's majority branch ----


def test_three_way_majority_finding_does_not_crash_on_a_dict_evidence_in_the_winning_call():
    """Reproduces the EXACT real crash shape: 2 of 3 calls agree
    (majority), and the winning entry (first() picks whichever matching
    call came first) has a dict for `evidence` instead of a string."""
    f = _finding("fail", evidence={"page": 12, "detail": "the model wrapped its answer oddly"})
    s = _finding("pass", evidence="a normal string")
    t = _finding("fail", evidence="also normal")
    result = judge._three_way_majority_finding(f, s, t)
    assert result["result"] == "fail"
    assert isinstance(result["evidence"], str)
    assert result["evidence"] == "the model wrapped its answer oddly"


def test_three_way_majority_finding_still_works_normally_with_all_strings():
    f = _finding("pass", "a")
    s = _finding("fail", "b")
    t = _finding("pass", "c")
    result = judge._three_way_majority_finding(f, s, t)
    assert result["result"] == "pass"
    assert result["evidence"] == "a"  # unchanged behavior: first matching entry wins, verbatim


def test_three_way_majority_finding_no_majority_still_stringifies_dict_evidence():
    f = _finding("pass", {"odd": "shape"})
    s = _finding("fail", "b")
    t = _finding("uncertain", "c")
    result = judge._three_way_majority_finding(f, s, t)
    assert result["result"] == "uncertain"
    assert "odd" in result["evidence"]


def test_two_way_uncertain_finding_still_handles_dict_evidence():
    f = _finding("pass", {"odd": "shape"})
    s = _finding("fail", "b")
    result = judge._two_way_uncertain_finding(f, s)
    assert result["result"] == "uncertain"
    assert "odd" in result["evidence"]


# --- run_judgment_checks's plain 2-call agreement path ----------------------


def test_run_judgment_checks_agreement_path_coerces_dict_evidence(monkeypatch):
    """Same exposure as the tie-break majority branch, just the OTHER call
    site that shares it (calls 1 and 2 agreeing outright, no tie-break
    needed at all)."""
    calls = []

    def fake_once(rules, fields, images, *, tracker, call_reason, model_override=None):
        calls.append(call_reason)
        return {"R-1": _finding("fail", evidence={"page": 4, "detail": "dict-shaped but agreeing"})}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    result = judge.run_judgment_checks([{"rule_id": "R-1"}], {}, {}, tracker=None)
    assert result["R-1"]["result"] == "fail"
    assert result["R-1"]["evidence"] == "dict-shaped but agreeing"
    assert len(calls) == 2  # confirms no tie-break 3rd call was needed (they agreed)


# --- run_judgment_checks_majority_vote (not live-wired, fixed anyway) -------


def test_reconcile_majority_vote_does_not_crash_on_dict_evidence():
    entries = [
        _finding("fail", {"page": 1, "detail": "dict shaped"}),
        _finding("fail", "normal"),
        _finding("pass", "normal2"),
    ]
    result = judge._reconcile_majority_vote([{"R-1": e} for e in entries])
    assert result["R-1"]["result"] == "fail"
    assert isinstance(result["R-1"]["evidence"], str)


# --- merge.py::_explode_to_rows defense-in-depth ----------------------------


def test_explode_to_rows_coerces_a_dict_evidence_instead_of_crashing():
    entry = {
        "category": "Problem Areas", "result": "fail", "confidence": 0.7,
        "action_lane": "BCBA-fix", "action_tag": None,
        "evidence": {"page": 9, "detail": "a real finding wrapped in a dict"},
        "page": 9,
    }
    rows = merge._explode_to_rows("QA-PROB-01", entry)
    assert len(rows) == 1
    assert rows[0]["detail"] == "a real finding wrapped in a dict"


def test_explode_to_rows_still_handles_a_plain_string_unchanged():
    entry = {
        "category": "Problem Areas", "result": "pass", "confidence": 0.8,
        "action_lane": "BCBA-fix", "action_tag": None,
        "evidence": "a completely normal finding", "page": 3,
    }
    rows = merge._explode_to_rows("QA-PROB-01", entry)
    assert rows[0]["detail"] == "a completely normal finding"


def test_explode_to_rows_still_handles_the_list_evidence_form_unchanged():
    entry = {
        "category": "Problem Areas", "result": "fail", "confidence": 0.8,
        "action_lane": "BCBA-fix", "action_tag": None,
        "evidence": [{"page": 3, "detail": "row 1"}, {"page": 5, "detail": "row 2"}],
        "page": None,
    }
    rows = merge._explode_to_rows("QA-PROB-01", entry)
    assert [r["detail"] for r in rows] == ["row 1", "row 2"]
