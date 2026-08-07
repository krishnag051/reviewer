"""Shared pytest fixtures.

Round 62 -- real-Anthropic-call guardrail (closes the actual gap, not just
one command): before this round, the ONLY thing standing between this
suite and a real, billed Anthropic call was
`HAS_ANTHROPIC_CREDENTIALS = bool(os.environ.get("ANTHROPIC_API_KEY") ...)`
inside test_regression_snapshot.py / test_regression_ground_truth.py --
which is backwards, since a real key is REQUIRED to be in `.env` for this
repo's normal (non-test) use, so its mere presence was sufficient to let
live tests run for real. Confirmed live this round: running the full
suite with a real key in `.env` actually reached the real API and spent
real money (~$0.13), the second such near-miss in this project (the first
was backend's Round 55-56 `pytest -k` incident, which is exactly why
backend/tests/conftest.py already has this pattern -- Round 44). This is
agent-making's own equivalent, adapted to ITS seam.

Unlike backend (one funnel function, `client.review_treatment_plan`),
agent-making has FOUR independent real-Anthropic call sites (judge.py,
model_provider.py, supporting_doc_extraction.py,
supporting_doc_resolution.py), all of which do `client =
anthropic.Anthropic()` and then call `.messages.create(...)` or
`.messages.stream(...)`. Rather than patch each call site individually
(fragile -- a 5th call site added later would silently slip through), this
patches the actual `anthropic.Anthropic` class itself, for every test, by
default -- so no matter which module instantiates a client, the instance
it gets back has its `.messages.create`/`.messages.stream` methods replaced
with something that raises immediately, before any network I/O. This is
autouse and runs regardless of whether ANTHROPIC_API_KEY is set in the
environment -- the credential being valid/present is no longer a factor at
all in whether a test can reach the real API.

The one deliberate escape hatch: `@pytest.mark.real_api` on a specific
test. When present, this fixture stands down for that test ONLY. Same as
backend's identical rule: the marker existing on a test, or that test
having run before, is NOT itself permission -- running any real_api-marked
test still needs the user's separate, per-instance go-ahead in chat first,
exact command and cost stated, every single time.

Going forward: no blanket `pytest tests/` or `pytest -k "..."` invocations
in this suite either (same reasoning as backend's identical rule) -- only
exact, individually-named node IDs. This fixture makes that a belt-and-
suspenders protection rather than the only protection, but the naming
discipline stays required regardless, since a fuzzy filter can still pull
in a real_api-marked test whose marker was (wrongly) treated as standing
permission by a future round that didn't read this docstring.

Round 59 -- OpenRouter call ceiling: this repo's own equivalent of the
backend's ceiling, scoped to agent-making's test suite. Not "block
everything by default" the way the guard above is -- OpenRouter's free
model is the SANCTIONED default for building/testing, real calls to it are
expected and fine. What this guards against is a runaway retry loop
hammering OpenRouter's rate limits: every real call through
pipeline/model_provider.py's call_tool_json (regardless of which module
made it) increments one shared, session-wide counter and raises BEFORE the
(N+1)th call past MAX_OPENROUTER_CALLS_PER_SESSION would ever go out.

synthetic_tp_pdf is a synthetic, generated-on-the-fly placeholder used by
tests that check specific pipeline mechanics against known, controlled
content (e.g. exact page-flagging behavior) — keep using it for those.

real_tp_pdf points at the actual Zyaan Ullah TP now that it's in the repo
(agent/sample_tps/Ullah_Zyaan_Redacted.pdf) — this is what the regression
snapshot test uses, since a real document is what makes that test a
meaningful gate instead of one that runs on near-empty synthetic pages.

reeda_tp_pdf / charny_tp_pdf back test_regression_ground_truth.py (2026-07-28
round, item 4). Deliberately NOT copied into the repo like Ullah_Zyaan's
file: unlike that one (filename says "_Redacted"), these two documents
contain real, unredacted PHI (real patient name, DOB, insurance ID) — these
fixtures point at their existing external location instead, and skip (not
fail) if that location isn't present on the machine running the suite. If
these should become permanent, durable, repo-committed fixtures the way
Ullah_Zyaan's is, that needs a deliberate redaction pass first and is a call
for a human to make, not something to do silently while building a test
harness.
"""
import os
from pathlib import Path

import anthropic
import fitz
import pytest


# --- Round 62: real-Anthropic-call guardrail (see module docstring above) --


class BlockedRealAnthropicCallError(Exception):
    """Raised the instant test code would make a real, billed Anthropic API
    call — before any network I/O happens, not after. If you're seeing this
    and you DID mean to make a real call, mark that specific test
    `@pytest.mark.real_api` AND get the user's explicit, per-instance
    approval first — the marker alone is never permission."""


class _BlockedAnthropicMessages:
    def create(self, *args, **kwargs):
        raise BlockedRealAnthropicCallError(
            "BLOCKED by tests/conftest.py's autouse real-Anthropic guardrail: "
            "client.messages.create(...) was about to make a REAL, BILLED call to the Anthropic API. "
            "This is blocked by default for every test, regardless of whether a real ANTHROPIC_API_KEY is "
            "present in .env. To run a real call on purpose, mark the specific test @pytest.mark.real_api "
            "AND get the user's explicit, per-instance approval in chat first (exact command + cost estimate) "
            "— the marker existing is not itself permission."
        )

    def stream(self, *args, **kwargs):
        raise BlockedRealAnthropicCallError(
            "BLOCKED by tests/conftest.py's autouse real-Anthropic guardrail: "
            "client.messages.stream(...) was about to make a REAL, BILLED call to the Anthropic API. "
            "This is blocked by default for every test, regardless of whether a real ANTHROPIC_API_KEY is "
            "present in .env. To run a real call on purpose, mark the specific test @pytest.mark.real_api "
            "AND get the user's explicit, per-instance approval in chat first (exact command + cost estimate) "
            "— the marker existing is not itself permission."
        )


