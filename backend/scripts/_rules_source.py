"""Shared loader: agent-making's rules.json -> this backend's Rule row shape.

Extracted out of seed.py (Master Fix Round, Priority 0) so seed.py (insert-only,
initial bootstrap) and sync_rules_from_agent_making.py (real upsert, this
round's fix) read the exact same mapping and can never silently drift from
each other. Do not duplicate this logic anywhere else.
"""
import json
from pathlib import Path

from app.config import settings

# Relative to backend/, matching app/rule_engine/client.py's own path
# resolution -- kept independent (not imported from there) so scripts in
# this directory have no import-time dependency on that module's
# sys.path/dotenv side effects.
AGENT_MAKING_RULES_JSON = Path(__file__).resolve().parent.parent / settings.agent_making_agent_path / "rules" / "rules.json"

# agent-making's check_type has no equivalent axis in this backend's schema
# (rule_type is structural/semantic/cross_reference, not
# deterministic/judgment) -- this is a judgment call made at the original
# reseed, not a given mapping: "structural" for pattern/field-based
# deterministic checks, "semantic" for meaning-requiring judgment checks.
# cross_reference stays unused, same as before (blocked on the CentralReach
# integration -- see QA-SCH-02's own confirmed gap).
CHECK_TYPE_TO_RULE_TYPE = {"deterministic": "structural", "judgment": "semantic"}

# Fields this loader emits per rule -- also the exact set of fields the sync
# script is allowed to write to an existing DB row. tp_section and
# session_notes_only are deliberately NOT here: they have no equivalent in
# agent-making's rules.json at all (see Rule.tp_section's own docstring --
# "metadata only... never read by any comparison logic"), so there is
# nothing in rules.json to sync them FROM. An automated sync must never
# touch a field it has no real source value for.
SYNCED_FIELDS = ["category", "question_set", "question_text", "rule_type", "payor", "active"]


def load_rules_from_agent_making() -> list[dict]:
    data = json.loads(AGENT_MAKING_RULES_JSON.read_text(encoding="utf-8"))
    return [
        dict(
            rule_code=r["rule_id"],
            category=r["category"],
            # No equivalent field exists in agent-making's rules -- category
            # is reused here rather than inventing a fake grouping.
            question_set=r["category"],
            question_text=r["description"],
            rule_type=CHECK_TYPE_TO_RULE_TYPE[r["check_type"]],
            # "ALL" maps to NULL (this backend's own universal sentinel);
            # any real payor value maps straight through (agent-making's own
            # values are already a subset of this backend's rule_payor enum).
            payor=None if r["applies_to_payor"] == "ALL" else r["applies_to_payor"],
            active=r["active"],
        )
        for r in data["rules"]
    ]
