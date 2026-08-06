"""Round 44: proves the structural guardrail in conftest.py
(`_block_real_api_calls`) actually blocks the real Anthropic API call BEFORE
any network request is constructed -- not just that it happens to fail the
same way a zero-credit account would (that was the whole gap Round 43's
incident exposed: a real request that reaches Anthropic's servers and gets
rejected is still a real, unapproved API call).

Zero real Anthropic API calls in this file, by construction: the guardrail
this file tests is exactly what prevents that, and the one test that opts
out via `@pytest.mark.real_api` immediately re-patches the same seam with
its own local stub -- it never lets the real import run either.
"""
import io
import uuid

import pytest
from pypdf import PdfWriter

from tests.conftest import ROUND56_QA_FORM_DATA, login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _create_upload(client, headers) -> dict:
    ref = f"TP-TEST-guardrail-{uuid.uuid4().hex[:8]}"
    patient = client.post("/patients", json={"reference_id": ref, "name": "Guardrail Test Patient"}, headers=headers).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()
    upload = client.post(
        f"/versions/{version['id']}/uploads",
        data=ROUND56_QA_FORM_DATA,
        files={
            "file": ("tp.pdf", _pdf_bytes(), "application/pdf"),
            "supporting_document": ("supporting.pdf", _pdf_bytes(), "application/pdf"),
            "session_notes": ("session-note.pdf", _pdf_bytes(), "application/pdf"),
        },
        headers=headers,
    ).json()
    return client.get(f"/uploads/{upload['id']}", headers=headers).json()


def test_real_pipeline_call_is_blocked_before_any_network_request(client, seeded_baseline):
    """A genuinely valid PDF (so parse_pdf succeeds and the pipeline reaches
    run_rule_checks -> review_treatment_plan for real) still ends in
    status="error" with the guardrail's own message -- proving the block
    fires at the Python call site, not at Anthropic's servers.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    detail = _create_upload(client, headers)

    assert detail["status"] == "error", detail
    assert "BLOCKED by tests/conftest.py::_block_real_api_calls" in detail["error_detail"]
    assert detail["rule_results"] == [], "a blocked pipeline run must leave zero rule_results, same all-or-nothing guarantee as any other pipeline failure"
    assert detail["rules_snapshot_id"] is None


def test_guardrail_active_by_default_with_no_special_setup(client, seeded_baseline):
    """Confirms the fixture is autouse -- a completely ordinary test, with no
    marker and no explicit reference to the guardrail fixture, still gets
    the real seam patched out from under it.
    """
    import app.rule_engine.client as client_module

    assert client_module.review_treatment_plan.__name__ == "_blocked_review_treatment_plan"


def _fake_review_treatment_plan(
    pdf_path, *, supporting_doc_path=None, payor_override=None, plan_type_override=None, max_calls=None,
):
    return {
        "schema_version": 1, "status": "complete", "detected_payor": None, "detected_plan_type": None,
        "findings": [], "summary": {}, "usage": {"calls": 0}, "error": None,
    }


@pytest.mark.real_api
def test_real_api_marker_opts_out_of_the_autouse_guard(client, seeded_baseline, monkeypatch):
    """Proves the escape hatch works -- WITHOUT spending anything or needing
    real credentials. `@pytest.mark.real_api` makes the autouse fixture stand
    down entirely for this one test; this test then patches the same seam
    itself with a controlled fake "complete" ReviewResult (never touching the
    real network). If the autouse guard had NOT stood down, it would have
    overwritten this test's own patch with the blocking stub, and the
    resulting upload would be status="error" with the BLOCKED message
    instead of "ready" -- so this assertion is a genuine proof the marker
    works, not a tautology.
    """
    monkeypatch.setattr("app.rule_engine.client.review_treatment_plan", _fake_review_treatment_plan)
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    detail = _create_upload(client, headers)

    assert detail["status"] == "ready", detail
    assert detail["error_detail"] is None


# ---------------------------------------------- Round 45: real-API spend ceiling


def test_ceiling_blocks_a_real_call_past_the_configured_max_before_it_reaches_the_real_function(monkeypatch):
    """Directly exercises tests/conftest.py's _make_ceiling_enforced_real_call
    with an artificially low ceiling (2) and a fake "real" function that just
    records how many times it was actually invoked -- proving the (N+1)th
    call raises BEFORE the underlying function ever runs, not merely that it
    gets logged/counted after the fact. Doesn't touch the shared module-level
    counter's real state destructively for other tests: saves and restores it.
    """
    import tests.conftest as conftest_module

    original_count = conftest_module._real_api_call_counter.count
    original_max = conftest_module.MAX_REAL_API_CALLS_PER_SESSION
    try:
        conftest_module._real_api_call_counter.count = 0
        monkeypatch.setattr(conftest_module, "MAX_REAL_API_CALLS_PER_SESSION", 2)

        calls_that_actually_ran = []

        def _fake_real_fn(*args, **kwargs):
            calls_that_actually_ran.append((args, kwargs))
            return "fake result"

        wrapped = conftest_module._make_ceiling_enforced_real_call(_fake_real_fn)

        assert wrapped("first") == "fake result"
        assert wrapped("second") == "fake result"
        assert len(calls_that_actually_ran) == 2

        with pytest.raises(RuntimeError, match="BLOCKED.*real-API spend ceiling"):
            wrapped("third — should never reach _fake_real_fn")

        assert len(calls_that_actually_ran) == 2, (
            "the 3rd call must be blocked BEFORE reaching the real function -- "
            "the underlying function call count must not have incremented"
        )
    finally:
        conftest_module._real_api_call_counter.count = original_count
        conftest_module.MAX_REAL_API_CALLS_PER_SESSION = original_max


def test_ceiling_counts_raw_api_calls_not_review_treatment_plan_invocations(monkeypatch):
    """A single review_treatment_plan call reviews one whole document via
    agent-making's self-consistency pass -- itself 2+ raw Anthropic API
    requests (result["usage"]["api_calls"]), confirmed live this round: one
    document = 2 raw calls. The ceiling must count THAT number, not "1 per
    invocation" -- otherwise MAX_REAL_API_CALLS_PER_SESSION=4 would actually
    permit 4 full document reviews (8+ raw calls), silently doubling the
    real spend the number implies.
    """
    import tests.conftest as conftest_module

    original_count = conftest_module._real_api_call_counter.count
    original_max = conftest_module.MAX_REAL_API_CALLS_PER_SESSION
    try:
        conftest_module._real_api_call_counter.count = 0
        monkeypatch.setattr(conftest_module, "MAX_REAL_API_CALLS_PER_SESSION", 4)

        def _fake_real_fn_making_2_calls(*args, **kwargs):
            return {"status": "complete", "usage": {"api_calls": 2}}

        wrapped = conftest_module._make_ceiling_enforced_real_call(_fake_real_fn_making_2_calls)

        wrapped("first document")  # counts as 2 -> total 2/4
        assert conftest_module._real_api_call_counter.count == 2
        wrapped("second document")  # counts as 2 -> total 4/4, at the ceiling
        assert conftest_module._real_api_call_counter.count == 4

        with pytest.raises(RuntimeError, match="BLOCKED.*real-API spend ceiling"):
            wrapped("third document — must never run, ceiling already reached")
    finally:
        conftest_module._real_api_call_counter.count = original_count
        conftest_module.MAX_REAL_API_CALLS_PER_SESSION = original_max
