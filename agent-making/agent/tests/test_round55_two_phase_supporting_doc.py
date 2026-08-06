"""Round 55: replaces Round 52-54's blanket approach (append the whole
supporting_doc JSON to EVERY judgment prompt) with a scoped, two-phase
design. This file proves, at zero real cost:

1. Regression proof: judge.py's _build_prompt no longer includes
   supporting_doc anywhere, for any rule -- the old behavior is actually
   gone, not just superseded by something that happens to also work.
2. Tagging logic (pipeline/supporting_doc_resolution.py) fires exactly
   under the documented conditions and not otherwise.
3. Phase 2 (the one additional real call) is only ever attempted when
   something was tagged -- proven by mocking the Anthropic client
   boundary and asserting it was never touched when nothing is tagged,
   and touched exactly once (with the correct scoped, small prompt) when
   something is.
4. End-to-end through pipeline/api.py, with both the judgment client and
   the phase-2 resolution client mocked, confirming the two are wired
   together correctly and QA-PPI-05 (deterministic, no phase 2 involved)
   is unaffected by any of this.

Explicit limitation (not hidden): this proves the MECHANISM behaves as
designed against synthetic/mocked data and against the same real proxy
documents Round 54 used. It does not prove these resolutions would match
Ms. Yachnes's real-world judgment -- her real example set (a real TP plus
her actual filled-in review columns) does not exist in this repo yet.

Zero real Anthropic API calls anywhere in this file.
"""
import json

import fitz
import pytest

from pipeline import api, judge
from pipeline.supporting_doc_resolution import (
    TAGGABLE_RULE_FIELDS,
    find_taggable_findings,
    resolve_tagged_findings,
)


# --------------------------------------------------------------------------
# 1. Regression proof: the Round 52 blanket injection is actually gone.
# --------------------------------------------------------------------------

def test_build_prompt_never_includes_supporting_doc_for_any_rule_now():
    """The exact behavior Round 52 introduced and this round removed --
    proven for a rule that IS in TAGGABLE_RULE_FIELDS too, since phase 1
    must be clean even for the 3 known candidate rules. Phase-2-only
    content lives entirely in supporting_doc_resolution.py, never in
    judge.py's shared prompt builder."""
    supporting_doc = {
        "cpt_97153_hours_pos_schedule": {"value": "25 hrs/week", "confidence": "high", "source_quote": "q"},
    }
    fields = {
        "pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}],
        "supporting_doc": supporting_doc,
    }
    rule = {"rule_id": "QA-HRS-01", "category": "Hours Requesting", "description": "d", "notes": "n"}
    content = judge._build_prompt([rule], fields, rendered_images={})

    for block in content:
        assert "supporting document" not in block["text"].lower()
        assert "cpt_97153_hours_pos_schedule" not in block["text"]


def test_rules_json_notes_for_hrs01_and_bio01_carry_no_round54_instruction():
    """Confirms the revert landed in rules.json itself, not just in
    judge.py's behavior -- a stale instruction referencing a block that
    phase 1 no longer sends would be actively misleading to the model."""
    rules = {r["rule_id"]: r for r in json.load(open("rules/rules.json", encoding="utf-8"))["rules"]}
    assert "supporting document" not in rules["QA-HRS-01"]["notes"].lower()
    assert "supporting document" not in rules["QA-BIO-01"]["notes"].lower()
    assert rules["QA-HRS-01"]["notes"] == (
        "Coordinator email content isn't captured anywhere in the system today. Needs either a "
        "pre-upload 'approved hours' field or this rule is dropped for V1."
    )
    assert rules["QA-BIO-01"]["notes"] == (
        "Needs the diagnostic report as a supporting upload; not checkable against TP alone."
    )


# --------------------------------------------------------------------------
# 2. Tagging logic.
# --------------------------------------------------------------------------

def _finding(result: str, evidence: str = "e") -> dict:
    return {"result": result, "evidence": evidence, "page": None, "confidence": 0.5}


def test_tags_when_uncertain_and_supporting_doc_has_usable_field():
    judgment_results = {"QA-HRS-01": _finding("uncertain")}
    supporting_doc = {"cpt_97153_hours_pos_schedule": {"value": "25 hrs/week", "confidence": "high", "source_quote": None}}
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    assert set(tagged) == {"QA-HRS-01"}


def test_tags_when_not_checkable_and_supporting_doc_has_usable_field():
    judgment_results = {"QA-BIO-01": _finding("not_checkable")}
    supporting_doc = {"diagnostic_report_match": {"value": "Yes", "confidence": "medium", "source_quote": None}}
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    assert set(tagged) == {"QA-BIO-01"}


