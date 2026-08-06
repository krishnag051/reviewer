"""Round 52 — zero-cost proof that the supporting-document extraction call
site (pipeline/supporting_doc_extraction.py) is (a) wired correctly into
api.py's orchestration so extracted data reaches both rule-checking layers,
and (b) automatically covered by the same ApiCallTracker cap/ceiling every
other real call in this pipeline goes through — per Round 52 Step 3's
explicit instructions. Mocks anthropic.Anthropic at the same seam
test_call_tracker_wiring.py already established (judge.anthropic.Anthropic),
plus the analogous seam in supporting_doc_extraction.py
(supporting_doc_extraction.anthropic.Anthropic) — so the real
check_before_call/record code in both modules actually executes.

Uses a tiny, hand-built 1-rule ruleset (monkeypatching api._load_rules)
instead of the real 114-rule rules.json, so the fake judgment response only
ever needs to answer for one rule_id — avoids coupling this test's fakes to
however many judgment rules happen to exist in rules.json right now.

Zero real API calls, zero cost — per the standing rule against spending real
money to verify a cost guardrail.
"""
import fitz
import pytest

from pipeline import api, judge
from pipeline.call_tracker import ApiCallTracker
from pipeline.supporting_doc_extraction import SUPPORTING_DOC_FIELDS

TINY_RULES = [
    {
        "rule_id": "J-1",
        "active": True,
        "applies_to_plan_type": "Both",
        "applies_to_payor": "ALL",
        "check_type": "judgment",
        "category": "Test",
        "description": "d",
        "notes": None,
    }
]


class _FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class _FakeResponse:
    def __init__(self, tool_input, stop_reason="tool_use"):
        self.content = [_FakeToolUseBlock(tool_input)]
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeStreamCM:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get_final_message(self):
        return self._response


class _FakeJudgeMessages:
    """Mimics judge.py's client.messages.stream(...) usage. Tracked
    separately from _FakeExtractionMessages below because judge.py and
    supporting_doc_extraction.py each import their own `anthropic` module
    reference, but `import anthropic` resolves to the exact same module
    object in both -- monkeypatching `judge.anthropic.Anthropic` and
    `supporting_doc_extraction.anthropic.Anthropic` separately patches the
    SAME attribute on the SAME object twice, so whichever install call runs
    second wins for both call sites. The fix is one shared fake client
    exposing both `.stream()` (judge.py) and `.create()`
    (supporting_doc_extraction.py) on the same `.messages`, installed with
    a single patch -- see _install_fake_anthropic below.
    """

    def __init__(self, stream_response_fn, create_response_fn):
        self._stream_fn = stream_response_fn
        self._create_fn = create_response_fn
        self.stream_call_count = 0
        self.create_call_count = 0

    def stream(self, **kwargs):
        self.stream_call_count += 1
        return _FakeStreamCM(self._stream_fn(kwargs, self.stream_call_count))

    def create(self, **kwargs):
        self.create_call_count += 1
        return self._create_fn(kwargs, self.create_call_count)


class _FakeClient:
    def __init__(self, stream_response_fn, create_response_fn):
        self.messages = _FakeJudgeMessages(stream_response_fn, create_response_fn)


def _finding(rule_id, result="pass"):
    return {
        "rule_id": rule_id,
        "result": result,
        "evidence": "ok",
        "page": None,
        "confidence": 0.9,
        "evidence_supports_result": True,
    }


def _full_extraction_input():
    return {
        field: {"value": f"extracted-{field}", "confidence": "high", "source_quote": "quote"}
        for field in SUPPORTING_DOC_FIELDS
    }


def _blank_pdf(tmp_path, name) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Some document text.")
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture
def two_pdfs(tmp_path):
    return _blank_pdf(tmp_path, "tp.pdf"), _blank_pdf(tmp_path, "supporting.pdf")


def _install_fake_anthropic(monkeypatch, stream_response_fn, create_response_fn):
    """Installs ONE fake client shared by both judge.py's client.messages.stream(...)
    and supporting_doc_extraction.py's client.messages.create(...) -- see
    _FakeJudgeMessages's docstring for why two separate patches would silently
    clobber each other (both modules' `anthropic` name is the same module object)."""
    fake_client = _FakeClient(stream_response_fn, create_response_fn)
    monkeypatch.setattr(judge.anthropic, "Anthropic", lambda: fake_client)
    return fake_client


def test_extract_supporting_document_normalizes_and_counts_tracker(monkeypatch, tmp_path):
    """Direct unit test of extract_supporting_document, independent of api.py."""
    import pipeline.supporting_doc_extraction as sde

    doc_path = _blank_pdf(tmp_path, "supporting.pdf")
    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": []}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    tracker = ApiCallTracker(max_calls=5)
    result = sde.extract_supporting_document(doc_path, tracker=tracker)

    assert set(result.keys()) == set(SUPPORTING_DOC_FIELDS)
    for field in SUPPORTING_DOC_FIELDS:
        assert result[field] == {"value": f"extracted-{field}", "confidence": "high", "source_quote": "quote"}
    assert tracker.count == 1
    assert fake_client.messages.create_call_count == 1


