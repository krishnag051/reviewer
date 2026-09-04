"""Previous TP round -- EXTRACTION PLUMBING ONLY, no comparison logic.

Scope, per this round's own brief: reuse the exact same field-extraction
functions already run against the CURRENT TP, point them at a Previous TP
file, and hand back the results in a shape a future compound-rule function
can read alongside the current TP's own extracted fields. The actual
pass/fail comparison for QA-MAST-01, QA-MAST-02, QA-PROB-04, QA-ACF-04, and
QA-RPT-05 is deliberately NOT built here -- it's being held for a separate
round, once real worked examples for each of those 5 rules arrive. Nothing
in this module changes any rule's check_type or result; nothing here is
called from the live rule-checking pipeline yet (see
backend/app/agent_client.py::get_previous_tp_fields for the one thin
backend-side wrapper that calls into this module, and its own docstring for
why it isn't wired into app/rule_engine/client.py::run_rule_checks this
round).

Structural mirror of pipeline/session_note_comparison.py's own extraction
preamble (see backend/app/agent_client.py::review_session_notes, lines
347-350: extract_pdf_text -> extract_fields -> the current-TP-side field
extractors) -- same idea, second file, stops short of the actual "compare"
step that file also contains.
"""
from __future__ import annotations

from .extract import extract_pdf_text
from .fields import (
    _acf_section_page_range,
    _extract_mastered_goals_with_dates,
    _extract_problem_areas,
    _find_labeled_date_range,
    _milestone_grid_page_range,
    extract_acf_fields,
    extract_acf_score_boxed,
    extract_fields,
)
from .render import render_pages_cropped_below_anchor

_MILESTONE_GRID_ANCHOR_PHRASE = "Below you will find the milestone grid"


def extract_previous_tp_fields(previous_tp_pdf_path: str) -> dict:
    """Given a Previous TP's own PDF path, runs the exact same extraction
    steps `review_session_notes` already runs against the CURRENT TP's own
    file (extract_pdf_text -> extract_fields), then pulls the field types
    the Previous TP round's briefs name -- reusing extract_acf_fields,
    extract_acf_score_boxed, and _find_labeled_date_range completely
    unmodified, and the sibling extractors added to fields.py in the
    plumbing round (_extract_mastered_goals_with_dates,
    _extract_problem_areas -- each documented at its own definition for why
    no equivalent already existed to reuse as-is).

    Returns:
        {
            "mastered_goals": [{"name": str, "date_mastered": str | None, "offset": int}, ...],
            "problem_areas": [{"text": str, "offset": int}, ...],
            "acf_fields": {"assessment_date", "pos", "patient_location", "assessment_tool"},
            "acf_score_boxed": float | None,
            "auth_dates_requested": (start, end) | None,
            "report_date_range": (start, end) | None,
            "milestone_grid_images": {page_number: png_bytes, ...},
            "page_count": int,
            "full_text": str,
        }

    `full_text` and `acf_score_boxed` were added in the comparison-logic
    round -- the plumbing round's original 5 keys are unchanged. `full_text`
    exists so pipeline/previous_tp_comparison.py's QA-ACF-04 narrative-score
    judgment fallback and QA-PROB-04's near-identical semantic judgment
    check have real document text to give the model, without either of
    those callers re-running PDF extraction a second time on the same file.

    `report_date_range` and `milestone_grid_images` were added in the
    bugfix round (Fix Round, Previous TP: 3 Real Bugs, Jacob F) --
    - `report_date_range`: "Date of Current Report", the field Bug 1
      confirmed QA-MAST-01 actually needs (NOT "Authorization Dates
      Requested", last round's wrong working assumption) -- same
      `_find_labeled_date_range` helper, just a different, already-used-
      elsewhere-in-this-codebase label string (see `_check_RPT05`/
      `_check_ACF12`'s own identical calls).
    - `milestone_grid_images`: real, rendered PNG bytes for the grid's
      real page(s). CORRECTED in the U3 re-run round: page selection is
      now `_acf_section_page_range(fields) | _milestone_grid_page_range
      (fields)` -- the union of the proven "acf" section span (same
      mechanism CIG-01/QA-ACF-03/06/07/11 already use, confirmed by real
      testing to correctly cover the grid on documents that have NO
      "milestone grid" anchor phrase at all) and the original phrase-
      search finder (kept as a second, additive signal, in case a future
      document has the phrase somewhere outside its own "acf" section
      span). Rendered via `render_pages_cropped_below_anchor` -- higher
      DPI, and cropped to just below the anchor phrase on whichever page
      actually contains it (real, confirmed working on Jacob Freund's
      current TP), full-page-but-still-higher-DPI on any page where the
      phrase isn't found (Jacob Freund's own previous TP -- confirmed
      real case, see that function's own docstring for why no crop
      happens there). Rendered HERE, not left as a page-number list, so
      `previous_tp_comparison.py` never needs to know this module's own
      pdf-path/file-storage details (same separation of concerns
      get_previous_tp_fields's own docstring already keeps for the
      backend layer). Empty dict (no render call made) when no candidate
      pages are found at all.

    Zero MODEL calls in THIS function (page rendering is local PyMuPDF, not
    an API call) -- pure PDF text/image extraction + regex, same as every
    function it calls (extract_acf_score_boxed included: it's a regex-only
    structured-field extractor, not a model call -- see its own docstring
    for the separate, judgment-layer narrative-text case, which lives in
    previous_tp_comparison.py, not here). Raises whatever extract_pdf_text/
    extract_fields raise on a genuinely unreadable file (e.g. a corrupt
    PDF) -- this module adds no extra error handling of its own; the
    caller (backend wrapper) decides how to handle that.
    """
    pages = extract_pdf_text(previous_tp_pdf_path)
    fields = extract_fields(previous_tp_pdf_path, pages)
    text = fields["full_text"]

    grid_pages = sorted(_acf_section_page_range(fields) | _milestone_grid_page_range(fields))
    milestone_grid_images = (
        render_pages_cropped_below_anchor(previous_tp_pdf_path, grid_pages, anchor_phrase=_MILESTONE_GRID_ANCHOR_PHRASE)
        if grid_pages else {}
    )

    return {
        "mastered_goals": _extract_mastered_goals_with_dates(text),
        "problem_areas": _extract_problem_areas(text),
        "acf_fields": extract_acf_fields(fields),
        "acf_score_boxed": extract_acf_score_boxed(fields),
        "auth_dates_requested": _find_labeled_date_range(text, "Authorization Dates Requested"),
        "report_date_range": _find_labeled_date_range(text, "Date of Current Report"),
        "milestone_grid_images": milestone_grid_images,
        "page_count": fields["page_count"],
        "full_text": text,
    }
