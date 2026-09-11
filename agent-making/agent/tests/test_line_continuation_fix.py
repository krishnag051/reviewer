"""Fix Round (Performance/Question Revisions, 2026-09-10), items 9/22/27 --
all three were confirmed to be the SAME shared bug class: a label's real
value sometimes continues onto a LATER line (real PDF text wrapping) or a
LATER page (QA-RPT-01 specifically) than the checker only ever looked at,
so a genuinely-filled field read as blank/missing.

One shared fix (pipeline/fields.py::_extract_labeled_value), one real test
per affected rule confirming it, per this round's own explicit ask not to
patch the three symptoms separately.
"""
from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# --- shared helper, direct coverage ---------------------------------------

def test_extract_labeled_value_reads_same_line():
    assert fields._extract_labeled_value("Baseline: 10%\nNext: x", "Baseline") == "10%"


def test_extract_labeled_value_reads_a_wrapped_next_line():
    """The real, confirmed shape: PDF extraction wraps a long value onto
    the line after its label, purely due to page width."""
    text = "Mastered Goals:\nJ will identify 10 colors independently across 3 settings.\nParent/Caregiver Involvement:"
    assert fields._extract_labeled_value(text, "Mastered Goals") == \
        "J will identify 10 colors independently across 3 settings."


def test_extract_labeled_value_stops_at_the_next_real_label():
    """Must not swallow the NEXT field's own value as if it were this
    field's wrapped continuation."""
    text = "Mastery Criteria: \nSampling Method: Frequency\n"
    assert fields._extract_labeled_value(text, "Mastery Criteria") == ""


def test_extract_labeled_value_returns_empty_for_a_genuinely_blank_field():
    text = "Mastered Goals:\n\n\nParent/Caregiver Involvement: yes"
    assert fields._extract_labeled_value(text, "Mastered Goals") == ""


# --- item 9: QA-RPT-01 ------------------------------------------------------

def test_rpt01_does_not_false_fail_when_value_wraps_to_next_line():
    text = "Mastered Goals:\nJ will identify 10 colors independently.\n"
    result, evidence, page, confidence = fields._check_RPT01({}, _fields(text))
    assert result == "pass", evidence


def test_rpt01_does_not_false_fail_when_value_is_on_the_next_page():
    """The other real half of item 9: a label at the very end of one page,
    whose value is the first line of the NEXT page -- must not read as
    blank just because the checker used to search one page's text at a time."""
    page1 = "Mastered Goals:"
    page2 = "J will identify 10 colors independently across 3 settings."
    result, evidence, page, confidence = fields._check_RPT01({}, _fields(page1, page2))
    assert result == "pass", evidence


def test_rpt01_still_fails_a_genuinely_blank_field():
    text = "Mastered Goals:\n\n\nParent/Caregiver Involvement: yes\n"
    result, evidence, page, confidence = fields._check_RPT01({}, _fields(text))
    assert result == "fail"
    assert "Mastered Goals" in str(evidence)


# --- item 22: QA-GIP-19 -----------------------------------------------------

def test_gip19_does_not_false_fail_when_summary_wraps_to_next_line():
    text = (
        "Skill Domain: Functional Behavior Skills\n"
        "Behavioral Summary:\n"
        "Patient continues to show a reduction in tantrum behaviors across settings.\n"
    )
    result, evidence, page, confidence = fields._check_GIP19({}, _fields(text))
    assert result == "pass", evidence


def test_gip19_still_fails_a_genuinely_blank_summary():
    text = "Skill Domain: Functional Behavior Skills\nBehavioral Summary:\n\n\nNext Section: x\n"
    result, evidence, page, confidence = fields._check_GIP19({}, _fields(text))
    assert result == "fail"


# --- item 27: QA-GIP-10 -----------------------------------------------------

def test_gip10_does_not_false_fail_when_mastery_criteria_wraps_to_next_line():
    goal = (
        "Target Goal: Z will do W\n"
        "Baseline: 10%\n"
        "Mastery Criteria:\n"
        "85% independent across 3 consecutive sessions\n"
        "Sampling Method: Percent Correct\n"
    )
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(goal))
    assert result == "pass", evidence


