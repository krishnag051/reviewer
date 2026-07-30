"""Diagnostic, not a pytest test (underscore prefix, not collected). Runs the
full pipeline multiple times with zero code changes in between, and reports
per-rule_id agreement across runs.

Cost-guardrail history (why this script looks the way it does now): a
"5 run" invocation of this script previously made ~10+ real API calls
without any visibility into it, because a single logical "run" can itself
be 1-3 real API calls (judge.py's evidence_supports_result retry and
integrity.py's missing-rule_id retry both loop on the same underlying call).
The cap below is therefore on REAL API CALLS, not on "runs" — it can and
will stop mid-run if the cap is hit partway through a retry, rather than
finishing out a run that's already over budget. See pipeline/call_tracker.py.

Usage (from agent-making/agent):
    ../.venv/Scripts/python.exe tests/_consistency_probe.py --n-runs 5 --max-calls 20 [--synthetic]

--synthetic runs against a free, generated-on-the-fly placeholder document
instead of the real Zyaan Ullah TP — use this to verify the script itself
(call counting, capping, logging, partial-result persistence) without
spending real money. Only drop --synthetic once you're confident the
mechanism works and want the real thing.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import run_full_pipeline  # noqa: E402
from pipeline.call_tracker import ApiCallCapExceeded, ApiCallTracker  # noqa: E402

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "rules.json"
REAL_TP_PDF_PATH = Path(__file__).resolve().parent.parent / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"
OUTPUT_PATH = Path(__file__).resolve().parent / "snapshots" / "consistency_probe_results.json"


def _build_synthetic_pdf(path: Path) -> None:
    """Mirrors conftest.py::synthetic_tp_pdf — kept in sync by hand since
    this script runs standalone, outside the pytest fixture system."""
    import fitz

    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "Treatment Plan\nPage 1")
    page1.insert_text((72, 100), "Patient: Test Patient. RBT will provide services. Signature: BCBA, John Smith, 01/02/2026.")
    page1.insert_text((72, 750), "Page 1 of 3")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Treatment Plan\nPage 2")
    page2.insert_text(
        (72, 100),
        "Place of service: home. 97151: 4 hrs. Current level: baseline. "
        "This page also documents observation notes and preference assessment results for the review.",
    )
    page2.insert_text((72, 750), "Page 2 of 3")

    doc.new_page()  # nearly-blank page, stands in for an image-only page

    doc.save(str(path))
    doc.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-runs", type=int, default=5, help="Target number of independent full-pipeline runs.")
    parser.add_argument("--max-calls", type=int, required=True, help="Hard cap on total real API calls across the whole script — required, no default, so this is never run without a deliberately-chosen ceiling.")
    parser.add_argument("--synthetic", action="store_true", help="Use a free generated placeholder document instead of the real TP.")
    parser.add_argument(
        "--rule-ids",
        type=str,
        default=None,
        help="Comma-separated rule_ids to scope the run to (e.g. for probing just the rules known to disagree), instead of all rules in rules.json.",
    )
    parser.add_argument(
        "--pdf-path",
        type=str,
        default=None,
        help="Path to a real TP PDF to use instead of the default sample_tps/Ullah_Zyaan_Redacted.pdf. Ignored if --synthetic is set.",
    )
    args = parser.parse_args()

    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]

    if args.rule_ids:
        target_ids = {rid.strip() for rid in args.rule_ids.split(",") if rid.strip()}
        rules = [r for r in rules if r["rule_id"] in target_ids]
        missing = target_ids - {r["rule_id"] for r in rules}
        if missing:
            print(f"WARNING: rule_id(s) not found in rules.json, skipping: {sorted(missing)}", file=sys.stderr)
        print(f"Scoped to {len(rules)} rule_id(s): {sorted(r['rule_id'] for r in rules)}\n")

    if args.synthetic:
        pdf_path = Path(__file__).resolve().parent / "snapshots" / "_tmp_synthetic_for_probe.pdf"
        _build_synthetic_pdf(pdf_path)
    elif args.pdf_path:
        pdf_path = Path(args.pdf_path)
        if not pdf_path.exists():
            print(f"PDF not found at {pdf_path}", file=sys.stderr)
            sys.exit(1)
    else:
        if not REAL_TP_PDF_PATH.exists():
            print(f"Real TP not found at {REAL_TP_PDF_PATH}", file=sys.stderr)
            sys.exit(1)
        pdf_path = REAL_TP_PDF_PATH

    tracker = ApiCallTracker(max_calls=args.max_calls)
    print(f"Starting: target {args.n_runs} run(s), hard cap {args.max_calls} real API call(s), "
          f"document={'synthetic placeholder' if args.synthetic else pdf_path.name}.\n")

    runs = []
    stopped_early = False
    for i in range(args.n_runs):
        print(f"Run {i + 1}/{args.n_runs}...", flush=True)
        try:
            result = run_full_pipeline(str(pdf_path), rules, tracker=tracker)
        except ApiCallCapExceeded as e:
            print(f"\nSTOPPED: {e}")
            print(f"Completed {len(runs)}/{args.n_runs} full run(s) before hitting the call cap.")
            stopped_early = True
            break
        runs.append({rule_id: entry["result"] for rule_id, entry in result["findings"].items()})
        print(f"  done ({len(runs[-1])} rule_ids)\n", flush=True)

        OUTPUT_PATH.write_text(
            json.dumps({
                "n_runs_completed": len(runs),
                "n_runs_requested": args.n_runs,
                "stopped_early_on_call_cap": False,
                "total_api_calls": tracker.count,
                "estimated_cost": tracker.estimated_cost(),
                "runs": runs,
            }, indent=2),
            encoding="utf-8",
        )

    if args.synthetic:
        pdf_path.unlink(missing_ok=True)

    if not runs:
        print("No complete runs — nothing to analyze.")
        return

    all_rule_ids = sorted(set().union(*(r.keys() for r in runs)))

    per_rule = {}
    for rule_id in all_rule_ids:
        results_across_runs = [run.get(rule_id, "<MISSING>") for run in runs]
        counts = Counter(results_across_runs)
        per_rule[rule_id] = {
            "results": results_across_runs,
            "counts": dict(counts),
            "unanimous": len(counts) == 1,
        }

    unstable = {rid: v for rid, v in per_rule.items() if not v["unanimous"]}
    stable = {rid: v for rid, v in per_rule.items() if v["unanimous"]}

    OUTPUT_PATH.write_text(
        json.dumps({
            "n_runs_completed": len(runs),
            "n_runs_requested": args.n_runs,
            "stopped_early_on_call_cap": stopped_early,
            "total_api_calls": tracker.count,
            "estimated_cost": tracker.estimated_cost(),
            "per_rule": per_rule,
        }, indent=2),
        encoding="utf-8",
    )

    print(f"\n{'=' * 70}")
    print(f"Completed {len(runs)}/{args.n_runs} run(s) using {tracker.count}/{args.max_calls} real API call(s), "
          f"est. total cost ${tracker.estimated_cost():.4f}.")
    print(f"{len(stable)}/{len(all_rule_ids)} rule_ids unanimous across all {len(runs)} completed run(s).")
    print(f"{len(unstable)}/{len(all_rule_ids)} rule_ids disagreed at least once:\n")
    for rule_id in sorted(unstable, key=lambda r: -max(unstable[r]["counts"].values())):
        counts = unstable[rule_id]["counts"]
        counts_str = ", ".join(f"{n}/{len(runs)} {result}" for result, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"  {rule_id}: {counts_str}")

    print(f"\nFull per-run data written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
