"""Step 6 of the pipeline (Section 4): rule-id coverage check. Diffs the
rule_ids returned by the judgment layer against the rule_ids sent. A gap is
a hard failure, not a warning — reject and retry, per the design doc.
"""
from . import judge


class IntegrityError(Exception):
    """Raised when the judgment layer drops one or more rule_ids, even after
    retrying. This must never be silently swallowed.
    """


def missing_rule_ids(sent_rule_ids: list[str], results: dict[str, dict]) -> list[str]:
    return [rid for rid in sent_rule_ids if rid not in results]


def run_judgment_with_integrity_check(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    max_retries: int = 2,
    tracker=None,
) -> dict[str, dict]:
    """Calls judge.run_judgment_checks, and on any missing rule_id, retries
    only for the missing subset, up to max_retries times. Raises
    IntegrityError (hard failure) if gaps remain after retrying.

    `tracker` (an ApiCallTracker) is forwarded to every real call this makes
    — the initial one and every retry. This is the ONLY place retries are
    triggered, so it's the one place that must never make a real call
    without checking the tracker's cap first (judge.py checks too, but the
    reason string here is what makes the resulting log line tell you *why*
    a given call happened, not just that it did).
    """
    sent_ids = [r["rule_id"] for r in judgment_rules]
    results = judge.run_judgment_checks(judgment_rules, fields, rendered_images, tracker=tracker, call_reason="initial batch")

    attempt = 0
    while True:
        missing = missing_rule_ids(sent_ids, results)
        if not missing:
            return results
        attempt += 1
        if attempt > max_retries:
            raise IntegrityError(
                f"Judgment layer failed to return {len(missing)} rule_id(s) after "
                f"{max_retries} retries: {missing}. Rejecting — this is a hard "
                f"failure, not a warning."
            )
        retry_rules = [r for r in judgment_rules if r["rule_id"] in missing]
        retry_results = judge.run_judgment_checks(
            retry_rules,
            fields,
            rendered_images,
            tracker=tracker,
            call_reason=f"retry {attempt}/{max_retries} (missing or evidence_supports_result=false in previous response)",
        )
        results.update(retry_results)
