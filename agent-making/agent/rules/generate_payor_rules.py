"""Generates each additional payor's rule file from rules.json — never
hand-write a duplicate.

rules.json is the single source of truth for every rule, universal AND
payor-specific (Healthfirst's HF-01/02/03, Straight Medicaid's SM-01/02,
etc. all live there, under their own applies_to_payor value). This script
just filters and exports a reference copy per payor: every applies_to_payor
"ALL" rule, plus that payor's own applies_to_payor-matching rules — nothing
is hand-duplicated here. Healthfirst has no generated file because the
master rules.json already reads naturally payor-agnostic; these exports
exist purely for payors where seeing "my rules in one file" is convenient.

Usage (from agent-making/agent):
    ../.venv/Scripts/python.exe rules/generate_payor_rules.py
"""
import json
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent
SOURCE_PATH = RULES_DIR / "rules.json"

# One entry per additional payor to generate a reference export for.
# Healthfirst has no generated file — see the module docstring above; the
# master rules.json already reads naturally payor-agnostic for it. Every
# other payor in the official 9-payor scope (Project1_Full_Build_Scope.docx)
# gets one, plus New York Medicaid (real, working, but not one of the
# official 9).
GENERATED_PAYORS = {
    "aetna.json": "Aetna",
    "anthem.json": "Anthem",
    "cigna.json": "Cigna",
    "emblem.json": "Emblem",
    "empire.json": "Empire",
    "molina.json": "Molina",
    "mvp.json": "MVP",
    "straight_medicaid.json": "Straight Medicaid",
    "new_york_medicaid.json": "New York Medicaid",
}


def main() -> None:
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    all_rules = source["rules"]
    universal_rules = [r for r in all_rules if r["applies_to_payor"] == "ALL"]

    for filename, payor in GENERATED_PAYORS.items():
        payor_specific_rules = [r for r in all_rules if r["applies_to_payor"] == payor]
        rules = universal_rules + payor_specific_rules
        output = {
            "payor": payor,
            "rule_count": len(rules),
            "_generated_from": SOURCE_PATH.name,
            "_generated_warning": (
                "AUTO-GENERATED — do not hand-edit this file. Edit rules.json "
                "(the applies_to_payor:'ALL' rules, or this payor's own "
                f"applies_to_payor:'{payor}' rules) and re-run "
                "generate_payor_rules.py instead."
            ),
            "rules": rules,
        }
        out_path = RULES_DIR / filename
        out_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {len(rules)} rule(s) ({len(universal_rules)} universal + "
              f"{len(payor_specific_rules)} payor-specific) to {out_path.name}")


if __name__ == "__main__":
    main()
