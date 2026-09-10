"""Real upsert sync — Master Fix Round, Priority 0.

Root cause this fixes (confirmed with code, not guessed): the Rules Studio
UI (frontend/src/routes/rules.tsx) and every reviewed-result card
(frontend/src/components/tp/RuleResultCard.tsx) render the DATABASE's
`rules.question_text` column directly -- never agent-making's rules.json.
scripts/seed.py only ever INSERTs a rule_code it hasn't seen before (by
design -- see its own docstring); it was never meant to be, and must not
become, the thing that keeps an EXISTING row's question_text/rule_type/
active in sync with rules.json after the initial seed. Every rule edit
across this whole engagement has gone straight into rules.json on disk,
bypassing PATCH /rules/:id entirely, so the DB row for an edited rule_code
silently kept serving whatever text it was seeded with. Confirmed directly
during the master checklist audit: QA-TEMP-05, HF-01, QA-ACF-03,
QA-GIP-01, and QA-BIP-03 were all found still serving pre-edit DB text
while rules.json itself was already correct.

This script is the real fix: for every rule_code in the CURRENT
rules.json, if a DB row with that rule_code exists, update it (via the
same edit_rule/set_rule_active services PATCH /rules/:id itself uses --
so history v(n+1), audit entry, and rule_sync_state.pending_change_count
are never skipped, exactly like a human edit would produce); if it
doesn't exist, insert it (via create_rule, same as seed.py). Only the
fields agent-making's rules.json actually has values for are synced --
see scripts/_rules_source.py::SYNCED_FIELDS. tp_section/session_notes_only
are deliberately left untouched (no equivalent field in rules.json to
sync them FROM).

What this script deliberately does NOT do: it never deactivates or
removes a DB row whose rule_code no longer appears in rules.json at all
(the AET-01/HF-09-shaped case from an earlier round's production
investigation) -- that's a real, separate decision (a renamed/retired
rule_code needs a human to confirm it's genuinely retired, not silently
auto-deactivated by a sync script), flagged back rather than guessed at
here.

Actor: passes actor_user_id=None to edit_rule/set_rule_active/create_rule
-- same "system/scheduled job" convention the rule_snapshots sync tick's
own audit entries already use. This is not a human editing a rule; it's
this backend catching up to a rules.json change that already happened.

USAGE (run from backend/):
    .venv/Scripts/python.exe scripts/sync_rules_from_agent_making.py           # apply
    .venv/Scripts/python.exe scripts/sync_rules_from_agent_making.py --check   # dry run,
        prints what WOULD change and exits 1 if anything is out of sync (0 if
        already fully in sync) -- for a CI/pre-deploy gate, see the proposed
        mechanism below. Makes zero writes.

PROPOSED MECHANISM so this class of bug cannot recur silently (Priority 0,
part 3 -- a decision for the team, not unilaterally adopted here):
  1. Run this script (no --check) as a required step immediately after
     every `docker compose up -d backend` / `--force-recreate backend`,
     against that same environment's own database -- local, staging, AND
     production each need their own run; the DB is genuinely per-environment,
     a sync against staging's DB does nothing for production's.
  2. Add `--check` as a CI step (or a pre-commit hook) that runs against a
     disposable/test DB seeded from the PREVIOUS commit's rules.json, then
     fails the build if the new commit's rules.json would produce any
     diff -- catching a forgotten sync before merge, not after deploy.
  Whichever of these (or both) the team adopts, rules.json stays the
  source of truth for question_text's actual content; the DB is a synced
  read-replica of it for display/versioning purposes, never edited by hand
  in a way that would need to flow the other direction.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Rule
from app.services.rules import create_rule, edit_rule, set_rule_active
from scripts._rules_source import SYNCED_FIELDS, load_rules_from_agent_making

_CONTENT_FIELDS = [f for f in SYNCED_FIELDS if f != "active"]


def sync_rules(session, *, dry_run: bool) -> dict:
    """Returns a summary dict; makes zero writes if dry_run=True."""
    rules_from_json = load_rules_from_agent_making()
    created: list[str] = []
    updated_content: list[tuple[str, dict]] = []
    updated_active: list[tuple[str, bool, bool]] = []
    unchanged = 0

    for r in rules_from_json:
        existing = session.execute(select(Rule).where(Rule.rule_code == r["rule_code"])).scalar_one_or_none()

        if existing is None:
            if not dry_run:
                create_rule(session, actor_user_id=None, **r)
                session.commit()
            created.append(r["rule_code"])
            continue

        content_diff = {field: r[field] for field in _CONTENT_FIELDS if getattr(existing, field) != r[field]}
        if content_diff:
            if not dry_run:
                edit_rule(session, existing.id, changes=content_diff, actor_user_id=None)
                session.commit()
            updated_content.append((r["rule_code"], content_diff))

        if existing.active != r["active"]:
            if not dry_run:
                set_rule_active(session, existing.id, r["active"], actor_user_id=None)
                session.commit()
            updated_active.append((r["rule_code"], existing.active, r["active"]))

        if not content_diff and existing.active == r["active"]:
            unchanged += 1

    return {
        "created": created,
        "updated_content": updated_content,
        "updated_active": updated_active,
        "unchanged": unchanged,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true",
        help="dry run -- print what would change, make zero writes, exit 1 if anything is out of sync",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        result = sync_rules(session, dry_run=args.check)
    finally:
        session.close()

    print(f"rules: {len(result['created'])} to create, {len(result['updated_content'])} with stale content, "
          f"{len(result['updated_active'])} with stale active status, {result['unchanged']} already in sync"
          + (" (DRY RUN -- no writes made)" if args.check else ""))

    for code in result["created"]:
        print(f"  + would create {code}" if args.check else f"  + created {code}")
    for code, diff in result["updated_content"]:
        fields = ", ".join(diff.keys())
        print(f"  ~ {'would update' if args.check else 'updated'} {code} content ({fields})")
    for code, old, new in result["updated_active"]:
        print(f"  ~ {'would set' if args.check else 'set'} {code} active {old} -> {new}")

    out_of_sync = bool(result["created"] or result["updated_content"] or result["updated_active"])
    if args.check and out_of_sync:
        sys.exit(1)


if __name__ == "__main__":
    main()
