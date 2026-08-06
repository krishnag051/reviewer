"""Step 2 regression coverage: the seed script's idempotency and content.

Rule/history/snapshot assertions here are scoped to the specific rule_codes
the seed script creates (agent-making's real rule set, as of 2026-07-30 —
previously a 24-rule hand-written placeholder set), never to "every row in
the table" — other test files legitimately create their own extra rules
with unique codes, and pytest's default collection order runs some of those
files before this one alphabetically. Scoping by rule_code keeps these
assertions correct regardless of execution order.

Counts/distributions below are computed from the same loader the seed
script itself uses (`_load_rules_from_agent_making`), not hardcoded — this
tracks agent-making's actual rule count automatically rather than needing a
hand-update here every time that rule set changes.
"""
from sqlalchemy import func, select

from app.db.models import AppConfig, Organization, Rule, RuleSnapshot, RuleSyncState, RuleVersionHistory, User
from scripts.seed import (
    _load_rules_from_agent_making,
    seed_app_config,
    seed_organization,
    seed_rules,
    seed_snapshot_zero,
    seed_users,
)

SEEDED_RULES = _load_rules_from_agent_making()
SEEDED_RULE_CODES = {r["rule_code"] for r in SEEDED_RULES}


def test_seed_is_idempotent(db_session, seeded_baseline):
    def counts():
        return {
            "organizations": db_session.execute(select(func.count()).select_from(Organization)).scalar_one(),
            "seeded_users": db_session.execute(
                select(func.count()).select_from(User).where(User.email.in_(
                    ["m.chen@brightpath-aba.com", "s.patel@brightpath-aba.com", "j.rivera@brightpath-aba.com",
                     "l.nguyen@brightpath-aba.com", "a.thompson@brightpath-aba.com"]
                ))
            ).scalar_one(),
            "seeded_rules": db_session.execute(
                select(func.count()).select_from(Rule).where(Rule.rule_code.in_(SEEDED_RULE_CODES))
            ).scalar_one(),
            "app_config": db_session.execute(select(func.count()).select_from(AppConfig)).scalar_one(),
            "rule_sync_state": db_session.execute(select(func.count()).select_from(RuleSyncState)).scalar_one(),
        }

    before = counts()

    # Re-run every seed step exactly as scripts/seed.py:main() does.
    seed_organization(db_session)
    users_by_email = seed_users(db_session)
    admin = users_by_email["m.chen@brightpath-aba.com"]
    seed_rules(db_session, actor_user_id=admin.id)
    seed_app_config(db_session)
    seed_snapshot_zero(db_session)

    after = counts()
    assert after == before, f"seed script created duplicates on re-run: before={before} after={after}"


def test_app_config_retention_days_default_is_30(db_session, seeded_baseline):
    """CLAUDE.md: app_config.retention_days default is 30, not the schema's
    original 10 — a wider window to notice a mistaken finalize before
    sibling PDFs are actually purged. Confirms the actual seeded value, not
    just that the column exists.
    """
    app_config = db_session.execute(select(AppConfig)).scalar_one()
    assert app_config.retention_days == 30


def test_all_seeded_rules_present_with_expected_distribution(db_session, seeded_baseline):
    rules = db_session.execute(select(Rule).where(Rule.rule_code.in_(SEEDED_RULE_CODES))).scalars().all()
    assert len(rules) == len(SEEDED_RULES)

    by_rule_type = {}
    for r in rules:
        by_rule_type[r.rule_type] = by_rule_type.get(r.rule_type, 0) + 1

    expected_by_rule_type = {}
    for r in SEEDED_RULES:
        expected_by_rule_type[r["rule_type"]] = expected_by_rule_type.get(r["rule_type"], 0) + 1
    assert by_rule_type == expected_by_rule_type
    assert "cross_reference" not in by_rule_type, "unused — blocked on the CentralReach integration"
    assert not hasattr(Rule, "severity"), "severity column should be fully removed, not just unused"

    rule_codes = {r.rule_code for r in rules}
    assert rule_codes == SEEDED_RULE_CODES


def test_every_seeded_rule_has_exactly_one_history_row_at_version_1(db_session, seeded_baseline):
    rules = db_session.execute(select(Rule).where(Rule.rule_code.in_(SEEDED_RULE_CODES))).scalars().all()
    assert len(rules) == len(SEEDED_RULES)
    for rule in rules:
        history_rows = db_session.execute(
            select(RuleVersionHistory).where(RuleVersionHistory.rule_id == rule.id)
        ).scalars().all()
        assert len(history_rows) == 1, f"{rule.rule_code} has {len(history_rows)} history rows, expected 1"
        assert history_rows[0].version == 1
        assert rule.current_version == 1


def test_snapshot_zero_and_sync_state_exist_with_all_seeded_rules(db_session, seeded_baseline):
    sync_state = db_session.execute(select(RuleSyncState)).scalar_one()
    assert sync_state.current_snapshot_id is not None

    # Snapshot 0 is, by definition, the earliest-created snapshot — this
    # holds regardless of whether a later test's sync tick has since moved
    # current_snapshot_id on to something newer (published snapshots never
    # change, so Snapshot 0's own content is permanent either way).
    snapshot_zero = db_session.execute(
        select(RuleSnapshot).order_by(RuleSnapshot.created_at.asc()).limit(1)
    ).scalar_one()
    assert len(snapshot_zero.rule_ids_and_versions) == len(SEEDED_RULES)
    versions_used = {entry["version"] for entry in snapshot_zero.rule_ids_and_versions}
    assert versions_used == {1}

    seeded_rule_ids = {
        str(r.id)
        for r in db_session.execute(select(Rule).where(Rule.rule_code.in_(SEEDED_RULE_CODES))).scalars().all()
    }
    snapshot_rule_ids = {entry["rule_id"] for entry in snapshot_zero.rule_ids_and_versions}
    assert snapshot_rule_ids == seeded_rule_ids

    seeded_rule_ids = {
        str(r.id)
        for r in db_session.execute(select(Rule).where(Rule.rule_code.in_(SEEDED_RULE_CODES))).scalars().all()
    }
    snapshot_rule_ids = {entry["rule_id"] for entry in snapshot_zero.rule_ids_and_versions}
    assert snapshot_rule_ids == seeded_rule_ids
