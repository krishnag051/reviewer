"""Locks in the merge-level fix for the page-attribution bug found against
CS TP.pdf: bumping QA-RPT-01's confidence only stopped THAT rule from
escalating — any other deterministic rule sitting at 0.5-0.59 confidence
would still hit the same silent-overwrite. The real fix is structural: when
a rule escalates, the deterministic layer's own computed page number must
survive into the merged result rather than being replaced by the judgment
layer's re-derived one, whenever judgment's evidence is the plain-string
form (the multi-page list form carries its own per-item pages instead and
is left alone).

2026-07-28 addition: the multi-page-finding schema change (page can now be
a list of ints, not just a single int-or-None) opened a SEPARATE gap in
this exact same override — proven with a live-reproduced fixture before
fixing (see test_escalated_rule_keeps_its_multipage_page_when_judgment_returns_one
below): when judgment's own `page` is itself a list, det's single page was
silently overwriting it, discarding a genuine multi-page finding even
though judgment's evidence explicitly discussed the pages it named. Fixed
by also skipping the override when judgment's page is a list.

No live document, no live API — fields_module.run_deterministic_checks and
judge.run_judgment_checks are both monkeypatched with canned, controlled
responses so this test isolates pipeline/__init__.py's merge logic itself.
"""
import fitz
import pytest

import pipeline as pipeline_module
from pipeline import fields as fields_module
from pipeline import judge


@pytest.fixture
def minimal_pdf(tmp_path) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Treatment Plan\nSome content.")
    path = tmp_path / "minimal.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _rule(rule_id, check_type="deterministic"):
    return {
        "rule_id": rule_id,
        "category": "Test",
        "description": f"Test rule {rule_id}",
        "notes": None,
        "applies_to_payor": "ALL",
        "applies_to_plan_type": "Both",
        "check_type": check_type,
        "params": None,
        "action_lane": "BCBA-fix",
        "action_tag": None,
        "active": True,
    }


def test_escalated_rule_keeps_deterministic_page_when_judgment_disagrees(minimal_pdf, monkeypatch):
    """Reproduces the exact CS TP.pdf shape: a low-confidence deterministic
    finding with a code-computed page (20), escalated, and judgment comes
    back with a different, LLM-recounted page (19) for a plain-string
    finding. The deterministic page must win in the final merged output."""
    rules = [_rule("QA-FAKE-01")]

    def fake_run_deterministic_checks(applicable_rules, extracted_fields):
        return {
            "QA-FAKE-01": {
                "result": "fail",
                "evidence": "Possible unfilled field(s) on page 20: ['Mastery Criteria:'].",
                "page": 20,
                "confidence": 0.5,  # below ESCALATION_CONFIDENCE_THRESHOLD -> escalates
            }
        }

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-FAKE-01": {
                "result": "fail",
                "evidence": "Mastery Criteria field left blank for this goal.",
                "page": 19,  # the model's own, wrong, re-derived page
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(fields_module, "run_deterministic_checks", fake_run_deterministic_checks)
    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    finding = result["findings"]["QA-FAKE-01"]

    assert finding["page"] == 20, "the deterministic layer's computed page must survive escalation"
    assert finding["result"] == "fail"
    assert finding["evidence"] == "Mastery Criteria field left blank for this goal."
    assert finding["det_attempt"]["page"] == 20


def test_escalated_rule_uses_judgment_page_when_det_had_none(minimal_pdf, monkeypatch):
    """No regression: when the deterministic layer never had a page to
    begin with (e.g. a not_applicable/not_checkable default with
    page=None), judgment's page is used as-is — there is nothing more
    reliable to prefer."""
    rules = [_rule("QA-FAKE-02")]

    def fake_run_deterministic_checks(applicable_rules, extracted_fields):
        return {
            "QA-FAKE-02": {
                "result": "not_checkable",
                "evidence": "Needs backend integration.",
                "page": None,
                "confidence": 0.0,
            }
        }

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-FAKE-02": {
                "result": "pass",
                "evidence": "Confirmed fine on page 7.",
                "page": 7,
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(fields_module, "run_deterministic_checks", fake_run_deterministic_checks)
    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    finding = result["findings"]["QA-FAKE-02"]
    assert finding["page"] == 7


def test_escalated_rule_with_multi_page_judgment_evidence_is_left_alone(minimal_pdf, monkeypatch):
    """When judgment's evidence is the multi-page {page, detail} list form,
    top-level page is structurally null and each item carries its own page
    — the deterministic layer's single page number doesn't fit that shape
    and must not be forced in."""
    rules = [_rule("QA-FAKE-03")]

    def fake_run_deterministic_checks(applicable_rules, extracted_fields):
        return {
            "QA-FAKE-03": {
                "result": "fail",
                "evidence": "Possible unfilled field(s) on page 5: ['Baseline:'].",
                "page": 5,
                "confidence": 0.5,
            }
        }

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-FAKE-03": {
                "result": "fail",
                "evidence": [
                    {"page": 5, "detail": "Baseline blank."},
                    {"page": 9, "detail": "Baseline also blank here."},
                ],
                "page": None,
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(fields_module, "run_deterministic_checks", fake_run_deterministic_checks)
    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    finding = result["findings"]["QA-FAKE-03"]
    assert finding["page"] is None
    assert finding["evidence"] == [
        {"page": 5, "detail": "Baseline blank."},
        {"page": 9, "detail": "Baseline also blank here."},
    ]


def test_escalated_rule_keeps_its_multipage_page_when_judgment_returns_one(minimal_pdf, monkeypatch):
    """The interaction the general 170/170 pass didn't specifically probe:
    judgment's evidence is a plain STRING (not the {page, detail} list
    form) but its own `page` is a genuine multi-page list -- e.g. a
    reviewer comment on one page pointing to content on another. Before
    the fix, this silently collapsed to det's unrelated single page,
    proven live: evidence explicitly named pages 11 and 14, but the
    reported page was det's 20 -- neither 11 nor 14 survived."""
    rules = [_rule("QA-FAKE-04")]

    def fake_run_deterministic_checks(applicable_rules, extracted_fields):
        return {
            "QA-FAKE-04": {
                "result": "fail",
                "evidence": "det found something unrelated on page 20.",
                "page": 20,
                "confidence": 0.5,
            }
        }

    def fake_run_judgment_checks(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-FAKE-04": {
                "result": "fail",
                "evidence": "The reviewer's note on page 14 references content established on page 11.",
                "page": [11, 14],
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(fields_module, "run_deterministic_checks", fake_run_deterministic_checks)
    monkeypatch.setattr(judge, "run_judgment_checks", fake_run_judgment_checks)

    result = pipeline_module.run_full_pipeline(minimal_pdf, rules)
    finding = result["findings"]["QA-FAKE-04"]

    assert finding["page"] == [11, 14], "judgment's genuine multi-page answer must survive, not collapse to det's single page"
    assert finding["evidence"] == "The reviewer's note on page 14 references content established on page 11."
    assert finding["det_attempt"]["page"] == 20
