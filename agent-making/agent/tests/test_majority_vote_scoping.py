"""Item 5 (2026-07-28 round 3): the majority-vote allow-list is scoped, not
universal. See judge.MAJORITY_VOTE_RULE_IDS's own comment for the evidence
behind each entry.
"""
from pipeline import judge


def test_scoped_list_contains_exactly_the_confirmed_unstable_rules():
    assert judge.MAJORITY_VOTE_RULE_IDS == {
        "QA-GIP-06", "QA-HRS-07", "QA-HRS-09", "QA-GIP-07", "QA-PROB-01",
    }


def test_gip10_not_on_the_list_since_it_is_now_deterministic():
    assert "QA-GIP-10" not in judge.MAJORITY_VOTE_RULE_IDS


def test_should_use_majority_vote_helper():
    assert judge.should_use_majority_vote("QA-GIP-06") is True
    assert judge.should_use_majority_vote("QA-BIP-05") is False


def test_run_judgment_checks_still_makes_exactly_two_calls_for_a_listed_rule(monkeypatch):
    """The allow-list exists but is NOT wired into production yet --
    run_judgment_checks must still make exactly 2 calls even for a rule_id
    on the list, since nothing in this round dispatches to the 3-call path
    automatically."""
    call_log = []

    def fake_once(judgment_rules, fields, rendered_images, tracker=None, call_reason="call", model_override=None):
        call_log.append(call_reason)
        return {"QA-GIP-06": {"result": "fail", "evidence": "x", "page": None, "confidence": 0.8}}

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_once)
    rules = [{"rule_id": "QA-GIP-06", "category": "Test", "description": "d", "notes": None}]
    judge.run_judgment_checks(rules, {"pages": []}, {})
    assert len(call_log) == 2
