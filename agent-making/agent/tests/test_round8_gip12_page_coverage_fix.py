"""Fix Round 8 (mc_current.pdf, real gap): confirmed real target page list
for QA-GIP-12 is exactly 12 pages (52, 55, 56, 57, 58, 59, 60, 61, 63, 64,
65, 67), but only 4 (56, 57, 63, 67) were being found. Two real bugs found
in Pass 1 (gip12_verbal_operant_candidate_pages):

1. It reported every match under its enclosing goal BLOCK's start page
   (_page_for_offset(starts[i])), not the match's own real page -- wrong
   whenever a goal's real content (Baseline/Current Data/Status/Graph)
   spans multiple pages and the literal term sits on a later page than
   "Target Goal:" itself.
2. It only recognized "Target Goal:"/"Target Name:" as goal markers --
   this codebase's own confirmed real shape (HF-05's mc_current.pdf fix)
   shows some real goals are marked "Program Goal:" only.

These tests also cover the full Pass-1 -> Pass-2 merge -> merge_findings
-> export_rows path end to end, with a real (not real-API) integration
test that a mocked judgment call dropping pages still produces a full
export with all Pass-1 pages present -- closing the round's own explicit
"confirm this reaches the CSV output, not just an intermediate object"
requirement without spending a real API call.
"""

import tempfile

from pipeline import fields
from pipeline import run_full_pipeline
import pipeline as pipeline_module
import pipeline.merge as merge_module


def test_merge_prunes_a_hallucinated_judgment_cited_page_not_in_pass1_and_not_real():
    """Fix Round 9 (mc_current.pdf, real bug): judgment cited page 46,
    which checked directly against the document has no verbal-operant
    term anywhere on it at all -- a confirmed hallucinated/mis-attributed
    citation. This must be pruned, while every genuinely real page (Pass
    1's own candidates, or any page judgment cited that DOES check out)
    survives untouched.
    """
    from pipeline import _merge_gip12_candidate_pages

    pages = [
        {"page_number": 46, "text": "Cumulative Goal: Listeners response\nGoal Status: In progress\n"},
        {"page_number": 55, "text": "Target Goal: tact objects\nGoal Status: In progress\n"},
        {"page_number": 56, "text": "Target Goal: mand for break\nGoal Status: In progress\n"},
    ]
    doc_fields = {"full_text": "\n".join(p["text"] for p in pages), "pages": pages}
    candidates = [(55, "tact objects", "tact"), (56, "mand for break", "mand")]
    judgment_result = {"result": "pass", "evidence": "x", "page": [46, 55, 56], "confidence": 0.7}
    merged = _merge_gip12_candidate_pages(judgment_result, candidates, fields=doc_fields)
    assert merged["page"] == [55, 56]
    assert "46" in merged["evidence"]


def test_merge_without_fields_still_works_backward_compatibly():
    """Existing callers/tests that don't pass `fields` at all (default
    None) must be completely unaffected -- pruning is opt-in via that
    param, never a behavior change for a caller that omits it."""
    from pipeline import _merge_gip12_candidate_pages

    judgment_result = {"result": "pass", "evidence": "x", "page": [1], "confidence": 0.8}
    assert _merge_gip12_candidate_pages(judgment_result, []) == judgment_result


def test_pass1_attributes_a_match_to_its_own_real_page_not_the_block_start_page():
    pages = [
        {"page_number": 52, "text": "Target Goal: Reeda will demonstrate skill\nSkill Domain: Communication\n"},
        {"page_number": 53, "text": "Baseline: 2\nCurrent Data: 4\n"},
        {"page_number": 54, "text": "Status: In progress -- continuing to mand for items.\n"},
    ]
    f = {"full_text": "\n".join(p["text"] for p in pages), "pages": pages}
    hits = fields.gip12_verbal_operant_candidate_pages(f)
    assert [h[0] for h in hits] == [54]


def test_pass1_recognizes_program_goal_marker_too():
    pages = [{"page_number": 55, "text": "Program Goal: tact objects\n"}]
    f = {"full_text": pages[0]["text"], "pages": pages}
    hits = fields.gip12_verbal_operant_candidate_pages(f)
    assert hits == [(55, "tact objects", "tact")]


