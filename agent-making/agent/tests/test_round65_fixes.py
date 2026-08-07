"""Round 65: fix QA-ACF-08's exact-match bug (substring instead) and
QA-ACF-02's field-pairing + note-selection bug. Every fixture here is
SYNTHETIC -- none reference Yisroel Leibowitz's name, dates, or wording.
Zero model calls anywhere in this file.
"""
from pipeline.session_note_comparison import (
    check_tool_mentioned,
    compare_session_note_to_tp,
    compare_session_notes_to_tp,
    select_matching_session_note,
)


def _extraction(**overrides) -> dict:
    base = {
        "session_date": {"value": "03/10/2025", "confidence": "high", "source_quote": "q"},
        "session_location": {"value": "Office", "confidence": "high", "source_quote": "q"},
        "clinician_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "patient_telehealth_location": {"value": None, "confidence": "none", "source_quote": None},
        "assessment_activity": {"value": "PEAK", "confidence": "high", "source_quote": "q"},
    }
    base.update(overrides)
    return base


# ------------------------------------------------- item 1: check_tool_mentioned


def test_tool_mentioned_passes_when_tool_is_one_of_several_checked_items():
    result = check_tool_mentioned(
        "Direct observation/treatment of patient to inform treatment goals; Treatment plan development; PEAK",
        "PEAK",
        field_label="Assessment type/tool",
    )
    assert result["result"] == "pass"


def test_tool_mentioned_fails_when_tool_genuinely_absent():
    result = check_tool_mentioned(
        "Direct observation/treatment of patient to inform treatment goals; Treatment plan development",
        "PEAK",
        field_label="Assessment type/tool",
    )
    assert result["result"] == "fail"


def test_tool_mentioned_fails_when_a_different_tool_is_present():
    """Proves this is a real substring check, not something that
    accidentally always passes -- a different tool present must still
    fail, not pass just because SOME tool name is in the text."""
    result = check_tool_mentioned(
        "Direct observation/treatment of patient to inform treatment goals; VB-MAPP",
        "PEAK",
        field_label="Assessment type/tool",
    )
    assert result["result"] == "fail"


def test_tool_mentioned_uncertain_when_either_side_missing():
    assert check_tool_mentioned(None, "PEAK", field_label="x")["result"] == "uncertain"
    assert check_tool_mentioned("PEAK", None, field_label="x")["result"] == "uncertain"


def test_compare_session_note_to_tp_acf08_now_passes_via_substring():
    """End-to-end proof through the real orchestration function, not just
    the standalone comparison function."""
    result = compare_session_note_to_tp(
        _extraction(assessment_activity={
            "value": "Direct observation; Treatment plan development; PEAK", "confidence": "high", "source_quote": "q",
        }),
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Office",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-ACF-08"]["result"] == "pass"


# ------------------------------------------------- item 2a: field pairing --


def test_acf02_clinician_location_uses_session_location_not_telehealth_sublocation():
    """SYNTHETIC reproduction of the real bug shape: TP states the overall
    modality ('Telehealth'); the session note's session_location agrees
    ('Telehealth'), but its finer clinician_telehealth_location sub-detail
    is a DIFFERENT fact ('Clinician's Home') that has no TP-side
    counterpart at all. Must pass -- the correct pairing is
    tp_pos vs. session_location, not vs. clinician_telehealth_location."""
    result = compare_session_note_to_tp(
        _extraction(
            session_location={"value": "Telehealth", "confidence": "high", "source_quote": "q"},
            clinician_telehealth_location={"value": "Clinician's Home", "confidence": "high", "source_quote": "q"},
            patient_telehealth_location={"value": "Office", "confidence": "high", "source_quote": "q"},
        ),
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Telehealth",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-ACF-02"]["result"] == "pass"
    assert "clinician location" not in result["QA-ACF-02"]["evidence"].lower() or "Telehealth" in result["QA-ACF-02"]["evidence"]


def test_acf02_still_fails_on_a_genuinely_different_modality():
    """Negative direction: TP says Telehealth, session's own session_location
    says something genuinely different (Home, in-person) -- must still fail."""
    result = compare_session_note_to_tp(
        _extraction(
            session_location={"value": "Home", "confidence": "high", "source_quote": "q"},
            clinician_telehealth_location={"value": None, "confidence": "none", "source_quote": None},
            patient_telehealth_location={"value": "Home", "confidence": "high", "source_quote": "q"},
        ),
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Telehealth",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-ACF-02"]["result"] == "fail"


