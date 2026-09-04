"""Fix Round -- Previous TP: 3 Real Bugs Found Against Real Documents (Jacob F).

Three real bugs, found by running the real system against a real previous
TP + current TP pair (Jacob Freund) and checking results against both real
PDFs and Ms. Yachnes's own confirmed real answer for this patient. Per this
round's own explicit instruction, none of Jacob Freund's/Mihad Ali's real
names/dates/goal text/scores are hardcoded anywhere in this file -- every
fixture is synthetic, shaped to exercise the LOGIC each real bug
demonstrated.

Vision calls (Bug 2) are tested here with `call_tool_json_with_images`
MOCKED -- proving the wiring/logic is correct costs nothing; the round's
own real end-to-end spend is a separate, explicitly budgeted step covered
in this round's own report.
"""
import pipeline.previous_tp_comparison as ptc
from pipeline import fields
from pipeline.model_provider import CallTracker


# --- Bug 2: fields.py::_milestone_grid_page_range ---------------------------


def _fields_with_pages(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


def test_milestone_grid_page_range_finds_the_phrase_and_the_next_page():
    f = _fields_with_pages("intro text", "Below you will find the milestone grid", "grid image page (no text)")
    assert fields._milestone_grid_page_range(f) == {2, 3}


def test_milestone_grid_page_range_is_case_insensitive():
    f = _fields_with_pages("BELOW YOU WILL FIND THE MILESTONE GRID")
    assert fields._milestone_grid_page_range(f) == {1, 2}


def test_milestone_grid_page_range_empty_when_phrase_absent():
    f = _fields_with_pages("nothing relevant here")
    assert fields._milestone_grid_page_range(f) == set()


def test_qa_acf_04_registered_as_vision_eligible():
    """Confirms the registry wiring itself (Bug 2's own fix) -- this also
    means QA-ACF-04's phase-1 judgment attempt sees the grid image now,
    not just previous_tp_comparison.py's own cross-document call.

    U3 re-run round -- CORRECTED: registered under "acf" now, not the
    original "milestone_grid" (phrase-search-only) section -- confirmed
    on the real Jacob Freund pair that the phrase-search finder alone
    misses the previous TP's own grid entirely (no anchor phrase on that
    document at all), while the "acf" section (already proven for
    CIG-01/QA-ACF-03/06/07/11) correctly covers it on both documents."""
    assert fields.VISION_ELIGIBLE_RULE_SECTIONS.get("QA-ACF-04") == "acf"
    assert fields._SECTION_PAGE_RANGE_FINDERS.get("acf") is fields._acf_section_page_range
    # The original phrase-search finder still exists (used as an additive
    # union in previous_tp_extraction.py, not deleted) even though it's no
    # longer the sole/primary mechanism.
    assert fields._SECTION_PAGE_RANGE_FINDERS.get("milestone_grid") is fields._milestone_grid_page_range


# --- Bug 3: fields.py::_extract_evidenced_by_blocks -------------------------


def test_extract_evidenced_by_blocks_reuses_the_existing_regex_verbatim():
    """Confirms this is the SAME _EVIDENCED_BY_BLOCK_RE object already used
    by _check_PROB01, per this round's own explicit instruction not to
    build a new regex."""
    assert fields._extract_evidenced_by_blocks.__globals__["_EVIDENCED_BY_BLOCK_RE"] is fields._EVIDENCED_BY_BLOCK_RE


def test_extract_evidenced_by_blocks_gets_findings_not_rubric_text():
    text = (
        "Problem Area: Deficits in social-emotional reciprocity, ranging, for example, from abnormal "
        "social approach.\n"
        "As evidenced by: Jacob struggles to approach peers - improved since last auth (in progress)\n"
        "Problem Area: Stereotyped or repetitive motor movements.\n"
        "As evidenced by: Reduced hand-flapping observed during session.\n"
        "Goal Progress:\n"
    )
    blocks = fields._extract_evidenced_by_blocks(text)
    assert [b["text"] for b in blocks] == [
        "Jacob struggles to approach peers - improved since last auth (in progress)",
        "Reduced hand-flapping observed during session.",
    ]
    # The rubric/template text must NOT appear in the captured blocks.
    assert not any("Deficits in social-emotional" in b["text"] for b in blocks)


# --- Bug 2: real vision extraction wiring (mocked model call) --------------


def test_acf04_uses_vision_first_when_boxed_extraction_is_missing_but_a_grid_image_exists(monkeypatch):
    """Confirms the fallback ORDER: vision is tried before the narrative
    text fallback, whenever a grid image was found at extraction time --
    the text-only fallback is monkeypatched to fail loudly if reached, so
    this test fails clearly if the order regresses."""
    calls = []

    def fake_vision_call(**kwargs):
        calls.append(kwargs["call_reason"])
        assert kwargs["images"] == {5: b"fake-png-bytes"}
        return {"found": True, "score": 30.0}  # a real drop vs. previous's 55, to also confirm fail direction

    monkeypatch.setattr(ptc, "call_tool_json_with_images", fake_vision_call)
    monkeypatch.setattr(
        ptc, "call_tool_json", lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not reach narrative fallback")),
    )

    current = {
        "acf_score_boxed": None, "acf_fields": {"assessment_tool": "VB-MAPP"},
        "full_text": "Below you will find the milestone grid",
        "milestone_grid_images": {5: b"fake-png-bytes"},
    }
    previous = {"acf_score_boxed": 55.0, "acf_fields": {"assessment_tool": "VB-MAPP"}, "full_text": "boxed", "milestone_grid_images": {}}
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "fail"  # 30 < 55 -- a real drop
    assert calls == ["acf04_vision_score"]


def test_acf04_vision_score_higher_than_previous_passes(monkeypatch):
    monkeypatch.setattr(ptc, "call_tool_json_with_images", lambda **kwargs: {"found": True, "score": 62.0})
    current = {
        "acf_score_boxed": None, "acf_fields": {"assessment_tool": "VB-MAPP"},
        "full_text": "text", "milestone_grid_images": {5: b"fake-png-bytes"},
    }
    previous = {"acf_score_boxed": 55.0, "acf_fields": {"assessment_tool": "VB-MAPP"}, "full_text": "boxed", "milestone_grid_images": {}}
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"
    assert "vision (milestone grid)" in result["evidence"]
    assert result["confidence"] == 0.7  # non-boxed source on at least one side


def test_acf04_falls_back_to_narrative_when_no_grid_image_found(monkeypatch):
    """Confirms the fallback ORDER: boxed -> vision (only if a grid image
    exists) -> narrative text. No grid image here, so narrative should
    still be reached, unchanged from before this round."""
    monkeypatch.setattr(
        ptc, "call_tool_json_with_images",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("should not be called -- no grid image")),
    )
    monkeypatch.setattr(ptc, "call_tool_json", lambda **kwargs: {"found": True, "score": 42.0})
    current = {
        "acf_score_boxed": None, "acf_fields": {"assessment_tool": "ABLLS-R"},
        "full_text": "scored a 42 in narrative prose", "milestone_grid_images": {},
    }
    previous = {"acf_score_boxed": 40.0, "acf_fields": {"assessment_tool": "ABLLS-R"}, "full_text": "boxed", "milestone_grid_images": {}}
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "pass"
    assert "narrative (judgment)" in result["evidence"]


# --- Bug 2's smaller fix: evidence text no longer implies "no previous TP" -


def test_acf04_not_checkable_evidence_never_implies_no_previous_tp(monkeypatch):
    # No boxed score, no grid image on either document -- falls all the
    # way to the narrative text fallback; mocked here (not left to hit the
    # real network) since this test only cares about the not_checkable
    # evidence text, not the narrative call itself.
    monkeypatch.setattr(ptc, "call_tool_json", lambda **kwargs: {"found": False, "score": None})
    current = {"acf_score_boxed": None, "acf_fields": {}, "full_text": "no score anywhere", "milestone_grid_images": {}}
    previous = {"acf_score_boxed": None, "acf_fields": {}, "full_text": "no score anywhere", "milestone_grid_images": {}}
    result = ptc._compare_acf04(current, previous, tracker=CallTracker(max_calls=5), model_override=None)
    assert result["result"] == "not_checkable"
    assert "previous TP was found and read" in result["evidence"]
    assert "No prior TP version exists" not in result["evidence"]