class _BlockedAnthropicClient:
    """Stands in for the real anthropic.Anthropic class. Accepts any
    constructor args (real callers pass none, e.g. `anthropic.Anthropic()`,
    but this doesn't assume that) and exposes just enough surface
    (`.messages.create`/`.stream`) to intercept every one of this repo's
    four real call sites without needing to know about a fifth one added
    later — anything that does `anthropic.Anthropic()` then
    `.messages.create(...)`/`.stream(...)` is caught by construction.
    """

    def __init__(self, *args, **kwargs):
        self.messages = _BlockedAnthropicMessages()


@pytest.fixture(autouse=True)
def _block_real_anthropic_calls(request, monkeypatch):
    if request.node.get_closest_marker("real_api"):
        # The ONE escape hatch — see module docstring. Standing down here
        # does not itself mean the user approved this run; that approval
        # must already have happened in chat before this test was invoked.
        return
    monkeypatch.setattr(anthropic, "Anthropic", _BlockedAnthropicClient)

# --- Round 59: OpenRouter call ceiling (see module docstring above) --------

MAX_OPENROUTER_CALLS_PER_SESSION = int(os.environ.get("MAX_OPENROUTER_CALLS_PER_SESSION", "20"))


class _OpenRouterCallCounter:
    """Module-level, not per-fixture -- survives across every test in one
    pytest session, same reason backend/tests/conftest.py's own
    _real_api_call_counter is module-level (a per-test fixture would reset
    to 0 every test and never actually cap the SESSION total)."""

    def __init__(self):
        self.count = 0


_openrouter_call_counter = _OpenRouterCallCounter()


def _make_ceiling_enforced_openrouter_call(real_fn):
    def _wrapper(*args, **kwargs):
        if _openrouter_call_counter.count >= MAX_OPENROUTER_CALLS_PER_SESSION:
            raise RuntimeError(
                f"BLOCKED by tests/conftest.py's OpenRouter call ceiling: "
                f"{MAX_OPENROUTER_CALLS_PER_SESSION} real OpenRouter call(s) already made this session -- "
                f"refusing to make another before it goes out. Raise MAX_OPENROUTER_CALLS_PER_SESSION "
                f"(env var) if this run genuinely needs more."
            )
        result = real_fn(*args, **kwargs)
        _openrouter_call_counter.count += 1
        print(
            f"[openrouter-ceiling] real OpenRouter calls this session: "
            f"{_openrouter_call_counter.count}/{MAX_OPENROUTER_CALLS_PER_SESSION}"
        )
        return result
    return _wrapper


@pytest.fixture(autouse=True)
def _enforce_openrouter_ceiling(monkeypatch):
    """Wraps pipeline.model_provider._call_openrouter -- the ONE real HTTP
    call site for the default provider (see that module's own docstring)
    -- for every test in this suite, regardless of which module actually
    calls call_tool_json(). Re-armed fresh each test (monkeypatch reverts
    the wrapping after each test), but _openrouter_call_counter itself is
    module-level and persists, so the cap holds across the whole session
    regardless of test order.
    """
    import pipeline.model_provider as model_provider

    monkeypatch.setattr(
        model_provider, "_call_openrouter", _make_ceiling_enforced_openrouter_call(model_provider._call_openrouter),
    )
    yield


REAL_TP_PDF_PATH = Path(__file__).parent.parent / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"
REEDA_TP_PDF_PATH = Path(r"C:\Users\DELL\OneDrive - Master Faster\Desktop\Re_ Examples of the TP's required\Reeda B S Review.pdf")
CHARNY_TP_PDF_PATH = Path(r"C:\Users\DELL\OneDrive - Master Faster\Desktop\charmy\Charny Gluck TP Feedback.pdf")


@pytest.fixture
def real_tp_pdf() -> str:
    if not REAL_TP_PDF_PATH.exists():
        pytest.skip(f"Real TP not present at {REAL_TP_PDF_PATH} — drop it in to run this test.")
    return str(REAL_TP_PDF_PATH)


@pytest.fixture
def reeda_tp_pdf() -> str:
    if not REEDA_TP_PDF_PATH.exists():
        pytest.skip(f"Reeda's TP not present at {REEDA_TP_PDF_PATH} on this machine.")
    return str(REEDA_TP_PDF_PATH)


@pytest.fixture
def charny_tp_pdf() -> str:
    if not CHARNY_TP_PDF_PATH.exists():
        pytest.skip(f"Charny's TP not present at {CHARNY_TP_PDF_PATH} on this machine.")
    return str(CHARNY_TP_PDF_PATH)


@pytest.fixture
def synthetic_tp_pdf(tmp_path) -> str:
    """A minimal multi-page PDF: two pages with real text, one nearly-blank
    page standing in for an image-only page (e.g. a goal graph).
    """
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

    # Nearly-blank page — stands in for an image-only page (e.g. a goal graph)
    doc.new_page()

    path = tmp_path / "synthetic_tp.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)
