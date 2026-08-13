"""Fix Round: six related robustness gaps. Every fix here is a general
mechanism, verified on synthetic documents with MADE-UP names/content never
seen in this project's real documents (Zohan Hossain, Blythe Diaz, Yisroel
Leibowitz, Shea Freund) or in any prior round's test fixtures -- precisely
so there's no way a fix could be accidentally overfit to one of those.
"""
import pytest

from pipeline import fields


def _fields(*page_texts: str) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts)}


# =========================================================================
# Item 1: rapidfuzz-based filename/name check (QA-PPI-03)
# =========================================================================
# Made-up patient never used in any prior round: "Priya Ferreira".

def test_item1_exact_filename_match_scores_100_and_passes():
    doc_fields = _fields("Patient Name: Priya Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n")
    doc_fields["source_filename"] = "Priya Ferreira TP.pdf"
    score = fields._name_filename_score("Priya Ferreira", "Priya Ferreira TP.pdf")
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    print(f"[Item 1] exact match score = {score}")
    assert score == 100.0
    assert result == "pass"


def test_item1_one_character_filename_typo_fails():
    """Made-up one-character mismatch, same shape as the real confirmed
    case but with a never-before-used name."""
    doc_fields = _fields("Patient Name: Priya Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n")
    doc_fields["source_filename"] = "Priya Fereira TP.pdf"  # one 'r' dropped
    score = fields._name_filename_score("Priya Ferreira", "Priya Fereira TP.pdf")
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    print(f"[Item 1] one-character typo score = {score}")
    assert score is not None and score < fields._FILENAME_MATCH_THRESHOLD
    assert result == "fail"
    assert str(score)[:4] not in ("100.",)


def test_item1_middle_and_last_name_initials_in_filename_still_pass():
    """REAL REGRESSION caught by testing against a real document (not one
    of the four hard-constraint names -- this is Priya's made-up case,
    shaped the same way): a filename using initials for the middle/last
    name ('Priya F R.pdf' for 'Priya Ferreira Reyes') is a legitimate,
    common convention, not a mismatch."""
    doc_fields = _fields("Patient Name: Priya Ferreira Reyes Patient DOB: 03/03/2019 Patient Insurance: 999\n")
    doc_fields["source_filename"] = "Priya F R.pdf"
    score = fields._name_filename_score("Priya Ferreira Reyes", "Priya F R.pdf")
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    print(f"[Item 1] initials-in-filename score = {score}")
    assert score == 100.0
    assert result == "pass"


def test_item1_filler_text_around_matching_name_still_passes():
    """The task's own example shape: extra filler text around a matching
    name must not be penalized -- token_set_ratio chosen specifically for
    this."""
    doc_fields = _fields("Patient Name: Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n")
    doc_fields["source_filename"] = "patient_ferreira_v2_final.pdf"
    score = fields._name_filename_score("Ferreira", "patient_ferreira_v2_final.pdf")
    result, evidence, page, confidence = fields._check_PPI03({}, doc_fields)
    print(f"[Item 1] filler-text score = {score}")
    assert score == 100.0
    assert result == "pass"


# =========================================================================
# Item 2: NER-based narrative name-contamination detection
# =========================================================================

def _prob_doc(narrative_extra: str, pcp: str | None = None, mother: str | None = None) -> str:
    lines = [
        "Patient Name: Priya Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n",
    ]
    if pcp:
        lines.append(f"PCP Name: {pcp}\n")
    if mother:
        lines.append(f"Mother's Name: {mother}\n")
    lines.append(
        "Developmental/Psychological History: Priya was born full-term with no complications. "
        f"{narrative_extra}\n"
    )
    return "".join(lines)


