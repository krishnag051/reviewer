"""Live smoke test -- the ONE test file in this suite that makes real
Anthropic API calls. Per the standing rule (verbatim in CLAUDE.md,
agent-making/AGENT_STATE.md, agent-making/INTEGRATION_PLAN.md,
frontend/FRONTEND_STATE.md): no real API calls without explicit,
per-instance permission, with the exact command + call count + cost
estimate stated and confirmed in chat first, every time.

Round 40: approved to run exactly as proposed in Round 39 --
`pytest -q tests/test_live_smoke.py::test_one_real_upload_full_lifecycle`,
2 real API calls (one upload's self-consistency double-call), ~$0.50,
using agent-making's real sample_tps/Ullah_Zyaan_Redacted.pdf. One
document, one patient/version/upload, one pass through:
real upload -> real findings -> override a draft finding -> finalize ->
attempt another override (must reject 409).

Round 44/45: marked `@pytest.mark.real_api` -- tests/conftest.py's autouse
guardrail now blocks this test's real call by default like every other
test's, unless run with `-m real_api` (which is itself not permission on
its own). Every real call this test makes also counts against the
session-wide MAX_REAL_API_CALLS_PER_SESSION ceiling (default 4) -- see
conftest.py's `_block_real_api_calls`/`_make_ceiling_enforced_real_call`.

Do NOT add more test functions to this file, and do NOT re-run it, without
the same explicit per-instance sign-off each time -- this file existing is
not a standing invitation to re-run it freely.
"""
import io
import uuid
from pathlib import Path

import pytest
from pypdf import PdfWriter

from tests.conftest import login_headers

SAMPLE_PDF = (
    Path(__file__).resolve().parent.parent.parent
    / "agent-making" / "agent" / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"
)


def _synthetic_supporting_document_bytes() -> bytes:
    """Round 51's mandatory second file -- display-only, never fed into the
    real pipeline, so a synthetic blank PDF is honest here (no reason to
    spend anything extra making it "real" content).
    """
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.mark.real_api
def test_one_real_upload_full_lifecycle(client, db_session, seeded_baseline):
    assert SAMPLE_PDF.is_file(), f"sample PDF not found at {SAMPLE_PDF}"
    headers = login_headers(client, "m.chen@brightpath-aba.com")

    ref = f"TP-TEST-livesmoke-{uuid.uuid4().hex[:8]}"
    patient = client.post(
        "/patients", json={"reference_id": ref, "name": "Live Smoke Test Patient"}, headers=headers
    ).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()

    with open(SAMPLE_PDF, "rb") as f:
        upload = client.post(
            f"/versions/{version['id']}/uploads",
            files={
                "file": ("Ullah_Zyaan_Redacted.pdf", f, "application/pdf"),
                "supporting_document": ("supporting.pdf", _synthetic_supporting_document_bytes(), "application/pdf"),
            },
            headers=headers,
        ).json()

    # TestClient runs the upload's BackgroundTask (run_upload_pipeline) to
    # completion before the POST above even returns -- no polling needed,
    # same as every other real-pipeline test in this suite.
    detail = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    assert detail["status"] == "ready", detail
    rule_results = detail["rule_results"]

    # ---- confirm real findings, not stub output ----
    assert len(rule_results) == 120, f"expected one result per real seeded rule, got {len(rule_results)}"
    seen_statuses = {r["final_status"] for r in rule_results}
    assert seen_statuses <= {"pass", "fail", "na", "uncertain", "not_checkable"}
    assert len(seen_statuses) > 1, f"expected a real mix of statuses from the real agent, got only {seen_statuses}"
    assert not all(r["final_finding"] == "(agent not yet implemented)" for r in rule_results), (
        "still looks like the old hollow-stub output"
    )
    status_counts = {s: sum(1 for r in rule_results if r["final_status"] == s) for s in sorted(seen_statuses)}
    print(f"\nLIVE SMOKE -- real status counts across {len(rule_results)} rule_results: {status_counts}")
    print("LIVE SMOKE -- 5 sample findings:")
    for r in rule_results[:5]:
        print(f"  rule_id={r['rule_id']} final_status={r['final_status']!r} final_finding={r['final_finding'][:100]!r}")

    # ---- override one draft finding: flip status + edit the finding text ----
    target = rule_results[0]
    override_target_status = "fail" if target["final_status"] != "fail" else "pass"
    resp = client.patch(
        f"/rule_results/{target['id']}",
        json={
            "updated_at": target["updated_at"],
            "final_status": override_target_status,
            "final_finding": "Manually corrected during live smoke test (Round 40).",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    overridden = resp.json()
    assert overridden["final_status"] == override_target_status
    assert overridden["final_finding"] == "Manually corrected during live smoke test (Round 40)."
    assert overridden["is_overridden"] is True
    print(f"LIVE SMOKE -- overrode {target['rule_id']} to {override_target_status!r}, accepted and reflected immediately")

    # Resolve any real "uncertain" results to "na" first -- this test isn't
    # exercising finalize's uncertain-results guard, and real content can
    # legitimately produce some.
    fresh = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    for rr in fresh["rule_results"]:
        if rr["final_status"] == "uncertain":
            client.patch(
                f"/rule_results/{rr['id']}", json={"updated_at": rr["updated_at"], "final_status": "na"}, headers=headers,
            )

    # ---- finalize ----
    finalize_resp = client.post(f"/uploads/{upload['id']}/finalize", json={"reference_id": ref}, headers=headers)
    assert finalize_resp.status_code == 200, finalize_resp.text
    assert finalize_resp.json()["is_final"] is True
    print("LIVE SMOKE -- finalized successfully")

    # ---- attempt another override on the now-finalized upload: must reject ----
    fresh2 = client.get(f"/uploads/{upload['id']}", headers=headers).json()
    another = next(r for r in fresh2["rule_results"] if r["id"] != target["id"])
    reject_resp = client.patch(
        f"/rule_results/{another['id']}",
        json={"updated_at": another["updated_at"], "final_status": "pass"},
        headers=headers,
    )
    assert reject_resp.status_code == 409, reject_resp.text
    assert reject_resp.json()["detail"]["error"] == "upload_already_finalized"
    print("LIVE SMOKE -- override-on-finalized correctly rejected with 409 upload_already_finalized")
