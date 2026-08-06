"""Idempotent dev seed script — Master Build Doc §8.

Seeds: 1 organization, 5 users (matching the frontend mock names/roles),
the 120 real rules from agent-making/agent/rules/rules.json (each via the
create_rule service, so history v1 + audit are never skipped), 1
app_config row, and Snapshot 0 + rule_sync_state (gap A4 bootstrap).

2026-07-30: reseeded from agent-making's real rule set, replacing the
previous ~24 hand-written placeholder rules (R-001, R-010, etc) — this is
required for app/rule_engine/client.py's real implementation to produce
anything but "not_checkable" fallbacks, since it maps agent-making's
findings back onto backend Rule rows by rule_code, and the old placeholder
codes don't exist in agent-making's rule set at all. NOT a hard delete of
the old rows — this script only ever INSERTs (idempotent by rule_code) —
so a dev DB that already has the old 24 seeded will end up with BOTH sets
present unless someone separately deactivates the old ones by hand. A
fresh DB (this round's own verification, and any new dev setup) only ever
sees the real 120.

Safe to re-run: every insert is preceded by an existence check on its
natural key, so running this twice creates zero duplicate rows.

Run from backend/:
    .venv/Scripts/python.exe scripts/seed.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.config import settings
from app.db.base import SessionLocal
from app.db.models import AppConfig, Organization, Rule, User
from app.security import hash_password
from app.services.rule_snapshots import bootstrap_snapshot_zero
from app.services.rules import create_rule

# Relative to this backend/ directory, matching app/rule_engine/client.py's
# own path resolution -- kept independent (not imported from there) so this
# script has no import-time dependency on that module's sys.path/dotenv
# side effects.
_AGENT_MAKING_RULES_JSON = Path(__file__).resolve().parent.parent / settings.agent_making_agent_path / "rules" / "rules.json"

# agent-making's check_type has no equivalent axis in this backend's schema
# (rule_type is structural/semantic/cross_reference, not
# deterministic/judgment) -- this is a judgment call made for this reseed,
# not a given mapping: "structural" for pattern/field-based deterministic
# checks, "semantic" for meaning-requiring judgment checks. cross_reference
# stays unused, same as before (blocked on the CentralReach integration).
_CHECK_TYPE_TO_RULE_TYPE = {"deterministic": "structural", "judgment": "semantic"}


def _load_rules_from_agent_making() -> list[dict]:
    data = json.loads(_AGENT_MAKING_RULES_JSON.read_text(encoding="utf-8"))
    return [
        dict(
            rule_code=r["rule_id"],
            category=r["category"],
            # No equivalent field exists in agent-making's rules -- category
            # is reused here rather than inventing a fake grouping.
            question_set=r["category"],
            question_text=r["description"],
            rule_type=_CHECK_TYPE_TO_RULE_TYPE[r["check_type"]],
            # Round 50: seeded from agent-making's own applies_to_payor for a
            # real initial value rather than leaving every rule NULL --
            # "ALL" maps to NULL (this backend's own universal sentinel,
            # matching the pre-existing mock's "ALL"), any real payor value
            # maps straight through (agent-making's own values are already
            # a subset of this backend's 10-value rule_payor enum). This is
            # a one-time seed convenience, not a live link -- editing payor
            # here afterward never reaches agent-making's rules.json.
            payor=None if r["applies_to_payor"] == "ALL" else r["applies_to_payor"],
            active=r["active"],
        )
        for r in data["rules"]
    ]

# Dev-only default password for every seeded user. Never reuse this in a
# shared/staging/prod environment — it exists purely so a fresh local dev DB
# has working logins on day one.
DEV_PASSWORD = "ChangeMe123!"

USERS = [
    # 2026-07-31: three flat roles (admin/user/developer), no
    # BCBA/Facilitator-specific naming -- "standard" renamed to "user" in
    # the same round (migration b66328017716). None of the seeded staff
    # get "developer" by default; that role is for whoever's actually doing
    # dev/diagnostics work, provisioned separately via POST /admin/users.
    {"name": "M. Chen", "email": "m.chen@brightpath-aba.com", "role": "admin", "credential_title": "BCBA-D"},
    {"name": "S. Patel", "email": "s.patel@brightpath-aba.com", "role": "user", "credential_title": "BCBA"},
    {"name": "J. Rivera", "email": "j.rivera@brightpath-aba.com", "role": "user", "credential_title": "BCBA"},
    {"name": "L. Nguyen", "email": "l.nguyen@brightpath-aba.com", "role": "user", "credential_title": "BCBA"},
    {"name": "A. Thompson", "email": "a.thompson@brightpath-aba.com", "role": "user", "credential_title": "BCaBA"},
]

def seed_organization(session) -> None:
    if session.execute(select(Organization)).first() is not None:
        print("organizations: already seeded, skipping")
        return
    session.add(Organization(name="Master Faster", region="US"))
    session.commit()
    print("organizations: created 1 row")


def seed_users(session) -> dict[str, User]:
    by_email: dict[str, User] = {}
    created = 0
    for u in USERS:
        existing = session.execute(select(User).where(User.email == u["email"])).scalar_one_or_none()
        if existing is not None:
            by_email[u["email"]] = existing
            continue
        user = User(
            name=u["name"],
            email=u["email"],
            password_hash=hash_password(DEV_PASSWORD),
            role=u["role"],
            credential_title=u["credential_title"],
            active=True,
        )
        session.add(user)
        session.commit()
        by_email[u["email"]] = user
        created += 1
    print(f"users: created {created} row(s), {len(USERS) - created} already existed")
    return by_email


def seed_rules(session, *, actor_user_id) -> None:
    rules = _load_rules_from_agent_making()
    created = 0
    for r in rules:
        existing = session.execute(select(Rule).where(Rule.rule_code == r["rule_code"])).scalar_one_or_none()
        if existing is not None:
            continue
        create_rule(session, actor_user_id=actor_user_id, **r)
        session.commit()
        created += 1
    print(f"rules: created {created} row(s), {len(rules) - created} already existed")


def seed_app_config(session) -> None:
    if session.execute(select(AppConfig)).first() is not None:
        print("app_config: already seeded, skipping")
        return
    session.add(AppConfig(retention_days=settings.retention_days_default))
    session.commit()
    print(f"app_config: created 1 row (retention_days={settings.retention_days_default})")


def seed_snapshot_zero(session) -> None:
    state = bootstrap_snapshot_zero(session)
    session.commit()
    print(f"rule_sync_state: current_snapshot_id={state.current_snapshot_id}")


def main() -> None:
    session = SessionLocal()
    try:
        seed_organization(session)
        users_by_email = seed_users(session)
        admin = users_by_email["m.chen@brightpath-aba.com"]
        seed_rules(session, actor_user_id=admin.id)
        seed_app_config(session)
        seed_snapshot_zero(session)  # after rules — Snapshot 0 reflects whatever rules exist now
    finally:
        session.close()
    print("\nSeed complete.")
    print(f"Dev login password for all seeded users: {DEV_PASSWORD}")


if __name__ == "__main__":
    main()