def test_item2_flags_a_narrative_name_not_on_the_documents_own_allow_list():
    """A name in narrative text that isn't the patient, a stated family
    member, or a stated provider -- should flag. 'Marcus Whitfield' is a
    made-up name never used anywhere else in this fix, appearing ONLY in
    the narrative, not in any structured field."""
    text = _prob_doc(
        "Her PCP is Dr. Marcus Whitfield, who has managed her care since infancy.",
        pcp="Dr. Sandra Okafor",
    )
    doc_fields = _fields(text)
    result, evidence, page, confidence = fields._check_narrative_name_contamination({}, doc_fields)
    print(f"[Item 2] contaminated-narrative result = {result}, evidence = {evidence}")
    assert result in ("fail", "uncertain")
    assert "Whitfield" in str(evidence)


def test_item2_does_not_flag_a_legitimate_stated_family_member_or_provider():
    text = _prob_doc(
        "Her mother, Ana Ferreira, reports no complications during pregnancy. Her PCP, Dr. Sandra Okafor, "
        "has managed her care since infancy.",
        pcp="Dr. Sandra Okafor",
        mother="Ana Ferreira",
    )
    doc_fields = _fields(text)
    result, evidence, page, confidence = fields._check_narrative_name_contamination({}, doc_fields)
    print(f"[Item 2] legitimate-names result = {result}, evidence = {evidence}")
    assert result in ("pass", "not_checkable")


# =========================================================================
# Item 3: cross-rule contradiction post-processing pass
# =========================================================================

def test_item3_flags_a_direct_blank_vs_populated_contradiction():
    det_results = {
        "QA-ACF-01": {"result": "pass", "evidence": "Date/location fields are present.", "page": 1, "confidence": 0.8},
        "QA-ACF-05": {"result": "pass", "evidence": "Assessment Summary Statement is documented: ...", "page": 2, "confidence": 0.8},
        "QA-ACF-07": {"result": "fail", "evidence": "The Assessment of Current Functioning section is entirely blank.", "page": 1, "confidence": 0.8},
    }
    flags = fields.find_cross_rule_contradictions(det_results)
    print(f"[Item 3] contradiction flags = {flags}")
    assert flags
    assert any("QA-ACF-07" in f["rule_ids"] for f in flags)


def test_item3_clean_document_produces_zero_false_flags():
    det_results = {
        "QA-ACF-01": {"result": "pass", "evidence": "Date/location fields are present.", "page": 1, "confidence": 0.8},
        "QA-ACF-05": {"result": "pass", "evidence": "Assessment Summary Statement is documented: ...", "page": 2, "confidence": 0.8},
        "QA-ACF-07": {"result": "pass", "evidence": "Testing tool administration dates found.", "page": 1, "confidence": 0.8},
        "QA-GIP-10": {"result": "fail", "evidence": "unrelated section, no contradiction", "page": 5, "confidence": 0.8},
    }
    flags = fields.find_cross_rule_contradictions(det_results)
    print(f"[Item 3] clean-document flags = {flags}")
    assert flags == []


# =========================================================================
# Item 4: adjacent-context expansion for isolated-field rules
# =========================================================================

def test_item4_bip06_downgrades_to_uncertain_when_nearby_explanation_found():
    """Made-up goal, bare N/A on its own field, but a real explanation
    sits in the block's own 'Additional Notes:' field a few lines away --
    generic adjacency, not a hardcoded field name."""
    text = (
        "Target Name: Reduce Hand-Flapping\nBaseline: 5\n"
        "Current Level: N/A\n"
        "Mastery Criteria: 0 occurrences\n"
        "Additional Notes: No direct sessions occurred this period due to a documented scheduling gap "
        "with the assigned BT.\n"
    )
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    print(f"[Item 4] BIP-06 with nearby explanation: {result} -- {evidence}")
    assert result == "uncertain"


def test_item4_bip06_still_fails_when_truly_blank_with_no_nearby_explanation():
    text = (
        "Target Name: Reduce Hand-Flapping\nBaseline: 5\n"
        "Current Level: N/A\n"
        "Mastery Criteria: 0 occurrences\n"
        "Additional Notes:\n"
    )
    result, evidence, page, confidence = fields._check_BIP06({}, _fields(text))
    print(f"[Item 4] BIP-06 with no nearby explanation: {result} -- {evidence}")
    assert result == "fail"


