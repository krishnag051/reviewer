"""Step 6 of the pipeline (Section 4): rule-id coverage check. Diffs the
rule_ids returned by the judgment layer against the rule_ids sent. A gap is
a real problem, not a warning — retried, and never silently guessed at.

REAL BUG FOUND AND FIXED (2026-08, live incident): a persistently-missing
rule_id (confirmed case: QA-GIP-11) used to raise IntegrityError all the
way up through run_full_pipeline -> pipeline.api.review_treatment_plan,
which turned the ENTIRE review into `{"status": "failed"}` -- discarding
every other rule_id's real, already-computed, perfectly good finding along
with it. A real backend upload lost all 143 other rules' results over ONE
rule the judgment layer couldn't confidently answer after retrying. That's
a wildly disproportionate failure mode: the fix is not to give up and
throw away everything, and it's also not to guess a pass/fail for the
stubborn rule -- it's to mark ONLY that rule_id "not_checkable" (an honest
"couldn't determine," the same vocabulary this pipeline already uses for
every other genuine "no confident answer" case) and let every other rule's
real result through untouched. See run_judgment_with_integrity_check's own
docstring below for the mechanics.
"""
from . import judge

NOT_CHECKABLE_AFTER_RETRIES_TEMPLATE = (
    "The judgment layer could not produce a confirmed answer for this rule after "
    "{attempts} attempt(s) (dropped from the self-consistency check each time, or "
    "internally rejected as evidence_supports_result=false). Flagged not_checkable "
    "rather than guessed at or silently omitted."
)


class IntegrityError(Exception):
    """Retained for callers/tests that want to distinguish this failure
    mode by type, and for genuinely catastrophic cases (e.g. every single
    rule_id missing, which would mean something is badly broken with the
    call itself, not just one hard rule) -- see
    run_judgment_with_integrity_check's own docstring for exactly when
    this still raises vs. when it degrades gracefully instead.
    """


def missing_rule_ids(sent_rule_ids: list[str], results: dict[str, dict]) -> list[str]:
    return [rid for rid in sent_rule_ids if rid not in results]


def run_judgment_with_integrity_check(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    max_retries: int = 2,
    tracker=None,
    model_override: str | None = None,
) -> dict[str, dict]:
    """Calls judge.run_judgment_checks, and on any missing rule_id, retries
    only for the missing subset, up to max_retries times.

    FIXED (live incident, 2026-08): if any rule_id is STILL missing after
    exhausting retries, this used to raise IntegrityError unconditionally
    -- which propagated all the way up and discarded every OTHER rule_id's
    real, already-computed finding along with it (one stubborn rule
    nuking a real, paid-for review of everything else). Now:
    - If EVERY sent rule_id is missing (0 real answers came back at all),
      that's a sign the call mechanism itself is broken, not that one
      hard rule tripped up the model -- still raises IntegrityError, same
      as before, since there's nothing real to salvage.
    - Otherwise, each rule_id still missing after max_retries gets a real,
      honest "not_checkable" finding (NOT_CHECKABLE_AFTER_RETRIES_TEMPLATE)
      instead of a raised exception -- never a guessed pass/fail, and
      never silently dropped either (this print line, plus the finding's
      own distinctive evidence text, make it visible both in logs and in
      the final result). Every other rule_id's real answer is returned
      untouched.

    `tracker` (an ApiCallTracker) is forwarded to every real call this makes
    — the initial one and every retry. This is the ONLY place retries are
    triggered, so it's the one place that must never make a real call
    without checking the tracker's cap first (judge.py checks too, but the
    reason string here is what makes the resulting log line tell you *why*
    a given call happened, not just that it did).

    `model_override` (Round 61) is forwarded unchanged to every judge.py
    call this makes — defaults to None, which keeps this function's
    behavior identical to before this round for every caller that doesn't
    pass it (see judge.py's own docstring on this same parameter).
    """
    sent_ids = [r["rule_id"] for r in judgment_rules]
    results = judge.run_judgment_checks(
        judgment_rules, fields, rendered_images, tracker=tracker, call_reason="initial batch",
        model_override=model_override,
    )

    attempt = 0
    while True:
        missing = missing_rule_ids(sent_ids, results)
        if not missing:
            return results
        attempt += 1
        if attempt > max_retries:
            if len(missing) >= len(sent_ids):
                raise IntegrityError(
                    f"Judgment layer failed to return ANY of the {len(sent_ids)} rule_id(s) sent, "
                    f"after {max_retries} retries. Rejecting — this looks like the call mechanism "
                    f"itself is broken, not one hard rule, so there is nothing real to salvage."
                )
            print(
                f"[integrity] {len(missing)} rule_id(s) never returned a confirmed answer after "
                f"{max_retries} retries: {missing}. Marking not_checkable and returning every OTHER "
                f"rule_id's real result — NOT raising, so one stubborn rule doesn't discard everything "
                f"else this review already correctly computed."
            )
            for rule_id in missing:
                results[rule_id] = {
                    "result": "not_checkable",
                    "evidence": NOT_CHECKABLE_AFTER_RETRIES_TEMPLATE.format(attempts=max_retries + 1),
                    "page": None,
                    "confidence": 0.0,
                }
            return results
        retry_rules = [r for r in judgment_rules if r["rule_id"] in missing]
        retry_results = judge.run_judgment_checks(
            retry_rules,
            fields,
            rendered_images,
            tracker=tracker,
            call_reason=f"retry {attempt}/{max_retries} (missing or evidence_supports_result=false in previous response)",
            model_override=model_override,
        )
        results.update(retry_results)
