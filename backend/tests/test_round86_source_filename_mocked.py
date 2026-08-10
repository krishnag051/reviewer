"""Round 86: zero-cost (mocked, no real pipeline call) proof that
run_rule_checks passes source_filename=upload.original_filename through to
review_treatment_plan -- and that a row with no original_filename at all
(e.g. one created before this round's migration) still works exactly as
before: falls back to None, never errors.
"""
import uuid

from sqlalchemy import select

from app.agent_client import ReviewResult, UsageInfo
from app.db.models import RuleSyncState, Upload
from app.rule_engine.client import run_rule_checks
from tests.conftest import make_patient_version_upload


def _fake_complete_result(seen_kwargs: dict):
    def _fake(pdf_path, *, supporting_doc_path=None, payor_override=None, plan_type_override=None,
               source_filename=None, max_calls=None):
        seen_kwargs["source_filename"] = source_filename
        return ReviewResult(
            schema_version="1.0", status="complete", detected_payor=None, detected_plan_type=None,
            supporting_doc_extraction=None, results=[], bcba_fix_rule_ids=[], facilitator_assign_rule_ids=[],
            counts_by_result={}, usage=UsageInfo(api_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0),
            error=None,
        )
    return _fake


def test_source_filename_flows_from_upload_original_filename_to_review_call(
    db_session, monkeypatch, seeded_baseline,
):
    seen_kwargs = {}
    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan", _fake_complete_result(seen_kwargs),
    )
    monkeypatch.setattr("app.rule_engine.client.review_session_notes", lambda *a, **k: [])

    upload = make_patient_version_upload(db_session, file_path="/tmp/fake.pdf")
    upload.original_filename = "Zohran Hossain TP.pdf"
    db_session.commit()

    snapshot_id = db_session.execute(select(RuleSyncState)).scalar_one().current_snapshot_id
    run_rule_checks(db_session, str(upload.id), str(snapshot_id), parsed_pages=[])

    assert seen_kwargs["source_filename"] == "Zohran Hossain TP.pdf"


def test_source_filename_falls_back_to_none_when_upload_has_no_original_filename(
    db_session, monkeypatch, seeded_baseline,
):
    """A row with no original_filename at all (None -- e.g. created before
    this round's migration) must still work exactly as before this round:
    source_filename=None is passed through (agent-making's own default,
    inert fallback), never an error."""
    seen_kwargs = {}
    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan", _fake_complete_result(seen_kwargs),
    )
    monkeypatch.setattr("app.rule_engine.client.review_session_notes", lambda *a, **k: [])

    upload = make_patient_version_upload(db_session, file_path="/tmp/fake.pdf")
    assert upload.original_filename is None  # the real pre-migration-row shape

    snapshot_id = db_session.execute(select(RuleSyncState)).scalar_one().current_snapshot_id
    drafts = run_rule_checks(db_session, str(upload.id), str(snapshot_id), parsed_pages=[])  # must not raise

    assert seen_kwargs["source_filename"] is None
    assert isinstance(drafts, list)
