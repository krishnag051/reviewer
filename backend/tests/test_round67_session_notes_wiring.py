"""Round 67: wires app.agent_client.review_session_notes into
app.rule_engine.client.run_rule_checks, merging QA-RPT-03/QA-ACF-02/
QA-ACF-08 into the SAME rule_results set an upload already produces --
the first real backend call site for session-notes extraction/comparison
(Rounds 59-65's agent-making work), previously only ever exercised by
agent-making's own standalone Streamlit script.

Zero real Anthropic API calls, zero real OpenRouter calls either -- both
app.rule_engine.client.review_treatment_plan AND .review_session_notes are
mocked at the exact seam run_rule_checks imports them through (same
discipline Round 66 already established for the main TP pipeline).
"""
import uuid

import pytest
from sqlalchemy import select

from app.agent_client import ReviewResult, RuleResult, UsageInfo
from app.db.models import Rule, SessionNoteFile
from app.rule_engine.client import run_rule_checks
from tests.conftest import make_patient_version_upload


def _fake_main_review_result(rule_ids: list[str]) -> ReviewResult:
    """A "complete" main-TP ReviewResult whose findings include
    placeholder, deliberately-recognizable values for the 3 session-notes
    rule_ids -- proving they get OVERRIDDEN by the merge, not just left
    alone because the main call never mentions them."""
    return ReviewResult(
        schema_version="1.0", status="complete", detected_payor="Aetna", detected_plan_type="Initial",
        supporting_doc_extraction=None,
        results=[
            RuleResult(
                rule_id=rid, category="Placeholder", status="not_checkable", page=[],
                evidence=f"MAIN-TP-PLACEHOLDER-{rid}", confidence=0.0, action_lane=None, action_tag=None,
            )
            for rid in rule_ids
        ],
        bcba_fix_rule_ids=[], facilitator_assign_rule_ids=rule_ids, counts_by_result={"not_checkable": len(rule_ids)},
        usage=UsageInfo(api_calls=0, input_tokens=0, output_tokens=0, estimated_cost_usd=0.0), error=None,
    )


def _add_session_note_file(session, upload, filename: str) -> SessionNoteFile:
    note = SessionNoteFile(upload_id=upload.id, file_path=f"/fake/{filename}", original_filename=filename)
    session.add(note)
    session.flush()
    return note


def test_session_notes_results_are_merged_into_the_same_drafts_list(db_session, seeded_baseline, monkeypatch):
    """Real assertion: with a session-note file attached, QA-RPT-03/
    QA-ACF-02/QA-ACF-08's drafts come from review_session_notes, NOT the
    main-TP placeholder -- proving the merge actually overrides, not just
    runs alongside without effect."""
    upload = make_patient_version_upload(db_session, status="processing")
    _add_session_note_file(db_session, upload, "session-note.pdf")
    db_session.commit()

    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan",
        lambda *a, **k: _fake_main_review_result(["QA-RPT-03", "QA-ACF-02", "QA-ACF-08"]),
    )

    captured_call = {}

    def _fake_review_session_notes(tp_pdf_path, session_note_paths, *, model_override=None, max_calls=None):
        captured_call["tp_pdf_path"] = tp_pdf_path
        captured_call["session_note_paths"] = session_note_paths
        captured_call["model_override"] = model_override
        return [
            RuleResult(rule_id="QA-RPT-03", category="Report Information", status="pass", page=[],
                       evidence="SESSION-NOTES-REAL-RPT03", confidence=0.9, action_lane="Facilitator-assign", action_tag="General"),
            RuleResult(rule_id="QA-ACF-02", category="Assessment of Current Functioning", status="pass", page=[],
                       evidence="SESSION-NOTES-REAL-ACF02", confidence=0.85, action_lane="Facilitator-assign", action_tag="QA"),
            RuleResult(rule_id="QA-ACF-08", category="Assessment of Current Functioning", status="fail", page=[],
                       evidence="SESSION-NOTES-REAL-ACF08", confidence=0.85, action_lane="Facilitator-assign", action_tag="QA"),
        ]

    monkeypatch.setattr("app.rule_engine.client.review_session_notes", _fake_review_session_notes)

    drafts = run_rule_checks(db_session, str(upload.id), str(upload.rules_snapshot_id), parsed_pages=[])

    # review_session_notes must have been called with the real upload file
    # path and the real {filename: path} mapping for its session notes.
    assert captured_call["tp_pdf_path"] == upload.file_path
    assert captured_call["session_note_paths"] == {"session-note.pdf": "/fake/session-note.pdf"}
    # Deliberate, still-OpenRouter-free-tier default for this real backend
    # call site -- see app.rule_engine.client.run_rule_checks's own comment.
    assert captured_call["model_override"] == "openrouter"

    rule_codes = {"QA-RPT-03": "pass", "QA-ACF-02": "pass", "QA-ACF-08": "fail"}
    rules_by_code = {
        r.rule_code: r for r in db_session.execute(select(Rule).where(Rule.rule_code.in_(rule_codes))).scalars().all()
    }
    drafts_by_id = {str(d.rule_id): d for d in drafts}
    for code, expected_status in rule_codes.items():
        draft = drafts_by_id[str(rules_by_code[code].id)]
        assert draft.model_status == expected_status, f"{code}: expected {expected_status}, got {draft.model_status}"
        assert draft.model_finding == f"SESSION-NOTES-REAL-{code.replace('QA-', '').replace('-', '')}"
        assert "MAIN-TP-PLACEHOLDER" not in draft.model_finding, (
            f"{code}: the main-TP placeholder must be OVERRIDDEN by the session-notes result, not left standing"
        )


def test_tp_only_upload_never_calls_review_session_notes_and_is_unaffected(db_session, seeded_baseline, monkeypatch):
    """The exact same drafts, byte-for-byte, as a plain Round-66-era call --
    review_session_notes must not even be invoked when no session-note
    files are attached to the upload."""
    upload = make_patient_version_upload(db_session, status="processing")
    db_session.commit()
    assert list(upload.session_note_files) == []

    monkeypatch.setattr(
        "app.rule_engine.client.review_treatment_plan",
        lambda *a, **k: _fake_main_review_result(["QA-RPT-03", "QA-ACF-02", "QA-ACF-08"]),
    )

    session_notes_called = {"value": False}

    def _fail_if_called(*a, **k):
        session_notes_called["value"] = True
        raise AssertionError("review_session_notes must never be called for a TP-only upload")

    monkeypatch.setattr("app.rule_engine.client.review_session_notes", _fail_if_called)

    drafts = run_rule_checks(db_session, str(upload.id), str(upload.rules_snapshot_id), parsed_pages=[])

    assert session_notes_called["value"] is False

    rules_by_code = {
        r.rule_code: r for r in db_session.execute(
            select(Rule).where(Rule.rule_code.in_(["QA-RPT-03", "QA-ACF-02", "QA-ACF-08"]))
        ).scalars().all()
    }
    drafts_by_id = {str(d.rule_id): d for d in drafts}
    for code, rule in rules_by_code.items():
        draft = drafts_by_id[str(rule.id)]
        assert draft.model_status == "not_checkable"
        assert draft.model_finding == f"MAIN-TP-PLACEHOLDER-{code}", (
            "the TP-only path must pass the main review's own value through completely unchanged"
        )