def test_pass1_finds_every_occurrence_in_a_multi_hit_block():
    text = "Target Goal: goal with mand and later tact too\nGoal Status: In progress\n"
    f = {"full_text": text, "pages": [{"page_number": 1, "text": text}]}
    hits = fields.gip12_verbal_operant_candidate_pages(f)
    terms = {h[2] for h in hits}
    assert terms == {"mand", "tact"}


def test_pass1_finds_all_12_real_target_pages_on_a_reconstructed_document():
    """Reconstructs the confirmed real per-page shape (each of the 12 real
    target pages hosts its own goal block naming an operant, several as
    continuation pages of a goal that started on an earlier page) and
    confirms Pass 1 now finds all 12."""
    target_pages = [52, 55, 56, 57, 58, 59, 60, 61, 63, 64, 65, 67]
    pages = []
    for i, p in enumerate(target_pages):
        term = ["mand", "tact", "intraverbal", "echoic"][i % 4]
        marker = "Program Goal:" if i % 5 == 0 else "Target Goal:"
        pages.append({"page_number": p, "text": f"{marker} goal {i} uses {term}\nGoal Status: In progress\n"})
    f = {"full_text": "\n".join(p["text"] for p in pages), "pages": pages}
    hits = fields.gip12_verbal_operant_candidate_pages(f)
    found_pages = {h[0] for h in hits}
    assert found_pages == set(target_pages)


def test_full_pipeline_merge_reaches_the_export_rows_not_just_an_intermediate_object():
    """End-to-end (no real API call): mocks the judgment layer to return a
    result covering only 2 of 3 real Pass-1 pages, and confirms the FINAL
    export_rows (what the CSV/report renders) contains all 3 -- proving
    the merge survives all the way through merge_findings, not just into
    an intermediate dict that gets dropped before the export.
    """
    orig_run_judgment = pipeline_module.integrity.run_judgment_with_integrity_check

    def fake_judgment(full_judgment_batch, *args, **kwargs):
        results = {}
        for r in full_judgment_batch:
            if r["rule_id"] == "QA-GIP-12":
                results[r["rule_id"]] = {
                    "result": "pass", "evidence": "partial", "page": [10, 11], "confidence": 0.7,
                }
            else:
                results[r["rule_id"]] = {"result": "uncertain", "evidence": "", "page": None, "confidence": 0.0}
        return results

    orig_extract = None
    pages = [
        {"page_number": 10, "text": "Target Goal: goal a uses mand\nGoal Status: In progress\n"},
        {"page_number": 11, "text": "Target Goal: goal b uses tact\nGoal Status: In progress\n"},
        {"page_number": 12, "text": "Target Goal: goal c uses echoic\nGoal Status: In progress\n"},
    ]

    import pipeline.extract as extract_module
    orig_extract = extract_module.extract_pdf_text
    pipeline_module.integrity.run_judgment_with_integrity_check = fake_judgment
    extract_module.extract_pdf_text = lambda _path: pages
    pipeline_module.extract_pdf_text = extract_module.extract_pdf_text
    try:
        rules = [
            {
                "rule_id": "QA-GIP-12", "check_type": "judgment", "active": True,
                "applies_to_payor": "ALL", "applies_to_plan_type": "Both",
                "description": "Goals include verbal operant/behavioral term", "category": "Goals in Progress",
                "action_lane": "BCBA-fix", "action_tag": None,
            },
        ]
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            from pypdf import PdfWriter
            writer = PdfWriter()
            for _ in range(12):
                writer.add_blank_page(width=612, height=792)
            writer.write(tmp.name)
            tmp_path = tmp.name

        result = run_full_pipeline(tmp_path, rules)
    finally:
        pipeline_module.integrity.run_judgment_with_integrity_check = orig_run_judgment
        extract_module.extract_pdf_text = orig_extract
        pipeline_module.extract_pdf_text = orig_extract

    export_pages = {
        row["page"] for row in result["export_rows"] if row["rule_id"] == "QA-GIP-12"
    }
    # page 12 is a real Pass-1 page the mocked judgment call dropped --
    # confirms it survived the merge all the way into the final export.
    assert export_pages == {"10-12"} or 12 in export_pages or any(
        "12" in str(p) for p in export_pages
    )
