"""Synthetic-only coverage for the CS TP.pdf page-attribution investigation
(QA-RPT-01 reported page 19 for content pypdf itself correctly placed on
page 20). No live document, no live API — the actual root-cause diagnosis
was done separately against the real PDF via pypdf only (no API call),
confirming: pypdf's page index matches every one of that document's own
printed footers 1:1 (no extraction bleed), and the blank-field text in
question is fully self-contained on the correct page. The real cause is
that `_check_RPT01`'s fail confidence (0.5) sat below
ESCALATION_CONFIDENCE_THRESHOLD (0.6), so its correct, code-computed page
number was always discarded in favor of the judgment layer's own re-derived
(and here, off-by-one) page count.
"""
from pipeline import fields, judge


def _fields(*page_texts):
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def _rule(**overrides):
    rule = {"rule_id": "QA-RPT-01", "check_type": "deterministic", "params": {}}
    rule.update(overrides)
    return rule


def test_rpt01_single_blank_no_longer_escalates():
    """A blank required field is a plain fact the regex either finds or
    doesn't — not something that needs a second, LLM-derived opinion that
    can silently replace the correct page number."""
    result, evidence, page, confidence = fields._check_RPT01(
        _rule(), _fields("Diagnosis:\n\nNext Section:")
    )
    assert result == "fail"
    assert page == 1
    assert not fields.needs_escalation({"result": result, "confidence": confidence}), (
        "RPT01's own accurate page number must not be thrown away by escalation"
    )


def test_rpt01_multi_page_list_form_no_longer_escalates():
    result, evidence, page, confidence = fields._check_RPT01(
        _rule(), _fields("Diagnosis:\n\nNext:", "Goals:\n\nNext:")
    )
    assert result == "fail"
    assert not fields.needs_escalation({"result": result, "confidence": confidence})


def test_prompt_no_longer_hardcodes_healthfirst():
    """Leftover from before payor detection existed — missed in the round
    that generalized app.py's framing. The judgment prompt itself still
    told the model it was reviewing "a Healthfirst ABA Treatment Plan"
    regardless of the document's actual detected payor."""
    rule = {"rule_id": "X", "category": "c", "description": "d", "notes": None}
    fields_dict = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}
    content = judge._build_prompt([rule], fields_dict, rendered_images={})
    intro_text = content[0]["text"]
    assert "Healthfirst" not in intro_text


def test_prompt_instructs_enumerating_every_recurring_page():
    """QA-GIP-07 cited only 3 of 8 pages where the same stale
    'Date Initiated: 11/18/2024' actually recurs, all individually
    accurate but collectively under-reporting the scope of the problem."""
    rule = {"rule_id": "X", "category": "c", "description": "d", "notes": None}
    fields_dict = {"pages": [{"page_number": 1, "text": "irrelevant", "low_text": False}]}
    content = judge._build_prompt([rule], fields_dict, rendered_images={})
    intro_text = content[0]["text"]
    assert "enumerate every page" in intro_text.lower()
