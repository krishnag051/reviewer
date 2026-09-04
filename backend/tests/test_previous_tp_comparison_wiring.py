"""Previous TP round (comparison logic) -- backend wiring regression test.

Confirms QA-MAST-01, QA-MAST-02, QA-RPT-05, QA-ACF-04, and QA-PROB-04 all
still resolve to not_checkable -- completely UNCHANGED from today's
behavior -- when `Upload.previous_tp_path` is None. This is the exact
"absence path" the round's own verification requirement asks for, using a
"plain, clearly-fake placeholder document" (an empty findings list from a
monkeypatched `review_treatment_plan` standing in for a real agent
response) -- no real API spend, no `@pytest.mark.real_api` needed, because
`app.agent_client.review_previous_tp` returns `[]` immediately (confirmed
separately, at the agent-making layer, in
agent-making/agent/tests/test_previous_tp_comparison_logic.py) the moment
`previous_tp_path` is None -- this test proves the BACKEND wiring around
that early-return never even reaches it, by directly exercising
`run_rule_checks` end-to-end (not the full HTTP upload flow) with a real
DB-backed snapshot/rules, but a fake (not the guardrail-blocked real)
`review_treatment_plan`.
"""
import uuid

from app.agent_client import ReviewResult, UsageInfo
from app.db.models import RuleSnapshot
from app.rule_engine.client import run_rule_checks
from tests.conftest import make_patient_version_upload


def _empty_complete_result() -> ReviewResult:
    """A minimal, clearly-fake 'complete' pipeline result with zero
    findings -- every pinned rule in the snapshot falls to the
    'no matching finding' not_checkable default in
    _drafts_from_review_result, which is exactly the real baseline
    behavior this test needs (no previous-TP-specific code involved yet)."""
    return ReviewResult(
        schema_version="1.0",
        status="complete",
        detected_payor=None,
        detected_plan_type=None,
        supporting_doc_extraction=None,
        results=[],
        bcba_fix_rule_ids=[],
        facilitator_assign_rule_ids=[],
        counts_by_result={},
        usage=UsageInfo(api_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0),
        error=None,
    )


def test_all_5_previous_tp_rules_stay_not_checkable_when_no_previous_tp_is_uploaded(
    monkeypatch, db_session, seeded_baseline,
):
    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan", lambda *args, **kwargs: _empty_complete_result(),
    )

    upload = make_patient_version_upload(
        db_session,
        status="processing",
        file_path="fake-current-tp.pdf",  # clearly-fake placeholder -- never actually read (review_treatment_plan is mocked)
        previous_tp_path=None,  # the exact absence path this test exists to confirm
    )
    snapshot = db_session.get(RuleSnapshot, upload.rules_snapshot_id)

    drafts = run_rule_checks(db_session, str(upload.id), str(snapshot.id), parsed_pages=[])

    from app.db.models import Rule
    rule_codes_by_id = {str(r.id): r.rule_code for r in db_session.query(Rule).all()}
    drafts_by_code = {rule_codes_by_id[str(d.rule_id)]: d for d in drafts if str(d.rule_id) in rule_codes_by_id}

    for rule_code in ("QA-MAST-01", "QA-MAST-02", "QA-RPT-05", "QA-ACF-04", "QA-PROB-04"):
        assert rule_code in drafts_by_code, f"{rule_code} missing from drafts -- rule set drift?"
        draft = drafts_by_code[rule_code]
        assert draft.model_status == "not_checkable", (
            f"{rule_code} should stay not_checkable with no previous TP, got {draft.model_status!r}: "
            f"{draft.model_finding!r}"
        )
        # Confirms this is the SAME "no matching finding" default every
        # other not-yet-answered rule gets -- not some new previous-TP-
        # specific not_checkable message, proving review_previous_tp's
        # override block genuinely never touched this draft.
        assert "No matching finding from the rule-checking agent" in draft.model_finding


def test_review_previous_tp_returns_empty_list_immediately_with_no_previous_tp_path():
    """Direct unit-level confirmation of the early-return itself (mirrors
    review_session_notes' own equivalent-shaped guard) -- zero extraction,
    zero model calls, zero DB access."""
    from app.agent_client import review_previous_tp

    assert review_previous_tp("some/current-tp.pdf", None) == []