def test_gip10_still_fails_a_genuinely_blank_mastery_criteria():
    goal = "Target Goal: Z will do W\nBaseline: 2 occurrences\nMastery Criteria: \nSampling Method: Frequency\n"
    result, evidence, page, confidence = fields._check_GIP10({}, _fields(goal))
    assert result == "fail"


# --- item 12: QA-HRS-11 -----------------------------------------------------
# (unrelated to the line-continuation bug class above, but written in the
# same real-fix pass this round -- kept here rather than a new one-off file.)

def test_hrs11_is_payor_aware_instead_of_excluding_healthfirst_and_emblem():
    """Fix Round (2026-09-10), item 12: the old version returned
    not_applicable for Healthfirst/Emblem entirely. Now checks the real,
    payor-appropriate cap directly for every payor."""
    import json
    d = json.load(open("rules/rules.json", encoding="utf-8"))
    rule = next(r for r in d["rules"] if r["rule_id"] == "QA-HRS-11")

    def _f(text, payor=None):
        return {"full_text": text, "payor": payor}

    hf_result, *_ = fields._check_HRS11(rule, _f("97151: 6 hrs requested", payor="Healthfirst"))
    assert hf_result == "fail"  # 6 > Healthfirst's 5-hr cap

    emb_result, *_ = fields._check_HRS11(rule, _f("97151: 6 hrs requested", payor="Emblem"))
    assert emb_result == "fail"  # 6 > Emblem's 3-hr cap

    other_result, *_ = fields._check_HRS11(rule, _f("97151: 6 hrs requested", payor="Aetna"))
    assert other_result == "pass"  # 6 <= the universal 8-hr default


# --- Performance Fix Round (2026-09-11): parallelized loops -------------

def test_majority_vote_calls_run_concurrently_not_sequentially(monkeypatch):
    """Real proof this is actually parallel, not just refactored: 5 calls
    that each sleep 0.2s must finish in well under 5x0.2s=1.0s total if
    they're truly concurrent (sequential would take >=1.0s)."""
    import time
    from pipeline import judge

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        time.sleep(0.2)
        return {r["rule_id"]: {"result": "pass", "evidence": "ok", "page": None, "confidence": 0.8} for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]

    start = time.monotonic()
    judge.run_judgment_checks_majority_vote(rules, {"pages": []}, {}, n_calls=5, call_reason="initial batch")
    elapsed = time.monotonic() - start
    assert elapsed < 0.6, f"expected concurrent execution well under 1.0s, took {elapsed:.2f}s"


def test_majority_vote_still_reconciles_correctly_with_concurrent_calls(monkeypatch):
    """Output equivalence check: concurrent execution must produce the
    exact same reconciled result as the old sequential version would --
    a real 4-of-5 majority still wins."""
    from pipeline import judge

    call_n = {"n": 0}

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_n["n"] += 1
        n = call_n["n"]
        result = "fail" if n <= 4 else "pass"  # 4 fail, 1 pass
        return {r["rule_id"]: {"result": result, "evidence": f"call {n}", "page": None, "confidence": 0.8} for r in judgment_rules}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks_majority_vote(
        rules, {"pages": []}, {}, n_calls=5, min_agreement=4, call_reason="initial batch",
    )
    assert result["A-1"]["result"] == "fail"


def test_call_tracker_is_thread_safe_under_real_concurrent_access():
    """Real regression test for the race this round's own parallelization
    would otherwise introduce: hammer one CallTracker from many threads
    at once and confirm the final count is EXACTLY the number of calls
    made -- no lost updates from an unsynchronized `self.count += 1`."""
    from concurrent.futures import ThreadPoolExecutor
    from pipeline.model_provider import CallTracker

    tracker = CallTracker(max_calls=1000)

    def make_one_call(i):
        tracker.check_before_call()
        tracker.record(reason="test", provider="anthropic", model="x", usage={"input_tokens": 1, "output_tokens": 1})

    with ThreadPoolExecutor(max_workers=20) as pool:
        list(pool.map(make_one_call, range(200)))

    assert tracker.count == 200