def test_extract_supporting_document_normalizes_missing_or_malformed_field(monkeypatch, tmp_path):
    """A field the model omits, or returns with a bad confidence value, must
    come back as the honest 'none' outcome -- never silently dropped or
    coerced into something that looks like a real answer."""
    import pipeline.supporting_doc_extraction as sde

    doc_path = _blank_pdf(tmp_path, "supporting.pdf")
    bad_input = _full_extraction_input()
    del bad_input["requested_hours"]
    bad_input["diagnostic_report_match"] = {"value": "yes", "confidence": "extremely-sure", "source_quote": "q"}

    _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": []}),
        create_response_fn=lambda kwargs, n: _FakeResponse(bad_input),
    )

    tracker = ApiCallTracker(max_calls=5)
    result = sde.extract_supporting_document(doc_path, tracker=tracker)

    assert result["requested_hours"] == {"value": None, "confidence": "none", "source_quote": None}
    assert result["diagnostic_report_match"] == {"value": None, "confidence": "none", "source_quote": None}
    assert result["bcba_credentials_npi"]["confidence"] == "high"  # untouched fields still pass through


def test_review_treatment_plan_wires_extraction_into_result_and_shares_tracker(monkeypatch, two_pdfs):
    """End-to-end through the real public entry point, review_treatment_plan
    -- proves (a) extracted data reaches the returned ReviewResult shape, and
    (b) the extraction call and the judgment call(s) increment the exact
    SAME tracker, i.e. the guardrail/ceiling wrapped around one automatically
    covers the other -- no separate, unguarded accounting path exists.
    """
    tp_pdf, supporting_pdf = two_pdfs
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": [_finding("J-1")]}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    result = api.review_treatment_plan(tp_pdf, supporting_doc_path=supporting_pdf, max_calls=20)

    assert result["status"] == "complete", result.get("error")
    assert result["supporting_doc_extraction"] is not None
    for field in SUPPORTING_DOC_FIELDS:
        assert result["supporting_doc_extraction"][field]["value"] == f"extracted-{field}"

    # Same tracker covers both call sites: total counted calls is exactly
    # the sum of what each fake client actually saw, not an independent count.
    assert fake_client.messages.create_call_count == 1
    assert fake_client.messages.stream_call_count >= 1
    assert result["usage"]["api_calls"] == fake_client.messages.stream_call_count + fake_client.messages.create_call_count


def test_supporting_doc_path_none_skips_extraction_entirely(monkeypatch, two_pdfs):
    """Pre-Round-52 callers (supporting_doc_path omitted) must see zero
    behavior change: no extraction call, supporting_doc_extraction stays
    None, tracker only counts the judgment call(s)."""
    tp_pdf, _ = two_pdfs
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": [_finding("J-1")]}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    result = api.review_treatment_plan(tp_pdf, max_calls=20)

    assert result["status"] == "complete", result.get("error")
    assert result["supporting_doc_extraction"] is None
    assert fake_client.messages.create_call_count == 0
    assert result["usage"]["api_calls"] == fake_client.messages.stream_call_count


def test_cap_of_zero_blocks_extraction_before_any_real_call_is_made(monkeypatch, two_pdfs):
    """The cap must catch the NEW extraction call site too, not just the
    pre-existing judgment call site. max_calls=0 means check_before_call()
    raises on the very first real call this run would make -- and because
    _run_pipeline_with_extras runs extraction BEFORE judgment, that first
    call is the extraction one. Neither fake client should ever be hit."""
    tp_pdf, supporting_pdf = two_pdfs
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": [_finding("J-1")]}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    result = api.review_treatment_plan(tp_pdf, supporting_doc_path=supporting_pdf, max_calls=0)

    assert result["status"] == "failed"
    assert result["error"]["code"] == "api_call_cap_exceeded"
    assert fake_client.messages.create_call_count == 0
    assert fake_client.messages.stream_call_count == 0
    assert result["usage"]["api_calls"] == 0


def test_cap_that_allows_extraction_but_not_judgment_still_stops_before_over_budget_call(monkeypatch, two_pdfs):
    """max_calls=1 lets the extraction call through (it goes first) but must
    stop the judgment call that would follow -- proving both call sites draw
    from, and are stopped by, the exact same shared cap."""
    tp_pdf, supporting_pdf = two_pdfs
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": [_finding("J-1")]}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    result = api.review_treatment_plan(tp_pdf, supporting_doc_path=supporting_pdf, max_calls=1)

    assert result["status"] == "failed"
    assert result["error"]["code"] == "api_call_cap_exceeded"
    assert fake_client.messages.create_call_count == 1, "extraction (goes first) should have been allowed through"
    assert fake_client.messages.stream_call_count == 0, "the judgment call must never have been made"
    assert result["usage"]["api_calls"] == 1


def test_missing_supporting_doc_path_returns_structured_error_before_any_call(monkeypatch, two_pdfs):
    tp_pdf, _ = two_pdfs
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    fake_client = _install_fake_anthropic(
        monkeypatch,
        stream_response_fn=lambda kwargs, n: _FakeResponse({"findings": []}),
        create_response_fn=lambda kwargs, n: _FakeResponse(_full_extraction_input()),
    )

    result = api.review_treatment_plan(tp_pdf, supporting_doc_path="does/not/exist.pdf", max_calls=20)

    assert result["status"] == "failed"
    assert result["error"]["code"] == "supporting_doc_not_found"
    assert fake_client.messages.create_call_count == 0
    assert fake_client.messages.stream_call_count == 0
