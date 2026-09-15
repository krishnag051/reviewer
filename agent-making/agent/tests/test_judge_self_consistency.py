"""Locks in the self-consistency double-call fix (2026-07-28 round): the
judgment-layer non-determinism confirmed via a live probe (QA-ACF-07 flipped
result across identical repeated calls, even in complete isolation from
other rules -- ruling out batching as the sole cause) is addressed by
calling the model twice with identical input and downgrading to "uncertain"
on disagreement, rather than silently keeping whichever call came back.

temperature=0 was confirmed NOT available as a cheaper fix via one live
call: passing a non-default temperature to claude-sonnet-5 returns a 400
("`temperature` is deprecated for this model"); only the model's own
default is accepted, as a no-op.

No live document, no live API -- _run_judgment_checks_once is monkeypatched
with canned per-call responses so this tests _reconcile_consistency_check's
logic in isolation.

Round 93 (2026-08-14), item 1: added the best-of-3 tie-breaker -- on a
call 1/2 disagreement, ONE additional batched 3rd call now runs, scoped
to only the disagreeing rule_id(s), majority-voted against calls 1/2. A
dropped/missing 3rd-call answer falls back to the exact pre-existing
two-call "uncertain" finding (_two_way_uncertain_finding), never a new
or different fallback. _reconcile_consistency_check itself (tested above,
unchanged) is retained standalone for callers/tests that want the plain
two-call reconciliation without the tie-breaker.
"""
from pipeline import judge


def _finding(result="pass", evidence="ok"):
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.8}


def test_agreeing_calls_keep_the_result():
    first = {"A-1": _finding("pass")}
    second = {"A-1": _finding("pass")}
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "pass"


def test_disagreeing_calls_downgrade_to_uncertain():
    first = {"A-1": _finding("pass", "looks fine")}
    second = {"A-1": _finding("fail", "actually a problem")}
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "uncertain"
    assert reconciled["A-1"]["confidence"] == 0.0
    # Fix Round (2026-09-10), item 4: a real usability complaint -- the
    # evidence used to be a raw per-call transcript dump. Simplified, then
    # (2026-09-15) over-corrected to a fully generic sentence with no
    # per-call evidence at all.
    # Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    # REAL FIX -- each side's own real evidence text is back, now with a
    # plain-English label instead of a raw transcript dump.
    assert "looks fine" in reconciled["A-1"]["evidence"]
    assert "actually a problem" in reconciled["A-1"]["evidence"]
    assert "confirm manually" in reconciled["A-1"]["evidence"].lower()


def test_rule_id_missing_from_either_call_is_left_out_entirely():
    """Not guessed at -- integrity.py's existing missing-rule_id retry
    already handles this case correctly; reconciliation shouldn't invent a
    result for a rule_id that only one of the two calls answered."""
    first = {"A-1": _finding("pass"), "A-2": _finding("pass")}
    second = {"A-1": _finding("pass")}  # A-2 dropped by the second call
    reconciled = judge._reconcile_consistency_check(first, second)
    assert set(reconciled.keys()) == {"A-1"}


def test_mixed_batch_some_agree_some_disagree_some_missing():
    first = {"A-1": _finding("pass"), "A-2": _finding("fail"), "A-3": _finding("pass")}
    second = {"A-1": _finding("pass"), "A-2": _finding("uncertain")}  # A-3 missing
    reconciled = judge._reconcile_consistency_check(first, second)
    assert reconciled["A-1"]["result"] == "pass"
    assert reconciled["A-2"]["result"] == "uncertain"
    assert "A-3" not in reconciled


def test_run_judgment_checks_makes_exactly_two_calls_when_calls_1_and_2_agree(monkeypatch):
    """Round 93, item 1: the best-of-3 tie-breaker must NEVER fire when
    calls 1/2 already agree -- zero extra cost on the common case."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"A-1": _finding("pass")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)

    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks(rules, {"pages": []}, {}, call_reason="initial batch")

    assert len(call_log) == 2
    assert "1/2" in call_log[0]
    assert "2/2" in call_log[1]
    assert result["A-1"]["result"] == "pass"


def test_run_judgment_checks_makes_a_third_tiebreak_call_only_on_disagreement(monkeypatch):
    """Round 93, item 1: when calls 1/2 disagree, exactly ONE additional
    batched 3rd call fires (not one per disagreeing rule_id), scoped to
    ONLY the disagreeing rule_id(s) -- A-2 (which agreed) must never be
    re-sent. Majority of the 3 calls wins when it's a real majority."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append((call_reason, [r["rule_id"] for r in judgment_rules]))
        n = len(call_log)
        if n == 1:
            return {"A-1": _finding("pass"), "A-2": _finding("pass")}
        if n == 2:
            return {"A-1": _finding("fail"), "A-2": _finding("pass")}
        # 3rd call: only A-1 should ever be sent here (A-2 already agreed).
        return {"A-1": _finding("fail")}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)

    rules = [
        {"rule_id": "A-1", "category": "Test", "description": "d", "notes": None},
        {"rule_id": "A-2", "category": "Test", "description": "d", "notes": None},
    ]
    result = judge.run_judgment_checks(rules, {"pages": []}, {}, call_reason="initial batch")

    assert len(call_log) == 3
    assert "tie-break 3/3" in call_log[2][0]
    assert call_log[2][1] == ["A-1"], "the 3rd call must be scoped to ONLY the disagreeing rule_id(s)"
    assert result["A-2"]["result"] == "pass", "A-2 agreed on calls 1/2 and must be untouched by the tie-break"
    assert result["A-1"]["result"] == "fail", "2 of 3 calls said fail -- majority wins"


def test_run_judgment_checks_falls_back_to_two_call_uncertain_when_tiebreak_drops_the_rule_id(monkeypatch):
    """Round 93, item 1's explicit requirement: if the 3rd call fails to
    answer a disagreeing rule_id, fall back to today's existing two-call
    'uncertain' behavior -- never silently drop it, never leave it unset."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        n = len(call_log)
        if n == 1:
            return {"A-1": _finding("pass", "looks fine")}
        if n == 2:
            return {"A-1": _finding("fail", "actually a problem")}
        return {}  # 3rd call drops A-1 entirely

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)

    rules = [{"rule_id": "A-1", "category": "Test", "description": "d", "notes": None}]
    result = judge.run_judgment_checks(rules, {"pages": []}, {}, call_reason="initial batch")

    assert len(call_log) == 3
    assert "A-1" in result, "must never be silently dropped"
    assert result["A-1"]["result"] == "uncertain"
    # Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence":
    # each side's real evidence text again, plain-English label, no vote-count.
    assert "looks fine" in result["A-1"]["evidence"]
    assert "actually a problem" in result["A-1"]["evidence"]
    assert "confirm manually" in result["A-1"]["evidence"].lower()


def test_run_judgment_checks_with_no_rules_makes_zero_calls(monkeypatch):
    monkeypatch.setattr(
        judge, "_run_judgment_checks_once",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    assert judge.run_judgment_checks([], {"pages": []}, {}) == {}
