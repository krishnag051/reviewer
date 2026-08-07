"""Round 64: fix the remaining QA-ACF-07 bug, fix the QA-GIP-09/QA-SCH-08
POS-source regression, and real highlight-detection for QA-TEMP-03. Every
fixture here is SYNTHETIC and self-built (including real PDFs for the
highlight tests) -- none reference Yisroel Leibowitz's name, dates, tool,
or wording. Zero model calls anywhere in this file.
"""
import fitz
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# ------------------------------------------- item 1: QA-ACF-07 (see also
# tests/test_item1_backlog_checkers.py for the primary synthetic coverage
# added directly alongside this fix -- these two are additional, distinct
# synthetic cases specific to Round 64's own verification ask).


def test_acf07_same_tool_two_dates_via_different_labels_still_passes():
    """SYNTHETIC: one date under 'Assessment Date:', a second under
    'Total Score on <date>:' for the SAME tool -- proves the two
    recognized date-label formats combine correctly, not just each alone."""
    text = (
        "Assessment of Current Functioning:\nAssessment Date: 05/01/2025\n"
        "The ADOS was administered.\n"
        "Assessment Summary Statement:\nTotal Score on 11/12/2025: 44\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result == "pass"


def test_acf07_genuinely_no_date_anywhere_is_not_a_guessed_pass():
    text = (
        "Assessment of Current Functioning:\nAssessment Methods/Measures: The CARS was administered.\n"
        "Assessment Summary Statement: Client shows continued need for support.\n"
        "Goal Progress:\n"
    )
    result, evidence, page, confidence = fields._check_ACF07({}, _fields(text))
    assert result in ("fail", "not_checkable")
    assert result != "pass"


# --------------------------------------------- item 2: POS-source notes --
# GIP-09/SCH-08/GIP-08 are judgment-only rules (no deterministic checker),
# so their fix lives in rules.json's notes text, not Python -- verified via
# a real (free OpenRouter) judgment call during this round's own work
# (see the Round 64 report), not re-testable here without a live call.
# This locks in the textual fix itself so a future edit can't silently
# drop it.


def test_gip09_notes_specify_hours_requesting_as_the_pos_source():
    import json
    from pathlib import Path

    rules = json.loads((Path(__file__).parent.parent / "rules" / "rules.json").read_text(encoding="utf-8"))["rules"]
    gip09 = next(r for r in rules if r["rule_id"] == "QA-GIP-09")
    sch08 = next(r for r in rules if r["rule_id"] == "QA-SCH-08")
    gip08 = next(r for r in rules if r["rule_id"] == "QA-GIP-08")
    for rule in (gip09, sch08, gip08):
        assert "Hours Requesting" in rule["notes"]
        assert "schedule grid" in rule["notes"] or "Schedule grid" in rule["notes"]


# --------------------------------------------- item 3: QA-TEMP-03, real --
# Self-built synthetic PDFs with KNOWN ground truth, not Yisroel's file.


def _pdf_with_real_highlight(tmp_path) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This is a test sentence with a HIGHLIGHTED word in it.")
    rect = page.search_for("HIGHLIGHTED")[0]
    page.add_highlight_annot(rect)
    path = tmp_path / "real_highlight.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _pdf_with_no_highlight(tmp_path) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This is a test sentence with a PLAIN word in it.")
    path = tmp_path / "plain.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def _pdf_with_flattened_highlight(tmp_path) -> str:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "This is a test sentence with a FLATTENED word in it.")
    rect = page.search_for("FLATTENED")[0]
    shape = page.new_shape()
    shape.draw_rect(rect)
    shape.finish(color=None, fill=(1, 1, 0), fill_opacity=0.4)
    shape.commit()
    path = tmp_path / "flattened.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_temp03_fails_on_a_real_highlight_annotation(tmp_path):
    pdf_path = _pdf_with_real_highlight(tmp_path)
    result, evidence, page, confidence = fields._check_TEMP03({}, {"pdf_path": pdf_path})
    assert result == "fail"
    assert "Highlight annotation" in evidence


def test_temp03_passes_with_no_highlighting_at_all(tmp_path):
    pdf_path = _pdf_with_no_highlight(tmp_path)
    result, evidence, page, confidence = fields._check_TEMP03({}, {"pdf_path": pdf_path})
    assert result == "pass"


def test_temp03_fails_on_a_flattened_highlight_fill_too(tmp_path):
    """The case real annotation detection structurally cannot see --
    proves the fallback method actually works, not just the primary one."""
    pdf_path = _pdf_with_flattened_highlight(tmp_path)
    result, evidence, page, confidence = fields._check_TEMP03({}, {"pdf_path": pdf_path})
    assert result == "fail"
    assert "fill" in evidence.lower()


def test_temp03_not_checkable_with_no_pdf_path():
    result, evidence, page, confidence = fields._check_TEMP03({}, {})
    assert result == "not_checkable"
