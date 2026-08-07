"""Round 59: provider/model resolution + the OpenRouter call ceiling.
Zero real network calls anywhere in this file -- resolution logic is pure
Python, and the ceiling-block test uses a fake stand-in function (same
technique backend/tests/test_real_api_guardrail.py's own ceiling tests
use), not a real OpenRouter call.
"""
import pytest

from pipeline.model_provider import (
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_OPENROUTER_MODEL,
    CallTracker,
    ModelCallError,
    resolve_provider_and_model,
)


def test_default_with_no_override_and_no_env_is_openrouter_free_model(monkeypatch):
    monkeypatch.delenv("AGENT_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AGENT_LLM_MODEL", raising=False)
    provider, model = resolve_provider_and_model()
    assert provider == "openrouter"
    assert model == DEFAULT_OPENROUTER_MODEL
    assert model == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_env_vars_override_the_default(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("AGENT_LLM_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")
    provider, model = resolve_provider_and_model()
    assert provider == "openrouter"
    assert model == "nvidia/nemotron-3-super-120b-a12b:free"


def test_explicit_override_provider_only():
    provider, model = resolve_provider_and_model("anthropic")
    assert provider == "anthropic"
    assert model == DEFAULT_ANTHROPIC_MODEL


def test_explicit_override_provider_and_model():
    provider, model = resolve_provider_and_model("openrouter:nvidia/nemotron-3-nano-30b-a3b:free")
    assert provider == "openrouter"
    assert model == "nvidia/nemotron-3-nano-30b-a3b:free"


def test_explicit_override_anthropic_with_model():
    provider, model = resolve_provider_and_model("anthropic:claude-sonnet-5")
    assert provider == "anthropic"
    assert model == "claude-sonnet-5"


def test_bare_openrouter_style_model_id_infers_provider_from_shape():
    """No "provider:" prefix at all -- just a raw OpenRouter model id
    (always "<org>/<model>"). Must infer openrouter, not misread the
    model's own trailing ":free" as a provider separator."""
    provider, model = resolve_provider_and_model("nvidia/nemotron-3-ultra-550b-a55b:free")
    assert provider == "openrouter"
    assert model == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_bare_anthropic_style_model_id_infers_provider_from_shape():
    provider, model = resolve_provider_and_model("claude-sonnet-5")
    assert provider == "anthropic"
    assert model == "claude-sonnet-5"


# --------------------------------------------------------------- CallTracker


def test_call_tracker_check_before_call_raises_at_cap():
    tracker = CallTracker(max_calls=2)
    tracker.record(reason="r", provider="openrouter", model="m", usage={"input_tokens": 1, "output_tokens": 1})
    tracker.check_before_call()  # 1/2, still fine
    tracker.record(reason="r", provider="openrouter", model="m", usage={"input_tokens": 1, "output_tokens": 1})
    with pytest.raises(ModelCallError):
        tracker.check_before_call()  # 2/2, refuses the 3rd


def test_call_tracker_uncapped_by_default():
    tracker = CallTracker()
    for _ in range(50):
        tracker.check_before_call()
        tracker.record(reason="r", provider="openrouter", model="m", usage={"input_tokens": 1, "output_tokens": 1})
    assert tracker.count == 50


def test_call_tracker_tracks_calls_by_provider():
    tracker = CallTracker()
    tracker.record(reason="r", provider="openrouter", model="m1", usage={"input_tokens": 1, "output_tokens": 1})
    tracker.record(reason="r", provider="openrouter", model="m2", usage={"input_tokens": 1, "output_tokens": 1})
    tracker.record(reason="r", provider="anthropic", model="m3", usage={"input_tokens": 1, "output_tokens": 1})
    assert tracker.calls_by_provider == {"openrouter": 2, "anthropic": 1}


# ------------------------------------------------ OpenRouter session ceiling


def test_openrouter_ceiling_blocks_the_over_limit_call_before_it_reaches_the_real_function(monkeypatch):
    """Directly exercises conftest.py's own ceiling-wrapping logic with an
    artificially low ceiling and a FAKE stand-in for the real HTTP call --
    proving the (N+1)th call raises BEFORE the underlying function ever
    runs, not merely that it's logged after the fact. Zero real network
    calls -- same technique backend/tests/test_real_api_guardrail.py's own
    ceiling tests use. Saves/restores the shared module state so this
    doesn't affect any other test's own budget.
    """
    import tests.conftest as conftest_module

    original_count = conftest_module._openrouter_call_counter.count
    original_max = conftest_module.MAX_OPENROUTER_CALLS_PER_SESSION
    try:
        conftest_module._openrouter_call_counter.count = 0
        monkeypatch.setattr(conftest_module, "MAX_OPENROUTER_CALLS_PER_SESSION", 2)

        calls_that_actually_ran = []

        def _fake_real_call(*args, **kwargs):
            calls_that_actually_ran.append((args, kwargs))
            return {"arguments": {}, "usage": {"input_tokens": 0, "output_tokens": 0}}

        wrapped = conftest_module._make_ceiling_enforced_openrouter_call(_fake_real_call)

        wrapped()
        wrapped()
        assert len(calls_that_actually_ran) == 2
        assert conftest_module._openrouter_call_counter.count == 2

        with pytest.raises(RuntimeError, match="BLOCKED.*OpenRouter call ceiling"):
            wrapped()

        assert len(calls_that_actually_ran) == 2, (
            "the 3rd (over-ceiling) call must be blocked BEFORE reaching the real function -- "
            "the underlying function's own call count must not have incremented"
        )
        assert conftest_module._openrouter_call_counter.count == 2, "the counter itself must not move past the cap"
    finally:
        conftest_module._openrouter_call_counter.count = original_count
        conftest_module.MAX_OPENROUTER_CALLS_PER_SESSION = original_max
