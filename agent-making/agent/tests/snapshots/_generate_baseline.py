"""Deliberately regenerate the regression snapshot baseline against the real
Zyaan Ullah TP. NOT collected by pytest (underscore prefix) and never invoked
automatically by the test suite — run this by hand only when a change to the
pipeline is an intentional fix whose new results should become the new
baseline.

Usage (from agent-making/agent):
    ../.venv/Scripts/python.exe tests/snapshots/_generate_baseline.py "a one-line reason"

Requires ANTHROPIC_API_KEY (loaded from agent-making/.env via judge.py) and
agent/sample_tps/Ullah_Zyaan_Redacted.pdf to be present.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pipeline import run_full_pipeline  # noqa: E402

RULES_PATH = Path(__file__).resolve().parent.parent.parent / "rules" / "rules.json"
REAL_TP_PDF_PATH = Path(__file__).resolve().parent.parent.parent / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "zyaan_ullah_baseline.json"


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} \"one-line reason for this snapshot update\"", file=sys.stderr)
        sys.exit(1)
    reason = sys.argv[1]

    if not REAL_TP_PDF_PATH.exists():
        print(f"Real TP not found at {REAL_TP_PDF_PATH}", file=sys.stderr)
        sys.exit(1)

    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]

    result = run_full_pipeline(str(REAL_TP_PDF_PATH), rules)
    results_by_rule_id = {rule_id: entry["result"] for rule_id, entry in result["findings"].items()}

    snapshot = {
        "_reason": reason,
        "results": dict(sorted(results_by_rule_id.items())),
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(results_by_rule_id)} rule_id results to {SNAPSHOT_PATH}")


if __name__ == "__main__":
    main()
