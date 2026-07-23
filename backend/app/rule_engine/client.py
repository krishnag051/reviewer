from sqlalchemy.orm import Session

from app.db.models import RuleSnapshot
from app.rule_engine.contract import RuleResultDraft


def run_rule_checks(
    session: Session, upload_id: str, snapshot_id: str, parsed_pages: list[dict]
) -> list[RuleResultDraft]:
    """HOLLOW — deliberately. Real rule-checking logic is built in a separate
    repo against `contract.py`; this backend never contains it (see
    CLAUDE.md's Boundaries section). Returns one stub draft per
    {rule_id, version} pair pinned in the snapshot — reads the snapshot's own
    frozen `rule_ids_and_versions`, not the live `rules` table, since the
    snapshot (not "whatever rules currently say") is what this upload's
    results must forever be interpretable against.
    """
    snapshot = session.get(RuleSnapshot, snapshot_id)
    return [
        RuleResultDraft(
            rule_id=entry["rule_id"],
            rule_version_used=entry["version"],
            model_status="na",
            model_finding="(agent not yet implemented)",
            model_pages=[],
            model_source_quote=None,
        )
        for entry in snapshot.rule_ids_and_versions
    ]
