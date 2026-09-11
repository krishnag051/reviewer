"""Fix Round (Judgment Layer Stability): confirms integrity.py's real
pipeline call site now goes through the 5-way/4-of-5 majority vote for its
INITIAL batch call, while the missing-rule-id retry pass stays on the
cheap, unchanged plain 2-call `run_judgment_checks`. No live document, no
live API -- `judge._run_judgment_checks_once` is mocked throughout.
"""
from pipeline import integrity, judge


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def test_initial_batch_makes_5_calls_not_2(monkeypatch):
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("fail")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = integrity.run_judgment_with_integrity_check(rules, {"pages": []}, {})
    assert len(call_log) == 5, "the initial batch must be the new 5-way vote, not the old 2-call path"
    assert result["A-1"]["result"] == "fail"


def test_a_genuine_4_of_5_split_now_correctly_commits_where_the_old_2_call_path_would_have_flipped(monkeypatch):
    """The real motivating case: a rule with a true ~80% per-call majority
    (4-of-5 in this synthetic reproduction) now reliably resolves to that
    majority answer, where a 2-3 sample window could easily have landed
    on either side by chance."""
    outcomes = ["fail", "fail", "fail", "fail", "uncertain"]
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding(outcomes[len(call_log) - 1])}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = integrity.run_judgment_with_integrity_check(rules, {"pages": []}, {})
    assert result["A-1"]["result"] == "fail"


def test_a_genuine_near_even_split_still_honestly_reports_uncertain_not_a_coin_flip(monkeypatch):
    """The other real, confirmed finding this round: some rules have a
    genuinely close-to-even raw split (this round's report identifies 5
    real rule_ids like this) -- even 5-way/4-of-5 correctly refuses to
    pick a side rather than force one, which is the honest behavior."""
    outcomes = ["fail", "fail", "uncertain", "uncertain", "pass"]
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        # Fix Round (2026-09-11 evening): the initial 5-way vote reports
        # "uncertain" (correctly, no majority) with page=None -- this now
        # legitimately triggers integrity.py's own page-recovery pass,
        # which makes further real calls beyond these initial 5. Every
        # call past the initial batch still honestly reports "uncertain"
        # (repeating the last outcome), same as a real page-recovery
        # attempt that reaffirms the same verdict without finding a page.
        index = min(len(call_log) - 1, len(outcomes) - 1)
        return {"A-1": _finding(outcomes[index])}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = integrity.run_judgment_with_integrity_check(rules, {"pages": []}, {})
    assert result["A-1"]["result"] == "uncertain"


def test_missing_rule_id_retry_still_uses_the_cheap_2_call_path(monkeypatch):
    """The retry pass (a rule_id the model dropped entirely from ALL 5
    initial calls) must stay on the cheap, unchanged plain
    run_judgment_checks -- confirms integrity.py's own retry call site
    (line ~118) was deliberately left untouched, not also switched to
    5-way."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        rule_ids = [r["rule_id"] for r in judgment_rules]
        if "retry" in call_reason:
            # The retry succeeds and returns the missing rule.
            return {rid: _finding("pass") for rid in rule_ids}
        # The initial 5-way batch never answers B-1 at all.
        return {rid: _finding("pass") for rid in rule_ids if rid != "B-1"}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [
        {"rule_id": "A-1", "category": "Test", "description": "d", "notes": None},
        {"rule_id": "B-1", "category": "Test", "description": "d", "notes": None},
    ]
    result = integrity.run_judgment_with_integrity_check(rules, {"pages": []}, {}, max_retries=2)
    initial_calls = [c for c in call_log if "retry" not in c]
    retry_calls = [c for c in call_log if "retry" in c]
    assert len(initial_calls) == 5, "initial batch is still the 5-way vote"
    assert len(retry_calls) == 2, "the retry pass for the missing rule_id is still the cheap 2-call path"
    assert result["B-1"]["result"] == "pass"
