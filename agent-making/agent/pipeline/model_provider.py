"""Round 59: a single, explicit provider/model selection point, so no call
site in this pipeline hardcodes "call Anthropic" anymore. Two providers:

- "openrouter" (the DEFAULT, for all building and automated/CI testing) --
  routes through OpenRouter's OpenAI-compatible REST API via plain
  `requests` (no new SDK dependency). Model defaults to
  `nvidia/nemotron-3-ultra-550b-a55b:free` -- confirmed live against
  OpenRouter's own /api/v1/models list this round: real, current,
  `pricing: {"prompt": "0", "completion": "0"}`, and
  `supported_parameters` includes `"tools"`/`"tool_choice"` (function-
  calling capable, which the extraction step needs for structured JSON
  output). Genuinely free -- $0 regardless of call volume -- but still
  call-ceiling-limited below so a runaway retry loop can't hammer
  OpenRouter's rate limits.
- "anthropic" -- the real, billed path. Never the default, never invoked
  by anything in this round's own tests or build steps. Reachable only via
  an explicit `model_override` a human passes deliberately -- same
  standing rule as every other round: no real Anthropic call without
  stating the exact command/count/cost and getting per-instance approval
  in chat FIRST. This module doesn't add a runtime block on top of that
  (the existing project discipline is "mock the boundary in tests, ask
  before running for real" -- see judge.py/supporting_doc_extraction.py),
  but it does mean the default can never accidentally reach Anthropic:
  you have to name it.

`model_override` accepts either:
- `None` -- use the env-configured default (AGENT_LLM_PROVIDER /
  AGENT_LLM_MODEL, both optional; falls back to "openrouter" + the free
  Nemotron model above if unset).
- `"openrouter"` / `"anthropic"` -- provider only, default model for that
  provider.
- `"openrouter:<model-id>"` / `"anthropic:<model-id>"` -- explicit
  provider AND model, e.g. `"openrouter:nvidia/nemotron-3-super-120b-a12b:free"`
  or `"anthropic:claude-sonnet-5"`.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"  # matches judge.py's MODEL

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT_SECONDS = 120

# Live incident (2026-08): OpenRouter's free-tier shared worker pool
# returned "Upstream error from Nvidia: ResourceExhausted: Worker local
# total request limit reached (32/32)" -- wrapped in a 200-status response
# with no `choices`, so _call_openrouter correctly raised, but as a PLAIN
# ModelCallError indistinguishable from a genuinely broken request (bad
# schema, bad API key). That's the wrong bucket: a shared-pool capacity
# wall is transient by nature -- the identical request will very likely
# succeed seconds later once a worker frees up. These substrings are
# matched case-insensitively against the raw error body/message; keep
# this list narrow and evidence-based (only patterns actually observed or
# clearly documented as transient-by-nature) rather than broad enough to
# accidentally swallow a real, permanent failure.
_TRANSIENT_ERROR_MARKERS = (
    "resourceexhausted",
    "worker local total request limit reached",
    "rate limit",
    "rate_limit",
    "too many requests",
    "temporarily unavailable",
    "try again later",
    "overloaded",
)


class ModelCallError(Exception):
    """Wraps a real failure from either provider's call site (HTTP error,
    missing tool_call in the response, etc.) into one exception type
    callers can catch regardless of which provider actually ran."""


class TransientModelCallError(ModelCallError):
    """A ModelCallError whose underlying cause looks like a temporary,
    shared-capacity problem on the PROVIDER'S side (worker pool exhausted,
    rate-limited, "try again"), not a real problem with this specific
    request. Distinguished from the plain ModelCallError superclass so
    call_tool_json's retry loop can retry ONLY this kind -- a genuinely
    malformed request or an auth failure raises the plain
    ModelCallError instead and is never retried here."""


def _is_transient_error_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _TRANSIENT_ERROR_MARKERS)


def resolve_provider_and_model(model_override: str | None = None) -> tuple[str, str]:
    """Pure resolution logic, no call made here. Returns (provider, model)."""
    if model_override:
        if ":" in model_override and "/" not in model_override.split(":", 1)[0]:
            # "provider:model" -- but guard against OpenRouter's OWN model
            # ids that contain a colon (e.g. "...:free") being misread as
            # "provider:model". A real provider prefix is always exactly
            # "openrouter" or "anthropic", never containing a "/".
            provider, _, model = model_override.partition(":")
            if provider in ("openrouter", "anthropic"):
                return provider, model or _default_model_for(provider)
        if model_override in ("openrouter", "anthropic"):
            return model_override, _default_model_for(model_override)
        # A bare model id with no recognized "provider:" prefix -- infer
        # from shape. OpenRouter ids are always "<org>/<model>"; Anthropic
        # ids never contain "/".
        provider = "openrouter" if "/" in model_override else "anthropic"
        return provider, model_override

    provider = os.environ.get("AGENT_LLM_PROVIDER", "openrouter")
    model = os.environ.get("AGENT_LLM_MODEL") or _default_model_for(provider)
    return provider, model


def _default_model_for(provider: str) -> str:
    return DEFAULT_OPENROUTER_MODEL if provider == "openrouter" else DEFAULT_ANTHROPIC_MODEL


def call_tool_json(
    *,
    prompt_text: str,
    tool_name: str,
    tool_description: str,
    input_schema: dict,
    tracker: "CallTracker",
    model_override: str | None = None,
    max_tokens: int = 4096,
    call_reason: str = "call",
    max_transient_retries: int = 2,
    backoff_seconds: float = 1.0,
    sleep_fn=time.sleep,
) -> dict[str, Any]:
    """The one call site both session_note_extraction.py's extraction step
    and any future comparison-adjacent reasoning should use -- dispatches
    to whichever provider resolve_provider_and_model() picks, and returns
    the tool call's parsed `arguments`/`input` dict either way, so callers
    never need to know which provider actually ran.

    `tracker` must support `.check_before_call()` (raise before an
    over-ceiling call) and `.record(reason, provider, model, usage)`
    (after a successful call) -- see CallTracker below. Always called,
    regardless of provider, so the SAME ceiling covers both.

    Live incident fix (2026-08): a TransientModelCallError (a provider-
    side, shared-capacity failure -- see the module docstring's marker
    list) is now retried up to `max_transient_retries` times (default 2,
    i.e. 3 total attempts) with short exponential backoff
    (`backoff_seconds * 2**attempt` -- 1s, then 2s by default) before
    being allowed to propagate. A plain ModelCallError (a genuinely broken
    request -- bad schema, bad API key, malformed response shape) is
    NEVER retried here and raises immediately on the first attempt,
    unchanged from before this fix -- retrying a permanently-broken
    request would just waste the same number of calls for the same
    guaranteed failure, and would risk masking a real problem as if it
    were transient.

    `sleep_fn` defaults to `time.sleep` but is a real parameter so tests
    can inject a fake, instant sleep and assert on the backoff schedule
    without a real test actually waiting seconds.
    """
    provider, model = resolve_provider_and_model(model_override)

    attempt = 0
    while True:
        tracker.check_before_call()
        try:
            if provider == "openrouter":
                result = _call_openrouter(
                    model=model, prompt_text=prompt_text, tool_name=tool_name,
                    tool_description=tool_description, input_schema=input_schema, max_tokens=max_tokens,
                )
            elif provider == "anthropic":
                result = _call_anthropic(
                    model=model, prompt_text=prompt_text, tool_name=tool_name,
                    tool_description=tool_description, input_schema=input_schema, max_tokens=max_tokens,
                )
            else:
                raise ModelCallError(f"Unknown provider {provider!r} (expected 'openrouter' or 'anthropic')")
        except TransientModelCallError as exc:
            if attempt >= max_transient_retries:
                raise
            wait = backoff_seconds * (2 ** attempt)
            attempt += 1
            print(
                f"[model-provider] transient upstream failure on attempt {attempt}/{max_transient_retries + 1} "
                f"({provider}:{model}, reason={call_reason!r}): {exc}. Retrying in {wait:.1f}s..."
            )
            sleep_fn(wait)
            continue
        break

    tracker.record(reason=call_reason, provider=provider, model=model, usage=result["usage"])
    return result["arguments"]


def _call_openrouter(
    *, model: str, prompt_text: str, tool_name: str, tool_description: str, input_schema: dict, max_tokens: int,
) -> dict:
    """The actual `requests.post` -- kept as its own function (not inlined
    into call_tool_json) so tests can monkeypatch exactly this one seam,
    same convention as this project's judge.py tests monkeypatch
    `judge.anthropic.Anthropic` at its own single seam.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ModelCallError("OPENROUTER_API_KEY is not set (checked agent-making/.env and the process environment)")

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt_text}],
        "tools": [{
            "type": "function",
            "function": {"name": tool_name, "description": tool_description, "parameters": input_schema},
        }],
        "tool_choice": {"type": "function", "function": {"name": tool_name}},
    }
    response = requests.post(
        OPENROUTER_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=OPENROUTER_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        error_cls = TransientModelCallError if (
            response.status_code in (429, 502, 503) or _is_transient_error_text(response.text)
        ) else ModelCallError
        raise error_cls(f"OpenRouter call failed: {response.status_code} {response.text[:500]}")

    body = response.json()
    if "choices" not in body or not body["choices"]:
        # A 200 status doesn't guarantee a usable body -- e.g. OpenRouter's
        # free tier can return a 200 with an `error` object instead of
        # `choices` under rate-limiting/provider-side issues. Surface the
        # real body rather than a bare KeyError, so this is diagnosable
        # from the first failure instead of needing a live re-run to see
        # what actually came back. Confirmed live incident (2026-08): this
        # exact shape -- {"error": {"message": "Upstream error from
        # Nvidia: ResourceExhausted: Worker local total request limit
        # reached (32/32)", "code": 502}} -- is a transient shared-pool
        # capacity wall, not a broken request; raise the retryable
        # subclass when the body's own text matches that pattern.
        body_text = json.dumps(body)
        error_cls = TransientModelCallError if _is_transient_error_text(body_text) else ModelCallError
        raise error_cls(f"OpenRouter response had no usable 'choices' (status 200): {body_text[:800]}")
    choice = body["choices"][0]
    tool_calls = choice.get("message", {}).get("tool_calls") or []
    if not tool_calls:
        raise ModelCallError(
            f"OpenRouter response had no tool_calls (finish_reason={choice.get('finish_reason')!r}); "
            f"message content: {choice.get('message', {}).get('content')!r}"
        )
    arguments_raw = tool_calls[0]["function"]["arguments"]
    arguments = json.loads(arguments_raw) if isinstance(arguments_raw, str) else arguments_raw

    usage = body.get("usage") or {}
    return {
        "arguments": arguments,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _call_anthropic(
    *, model: str, prompt_text: str, tool_name: str, tool_description: str, input_schema: dict, max_tokens: int,
) -> dict:
    """The real, billed path -- structurally identical shape to every
    other real Anthropic call site in this pipeline (judge.py,
    supporting_doc_extraction.py). Never invoked by this round's own code
    or tests; only reachable via an explicit model_override a human passes
    on purpose, per the standing per-instance-approval rule.
    """
    import anthropic

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        tools=[{"name": tool_name, "description": tool_description, "input_schema": input_schema}],
        tool_choice={"type": "tool", "name": tool_name},
        messages=[{"role": "user", "content": prompt_text}],
    )
    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    return {
        "arguments": tool_use_block.input,
        "usage": {
            "input_tokens": getattr(response.usage, "input_tokens", 0),
            "output_tokens": getattr(response.usage, "output_tokens", 0),
        },
    }


class CallTracker:
    """Round 59's OpenRouter-and-Anthropic-agnostic call tracker -- separate
    from call_tracker.py's ApiCallTracker (which is Anthropic-pricing-
    specific: INPUT_COST_PER_MTOK/OUTPUT_COST_PER_MTOK only make sense for
    the real billed path). This one tracks call COUNT for a cap regardless
    of provider, and cost only when the provider actually charges anything
    (OpenRouter's free-tier calls are always $0 by construction -- pricing
    is looked up per-provider, not assumed).
    """

    def __init__(self, max_calls: int | None = None):
        self.max_calls = max_calls
        self.count = 0
        self.calls_by_provider: dict[str, int] = {}
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def check_before_call(self) -> None:
        if self.max_calls is not None and self.count >= self.max_calls:
            raise ModelCallError(
                f"Refusing call #{self.count + 1}: cap is {self.max_calls}. Stopped before making the call, not after."
            )

    def record(self, *, reason: str, provider: str, model: str, usage: dict) -> None:
        self.count += 1
        self.calls_by_provider[provider] = self.calls_by_provider.get(provider, 0) + 1
        self.total_input_tokens += usage.get("input_tokens", 0)
        self.total_output_tokens += usage.get("output_tokens", 0)
        print(
            f"[model-provider] call #{self.count} ({provider}:{model}, reason={reason!r}) -- "
            f"tokens in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}. "
            f"Running total: {self.count}{f'/{self.max_calls}' if self.max_calls else ''} "
            f"({self.calls_by_provider})"
        )
