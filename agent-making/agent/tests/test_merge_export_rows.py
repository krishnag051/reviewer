"""Locks in the multi-page findings export: a rule whose evidence is the
{page, detail} list form must produce one export row per page-level entry,
never a single collapsed summary row.

Also covers a DIFFERENT multi-page case added 2026-07-28: one finding whose
own `page` field is itself a list of 2+ page numbers (e.g. a reviewer
comment on one page pointing to content established on an earlier page) --
this stays ONE export row, with the page list formatted into a readable
string, not exploded into multiple rows the way {page, detail} evidence is.
"""
from pipeline.merge import merge_findings, _format_page_display
from pipeline import judge


def _rule(rule_id, check_type="deterministic"):
    return {
        "rule_id": rule_id,
        "category": "Test",
        "check_type": check_type,
        "active": True,
        "action_lane": "BCBA-fix",
        "action_tag": None,
    }


def test_single_string_evidence_produces_one_row():
    rules = [_rule("A-1")]
    det_results = {"A-1": {"result": "pass", "evidence": "All fields filled.", "page": None, "confidence": 0.9}}
    result = merge_findings(rules, det_results, {})
    assert len(result["export_rows"]) == 1
    row = result["export_rows"][0]
    assert row["detail"] == "All fields filled."
    assert row["page"] is None


def test_multi_page_evidence_produces_one_row_per_page():
    rules = [_rule("A-1")]
    det_results = {
        "A-1": {
            "result": "fail",
            "evidence": [
                {"page": 13, "detail": "Missing header."},
                {"page": 48, "detail": "Missing page number."},
            ],
            "page": None,
            "confidence": 0.7,
        }
    }
    result = merge_findings(rules, det_results, {})
    rows = result["export_rows"]
    assert len(rows) == 2
    assert {r["page"] for r in rows} == {13, 48}
    by_page = {r["page"]: r["detail"] for r in rows}
    assert by_page[13] == "Missing header."
    assert by_page[48] == "Missing page number."
    # findings dict itself stays one-entry-per-rule_id regardless.
    assert len(result["findings"]) == 1


def test_mixed_rules_single_and_multi_page_coexist():
    rules = [_rule("A-1"), _rule("A-2")]
    det_results = {
        "A-1": {"result": "pass", "evidence": "fine", "page": None, "confidence": 0.9},
        "A-2": {
            "result": "fail",
            "evidence": [{"page": 5, "detail": "issue one"}, {"page": 9, "detail": "issue two"}],
            "page": None,
            "confidence": 0.7,
        },
    }
    result = merge_findings(rules, det_results, {})
    assert len(result["export_rows"]) == 3  # 1 + 2
    assert len(result["findings"]) == 2


# --- A single finding whose own `page` spans multiple specific pages ---

def test_genuine_two_page_finding_produces_one_row_with_both_pages_shown():
    """E.g. a reviewer comment on page 14 pointing to content established
    on page 11 -- ONE finding, ONE row, both pages visible in the export,
    not exploded into two rows and not dropping either page."""
    rules = [_rule("A-1", check_type="judgment")]
    judgment_results = {
        "A-1": {
            "result": "fail",
            "evidence": "The reviewer's note on page 14 references the goal established on page 11, which was never updated to match.",
            "page": [11, 14],
            "confidence": 0.7,
        }
    }
    result = merge_findings(rules, {}, judgment_results)
    rows = result["export_rows"]
    assert len(rows) == 1, "a multi-page single finding must stay one row, not explode"
    assert rows[0]["page"] == "11, 14"


def test_two_consecutive_pages_render_as_a_range():
    rules = [_rule("A-1", check_type="judgment")]
    judgment_results = {
        "A-1": {"result": "fail", "evidence": "Spans two consecutive pages.", "page": [14, 15], "confidence": 0.7}
    }
    result = merge_findings(rules, {}, judgment_results)
    assert result["export_rows"][0]["page"] == "14-15"


def test_existing_single_page_rules_are_unaffected():
    """Confirms the plain int and None cases render exactly as before --
    the multi-page change must not touch the common case."""
    rules = [_rule("A-1"), _rule("A-2")]
    det_results = {
        "A-1": {"result": "fail", "evidence": "Single page issue.", "page": 7, "confidence": 0.8},
        "A-2": {"result": "pass", "evidence": "No page-specific issue.", "page": None, "confidence": 0.9},
    }
    result = merge_findings(rules, det_results, {})
    by_id = {r["rule_id"]: r for r in result["export_rows"]}
    assert by_id["A-1"]["page"] == 7
    assert by_id["A-2"]["page"] is None


def test_format_page_display_helper_directly():
    assert _format_page_display(None) is None
    assert _format_page_display(7) == 7
    assert _format_page_display([7]) == 7
    assert _format_page_display([14, 15]) == "14-15"
    assert _format_page_display([11, 14]) == "11, 14"
    assert _format_page_display([3, 4, 5]) == "3-5"
    assert _format_page_display([15, 14]) == "14-15", "unsorted input still renders in page order"
    assert _format_page_display([9, 3, 14]) == "3, 9, 14", "unsorted non-consecutive still sorts for readability"


def test_findings_tool_schema_accepts_a_multi_page_array_for_the_judgment_layer():
    """The judgment layer's own tool schema must actually allow emitting a
    multi-page `page` array -- not just merge.py being able to render one
    if it ever received it. Confirms judge.py's side of item 4, not just
    merge.py's."""
    page_schema = judge.FINDINGS_TOOL["input_schema"]["properties"]["findings"]["items"]["properties"]["page"]
    variants = page_schema["anyOf"]
    types_offered = {v["type"] for v in variants}
    assert types_offered == {"integer", "array", "null"}
    array_variant = next(v for v in variants if v["type"] == "array")
    assert array_variant["items"]["type"] == "integer"
    assert array_variant["minItems"] == 2
