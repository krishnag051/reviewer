"""Idempotent dev seed script — Master Build Doc §8.

Seeds: 1 organization, 5 users (matching the frontend mock names/roles),
~24 placeholder rules across the six categories (each via the create_rule
service, so history v1 + audit are never skipped), 1 app_config row, and
Snapshot 0 + rule_sync_state (gap A4 bootstrap).

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

# Dev-only default password for every seeded user. Never reuse this in a
# shared/staging/prod environment — it exists purely so a fresh local dev DB
# has working logins on day one.
DEV_PASSWORD = "ChangeMe123!"

USERS = [
    {"name": "M. Chen", "email": "m.chen@brightpath-aba.com", "role": "admin", "credential_title": "BCBA-D"},
    {"name": "S. Patel", "email": "s.patel@brightpath-aba.com", "role": "standard", "credential_title": "BCBA"},
    {"name": "J. Rivera", "email": "j.rivera@brightpath-aba.com", "role": "standard", "credential_title": "BCBA"},
    {"name": "L. Nguyen", "email": "l.nguyen@brightpath-aba.com", "role": "standard", "credential_title": "BCBA"},
    {"name": "A. Thompson", "email": "a.thompson@brightpath-aba.com", "role": "standard", "credential_title": "BCaBA"},
]

# 24 rules, 4 per category, mixed rule_type. Every rule is mandatory — no
# severity tier. cross_reference is deliberately unused — that rule_type is
# blocked on the CentralReach integration per the architecture doc, out of
# scope until that exists.
RULES = [
    # Patient Info
    dict(rule_code="R-001", category="Patient Info", question_set="Treatment Plan",
         question_text="Is the patient's full legal name present on the cover page?",
         rule_type="structural"),
    dict(rule_code="R-002", category="Patient Info", question_set="Treatment Plan",
         question_text="Is the patient's date of birth documented and consistent throughout the plan?",
         rule_type="structural"),
    dict(rule_code="R-003", category="Patient Info", question_set="Treatment Plan",
         question_text="Is the insurance member ID present on the plan?",
         rule_type="structural"),
    dict(rule_code="R-004", category="Patient Info", question_set="Treatment Plan",
         question_text="Is parent/guardian contact information documented?",
         rule_type="structural"),
    # Diagnosis
    dict(rule_code="R-010", category="Diagnosis", question_set="Treatment Plan",
         question_text="Is a current DSM-5 diagnosis of ASD (F84.0) documented?",
         rule_type="semantic"),
    dict(rule_code="R-011", category="Diagnosis", question_set="Treatment Plan",
         question_text="Is the diagnosing provider's name and NPI listed?",
         rule_type="structural"),
    dict(rule_code="R-012", category="Diagnosis", question_set="Treatment Plan",
         question_text="Is the date of diagnosis documented?",
         rule_type="structural"),
    dict(rule_code="R-013", category="Diagnosis", question_set="Treatment Plan",
         question_text="Is relevant medical history or comorbid conditions documented?",
         rule_type="semantic"),
    # Assessment
    dict(rule_code="R-020", category="Assessment", question_set="97151",
         question_text="Is the FBA dated within the last 90 days?",
         rule_type="structural"),
    dict(rule_code="R-021", category="Assessment", question_set="97151",
         question_text="Are standardized assessment tools (VB-MAPP, ABLLS, Vineland) documented with scores?",
         rule_type="semantic"),
    dict(rule_code="R-022", category="Assessment", question_set="97151",
         question_text="Is caregiver/parent input on skill priorities documented?",
         rule_type="semantic"),
    dict(rule_code="R-023", category="Assessment", question_set="97151",
         question_text="Do the assessment results support the recommended service intensity?",
         rule_type="semantic"),
    # Goals & Objectives
    dict(rule_code="R-030", category="Goals & Objectives", question_set="Treatment Plan",
         question_text="Are goals written in measurable, observable terms?",
         rule_type="semantic"),
    dict(rule_code="R-031", category="Goals & Objectives", question_set="Treatment Plan",
         question_text="Does each goal include mastery criteria?",
         rule_type="structural"),
    dict(rule_code="R-032", category="Goals & Objectives", question_set="Treatment Plan",
         question_text="Does each goal include baseline data?",
         rule_type="structural"),
    dict(rule_code="R-033", category="Goals & Objectives", question_set="Treatment Plan",
         question_text="Are short-term objectives linked to long-term goals?",
         rule_type="semantic"),
    # Service Delivery
    dict(rule_code="R-040", category="Service Delivery", question_set="97153",
         question_text="Is the recommended weekly hours of 97153 documented with a specific unit count?",
         rule_type="structural"),
    dict(rule_code="R-041", category="Service Delivery", question_set="97155",
         question_text="Is the recommended weekly hours of 97155 (protocol modification) documented?",
         rule_type="structural"),
    dict(rule_code="R-042", category="Service Delivery", question_set="97156",
         question_text="Is parent training (97156) included with a specific frequency?",
         rule_type="structural"),
    dict(rule_code="R-043", category="Service Delivery", question_set="Treatment Plan",
         question_text="Is the location of services (home, clinic, school) specified?",
         rule_type="structural"),
    # Signatures
    dict(rule_code="R-070", category="Signatures", question_set="Treatment Plan",
         question_text="Is the BCBA signature present and dated?",
         rule_type="structural"),
    dict(rule_code="R-071", category="Signatures", question_set="Treatment Plan",
         question_text="Is the parent/guardian signature present and dated within 30 days of the BCBA signature?",
         rule_type="structural"),
    dict(rule_code="R-072", category="Signatures", question_set="Treatment Plan",
         question_text="Is the BCBA's credential and certification number listed under the signature?",
         rule_type="structural"),
    dict(rule_code="R-073", category="Signatures", question_set="Treatment Plan",
         question_text="If the plan was authored by a BCaBA, is a supervising BCBA co-signature present?",
         rule_type="semantic"),
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
    created = 0
    for r in RULES:
        existing = session.execute(select(Rule).where(Rule.rule_code == r["rule_code"])).scalar_one_or_none()
        if existing is not None:
            continue
        create_rule(session, actor_user_id=actor_user_id, **r)
        session.commit()
        created += 1
    print(f"rules: created {created} row(s), {len(RULES) - created} already existed")


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
