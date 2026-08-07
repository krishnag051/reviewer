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
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

DEFAULT_OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"  # matches judge.py's MODEL

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_TIMEOUT_SECONDS = 120


class ModelCallError(Exception):
    """Wraps a real failure from either provider's call site (HTTP error,
    missing tool_call in the response, etc.) into one exception type
    callers can catch regardless of which provider actually ran."""


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
    """
    provider, model = resolve_provider_and_model(model_override)
    tracker.check_before_call()

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
        raise ModelCallError(f"OpenRouter call failed: {response.status_code} {response.text[:500]}")

    body = response.json()
    if "choices" not in body or not body["choices"]:
        # A 200 status doesn't guarantee a usable body -- e.g. OpenRouter's
        # free tier can return a 200 with an `error` object instead of
        # `choices` under rate-limiting/provider-side issues. Surface the
        # real body rather than a bare KeyError, so this is diagnosable
        # from the first failure instead of needing a live re-run to see
        # what actually came back.
        raise ModelCallError(f"OpenRouter response had no usable 'choices' (status 200): {json.dumps(body)[:800]}")
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
