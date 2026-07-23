from app.db.models import RuleResult


def compute_score(rule_results: list[RuleResult]) -> tuple[float | None, str | None]:
    """The one locked-in scoring formula (decided 2026-07-21 — see CLAUDE.md's
    "Decided policy" section): score = pass / (pass + fail) * 100, with NA
    and uncertain excluded from both sides. audit_result = "pass" iff
    score == 100. No severity/critical-fail override clause — severity was
    removed from the schema entirely, so there's nothing left for one to
    trigger on.

    Every consumer that needs a version's score/audit_result must call this
    function — the override recompute-on-final path
    (app/services/rule_results.py) does; finalize (step 8, not yet built)
    must too. Never reimplement this formula inline anywhere else.

    Returns (None, None) if there's nothing scoreable yet — every
    rule_result is still na/uncertain, so pass + fail == 0.
    """
    pass_count = sum(1 for r in rule_results if r.final_status == "pass")
    fail_count = sum(1 for r in rule_results if r.final_status == "fail")
    denominator = pass_count + fail_count
    if denominator == 0:
        return None, None

    score = pass_count / denominator * 100
    audit_result = "pass" if score == 100 else "fail"
    return score, audit_result