def test_no_tag_when_no_supporting_doc_provided_at_all():
    judgment_results = {"QA-HRS-01": _finding("uncertain")}
    tagged = find_taggable_findings(judgment_results, None)
    assert tagged == {}


def test_no_tag_when_supporting_doc_field_confidence_is_none():
    """The supporting document was provided, but it doesn't actually
    contain anything usable for this rule -- tagging anyway would just
    waste a call on a resolution attempt with nothing to resolve with."""
    judgment_results = {"QA-HRS-01": _finding("uncertain")}
    supporting_doc = {
        "cpt_97153_hours_pos_schedule": {"value": None, "confidence": "none", "source_quote": None},
        "requested_hours": {"value": None, "confidence": "none", "source_quote": None},
    }
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    assert tagged == {}


def test_no_tag_when_phase_1_already_resolved_it():
    """A rule that already came back pass/fail in phase 1 is not a dead
    end -- must not be tagged even if the supporting document has a
    usable field, since there's nothing to improve."""
    judgment_results = {"QA-HRS-01": _finding("pass")}
    supporting_doc = {"cpt_97153_hours_pos_schedule": {"value": "25 hrs/week", "confidence": "high", "source_quote": None}}
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    assert tagged == {}


def test_no_tag_for_a_rule_not_in_the_known_taggable_set():
    """Some other uncertain/not_checkable judgment rule, unrelated to the
    supporting document -- must never be tagged, even with a fully
    populated supporting_doc, since it isn't one of the 2 known
    candidates."""
    judgment_results = {"QA-GIP-06": _finding("uncertain")}
    supporting_doc = {field: {"value": "x", "confidence": "high", "source_quote": None} for field in [
        "bcba_credentials_npi", "cpt_97153_hours_pos_schedule", "requested_hours", "diagnostic_report_match",
    ]}
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    assert tagged == {}


def test_qa_ppi_05_is_not_in_the_taggable_set():
    """Deterministic, resolves in-process with zero extra API cost
    (fields.py::_check_PPI05) -- must never be a phase-2 candidate."""
    assert "QA-PPI-05" not in TAGGABLE_RULE_FIELDS


# --------------------------------------------------------------------------
# 3. Phase 2 is only attempted when something is tagged; scoped prompt.
# --------------------------------------------------------------------------

class _FakeUsage:
    def __init__(self, input_tokens=50, output_tokens=30):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class _FakeResponse:
    def __init__(self, tool_input):
        self.content = [_FakeToolUseBlock(tool_input)]
        self.usage = _FakeUsage()


