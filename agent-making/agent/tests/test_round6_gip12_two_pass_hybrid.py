"""Fix Round 6 (Zaith 9-2026-U1): QA-GIP-12's two-pass hybrid. A real
staging run found judgment alone only covered 7 of ~12 real pages with a
literal verbal-operant term (mand/tact/intraverbal/echoic). This rule
can't be converted to a fully deterministic checker -- its own notes
document a real semantic exception ("will request..." passes as
mand-shaped without the literal word) that genuinely needs judgment. Pass
1 (fields.py::gip12_verbal_operant_candidate_pages) is the deterministic
floor; Pass 2 (run_full_pipeline's own extra_context injection) feeds it
to the real judgment call. These tests cover Pass 1 directly -- Pass 2's
actual judgment-quality effect needs a real, separately-approved API run.
"""

from pipeline import fields
from pipeline import run_full_pipeline


def _goal_pages():
    pages = [
        {"page_number": 10, "text": "Target Goal: Reeda will mand by calling BT's name\nGoal Status: In progress\n"},
        {"page_number": 11, "text": "Target Goal: Reeda will tact 10 common objects\nGoal Status: In progress\n"},
        {"page_number": 12, "text": "Target Goal: no operant term here at all\nGoal Status: In progress\n"},
        {
            "page_number": 13,
            "text": "Target Goal: Reeda will answer intraverbal questions\nGoal Status: In progress\n",
        },
        {"page_number": 14, "text": "Target Goal: Reeda will echoic repeat sounds\nGoal Status: In progress\n"},
    ]
    return {"full_text": "\n".join(p["text"] for p in pages), "pages": pages}


def test_gip12_candidate_scan_finds_every_literal_verbal_operant_term():
    hits = fields.gip12_verbal_operant_candidate_pages(_goal_pages())
    pages_found = {page for page, _name, _term in hits}
    terms_found = {term for _page, _name, term in hits}
    assert pages_found == {10, 11, 13, 14}
    assert terms_found == {"mand", "tact", "intraverbal", "echoic"}


def test_gip12_candidate_scan_skips_goals_with_no_operant_term():
    hits = fields.gip12_verbal_operant_candidate_pages(_goal_pages())
    assert not any(page == 12 for page, _name, _term in hits)


def test_gip12_candidate_scan_empty_when_no_goal_blocks_at_all():
    assert fields.gip12_verbal_operant_candidate_pages({"full_text": "no goals here"}) == []


def test_run_full_pipeline_injects_gip12_candidates_as_extra_context():
    """Confirms the Pass-1-to-Pass-2 wiring itself, not judgment quality:
    QA-GIP-12's own rule dict must carry the real candidate list as
    extra_context by the time the judgment batch is built. Zero real API
    calls -- this only inspects the rules list run_full_pipeline builds
    before making its (blocked-in-tests) judgment call.
    """
    import pipeline as pipeline_module

    captured = {}
    orig = pipeline_module.integrity.run_judgment_with_integrity_check

    def _capture(full_judgment_batch, *args, **kwargs):
        captured["batch"] = full_judgment_batch
        return {r["rule_id"]: {"result": "uncertain", "evidence": "", "page": None, "confidence": 0.0}
                 for r in full_judgment_batch}

    pipeline_module.integrity.run_judgment_with_integrity_check = _capture
    try:
        rules = [
            {
                "rule_id": "QA-GIP-12", "check_type": "judgment", "active": True,
                "applies_to_payor": "ALL", "applies_to_plan_type": "Both",
                "description": "Goals include verbal operant/behavioral term", "category": "Goals in Progress",
            },
        ]
        pages = [
            {"page_number": 1, "text": "Target Goal: Reeda will mand by calling BT's name\nGoal Status: In progress\n"},
        ]
        import tempfile
        from pypdf import PdfWriter

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.write(tmp.name)
            tmp_path = tmp.name

        import pipeline.extract as extract_module
        orig_extract = extract_module.extract_pdf_text
        extract_module.extract_pdf_text = lambda _path: pages
        pipeline_module.extract_pdf_text = extract_module.extract_pdf_text
        try:
            run_full_pipeline(tmp_path, rules)
        finally:
            extract_module.extract_pdf_text = orig_extract
            pipeline_module.extract_pdf_text = orig_extract
    finally:
        pipeline_module.integrity.run_judgment_with_integrity_check = orig

    batch_by_id = {r["rule_id"]: r for r in captured["batch"]}
    assert "QA-GIP-12" in batch_by_id
    assert "mand" in batch_by_id["QA-GIP-12"]["extra_context"]
    assert "page 1" in batch_by_id["QA-GIP-12"]["extra_context"]
