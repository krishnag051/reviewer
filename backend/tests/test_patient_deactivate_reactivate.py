"""Part 6, Fix Round (2026-08-27): deactivate/archive a TP -- reversible,
real backend flag, no hard delete. Zero pipeline/upload involvement --
this is purely patient-record-level, so these tests don't need a ready
upload at all (sidesteps this suite's own real-API guardrail entirely).
"""
from tests.conftest import login_headers


def _create_patient(client, headers, ref_id: str, name: str = "Deactivate Test Patient") -> dict:
    return client.post("/api/patients", json={"reference_id": ref_id, "name": name}, headers=headers).json()


def test_new_patient_is_active_by_default(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-default")
    assert patient["active"] is True
    assert patient["deactivated_at"] is None


def test_deactivate_flips_the_real_flag_and_is_reversible(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-flow")

    resp = client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["deactivated_at"] is not None

    # Real DB state confirmed via a fresh GET, not just the mutation's own response.
    listed = client.get("/api/patients?status_filter=all", headers=headers).json()
    entry = next(p for p in listed if p["id"] == patient["id"])
    assert entry["active"] is False


def test_deactivated_patient_excluded_from_default_active_list(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-excluded")
    client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)

    active_list = client.get("/api/patients", headers=headers).json()  # default status_filter=active
    assert patient["id"] not in {p["id"] for p in active_list}

    archived_list = client.get("/api/patients?status_filter=archived", headers=headers).json()
    assert patient["id"] in {p["id"] for p in archived_list}


def test_deactivate_twice_is_rejected_409(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-twice")
    client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)
    resp = client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)
    assert resp.status_code == 409


def test_reactivate_restores_to_the_active_list(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-reactivate-flow")
    client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)

    resp = client.post(f"/api/patients/{patient['id']}/reactivate", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["deactivated_at"] is None

    active_list = client.get("/api/patients", headers=headers).json()
    assert patient["id"] in {p["id"] for p in active_list}
    archived_list = client.get("/api/patients?status_filter=archived", headers=headers).json()
    assert patient["id"] not in {p["id"] for p in archived_list}


def test_reactivate_an_already_active_patient_is_rejected_409(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-reactivate-already-active")
    resp = client.post(f"/api/patients/{patient['id']}/reactivate", headers=headers)
    assert resp.status_code == 409


def test_deactivate_writes_a_real_audit_log_entry(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-audit")
    client.post(f"/api/patients/{patient['id']}/deactivate", headers=headers)

    from app.db.base import SessionLocal
    from app.db.models import AuditLog

    session = SessionLocal()
    try:
        entry = session.query(AuditLog).filter(
            AuditLog.target_type == "patient", AuditLog.target_id == patient["id"]
        ).order_by(AuditLog.created_at.desc()).first()
        assert entry is not None
        assert "Deactivated" in entry.action
        assert entry.details == {"active": {"from": True, "to": False}}
    finally:
        session.close()


def test_deactivate_requires_authentication(client, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    patient = _create_patient(client, headers, "TP-TEST-deactivate-noauth")
    resp = client.post(f"/api/patients/{patient['id']}/deactivate")  # no Authorization header
    assert resp.status_code == 401
