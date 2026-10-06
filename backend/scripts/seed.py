"""Idempotent dev seed script — Master Build Doc §8.

Seeds: 1 organization, 5 users (matching the frontend mock names/roles),
the real rules from agent-making/agent/rules/rules.json (each via the
create_rule service, so history v1 + audit are never skipped), 1
app_config row, and Snapshot 0 + rule_sync_state (gap A4 bootstrap).

2026-07-30: reseeded from agent-making's real rule set, replacing the
previous ~24 hand-written placeholder rules (R-001, R-010, etc) — this is
required for app/rule_engine/client.py's real implementation to produce
anything but "not_checkable" fallbacks, since it maps agent-making's
findings back onto backend Rule rows by rule_code, and the old placeholder
codes don't exist in agent-making's rule set at all.

Master Fix Round (Priority 0), 2026-09-08 — CORRECTED: this script only
ever INSERTs new rule_codes, by design (it's the initial-bootstrap path,
run once against a fresh DB) — it deliberately never touches an existing
row's question_text/rule_type/active/etc, because re-running it must stay
side-effect-free against a DB that's already been synced. That insert-only
behavior was previously the ONLY mechanism keeping the DB in sync with
rules.json at all, which is exactly what let question_text (and other
fields) silently go stale every time rules.json was edited afterward
(confirmed real: QA-TEMP-05, HF-01, QA-ACF-03, QA-GIP-01, QA-BIP-03, all
found serving pre-edit DB text during the master checklist audit). The
real fix is scripts/sync_rules_from_agent_making.py, a genuine upsert that
updates an existing row to match rules.json exactly — run that (not this
script) whenever rules.json changes after the initial seed, and run it as
a required step in every deploy (see that script's own docstring for the
proposed mechanism). This script and that one now share one loader
(scripts/_rules_source.py) so the mapping itself can never drift between
the two entry points.

Safe to re-run: every insert is preceded by an existence check on its
natural key, so running this twice creates zero duplicate rows.

Run from backend/:
    .venv/Scripts/python.exe scripts/seed.py
"""
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
from scripts._rules_source import load_rules_from_agent_making as _load_rules_from_agent_making

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
    # notif_from_address: confirmed with Krishna (2026-10-06) -- real Resend
    # account, mail.masterfaster.org already verified as a sending domain.
    # Still admin-editable at runtime via Admin Settings > Notifications
    # (AppConfig.notif_from_address/notif_from_name) -- this only sets the
    # starting value for a FRESH database; an existing, already-seeded
    # environment must set it there instead, since this function no-ops
    # once a row already exists.
    session.add(AppConfig(
        retention_days=settings.retention_days_default,
        notif_from_address="no-reply@mail.masterfaster.org",
    ))
    session.commit()
    print(f"app_config: created 1 row (retention_days={settings.retention_days_default}, "
          f"notif_from_address=no-reply@mail.masterfaster.org)")


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
