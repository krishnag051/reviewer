"""Round 52: extracts the 8 supporting-document fields Mrs. Ungar specified
from the second, free-form file Round 51 made mandatory on the backend
side (whatever the reviewer attaches -- an authorization letter, a payor
guideline sheet, an intake packet, anything). This is AI-driven extraction,
not a structured form: the document's actual shape is not known in
advance, so a single model call reads the whole thing and reports back
what it could and couldn't find.

This is a SEPARATE, ADDITIONAL real API call — not folded into, and not a
replacement for, the existing judgment-layer self-consistency pair. It
must be threaded through the SAME ApiCallTracker every other call in this
pipeline uses (see call_tracker.py's own "pass one shared instance through
everything" docstring) — `tracker` is a required, not optional, parameter
here specifically so this call site can never accidentally opt out of that
discipline. See pipeline/api.py's orchestration for where this is wired in
(the widened _run_pipeline_with_extras) and why pipeline/__init__.py did
not need to change to support it.

Confidence handling: every field comes back with its own confidence level.
"This document doesn't contain that information" is confidence="none",
value=None — a real, honest, EXPECTED outcome, never silently coerced into
a blank string, a guess, or an error. A rule (deterministic or judgment)
that wants to use one of these fields must check its confidence before
trusting the value, the same way agent-making's own deterministic checkers
already carry a confidence score per finding (fields.py).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anthropic

from .call_tracker import ApiCallTracker
from .extract import extract_pdf_text

MODEL = "claude-sonnet-5"  # matches judge.py's model + call_tracker.py's pricing table
MAX_TOKENS = 4096

CONFIDENCE_LEVELS = ("high", "medium", "low", "none")

# The 8 fields, in Mrs. Ungar's own framing -- kept as a flat, explicit list
# (not inferred from the tool schema) so a caller can validate the response
# shape without parsing the schema back out.
SUPPORTING_DOC_FIELDS = (
    "bcba_credentials_npi",
    "authorization_dates",
    "report_date_range",
    "assessment_date_pos_assessor",
    "cpt_97153_hours_pos_schedule",
    "requested_hours",
    "assessment_vs_payor_guideline",
    "diagnostic_report_match",
)

_FIELD_DESCRIPTIONS = {
    "bcba_credentials_npi": "The BCBA's credentials and NPI (National Provider Identifier) number.",
    "authorization_dates": "The authorization period's start and end dates.",
    "report_date_range": "The date range this report/document itself covers.",
    "assessment_date_pos_assessor": "The assessment date, place of service (POS), and who performed the assessment.",
    "cpt_97153_hours_pos_schedule": "CPT 97153 authorized hours, place of service, and the associated schedule.",
    "requested_hours": "The total hours being requested.",
    "assessment_vs_payor_guideline": "How the assessment's recommendation compares against the payor's own stated guideline (if the guideline is stated in this document).",
    "diagnostic_report_match": "Whether this document's diagnosis/diagnostic information matches what's expected (e.g. matches a diagnostic report referenced elsewhere) -- report what the document itself says, don't assume a match.",
}

EXTRACTION_TOOL = {
    "name": "record_supporting_doc_extraction",
    "description": (
        "Record the extracted value for each required field from the supporting document. "
        "Every field is required in the response, even when the document doesn't contain it -- "
        "in that case, set value to null and confidence to \"none\"."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            field: {
                "type": "object",
                "properties": {
                    "value": {
                        "type": ["string", "null"],
                        "description": "The extracted value as found in the document, or null if not present.",
                    },
                    "confidence": {
                        "type": "string",
                        "enum": list(CONFIDENCE_LEVELS),
                        "description": (
                            "\"none\" means this document does not contain this information -- "
                            "an expected, honest outcome, not a failure. \"low\"/\"medium\"/\"high\" "
                            "reflect how directly and unambiguously the document states the value."
                        ),
                    },
                    "source_quote": {
                        "type": ["string", "null"],
                        "description": "A short verbatim quote from the document supporting this value, or null.",
                    },
                },
                "required": ["value", "confidence", "source_quote"],
            }
            for field in SUPPORTING_DOC_FIELDS
        },
        "required": list(SUPPORTING_DOC_FIELDS),
    },
}


def _empty_field_result() -> dict[str, Any]:
    return {"value": None, "confidence": "none", "source_quote": None}


def _build_prompt(full_text: str) -> list[dict]:
    field_list = "\n".join(f"- {field}: {_FIELD_DESCRIPTIONS[field]}" for field in SUPPORTING_DOC_FIELDS)
    return [{
        "type": "text",
        "text": (
            "You are extracting specific factual fields from a supporting document submitted "
            "alongside an ABA Treatment Plan review. The document's format is not known in "
            "advance -- it could be an authorization letter, a payor guideline sheet, an intake "
            "packet, or something else entirely. Extract each of the following fields if present:\n\n"
            f"{field_list}\n\n"
            "For each field: if the document clearly states it, extract the value and a short "
            "supporting quote, with a confidence level reflecting how directly it's stated. If the "
            "document does NOT contain this information, you MUST still report the field with "
            "value=null and confidence=\"none\" -- never guess, never leave a field out, and never "
            "report a value that isn't actually in the document.\n\n"
            "Document text follows:\n\n" + full_text
        ),
    }]


def extract_supporting_document(
    supporting_doc_path: str,
    *,
    tracker: ApiCallTracker,
) -> dict[str, dict[str, Any]]:
    """Real, additive API call. `tracker` is required (no default of None)
    so this can never be invoked without being counted against the same
    cap/session ceiling every other real call in this pipeline goes
    through -- see call_tracker.py.

    Returns a dict keyed by every name in SUPPORTING_DOC_FIELDS, each value
    `{value, confidence, source_quote}`. Never raises for a normal
    "couldn't find this" case -- that's confidence="none", not an
    exception. Only raises if the file itself can't be read (bad/missing
    path -- caller's responsibility to check first, same convention as the
    rest of this pipeline) or the real API call fails outright (network
    error, or ApiCallCapExceeded via tracker.check_before_call()).
    """
    if not Path(supporting_doc_path).is_file():
        raise FileNotFoundError(f"supporting document not found: {supporting_doc_path}")

    pages = extract_pdf_text(supporting_doc_path)
    full_text = "\n\n".join(f"--- Page {p['page_number']} ---\n{p['text']}" for p in pages) or "(no extractable text)"

    tracker.check_before_call()
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_supporting_doc_extraction"},
        messages=[{"role": "user", "content": _build_prompt(full_text)}],
    )
    tracker.record(
        reason="supporting_doc_extraction",
        rule_ids=["__supporting_doc_extraction__"],
        usage=response.usage,
    )

    tool_use_block = next(b for b in response.content if b.type == "tool_use")
    extracted: dict[str, Any] = tool_use_block.input

    # Defensive normalization, not trust-by-default: guarantee every field
    # is present with a valid confidence level even if the model's tool
    # call somehow omits one (schema `required` should prevent this, but
    # this function's own contract -- "every field always present" -- must
    # hold regardless of what the model actually returns).
    result = {}
    for field in SUPPORTING_DOC_FIELDS:
        entry = extracted.get(field)
        if not isinstance(entry, dict) or entry.get("confidence") not in CONFIDENCE_LEVELS:
            result[field] = _empty_field_result()
        else:
            result[field] = {
                "value": entry.get("value"),
                "confidence": entry["confidence"],
                "source_quote": entry.get("source_quote"),
            }
    return result
