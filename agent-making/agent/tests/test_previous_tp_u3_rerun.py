"""Fix Round -- U3 Re-run: QA-MAST-01 Regression, QA-ACF-04 Vision Still Not
Working, QA-PROB-04 Self-Contradiction.

All three found by running the real system against the real Jacob Freund
pair and diffing the U3 CSV against Ms. Yachnes's confirmed real answers.
Per this round's own explicit instruction, none of Jacob Freund's real
names/dates/goal text/scores are hardcoded anywhere in this file -- every
fixture is synthetic, shaped to exercise the LOGIC each real finding
demonstrated. The real documents themselves were used only to DIAGNOSE
these three bugs (see this round's own report for the real min/max dates,
real grid layout, and real evidence text that led to each fix) -- not
baked into the system as reference data.
"""
import fitz
import pytest

import pipeline.previous_tp_comparison as ptc
from pipeline import fields
from pipeline.model_provider import CallTracker
from pipeline.render import render_pages_cropped_below_anchor


# --- Bug 2: pipeline/render.py::render_pages_cropped_below_anchor ----------


def _make_pdf(page_texts: list[str]) -> str:
    doc = fitz.open()
    for text in page_texts:
        page = doc.new_page()
        page.insert_text((72, 100), text)
    import tempfile
    path = tempfile.mktemp(suffix=".pdf")
    doc.save(path)
    doc.close()
    return path


def test_render_cropped_below_anchor_crops_when_phrase_is_found():
    path = _make_pdf(["Some paragraph text.\nBelow you will find the milestone grid\nmore text"])
    full_page = render_pages_cropped_below_anchor(path, [1], anchor_phrase=None)
    cropped = render_pages_cropped_below_anchor(path, [1], anchor_phrase="Below you will find the milestone grid")
    # A real crop starting partway down the page must produce a SMALLER
    # image than the uncropped full-page render at the same DPI.
    assert len(cropped[1]) < len(full_page[1])


def test_render_cropped_below_anchor_falls_back_to_full_page_when_phrase_absent():
    """Fix Round (U3 re-run), Bug 2 -- confirmed real case: Jacob Freund's
    own previous TP has no anchor phrase before its grid at all. Must
    still render (uncropped, at the higher DPI), not silently produce
    nothing."""
    path = _make_pdf(["A page with no anchor phrase on it at all."])
    result = render_pages_cropped_below_anchor(path, [1], anchor_phrase="Below you will find the milestone grid")
    assert 1 in result
    assert len(result[1]) > 0


def test_render_cropped_below_anchor_uses_higher_dpi_than_the_main_pipeline_default():
    from pipeline.render import CROPPED_RENDER_DPI, RENDER_DPI
    assert CROPPED_RENDER_DPI > RENDER_DPI


# --- Bug 2: fields.py registry now uses the proven "acf" section ----------


def test_acf_section_finder_covers_a_grid_page_with_no_anchor_phrase():
    """Fix Round (U3 re-run), Bug 2's real root cause: the ORIGINAL
    phrase-only finder found zero pages on a document with no anchor
    phrase before its grid (confirmed real case, Jacob Freund's own
    previous TP). The 'acf' section finder must still find real pages for
    such a document, since the grid lives inside the ACF section
    regardless of whether the phrase is present."""
    text = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 02/12/2026\n"
        + ("filler line\n" * 50) +  # push the boundary marker onto a later page
        "Goal Progress:\n"
    )
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate([text[:200], text[200:400], text[400:]])]
    full_text = "".join(p["text"] for p in pages)
    fields_dict = {"pages": pages, "full_text": full_text}
    acf_pages = fields._acf_section_page_range(fields_dict)
    milestone_pages = fields._milestone_grid_page_range(fields_dict)
    assert acf_pages  # the acf section itself is found...
    assert milestone_pages == set()  # ...even though there's no anchor phrase anywhere


# --- Bug 2: vision prompt now asks for the MOST RECENT completed row ------


def test_acf04_vision_prompt_asks_for_most_recent_row_not_just_any_score(monkeypatch):
    captured = []

    def fake_vision_call(**kwargs):
        captured.append(kwargs["prompt_text"])
        return {"found": True, "score": 110.5, "score_date": "Aug-26"}

    monkeypatch.setattr(ptc, "call_tool_json_with_images", fake_vision_call)
    current = {
        "acf_score_boxed": None, "acf_fields": {"assessment_tool": "VB-MAPP"},
        "full_text": "text", "milestone_grid_images": {8: b"fake"},
    }
    previous = {"acf_score_boxed": 98.0, "acf_fields": {"assessment_tool": "VB-MAPP"}, "full_text": "boxed", "milestone_grid_images": {}}
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert "most recent" in captured[0].lower()
    assert "blank" in captured[0].lower()  # explicit instruction not to pick a blank row
    assert result["result"] == "pass"  # 110.5 > 98
    assert "dated Aug-26" in result["evidence"]  # real traceability -- which row was read


def test_acf04_vision_score_never_silently_picks_a_blank_row(monkeypatch):
    """The schema itself can't enforce this (the model could still get it
    wrong), but confirms the code correctly uses whatever
    found=False/score=None the model returns for an all-blank grid,
    rather than crashing or guessing zero."""
    monkeypatch.setattr(ptc, "call_tool_json_with_images", lambda **kwargs: {"found": False, "score": None, "score_date": None})
    current = {"acf_score_boxed": None, "acf_fields": {}, "full_text": "text", "milestone_grid_images": {8: b"fake"}}
    previous = {"acf_score_boxed": None, "acf_fields": {}, "full_text": "text", "milestone_grid_images": {}}
    monkeypatch.setattr(ptc, "call_tool_json", lambda **kwargs: {"found": False, "score": None})
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "not_checkable"


# --- Bug 1: widened elapsed-authorization window ----------------------------


def test_mast01_real_shape_cumulative_list_spanning_many_months_now_passes():
    """Reproduces the real Jacob Freund shape directly (dates/counts
    invented, not his real ones): a genuinely cumulative Mastered Goals
    list with dates spanning many months, all of which fall within the
    widened [previous report start, current report end] window even
    though most fall well outside the previous TP's own narrow report
    window alone -- this must now PASS, where the prior round's fix
    would have failed nearly all of them."""
    current_goals = [
        {"name": f"Goal {i}", "date_mastered": d, "offset": i}
        for i, d in enumerate([
            "02/12/2026", "03/19/2026", "04/30/2026", "05/18/2026", "06/09/2026",
            "07/09/2026", "08/10/2026",
        ])
    ]
    current = {"mastered_goals": current_goals, "report_date_range": ("08/10/2026", "08/21/2026")}
    previous = {"report_date_range": ("02/10/2026", "02/26/2026")}
    result = ptc._compare_mast01(current, previous)
    assert result["result"] == "pass"


def test_mast01_still_catches_a_genuinely_implausible_date():
    """The widened window is strictly MORE permissive than before, but
    still real and bounded -- a date before the previous TP's own report
    even started (implausible -- the goal couldn't have been mastered
    before this authorization period began) must still fail."""
    current = {
        "mastered_goals": [{"name": "Goal X", "date_mastered": "01/01/2026", "offset": 0}],
        "report_date_range": ("08/10/2026", "08/21/2026"),
    }
    previous = {"report_date_range": ("02/10/2026", "02/26/2026")}
    result = ptc._compare_mast01(current, previous)
    assert result["result"] == "fail"
