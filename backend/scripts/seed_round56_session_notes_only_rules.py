"""Round 56, Item 5 -- one-time metadata flagging, NOT part of the normal
product seed (run once against a real DB; idempotent -- re-running is a
no-op for any rule already flagged, via edit_rule's own diff-based no-op
convention).

Marks the 3 rule_codes matching Ms. Yachnes's 5 session-note-based checks
(report-date-range match, assessment-type match, assessment-date match,
clinician-location match, patient-location match -- per both Kendra's and
Charny's real checklists) with session_notes_only=True and
tp_section="Assessment of Current Functioning":

- QA-RPT-03 ("Dates of current report match 97151 session notes") --
  report-date-range match. Category is "Report Information", not ACF --
  tp_section is independent of `category`, describing where in the TP this
  check anchors for future agent-wiring purposes, not this rule's own
  checklist grouping.
- QA-ACF-02 ("Note backing assessment matches date/location") -- covers
  THREE of the five named checks at once (assessment-date match,
  clinician-location match, patient-location match): this is currently
  ONE rule in rules.json, not three separate ones, and this round does not
  split it -- that would be rule-authoring, not metadata flagging.
- QA-ACF-08 ("Session note backs testing tool used") -- assessment-type
  match.

Metadata/config only -- zero comparison logic touched, zero agent-making
files touched. Goes through edit_rule (not a raw UPDATE) so this gets a
real rule_version_history row + audit_log entry, same as any other rule
edit -- CLAUDE.md's audit invariant applies here too, even though this is
a one-off script rather than an admin clicking through Rules Studio.

Run from backend/:
    .venv/Scripts/python.exe scripts/seed_round56_session_notes_only_rules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import Rule, User
from app.services.rules import edit_rule

TP_SECTION = "Assessment of Current Functioning"

TARGET_RULE_CODES = ["QA-RPT-03", "QA-ACF-02", "QA-ACF-08"]


def main() -> None:
    session = SessionLocal()
    try:
        admin = session.execute(select(User).where(User.email == "m.chen@brightpath-aba.com")).scalar_one()

        for rule_code in TARGET_RULE_CODES:
            rule = session.execute(select(Rule).where(Rule.rule_code == rule_code)).scalar_one_or_none()
            if rule is None:
                print(f"{rule_code}: NOT FOUND in rules table -- skipping (run scripts/seed.py first?)")
                continue

            result = edit_rule(
                session, rule.id,
                changes={"session_notes_only": True, "tp_section": TP_SECTION},
                actor_user_id=admin.id,
            )
            session.commit()
            print(f"{rule_code}: session_notes_only={result.session_notes_only}, tp_section={result.tp_section!r} (v{result.current_version})")
    finally:
        session.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