class _FakeMessages:
    def __init__(self, response_fn):
        self._response_fn = response_fn
        self.call_count = 0
        self.last_kwargs = None

    def create(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        return self._response_fn(kwargs)


class _FakeClient:
    def __init__(self, response_fn):
        self.messages = _FakeMessages(response_fn)


def test_resolve_tagged_findings_sends_only_the_relevant_fields_not_the_whole_supporting_doc(monkeypatch):
    import pipeline.supporting_doc_resolution as sdr
    from pipeline.call_tracker import ApiCallTracker

    fake_client = _FakeClient(lambda kwargs: _FakeResponse({
        "resolutions": [{"rule_id": "QA-HRS-01", "result": "fail", "evidence": "23 vs 25 hrs/week mismatch", "confidence": 0.85}],
    }))
    monkeypatch.setattr(sdr.anthropic, "Anthropic", lambda: fake_client)

    tagged = {"QA-HRS-01": _finding("not_checkable", "no coordinator email available")}
    rules_by_id = {"QA-HRS-01": {"rule_id": "QA-HRS-01", "description": "97153 hours match email from coordinator"}}
    supporting_doc = {
        "cpt_97153_hours_pos_schedule": {"value": "25 hrs/week", "confidence": "high", "source_quote": "q"},
        "bcba_credentials_npi": {"value": "unrelated NPI data", "confidence": "high", "source_quote": "q"},
    }
    tracker = ApiCallTracker(max_calls=5)

    resolved = sdr.resolve_tagged_findings(tagged, rules_by_id, supporting_doc, tracker=tracker)

    assert resolved == {"QA-HRS-01": {"result": "fail", "evidence": "23 vs 25 hrs/week mismatch", "confidence": 0.85}}
    assert fake_client.messages.call_count == 1
    assert tracker.count == 1

    sent_prompt = fake_client.messages.last_kwargs["messages"][0]["content"]
    assert "25 hrs/week" in sent_prompt, "the relevant field must be in the prompt"
    assert "unrelated NPI data" not in sent_prompt, "irrelevant supporting_doc fields must NOT be sent"
    assert "no coordinator email available" in sent_prompt, "phase 1's own evidence must be included as context"


def test_phase_2_never_calls_the_client_when_nothing_is_tagged(monkeypatch):
    """The other half of 'zero additional cost for the rules that were
    never candidates' -- if a caller correctly checks `if tagged:` before
    calling resolve_tagged_findings at all, the client is never touched."""
    import pipeline.supporting_doc_resolution as sdr

    fake_client = _FakeClient(lambda kwargs: pytest.fail("must never be called when nothing is tagged"))
    monkeypatch.setattr(sdr.anthropic, "Anthropic", lambda: fake_client)

    judgment_results = {"QA-HRS-01": _finding("pass")}  # already resolved, nothing to tag
    tagged = find_taggable_findings(judgment_results, {"cpt_97153_hours_pos_schedule": {"value": "x", "confidence": "high", "source_quote": None}})
    assert tagged == {}
    # Mirrors api.py's actual wiring: resolve_tagged_findings is only called inside `if tagged:`.
    if tagged:
        sdr.resolve_tagged_findings(tagged, {}, {}, tracker=None)
    assert fake_client.messages.call_count == 0


# --------------------------------------------------------------------------
# 4. End-to-end through pipeline/api.py -- ONE shared fake client.
#
# judge.py, supporting_doc_extraction.py, and supporting_doc_resolution.py
# each do `import anthropic`, but that name resolves to the exact same
# module object in all three -- monkeypatching `X.anthropic.Anthropic`
# separately for each one just overwrites the same attribute repeatedly,
# so whichever patch runs last silently wins for every call site (the same
# footgun Round 52's own test file already had to work around). The fix
# is one fake client whose `.messages` exposes both `.stream()` (judge.py)
# and `.create()` (extraction + resolution, dispatched by tool name), and
# ONE monkeypatch call.
# --------------------------------------------------------------------------

TINY_RULES = [
    {
        "rule_id": "QA-HRS-01", "active": True, "applies_to_plan_type": "Both", "applies_to_payor": "ALL",
        "check_type": "judgment", "category": "Hours Requesting",
        "description": "97153 hours match email from coordinator",
        "notes": "Coordinator email content isn't captured anywhere in the system today. Needs either a pre-upload 'approved hours' field or this rule is dropped for V1.",
    },
]


def _blank_pdf(tmp_path, name) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Some document text. 97153 hours: 23 per week.")
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


class _E2EUsage:
    input_tokens = 10
    output_tokens = 5


class _E2EToolUseBlock:
    type = "tool_use"

    def __init__(self, input_data):
        self.input = input_data


class _E2EResponse:
    def __init__(self, tool_input, stop_reason="tool_use"):
        self.content = [_E2EToolUseBlock(tool_input)]
        self.stop_reason = stop_reason
        self.usage = _E2EUsage()


class _E2EStreamCM:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self._response


class _E2EMessages:
    """One fake `.messages` covering every real call site this pipeline
    run touches: judge.py's `.stream()`, extraction's and resolution's
    `.create()` (dispatched by `tool_choice.name`, since both use
    `.create()` on the same object)."""

    def __init__(self, judgment_findings, extraction_fields, resolution_calls_out, resolutions):
        self._judgment_findings = judgment_findings
        self._extraction_fields = extraction_fields
        self._resolution_calls_out = resolution_calls_out
        self._resolutions = resolutions
        self.stream_call_count = 0
        self.create_call_count = 0

    def stream(self, **kwargs):
        self.stream_call_count += 1
        return _E2EStreamCM(_E2EResponse({"findings": self._judgment_findings}))

    def create(self, **kwargs):
        self.create_call_count += 1
        tool_name = kwargs["tool_choice"]["name"]
        if tool_name == "record_supporting_doc_extraction":
            return _E2EResponse(self._extraction_fields)
        if tool_name == "record_supporting_doc_resolutions":
            self._resolution_calls_out.append(kwargs)
            return _E2EResponse({"resolutions": self._resolutions})
        raise AssertionError(f"unexpected tool_choice: {tool_name!r}")


def _install_e2e_client(monkeypatch, *, judgment_findings, extraction_fields, resolutions):
    import pipeline.judge as judge_module

    resolution_calls: list[dict] = []
    messages = _E2EMessages(judgment_findings, extraction_fields, resolution_calls, resolutions)

    class _E2EClient:
        pass

    client = _E2EClient()
    client.messages = messages
    monkeypatch.setattr(judge_module.anthropic, "Anthropic", lambda: client)
    return messages, resolution_calls


def _full_extraction_all_none():
    from pipeline.supporting_doc_extraction import SUPPORTING_DOC_FIELDS
    return {f: {"value": None, "confidence": "none", "source_quote": None} for f in SUPPORTING_DOC_FIELDS}


def test_end_to_end_phase_2_fires_and_resolves_a_tagged_finding(monkeypatch, tmp_path):
    """review_treatment_plan, judgment client returns 'not_checkable' for
    QA-HRS-01 in phase 1, a supporting document is provided with a usable
    field -- phase 2 must fire exactly once and the final finding must
    reflect its resolution."""
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    extraction_fields = _full_extraction_all_none()
    extraction_fields["cpt_97153_hours_pos_schedule"] = {"value": "25 hrs/week", "confidence": "high", "source_quote": "q"}

    messages, resolution_calls = _install_e2e_client(
        monkeypatch,
        judgment_findings=[{
            "rule_id": "QA-HRS-01", "result": "not_checkable",
            "evidence": "No coordinator email available to compare against.",
            "page": None, "confidence": 0.3, "evidence_supports_result": True,
        }],
        extraction_fields=extraction_fields,
        resolutions=[{
            "rule_id": "QA-HRS-01", "result": "fail",
            "evidence": "TP requests 23 hrs/week but supporting doc states 25 hrs/week.",
            "confidence": 0.85,
        }],
    )

    tp_pdf = _blank_pdf(tmp_path, "tp.pdf")
    supporting_pdf = _blank_pdf(tmp_path, "supporting.pdf")

    result = api.review_treatment_plan(tp_pdf, supporting_doc_path=supporting_pdf, max_calls=20)

    assert result["status"] == "complete", result.get("error")
    assert len(resolution_calls) == 1, "phase 2 must have fired exactly once"
    hrs01_finding = next(f for f in result["findings"] if f["rule_id"] == "QA-HRS-01")
    assert hrs01_finding["result"] == "fail"
    assert "25 hrs/week" in hrs01_finding["detail"]
    # Same shared tracker counts everything: 1 extraction .create() + 2
    # judgment .stream() (the self-consistency pair, both calls agreeing
    # since the fake always returns the same finding) + 1 resolution
    # .create() = 4.
    assert result["usage"]["api_calls"] == 4
    assert messages.create_call_count == 2  # extraction + resolution
    assert messages.stream_call_count == 2  # judgment self-consistency pair


def test_end_to_end_phase_2_does_not_fire_when_no_supporting_doc_given(monkeypatch, tmp_path):
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    messages, resolution_calls = _install_e2e_client(
        monkeypatch,
        judgment_findings=[{
            "rule_id": "QA-HRS-01", "result": "not_checkable", "evidence": "e",
            "page": None, "confidence": 0.3, "evidence_supports_result": True,
        }],
        extraction_fields=_full_extraction_all_none(),
        resolutions=[],
    )

    tp_pdf = _blank_pdf(tmp_path, "tp.pdf")
    result = api.review_treatment_plan(tp_pdf, max_calls=20)  # no supporting_doc_path at all

    assert result["status"] == "complete", result.get("error")
    assert len(resolution_calls) == 0, "phase 2 must never fire with no supporting document"
    assert messages.create_call_count == 0, "extraction must not run either -- supporting_doc_path is None"
    hrs01_finding = next(f for f in result["findings"] if f["rule_id"] == "QA-HRS-01")
    assert hrs01_finding["result"] == "not_checkable"


def test_end_to_end_phase_2_does_not_fire_when_phase_1_already_resolves_qa_hrs_01(monkeypatch, tmp_path):
    """Supporting doc IS provided with a usable field, but phase 1 already
    came back pass -- not a dead end, so phase 2 must not fire."""
    monkeypatch.setattr(api, "_load_rules", lambda: TINY_RULES)

    extraction_fields = _full_extraction_all_none()
    extraction_fields["cpt_97153_hours_pos_schedule"] = {"value": "25 hrs/week", "confidence": "high", "source_quote": "q"}

    messages, resolution_calls = _install_e2e_client(
        monkeypatch,
        judgment_findings=[{
            "rule_id": "QA-HRS-01", "result": "pass", "evidence": "23 hrs/week matches.",
            "page": None, "confidence": 0.8, "evidence_supports_result": True,
        }],
        extraction_fields=extraction_fields,
        resolutions=[],
    )

    tp_pdf = _blank_pdf(tmp_path, "tp.pdf")
    supporting_pdf = _blank_pdf(tmp_path, "supporting.pdf")
    result = api.review_treatment_plan(tp_pdf, supporting_doc_path=supporting_pdf, max_calls=20)

    assert result["status"] == "complete", result.get("error")
    assert len(resolution_calls) == 0, "phase 1 already resolved this -- phase 2 must not fire"
    assert messages.create_call_count == 1  # extraction only, no resolution call
    hrs01_finding = next(f for f in result["findings"] if f["rule_id"] == "QA-HRS-01")
    assert hrs01_finding["result"] == "pass"