# --------------------------------------------- item 2b: note selection ----


def test_select_matching_session_note_finds_the_date_matched_note_among_several():
    notes = {
        "note_a.pdf": _extraction(session_date={"value": "03/12/2025", "confidence": "high", "source_quote": "q"}),
        "note_b.pdf": _extraction(session_date={"value": "03/10/2025", "confidence": "high", "source_quote": "q"}),
        "note_c.pdf": _extraction(session_date={"value": "03/14/2025", "confidence": "high", "source_quote": "q"}),
    }
    filename, extraction = select_matching_session_note(notes, "03/10/2025")
    assert filename == "note_b.pdf"
    assert extraction is notes["note_b.pdf"]


def test_select_matching_session_note_none_when_no_note_matches():
    notes = {
        "note_a.pdf": _extraction(session_date={"value": "03/12/2025", "confidence": "high", "source_quote": "q"}),
    }
    filename, extraction = select_matching_session_note(notes, "03/10/2025")
    assert filename is None
    assert extraction is None


def test_select_matching_session_note_none_when_tp_date_unparseable():
    notes = {
        "note_a.pdf": _extraction(session_date={"value": "03/10/2025", "confidence": "high", "source_quote": "q"}),
    }
    filename, extraction = select_matching_session_note(notes, "sometime in March")
    assert filename is None
    assert extraction is None


def test_compare_session_notes_to_tp_only_uses_the_date_matched_note_for_acf02_08():
    """The full multi-note orchestration: 3 uploaded notes, only ONE's date
    matches the TP's stated Assessment Date -- confirm ACF-02/ACF-08 are
    computed against that one only, proven by giving the OTHER notes
    deliberately WRONG data that would fail if they were (wrongly) used."""
    notes = {
        "wrong_date_but_matching_data.pdf": _extraction(
            session_date={"value": "03/12/2025", "confidence": "high", "source_quote": "q"},
            session_location={"value": "Telehealth", "confidence": "high", "source_quote": "q"},
            assessment_activity={"value": "PEAK", "confidence": "high", "source_quote": "q"},
        ),
        "matching_date.pdf": _extraction(
            session_date={"value": "03/10/2025", "confidence": "high", "source_quote": "q"},
            session_location={"value": "Telehealth", "confidence": "high", "source_quote": "q"},
            patient_telehealth_location={"value": "Office", "confidence": "high", "source_quote": "q"},
            assessment_activity={"value": "PEAK", "confidence": "high", "source_quote": "q"},
        ),
        "wrong_date_and_mismatched_data.pdf": _extraction(
            session_date={"value": "03/14/2025", "confidence": "high", "source_quote": "q"},
            session_location={"value": "Home", "confidence": "high", "source_quote": "q"},
            assessment_activity={"value": "ABLLS-R", "confidence": "high", "source_quote": "q"},
        ),
    }
    result = compare_session_notes_to_tp(
        notes,
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Telehealth",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-ACF-02"]["result"] == "pass"
    assert result["QA-ACF-08"]["result"] == "pass"
    # QA-RPT-03 is checked against every note independently -- all 3 dates
    # fall within the report window here, so it should still pass overall.
    assert result["QA-RPT-03"]["result"] == "pass"


def test_compare_session_notes_to_tp_uncertain_when_no_note_matches_assessment_date():
    notes = {
        "note_a.pdf": _extraction(session_date={"value": "03/12/2025", "confidence": "high", "source_quote": "q"}),
    }
    result = compare_session_notes_to_tp(
        notes,
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Telehealth",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-ACF-02"]["result"] == "uncertain"
    assert result["QA-ACF-08"]["result"] == "uncertain"
    assert "no uploaded session note" in result["QA-ACF-02"]["evidence"].lower()


def test_compare_session_notes_to_tp_rpt03_fails_if_any_note_out_of_range():
    notes = {
        "in_range.pdf": _extraction(session_date={"value": "03/10/2025", "confidence": "high", "source_quote": "q"}),
        "out_of_range.pdf": _extraction(session_date={"value": "05/01/2025", "confidence": "high", "source_quote": "q"}),
    }
    result = compare_session_notes_to_tp(
        notes,
        tp_current_report_period="03/01/2025 to 03/15/2025",
        tp_assessment_date="03/10/2025",
        tp_pos="Telehealth",
        tp_patient_location="Office",
        tp_assessment_tool="PEAK",
    )
    assert result["QA-RPT-03"]["result"] == "fail"