# =========================================================================
# Item 4b: QA-BIP-04 -- the second real case the user identified
# (Yisroel Leibowitz's document, "Reduce Crying Episodes" goal). This rule
# had NO deterministic checker at all before this (pure judgment-layer),
# so "before" is "no code-computed answer existed"; a real judgment call
# to get a literal before-answer isn't part of the approved real-API
# spend for this round. "After" is fields._check_BIP04, reusing the exact
# same _nearby_block_explanation helper Item 4 already built for BIP-06.
# =========================================================================

def test_item4b_bip04_fails_a_blank_mastery_criteria_with_no_nearby_duration_explanation():
    """SYNTHETIC, made-up goal -- mirrors Yisroel's real 'Reduce Crying
    Episodes' shape (blank Mastery Criteria, no duration language
    anywhere nearby)."""
    text = (
        "Target Name: Reduce Head-Banging Episodes\n"
        "Date Initiated: 02/16/2026 Baseline: 1 per hour as per caregiver report Frequency\n"
        "Mastery Criteria:  \n"
        "Sampling Method: Frequency \n"
        "Anticipated Mastery Date: \n"
        "Status: In Progress   Current Data: 1-2 per week  Frequency \n"
        "Graph: \n"
        "Additional Notes:\n"
    )
    result, evidence, page, confidence = fields._check_BIP04({}, _fields(text))
    print(f"[Item 4b] BIP-04 blank Mastery Criteria, no nearby explanation: {result} -- {evidence}")
    assert result == "fail"


def test_item4b_bip04_downgrades_to_uncertain_when_nearby_explanation_found():
    """Same shape, but a real explanation sits in 'Additional Notes:' a
    few lines away -- generic adjacency, the same mechanism BIP-06 uses."""
    text = (
        "Target Name: Reduce Head-Banging Episodes\n"
        "Date Initiated: 02/16/2026 Baseline: 1 per hour as per caregiver report Frequency\n"
        "Mastery Criteria:  \n"
        "Sampling Method: Frequency \n"
        "Additional Notes: Mastery Criteria was not yet set because the BCBA had not finalized the "
        "target level as of this authorization period, pending a follow-up assessment next month.\n"
    )
    result, evidence, page, confidence = fields._check_BIP04({}, _fields(text))
    print(f"[Item 4b] BIP-04 blank Mastery Criteria, WITH nearby explanation: {result} -- {evidence}")
    assert result == "uncertain"


def test_item4b_bip04_passes_when_a_duration_qualifier_is_present():
    """Made-up goal, same shape as the rule's own confirmed real PASS
    example (Reeda's 'near 0 levels per session for 5 consecutive
    sessions')."""
    text = (
        "Target Name: Reduce Head-Banging Episodes\n"
        "Baseline: 6x daily\n"
        "Mastery Criteria: near 0 levels per session for 4 consecutive sessions\n"
    )
    result, evidence, page, confidence = fields._check_BIP04({}, _fields(text))
    print(f"[Item 4b] BIP-04 with a duration qualifier present: {result} -- {evidence}")
    assert result == "pass"


def test_item4b_bip04_fails_a_populated_mastery_criteria_with_no_duration_qualifier():
    """The rule's own confirmed real FAIL example shape: a level/count is
    stated, but no consecutive-session/time-window qualifier at all."""
    text = (
        "Target Name: Reduce Head-Banging Episodes\n"
        "Baseline: 6x daily\n"
        "Mastery Criteria: near 0 levels per session\n"
    )
    result, evidence, page, confidence = fields._check_BIP04({}, _fields(text))
    print(f"[Item 4b] BIP-04 with a level but no duration qualifier: {result} -- {evidence}")
    assert result == "fail"


