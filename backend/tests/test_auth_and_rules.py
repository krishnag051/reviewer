"""Step 4 regression coverage: auth (login, role re-check) and the rules
router (CRUD, admin gate, PATCH ordering + no-op regression, optimistic-lock
helper).
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, text

from app.db.models import AuditLog, RuleSyncState, RuleVersionHistory
from app.optimistic_lock import check_not_stale
from app.security import decode_access_token
from tests.conftest import login, login_headers, make_user, unique_rule_code


def test_login_success(client, seeded_baseline):
    resp = login(client, "m.chen@brightpath-aba.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]

    payload = decode_access_token(body["access_token"])
    assert payload["role"] == "admin"


def test_login_wrong_password_401(client, seeded_baseline):
    resp = login(client, "m.chen@brightpath-aba.com", password="not-the-real-password")
    assert resp.status_code == 401


def test_login_inactive_user_401(db_session, client):
    user = make_user(db_session, role="standard", active=False)
    resp = login(client, user.email)
    assert resp.status_code == 401


def test_authorization_rechecks_db_role_not_stale_jwt_claim(db_session, client):
    user = make_user(db_session, role="admin")
    resp = login(client, user.email)
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    # The token's own claim still says admin — if the authorization gate
    # trusted this claim instead of re-querying, the request below would
    # succeed. It must not.
    payload = decode_access_token(token)
    assert payload["role"] == "admin"

    db_session.execute(text("UPDATE users SET role = 'standard' WHERE id = :id"), {"id": user.id})
    db_session.commit()

    resp = client.post(
        "/rules",
        json={
            "rule_code": unique_rule_code(),
            "category": "Patient Info",
            "question_set": "Treatment Plan",
            "question_text": "should be rejected",
            "rule_type": "structural",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, "demoted user's still-valid token must lose admin access immediately"


def test_get_and_post_rules_as_admin_succeeds(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")

    resp = client.get("/rules", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 24

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    pending_before = sync_state.pending_change_count

    code = unique_rule_code()
    resp = client.post(
        "/rules",
        json={
            "rule_code": code,
            "category": "Patient Info",
            "question_set": "Treatment Plan",
            "question_text": "Admin-created test rule",
            "rule_type": "structural",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    assert resp.json()["rule_code"] == code
    assert resp.json()["current_version"] == 1

    audit_row = db_session.execute(
        select(AuditLog)
        .where(AuditLog.target_type == "rule", AuditLog.target_id == uuid.UUID(resp.json()["id"]))
    ).scalar_one()
    assert audit_row.details["rule_code"]["to"] == code

    # Regression: rule CREATION (not just edits) must count as a pending
    # rule-set change post-bootstrap — this bug shipped silently once
    # (create_rule never bumped pending_change_count), meaning a brand-new
    # rule would never reach a published snapshot until some unrelated edit
    # happened to bump the counter.
    db_session.expire_all()
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == pending_before + 1


def test_post_rules_as_standard_user_403(client, seeded_baseline):
    headers = login_headers(client, "s.patel@brightpath-aba.com")

    resp = client.post(
        "/rules",
        json={
            "rule_code": unique_rule_code(),
            "category": "Patient Info",
            "question_set": "Treatment Plan",
            "question_text": "should be rejected",
            "rule_type": "structural",
        },
        headers=headers,
    )
    assert resp.status_code == 403


def _create_test_rule(client, headers) -> dict:
    code = unique_rule_code()
    resp = client.post(
        "/rules",
        json={
            "rule_code": code,
            "category": "Patient Info",
            "question_set": "Treatment Plan",
            "question_text": "Original text for PATCH tests",
            "rule_type": "structural",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    return resp.json()


def test_patch_rule_with_real_change(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rule = _create_test_rule(client, headers)
    rule_id = uuid.UUID(rule["id"])

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    pending_before = sync_state.pending_change_count

    resp = client.patch(
        f"/rules/{rule_id}",
        json={"question_text": "Updated text — a real change"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_text"] == "Updated text — a real change"
    assert body["current_version"] == 2

    db_session.expire_all()
    history_rows = db_session.execute(
        select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule_id).order_by(RuleVersionHistory.version)
    ).scalars().all()
    assert len(history_rows) == 2
    assert history_rows[0].version == 1
    assert history_rows[0].question_text == "Original text for PATCH tests"  # from creation
    assert history_rows[1].version == 2
    assert history_rows[1].question_text == "Updated text — a real change"  # POST-change state, new version

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == pending_before + 1

    audit_row = db_session.execute(
        select(AuditLog)
        .where(AuditLog.target_type == "rule", AuditLog.target_id == rule_id)
        .order_by(AuditLog.created_at.desc())
    ).scalars().first()
    assert audit_row is not None
    assert audit_row.details["question_text"]["from"] == "Original text for PATCH tests"
    assert audit_row.details["question_text"]["to"] == "Updated text — a real change"


def test_patch_rule_no_op_creates_nothing(client, db_session, seeded_baseline):
    """Regression test for the bug caught while building step 4: a PATCH
    that re-sends the rule's current values must be a true no-op — no
    history row, no version bump, no pending_change_count increment, no
    audit entry. Must never silently come back.
    """
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rule = _create_test_rule(client, headers)
    rule_id = uuid.UUID(rule["id"])

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    pending_before = sync_state.pending_change_count

    history_count_before = len(
        db_session.execute(select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule_id)).scalars().all()
    )
    audit_count_before = len(
        db_session.execute(
            select(AuditLog).where(AuditLog.target_type == "rule", AuditLog.target_id == rule_id)
        ).scalars().all()
    )

    resp = client.patch(
        f"/rules/{rule_id}",
        json={"question_text": rule["question_text"], "category": rule["category"]},  # identical values
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["current_version"] == 1, "no-op PATCH must not bump current_version"

    db_session.expire_all()
    history_count_after = len(
        db_session.execute(select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule_id)).scalars().all()
    )
    assert history_count_after == history_count_before, "no-op PATCH must not write a history row"

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == pending_before, "no-op PATCH must not bump pending_change_count"

    audit_count_after = len(
        db_session.execute(
            select(AuditLog).where(AuditLog.target_type == "rule", AuditLog.target_id == rule_id)
        ).scalars().all()
    )
    assert audit_count_after == audit_count_before, "no-op PATCH must not write an audit entry"


def test_deactivate_and_reactivate_rule(client, db_session, seeded_baseline):
    headers = login_headers(client, "m.chen@brightpath-aba.com")
    rule = _create_test_rule(client, headers)
    rule_id = uuid.UUID(rule["id"])

    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    pending_before = sync_state.pending_change_count

    resp = client.post(f"/rules/{rule_id}/deactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active"] is False
    assert resp.json()["current_version"] == 2

    db_session.expire_all()
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.pending_change_count == pending_before + 1

    # deactivating an already-inactive rule is a no-op
    resp = client.post(f"/rules/{rule_id}/deactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["current_version"] == 2, "deactivating an already-inactive rule must be a no-op"

    resp = client.post(f"/rules/{rule_id}/reactivate", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["active"] is True
    assert resp.json()["current_version"] == 3


def test_no_public_signup_route_exists(client):
    """CLAUDE.md: "No public signup route. Users are created only via
    POST /admin/users." Confirmed as an actual route-existence check, not
    just an assumption from reading app/routers/.
    """
    schema = client.app.openapi()
    for path in schema["paths"]:
        assert "signup" not in path.lower()
        assert "register" not in path.lower()

    for path in ("/auth/signup", "/auth/register", "/users/signup", "/signup"):
        resp = client.post(path, json={"email": "nobody@example.com", "password": "whatever"})
        assert resp.status_code in (404, 405)


def test_expired_jwt_is_rejected(client, seeded_baseline):
    """CLAUDE.md: JWT with 12-hour expiry. An expired token must be rejected
    outright — never silently trusted because the DB-role recheck already
    happened once.
    """
    import jwt as pyjwt

    from app.config import settings
    from app.security import JWT_ALGORITHM

    admin_id = seeded_baseline["m.chen@brightpath-aba.com"]
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": str(admin_id),
        "role": "admin",
        "iat": now - timedelta(hours=13),
        "exp": now - timedelta(hours=1),  # expired an hour ago
    }
    expired_token = pyjwt.encode(expired_payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)

    resp = client.get("/rules", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401


def test_optimistic_lock_helper_accepts_matching_timestamp():
    now = datetime.now(timezone.utc)
    check_not_stale(current_updated_at=now, client_updated_at=now)  # must not raise


def test_optimistic_lock_helper_rejects_stale_timestamp():
    now = datetime.now(timezone.utc)
    stale = now - timedelta(minutes=5)

    try:
        check_not_stale(current_updated_at=now, client_updated_at=stale)
        raise AssertionError("expected HTTPException for a stale updated_at")
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail["error"] == "stale_update"
