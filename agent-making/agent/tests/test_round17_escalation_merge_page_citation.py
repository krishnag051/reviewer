"""Fix Round 17 (2026-10-06): a real production run against zaith_new.pdf
showed Round 15's reconcile_page_citation fix did NOT actually hold for
QA-SCH-06 (still page 4) and only half-held for QA-BIO-06 (structured page
fixed to 5, but the evidence's own embedded "[Page 4]" mention was not).

Round 15's own test (test_round15_page_citation_reconciliation.py) only
tested reconcile_page_citation() in isolation -- it never proved its output
actually survived all the way through pipeline/__init__.py's real escalation
merge, which is exactly where it turned out to be silently overwritten. This
file closes that gap: it runs the REAL run_full_pipeline() end-to-end
(real PDF extraction, real deterministic checkers, real escalation-scoping
logic, real merge code) against the real zaith_new.pdf, with ONLY the
judgment-layer's own model call mocked (same "mock the real API boundary,
keep everything else real" convention as test_merge_preserves_det_page.py)
-- zero real API cost, but the full real code path this bug actually lived
in, not a reconstruction of it.
"""
import json
from pathlib import Path

import pytest

import pipeline as pipeline_module
from pipeline import fields as fields_module
from pipeline import judge

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
ALL_RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
ZAITH_NEW_PDF = Path(
    r"C:\Users\DELL\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude"
    r"\local-agent-mode-sessions\ba82bea0-e82a-44aa-af55-f87a0d0f833f"
    r"\0d5aa1c9-0e4c-44d6-a1a7-fe2ee38560aa\local_349ae652-bf70-4384-a22d-e4eea7f752c1"
    r"\uploads\zaith_new.pdf"
)

pytestmark = pytest.mark.skipif(not ZAITH_NEW_PDF.exists(), reason="real zaith_new.pdf fixture not present in this environment")


def _real_rule(rule_id: str) -> dict:
    return next(r for r in ALL_RULES if r["rule_id"] == rule_id)


def test_qa_sch06_real_pipeline_run_no_longer_loses_the_corrected_page(monkeypatch):
    """Reproduces the EXACT real production shape: the real _check_SCH06
    deterministic checker (unmodified, running against the real document)
    returns its own off-topic page (4, from an unrelated early-childhood
    "speech-language pathology" mention, not the real School & ABA Schedule
    content this rule cares about) alongside an escalating "uncertain"
    verdict. The judgment layer (mocked here) returns the real reported
    disagreement evidence, embedding "(page 5)" twice, with a stale
    structured page of 4 -- same shape Round 15's fix was supposed to
    resolve, now proven to survive the real escalation merge, not just the
    isolated reconcile function.
    """
    rules = [_real_rule("QA-SCH-06")]

    real_disagreement_evidence = (
        'This item genuinely came back uncertain: One assessment concluded this is uncertain -- '
        '"Document mentions related therapies (OT/speech/PT/counseling) via the IEP with frequency '
        "'2x 30' but does not state specific days/times for these other therapies anywhere, so no "
        'schedule for them was added to the TP." (page 5); A separate assessment concluded this '
        'doesn\'t apply -- "Document states the IEP mandates OT/speech/PT/counseling but these '
        'services have not yet begin for the 2026-2027 academic year" (page 5). Please confirm '
        "manually."
    )

    def fake_run_judgment_checks_once(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-SCH-06": {
                "result": "uncertain",
                "evidence": real_disagreement_evidence,
                "page": 4,  # the model's own stale/wrong structured page
                "confidence": 0.0,
            }
        }

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_run_judgment_checks_once)
    result = pipeline_module.run_full_pipeline(str(ZAITH_NEW_PDF), rules)

    finding = result["findings"]["QA-SCH-06"]
    assert finding["page"] == 5, (
        f"expected the escalation merge's det-page override to be corrected back to the real page "
        f"(5) by reconcile_page_citation running a second time on the final merged result; got "
        f"{finding['page']!r}. det_attempt was: {finding.get('det_attempt')!r}"
    )
    assert finding["result"] == "uncertain"  # verdict itself must never be touched
    assert "(page 5)" in finding["evidence"]


def test_qa_bio06_real_pipeline_run_keeps_structured_page_and_inline_citation_in_sync(monkeypatch):
    """Reproduces the real QA-BIO-06 shape: the model's raw judgment finding
    cites real document text verbatim (quote-matches real page 5) AND
    separately embeds its own "[Page 4]" bracket citation elsewhere in the
    same evidence string, both starting out wrong (4). Confirms BOTH the
    structured field and the embedded inline citation end up correct and
    consistent with each other -- not just the structured field alone.
    """
    rules = [_real_rule("QA-BIO-06")]

    real_judgment_evidence = (
        "Developmental/Psychological History says 'He is not currently on any prescribed "
        "medications aside from multivitamins and takes medication only when ill.' [Page 4]"
    )

    def fake_run_judgment_checks_once(judgment_rules, fields, rendered_images, **kwargs):
        return {
            "QA-BIO-06": {
                "result": "not_applicable",
                "evidence": real_judgment_evidence,
                "page": 4,
                "confidence": 0.8,
            }
        }

    monkeypatch.setattr(judge, "_run_judgment_checks_once", fake_run_judgment_checks_once)
    result = pipeline_module.run_full_pipeline(str(ZAITH_NEW_PDF), rules)

    finding = result["findings"]["QA-BIO-06"]
    assert finding["page"] == 5
    assert finding["result"] == "not_applicable"
    assert "[Page 5]" in finding["evidence"], finding["evidence"]
    assert "[Page 4]" not in finding["evidence"], finding["evidence"]