def test_item4b_bip04_real_document_yisroel_reduce_crying_episodes(yisroel_tp_pdf):
    """REAL document verification, per the user's explicit request: Yisroel
    Leibowitz's real 'Reduce Crying Episodes' goal (page 15/16 of the real
    PDF) has a genuinely blank Mastery Criteria field with no duration
    language anywhere nearby in that goal's own block (confirmed by
    direct inspection: 'Additional Notes:' is also blank) -- must FAIL,
    named specifically in the evidence."""
    from pipeline.extract import extract_pdf_text
    pages = extract_pdf_text(yisroel_tp_pdf)
    full_text = "\n".join(p["text"] for p in pages)
    doc_fields = {"pages": pages, "full_text": full_text}
    result, evidence, page, confidence = fields._check_BIP04({}, doc_fields)
    print(f"[Item 4b] BIP-04 on Yisroel's REAL document: {result} -- {evidence}")
    assert result == "fail"
    assert any("Crying" in (d.get("detail") if isinstance(d, dict) else str(evidence)) for d in (evidence if isinstance(evidence, list) else [evidence]))


# =========================================================================
# Item 5: opt-in vision-input routing for embedded image content
# =========================================================================
# Zero-cost dry run only -- confirms correct page selection. No real model
# call anywhere in this section. Made-up patient "Priya Ferreira" again,
# never any of the four real-document names.

def _acf_doc_fields(acf_page_text: str, page_before: str = "Cover page.\n", page_after: str = "Goal Progress: nothing relevant here.\n", low_text_pages: set[int] | None = None) -> dict:
    pages_text = [page_before, acf_page_text, page_after]
    pages = []
    for i, text in enumerate(pages_text):
        page_number = i + 1
        page = {"page_number": page_number, "text": text}
        if low_text_pages and page_number in low_text_pages:
            page["low_text"] = True
        pages.append(page)
    return {"pages": pages, "full_text": "\n".join(pages_text)}


def test_item5_vision_eligible_pages_selects_the_acf_sections_own_page_range():
    """A made-up document whose entire 'Assessment of Current Functioning:'
    section -- header, fields, AND the 'Goal Progress:' boundary phrase that
    ends it -- sits on page 2 alone. vision_eligible_pages must select
    exactly page 2 for a rule opted into VISION_ELIGIBLE_RULE_SECTIONS, and
    nothing on the unrelated cover/next pages."""
    acf_page = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 01/15/2026\n"
        "Assessment Methods/Measures: VB-MAPP\n"
        "Assessment Summary Statement: Priya demonstrates emerging skills.\n"
        "Provider Location During Assessment: Clinic\n"
        "Goal Progress: this same page also states the section is over.\n"
    )
    doc_fields = _acf_doc_fields(acf_page)
    rules = [{"rule_id": "QA-ACF-07", "active": True}, {"rule_id": "QA-GIP-10", "active": True}]
    pages = fields.vision_eligible_pages(rules, doc_fields)
    print(f"[Item 5] vision-eligible pages for ACF-only rule set = {pages}")
    assert pages == {2}


def test_item5_vision_eligible_pages_includes_a_low_text_page_inside_the_section():
    """The ACF section spans pages 2-4 (header on 2, a grid-only page 3
    in between, and the closing fields + 'Goal Progress:' boundary on 4)
    -- page 3 must be included even though it's neither the section's
    start nor end page."""
    page2 = "Assessment of Current Functioning:\nAssessment Date: 01/15/2026\n"
    page3 = "[grid image content, no extractable text]\n"
    page4 = (
        "Assessment Methods/Measures: VB-MAPP\n"
        "Assessment Summary Statement: Priya demonstrates emerging skills.\n"
        "Goal Progress: the section is over as of this page.\n"
    )
    doc_fields = _acf_doc_fields(page2, page_before="Cover page.\n", page_after=page4)
    doc_fields["pages"].insert(2, {"page_number": 3, "text": page3, "low_text": True})
    for i, p in enumerate(doc_fields["pages"]):
        p["page_number"] = i + 1
    doc_fields["full_text"] = "\n".join(p["text"] for p in doc_fields["pages"])
    rules = [{"rule_id": "QA-ACF-06", "active": True}]
    pages = fields.vision_eligible_pages(rules, doc_fields)
    print(f"[Item 5] vision-eligible pages spanning a low-text middle page = {pages}")
    assert pages == {2, 3, 4}


