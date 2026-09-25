"""Fix Round 12 (mc_current.pdf, real gap found): QA-BAR-01's VB-MAPP
cross-check (built Round 8) requires a real "VB-MAPP Barriers
Assessment:"/"Barriers Assessment:" line-start label -- confirmed against
the real document that this content never appears as a labeled field.
Its real shape is a plain sentence inside the "Assessment Summary
Statement:" narrative paragraph. This was a real, confirmed gap: the
cross-check never fired on the actual document, silently falling back to
the older generic keyword scan. Fixed with a free-prose fallback pattern.
"""

from pipeline import fields


def test_bar01_finds_vbmapp_barriers_stated_as_free_prose_not_a_labeled_section():
    text = (
        "The VB-MAPP Barriers Assessment increased from 20 to 21, indicating that clinically significant "
        "barriers to learning remain present. Identified barriers include behavior problems, "
        "instructional-control difficulties, weak motivation under some conditions, difficulty when response "
        "requirements increase, articulation concerns, hyperactive behavior, and sensory-related needs.\n"
        "Barriers to Treatment:\n"
        "Notes on barriers to treatment:\n"
        "During the reassessment period, the primary barrier to treatment was the loss of Matthielly's usual "
        "structured seating support after her high chair broke.\n"
        "Results of Preference Assessment:\nunrelated text\n"
    )
    f = {"full_text": text, "pages": [{"page_number": 14, "text": text}]}
    result, evidence, page, confidence = fields._check_BAR01({}, f)
    assert result == "fail"
    assert "behavior problems" in evidence
    assert "sensory-related needs" in evidence
    assert "hour" not in evidence.lower()
    assert page == 14


def test_bar01_free_prose_fallback_not_used_when_a_real_labeled_section_exists():
    """The label-based tier must still take priority when a document
    actually has one -- the free-prose fallback only kicks in when the
    label-based search finds nothing."""
    text = (
        "VB-MAPP Barriers Assessment:\nhyperactive behavior, and sensory-related needs.\n"
        "Barriers to Treatment:\n"
        "Client shows hyperactive behavior during sessions and has sensory-related needs.\n"
        "Results of Preference Assessment:\nunrelated\n"
    )
    f = {"full_text": text, "pages": [{"page_number": 14, "text": text}]}
    result, evidence, page, confidence = fields._check_BAR01({}, f)
    assert result == "pass"
    assert "2 barrier" in evidence
