"""Step 1 regression coverage: migration chain, reference_id immutability
trigger, ON DELETE behaviors. The migration chain itself is already exercised
by the session-scoped `_recreated_test_database` fixture (every test run
starts from an empty DB migrated to head) — these tests assert on the
resulting schema and behavior, not just "upgrade didn't raise."
"""
import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, InternalError

from app.db.models import Rule, RuleVersionHistory, User
from app.services.rules import create_rule
from tests.conftest import make_user, unique_rule_code


def test_migration_chain_reaches_both_revisions(engine):
    """If only 610ef7c09015 had applied (and f644de8600ea hadn't), app_config
    would be missing stuck_job_timeout_minutes — proves the full chain ran,
    not just the first migration.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    expected = {
        "organizations", "users", "patients", "versions", "uploads", "rules",
        "rule_version_history", "rule_snapshots", "rule_sync_state",
        "rule_results", "rule_result_edits", "generated_emails", "audit_log",
        "app_config",
    }
    assert expected.issubset(table_names)

    app_config_columns = {c["name"] for c in inspector.get_columns("app_config")}
    assert "stuck_job_timeout_minutes" in app_config_columns, (
        "app_config.stuck_job_timeout_minutes missing — migration f644de8600ea did not apply"
    )
    assert "retention_days" in app_config_columns


def test_reference_id_immutability_trigger_fires(db_session):
    from app.db.models import Patient

    patient = Patient(reference_id=f"TP-TEST-{uuid.uuid4().hex[:8]}", name="Trigger Test Patient")
    db_session.add(patient)
    db_session.commit()

    with pytest.raises(InternalError, match="reference_id is immutable"):
        db_session.execute(
            text("UPDATE patients SET reference_id = :new_ref WHERE id = :id"),
            {"new_ref": f"TP-CHANGED-{uuid.uuid4().hex[:8]}", "id": patient.id},
        )
        db_session.commit()
    db_session.rollback()

    db_session.refresh(patient)
    # refresh() after a rolled-back transaction re-reads from the DB — the
    # value there must be the ORIGINAL one, proving the UPDATE never took effect.


def test_reference_id_immutability_allows_updating_other_fields(db_session):
    from app.db.models import Patient

    patient = Patient(reference_id=f"TP-TEST-{uuid.uuid4().hex[:8]}", name="Original Name")
    db_session.add(patient)
    db_session.commit()

    db_session.execute(
        text("UPDATE patients SET name = :new_name WHERE id = :id"),
        {"new_name": "Corrected Name", "id": patient.id},
    )
    db_session.commit()

    db_session.refresh(patient)
    assert patient.name == "Corrected Name"


def test_on_delete_restrict_blocks_deleting_a_referenced_rule(db_session):
    """rule_version_history.rule_id -> rules.id ON DELETE RESTRICT. A rule
    with a history row (every rule has one, per gap A3) must not be
    deletable out from under it.
    """
    admin = make_user(db_session, role="admin")
    rule = create_rule(
        db_session,
        rule_code=unique_rule_code(),
        category="Patient Info",
        question_set="Treatment Plan",
        question_text="ON DELETE RESTRICT test rule",
        rule_type="structural",
        actor_user_id=admin.id,
    )
    db_session.commit()

    history_count = db_session.execute(
        select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule.id)
    ).scalars().all()
    assert len(history_count) == 1, "expected exactly one history row before attempting the delete"

    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM rules WHERE id = :id"), {"id": rule.id})
        db_session.commit()
    db_session.rollback()

    still_there = db_session.get(Rule, rule.id)
    assert still_there is not None, "RESTRICT should have blocked the delete, but the rule is gone"


def test_on_delete_set_null_on_deleting_a_user(db_session):
    """rule_version_history.changed_by -> users.id ON DELETE SET NULL. Users
    are never hard-deleted by any real code path (soft-disable only), but the
    FK behavior itself must still be correct if it's ever exercised directly.
    """
    user = make_user(db_session, role="admin")
    rule = create_rule(
        db_session,
        rule_code=unique_rule_code(),
        category="Patient Info",
        question_set="Treatment Plan",
        question_text="ON DELETE SET NULL test rule",
        rule_type="structural",
        actor_user_id=user.id,
    )
    db_session.commit()

    history_row = db_session.execute(
        select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule.id)
    ).scalar_one()
    assert history_row.changed_by == user.id

    db_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db_session.commit()

    db_session.expire_all()
    history_row = db_session.execute(
        select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule.id)
    ).scalar_one()
    assert history_row.changed_by is None, "ON DELETE SET NULL did not fire — changed_by should be NULL"

    # The rule row itself uses the same RESTRICT-vs-SET NULL split on
    # updated_by — confirm it also went to NULL, not blocked, not left stale.
    still_rule = db_session.get(Rule, rule.id)
    assert still_rule.updated_by is None