def test_item5_vision_eligible_pages_includes_a_middle_page_not_flagged_low_text():
    """REAL BUG this regression-tests: Blythe Diaz's real document had two
    genuine grid-image pages inside the ACF section that each still carried
    ~150 characters of real extractable text (a repeated Patient Name/DOB
    footer), so flag_pages.py's own low_text heuristic never flagged them
    -- a real judgment call against boundary pages alone came back
    not_checkable, unable to see either grid. Every page WITHIN the
    section's own boundaries must be rendered now, low_text or not --
    made-up equivalent here: page 3 has real (non-low-text) filler text
    but is still inside the section boundaries, and must be included."""
    page2 = "Assessment of Current Functioning:\nAssessment Date: 01/15/2026\n"
    page3 = "Patient Name: Priya Ferreira Patient DOB: 03/03/2019 Patient Insurance: 999\n"
    page4 = (
        "Assessment Methods/Measures: VB-MAPP\n"
        "Assessment Summary Statement: Priya demonstrates emerging skills.\n"
        "Goal Progress: the section is over as of this page.\n"
    )
    doc_fields = _acf_doc_fields(page2, page_before="Cover page.\n", page_after=page4)
    doc_fields["pages"].insert(2, {"page_number": 3, "text": page3})  # NOT flagged low_text
    for i, p in enumerate(doc_fields["pages"]):
        p["page_number"] = i + 1
    doc_fields["full_text"] = "\n".join(p["text"] for p in doc_fields["pages"])
    rules = [{"rule_id": "QA-ACF-06", "active": True}]
    pages = fields.vision_eligible_pages(rules, doc_fields)
    print(f"[Item 5] vision-eligible pages, middle page NOT low-text = {pages}")
    assert pages == {2, 3, 4}


def test_item5_vision_eligible_pages_empty_when_no_opted_in_rule_is_active():
    """No rule in the active set is in VISION_ELIGIBLE_RULE_SECTIONS -- must
    return an empty set, not render anything extra."""
    acf_page = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 01/15/2026\n"
        "Assessment Methods/Measures: VB-MAPP\n"
    )
    doc_fields = _acf_doc_fields(acf_page)
    rules = [{"rule_id": "QA-GIP-10", "active": True}]
    pages = fields.vision_eligible_pages(rules, doc_fields)
    print(f"[Item 5] vision-eligible pages with no opted-in active rule = {pages}")
    assert pages == set()


def test_item5_vision_eligible_pages_empty_when_the_opted_in_rule_is_inactive():
    """The rule is in the registry but not active on this rule set --
    must not render its section's pages either."""
    acf_page = (
        "Assessment of Current Functioning:\n"
        "Assessment Date: 01/15/2026\n"
        "Assessment Methods/Measures: VB-MAPP\n"
    )
    doc_fields = _acf_doc_fields(acf_page)
    rules = [{"rule_id": "QA-ACF-07", "active": False}]
    pages = fields.vision_eligible_pages(rules, doc_fields)
    print(f"[Item 5] vision-eligible pages with the opted-in rule inactive = {pages}")
    assert pages == set()


# =========================================================================
# Item 6: broaden GIP-16 to fail on a blank Mastery Criteria directly
# =========================================================================

def test_item6_gip16_fails_a_blank_mastery_criteria_in_isolation():
    """A goal with NO Sampling Method field either -- so GIP-10/BIP-05
    structurally cannot be the ones catching this; GIP-16 must catch it
    on its own."""
    text = "Target Name: Reduce Made-Up Behavior\nBaseline: 5\nMastery Criteria:\n"
    result, evidence, page, confidence = fields._check_GIP16({}, _fields(text))
    print(f"[Item 6] blank Mastery Criteria in isolation: {result} -- {evidence}")
    assert result == "fail"
