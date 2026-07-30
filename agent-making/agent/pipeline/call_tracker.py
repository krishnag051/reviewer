"""Tracks every real Anthropic API call a script makes, at the actual
call boundary — not at the outer "run" boundary. Built after discovering
that a single logical "run" of the pipeline can silently be 1-3 real API
calls (judge.py's evidence_supports_result retry + integrity.py's missing-
rule_id retry both loop on the SAME underlying call), which made a "5 run"
consistency probe actually make ~10+ real calls with no visibility into it
until the bill arrived.

Cost is computed from each call's actual response.usage (real token counts),
not guessed — see PRICING_PER_MTOK below, which must be kept in sync with
the model in judge.py if that ever changes.
"""

# claude-sonnet-5 intro pricing (through 2026-08-31); update if judge.MODEL
# changes or the intro window lapses (see shared model pricing table).
INPUT_COST_PER_MTOK = 2.00
OUTPUT_COST_PER_MTOK = 10.00


class ApiCallCapExceeded(Exception):
    """Raised the instant a script would make a real API call beyond its
    configured cap — before the call happens, not after."""


class ApiCallTracker:
    """Pass one shared instance through run_full_pipeline -> integrity.py ->
    judge.py so every real API call — initial or retry, for whatever reason
    — increments the same counter and is checked against the same cap.
    """

    def __init__(self, max_calls: int | None = None):
        self.max_calls = max_calls
        self.count = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def check_before_call(self) -> None:
        """Call this immediately before making a real API call. Raises
        before the call happens if it would exceed the cap — the cap is
        never breached, not even by one call.
        """
        if self.max_calls is not None and self.count >= self.max_calls:
            raise ApiCallCapExceeded(
                f"Refusing real API call #{self.count + 1}: cap is {self.max_calls}. "
                f"Stopped before making the call, not after."
            )

    def record(self, reason: str, rule_ids: list[str], usage) -> None:
        """Call this immediately after a real API call completes."""
        self.count += 1
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        print(
            f"[API call #{self.count}] {reason} — {len(rule_ids)} rule_id(s): {rule_ids}. "
            f"tokens this call: in={input_tokens} out={output_tokens}. "
            f"Running total: {self.count} call(s)"
            f"{f'/{self.max_calls}' if self.max_calls else ''}, "
            f"~{self.total_input_tokens} in / {self.total_output_tokens} out tokens total, "
            f"est. cost so far: ${self.estimated_cost():.4f}"
        )

    def estimated_cost(self) -> float:
        return (
            self.total_input_tokens / 1_000_000 * INPUT_COST_PER_MTOK
            + self.total_output_tokens / 1_000_000 * OUTPUT_COST_PER_MTOK
        )
