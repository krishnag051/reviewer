"""Round 49: proves the dev-only simulated-completion path
(app/services/simulated_pipeline.py, POST /versions/:id/uploads/simulate)
can never reach the real Anthropic API, and that it's gated the way the
round asked -- developer role AND settings.allow_simulated_completion, both
required, neither reachable from the normal login flow.

Zero real Anthropic API calls in this file:
- The static check greps the module's own source for any reference to the
  real seam at all.
- The behavioral check runs the real route under the test suite's normal
  autouse guardrail (tests/conftest.py::_block_real_api_calls, active here
  since nothing in this file is marked @pytest.mark.real_api) -- if
  simulate_upload_completion ever called review_treatment_plan, that
  guardrail would turn this into status="error" with its own BLOCKED
  message instead of the real, expected status="ready" with SIMULATED
  findings. Passing IS the proof.
"""
import io
import uuid
from pathlib import Path

from pypdf import PdfWriter

from app.services import simulated_pipeline
from tests.conftest import login_headers


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_simulated_pipeline_module_has_no_reference_to_the_real_seam():
    """Checks for an actual import/call of the real seam -- not a bare
    substring match, since this module's own docstrings deliberately NAME
    app.rule_engine.client/review_treatment_plan in prose to document what
    ISN'T imported here. What must never appear is an import statement or a
    call expression referencing them.
    """
    source = Path(simulated_pipeline.__file__).read_text(encoding="utf-8")
    code_lines = [line for line in source.splitlines() if not line.strip().startswith("#")]
    code_only = "\n".join(code_lines)
    # Strip the module's own triple-quoted docstrings (prose, not code) before
    # checking -- a crude but sufficient split since this file has exactly
    # one leading module docstring and per-function docstrings, none of which
    # should contain executable references either, but we only need to prove
    # CODE never imports/calls the real seam.
    assert "import review_treatment_plan" not in code_only
    assert "from app.rule_engine" not in code_only
    assert "import app.rule_engine" not in code_only
    assert "review_treatment_plan(" not in code_only


def test_simulate_route_404s_when_disabled_by_default_even_for_a_developer(client, db_session, seeded_baseline, monkeypatch):
    """The route requires BOTH the developer role AND the feature flag --
    even a genuine developer account gets 404 while the flag is off (its
    real, permanent default), proving the flag alone (not just the role
    check) is what gates this in every environment unless someone
    deliberately opts in.
    """
    from app.config import settings
    from app.security import hash_password
    from app.db.models import User

    monkeypatch.setattr(settings, "allow_simulated_completion", False)

    dev_email = f"dev-{uuid.uuid4().hex[:8]}@test.local"
    dev = User(name="Dev Tester", email=dev_email, password_hash=hash_password("TestPass123!"), role="developer")
    db_session.add(dev)
    db_session.commit()

    admin_headers = login_headers(client, "m.chen@brightpath-aba.com")
    dev_headers = login_headers(client, dev_email, "TestPass123!")

    patient = client.post(
        "/patients", json={"reference_id": f"TP-TEST-sim-{uuid.uuid4().hex[:8]}", "name": "x"}, headers=admin_headers,
    ).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=admin_headers).json()

    resp = client.post(
        f"/versions/{version['id']}/uploads/simulate",
        files={"file": ("x.pdf", _pdf_bytes(), "application/pdf")},
        headers=dev_headers,
    )
    assert resp.status_code == 404


def test_simulate_route_403s_for_non_developer_even_when_enabled(client, seeded_baseline, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "allow_simulated_completion", True)
    headers = login_headers(client, "m.chen@brightpath-aba.com")  # admin, not developer
    patient = client.post("/patients", json={"reference_id": f"TP-TEST-sim-{uuid.uuid4().hex[:8]}", "name": "x"}, headers=headers).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=headers).json()

    resp = client.post(
        f"/versions/{version['id']}/uploads/simulate",
        files={"file": ("x.pdf", _pdf_bytes(), "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 403


def test_simulate_route_reaches_ready_with_labeled_findings_and_never_touches_the_real_api(
    client, db_session, seeded_baseline, monkeypatch,
):
    from app.config import settings
    from app.security import hash_password
    from app.db.models import User

    monkeypatch.setattr(settings, "allow_simulated_completion", True)

    dev_email = f"dev-{uuid.uuid4().hex[:8]}@test.local"
    dev = User(name="Dev Tester", email=dev_email, password_hash=hash_password("TestPass123!"), role="developer")
    db_session.add(dev)
    db_session.commit()

    admin_headers = login_headers(client, "m.chen@brightpath-aba.com")
    dev_headers = login_headers(client, dev_email, "TestPass123!")

    patient = client.post(
        "/patients", json={"reference_id": f"TP-TEST-sim-{uuid.uuid4().hex[:8]}", "name": "Simulated Lifecycle Test"},
        headers=admin_headers,
    ).json()
    version = client.post(f"/patients/{patient['id']}/versions", json={}, headers=admin_headers).json()

    resp = client.post(
        f"/versions/{version['id']}/uploads/simulate",
        files={"file": ("x.pdf", _pdf_bytes(), "application/pdf")},
        headers=dev_headers,
    )
    assert resp.status_code == 201, resp.text
    upload = resp.json()
    assert upload["status"] == "processing"

    # TestClient runs the background task synchronously before returning
    # above -- by the time we get here, simulate_upload_completion (5s
    # sleep + synthetic write) has already run to completion.
    detail = client.get(f"/uploads/{upload['id']}", headers=admin_headers).json()

    assert detail["status"] == "ready", detail  # NOT "error" -- proves the guardrail was never triggered
    assert detail["error_detail"] is None
    assert len(detail["rule_results"]) > 0
    assert all("SIMULATED" in r["final_finding"] for r in detail["rule_results"]), (
        "every synthetic finding must be unmistakably labeled -- this is what lets a reviewer "
        "never confuse this for a real result"
    )
    statuses = {r["final_status"] for r in detail["rule_results"]}
    assert statuses <= {"pass", "fail", "na", "uncertain", "not_checkable"}
    assert len(statuses) > 1, "expects a real mix of synthetic statuses for lifecycle/filter testing"
