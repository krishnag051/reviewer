"""Round 70, Item 1 — apply the real, hand-authored question text in
_round70_questions.py to every matching Rule row's question_text, via the
real app.services.rules.edit_rule() helper (not raw SQL) so this gets a
proper rule_version_history row, an audit_log entry, and a
pending_change_count bump like any other rule edit -- same discipline as
every other mutation in this codebase.

Deliberately does NOT touch agent-making/agent/rules/rules.json's own
"description" field -- that's what judge.py/fields.py's real judgment
prompts read; rewriting it risks changing real judgment behavior, which is
out of scope for a frontend-display round. This only changes what the
BACKEND shows a human, via Rule.question_text.

Run from backend/ with the venv active:
    .venv/Scripts/python.exe scripts/apply_round70_questions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Rule, User
from app.services.rule_sync import run_sync_tick
from app.services.rules import edit_rule
from scripts._round70_questions import QUESTIONS


def main() -> None:
    session = SessionLocal()
    try:
        admin = session.execute(select(User).where(User.email == "m.chen@brightpath-aba.com")).scalar_one()

        rules_by_code = {r.rule_code: r for r in session.execute(select(Rule)).scalars().all()}
        matched, edited, unchanged, missing = 0, 0, 0, []

        for rule_code, question in QUESTIONS.items():
            rule = rules_by_code.get(rule_code)
            if rule is None:
                missing.append(rule_code)
                continue
            matched += 1
            before = rule.question_text
            result = edit_rule(session, rule.id, changes={"question_text": question}, actor_user_id=admin.id)
            if result is not None and rule.question_text != before:
                edited += 1
            else:
                unchanged += 1

        session.commit()
        print(f"Matched {matched}/{len(QUESTIONS)} authored questions to real Rule rows.")
        print(f"Edited (question_text actually changed): {edited}")
        print(f"Unchanged (already had this exact text): {unchanged}")
        if missing:
            print(f"NOT FOUND in rules table (rule_code mismatch): {missing}")

        # Rule edits only reach new uploads once a snapshot publishes them --
        # same as every other rule-content edit. Publish one now so this
        # round's own verification (a real upload) sees the new question text.
        run_sync_tick(session)
        session.commit()
        from app.db.models import RuleSnapshot, RuleSyncState
        sync_state = session.execute(select(RuleSyncState)).scalar_one()
        latest = session.get(RuleSnapshot, sync_state.current_snapshot_id)
        print(f"Current snapshot after sync tick: {latest.id} ({len(latest.rule_ids_and_versions)} rules pinned)")
    finally:
        session.close()


if __name__ == "__main__":
    main()
