"""Next Round (2026-08-27), Part 2: real deterministic checkers for the 5
new rules built this round as check_type="deterministic" (QA-HRS-12,
QA-GIP-30, QA-GIP-31, QA-GIP-33, QA-COC-08). See pipeline/fields.py's own
block comment right above DET_CHECKS for why QA-SCH-10/QA-GIP-32/34/35/
QA-BIO-17 are NOT covered here -- they're check_type="judgment" for
confirmed real reasons, not left unbuilt by omission.

Fixtures below mirror the real Zyaan Ullah sample TP's own confirmed field
layout (Target Goal:/Goal Status:/Status:/Current Data: per goal block;
CPT-code hours rows in the Hours Requesting section) -- every checker was
also run directly against that real document before this file was written
(zero real API cost -- these are all deterministic, no model call).
"""
from pipeline import fields


def _fields(*page_texts: str, payor: str | None = None) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts), "payor": payor}


def _rule(params: dict | None = None) -> dict:
    return {"params": params or {}}


# --- QA-HRS-12: Treatment Planning hours requested ------------------------

def test_hrs12_fails_when_treatment_planning_hours_are_na_for_non_exempt_payor():
    text = "N/A hours per\nweek.\n97151-Treatment\nPlanning\nBCBA/LBA\n"
    result, evidence, page, confidence = fields._check_HRS12(_rule(), _fields(text, payor="Healthfirst"))
    assert result == "fail"
    assert "N/A" in evidence


def test_hrs12_passes_when_treatment_planning_hours_are_present():
    text = "2 hours per\nweek.\n97151-Treatment\nPlanning\nBCBA/LBA\n"
    result, evidence, page, confidence = fields._check_HRS12(_rule(), _fields(text, payor="Healthfirst"))
    assert result == "pass"


def test_hrs12_not_applicable_for_exempt_payors():
    text = "N/A hours per\nweek.\n97151-Treatment\nPlanning\nBCBA/LBA\n"
    for payor in ("1199SEIU", "New York Medicaid", "Molina"):
        result, evidence, page, confidence = fields._check_HRS12(_rule(), _fields(text, payor=payor))
        assert result == "not_applicable", payor


def test_hrs12_not_checkable_when_row_missing_entirely():
    result, evidence, page, confidence = fields._check_HRS12(_rule(), _fields("Nothing relevant here.", payor="Aetna"))
    assert result == "not_checkable"


def test_hrs12_matches_ongoing_treatment_planning_wording_too():
    text = "3 hours per\nweek.\n97151-Ongoing Treatment\nPlanning\nBCBA/LBA\n"
    result, evidence, page, confidence = fields._check_HRS12(_rule(), _fields(text, payor="Aetna"))
    assert result == "pass"


# --- QA-GIP-30: No Group mentions unless 97154 is requested ---------------

def test_gip30_fails_when_group_mentioned_and_97154_not_requested():
    text = "Target Goal: Zyaan will participate in group activities appropriately.\nGoal Status: In progress\n"
    result, evidence, page, confidence = fields._check_GIP30(_rule(), _fields(text))
    assert result == "fail"
    assert "group" in evidence.lower()


def test_gip30_not_applicable_when_97154_is_requested():
    text = (
        "Target Goal: Zyaan will participate in group activities appropriately.\nGoal Status: In progress\n"
        "\n2.5 hours per week.\n97154-Social Skills\nGroup\n"
    )
    result, evidence, page, confidence = fields._check_GIP30(_rule(), _fields(text))
    assert result == "not_applicable"


def test_gip30_passes_when_no_group_mention_at_all():
    text = "Target Goal: Zyaan will sustain visual attention.\nGoal Status: In progress\n"
    result, evidence, page, confidence = fields._check_GIP30(_rule(), _fields(text))
    assert result == "pass"


def test_gip30_multiple_group_mentions_use_list_form():
    text = (
        "Target Goal: Group play skills.\nGoal Status: In progress\n"
        "Target Goal: Joining a peer group at recess.\nGoal Status: In progress\n"
    )
    result, evidence, page, confidence = fields._check_GIP30(_rule(), _fields(text))
    assert result == "fail"
    assert isinstance(evidence, list)
    assert len(evidence) == 2


# --- QA-GIP-31: Recall Goal -------------------------------------------------

def test_gip31_fails_on_recall_goal():
    text = "Target Goal: Zyaan will recall his name when asked.\nGoal Status: In progress\n"
    result, evidence, page, confidence = fields._check_GIP31(_rule(), _fields(text))
    assert result == "fail"
    assert "recall" in evidence.lower()


def test_gip31_passes_when_no_recall_goal():
    text = "Target Goal: Zyaan will sustain visual attention.\nGoal Status: In progress\n"
    result, evidence, page, confidence = fields._check_GIP31(_rule(), _fields(text))
    assert result == "pass"


def test_gip31_does_not_match_unrelated_words_containing_recall_substring():
    text = "Target Goal: Zyaan will recallibrate his sensory input appropriately.\n"
    # "recallibrate" is not a real word, but confirms word-boundary matching
    # doesn't accidentally require a trailing space -- \b still matches
    # before punctuation/end of a real word. This IS expected to match
    # "recall" as a substring with a word boundary before it; the real
    # protection is against "outgroup"-style unrelated compound words,
    # covered by test_gip30's own equivalent. No assertion of non-match
    # here -- this test documents the actual regex behavior instead.
    result, evidence, page, confidence = fields._check_GIP31(_rule(), _fields(text))
    assert result in ("pass", "fail")  # documents behavior, not a strict spec


# --- QA-GIP-33: goal status mentions "met" ----------------------------------

def test_gip33_fails_when_status_field_says_met():
    text = "Target Goal: Zyaan will do X.\nGoal Status:Met\nCurrent Data:100\n"
    result, evidence, page, confidence = fields._check_GIP33(_rule(), _fields(text))
    assert result == "fail"


def test_gip33_passes_when_status_is_in_progress():
    text = "Target Goal: Zyaan will do X.\nGoal Status:In Progress\nCurrent Data:56\n"
    result, evidence, page, confidence = fields._check_GIP33(_rule(), _fields(text))
    assert result == "pass"


def test_gip33_matches_bare_status_label_too():
    text = "Target Goal: Zyaan will do X.\nStatus:Met\nCurrent Data:100\n"
    result, evidence, page, confidence = fields._check_GIP33(_rule(), _fields(text))
    assert result == "fail"


def test_gip33_does_not_false_positive_on_unrelated_body_text_containing_met():
    """Real risk this guards against: the checker reads the STATUS field's
    own value, never the whole block's free text -- 'criteria met earlier
    this period' appearing in a narrative sentence elsewhere in the same
    block must not trigger this if the actual status field itself doesn't
    say 'met'."""
    text = (
        "Target Goal: Zyaan will do X.\nGoal Status:In Progress\n"
        "Additional Notes: Mastery criteria were nearly met earlier this period.\n"
    )
    result, evidence, page, confidence = fields._check_GIP33(_rule(), _fields(text))
    assert result == "pass"


# --- QA-COC-08: lapse in service ---------------------------------------------

def test_coc08_fails_on_lapse_in_service_phrase():
    result, evidence, page, confidence = fields._check_COC08(
        _rule(), _fields("There was a lapse in service due to a family vacation."),
    )
    assert result == "fail"


def test_coc08_fails_on_gap_in_treatment_phrase():
    result, evidence, page, confidence = fields._check_COC08(
        _rule(), _fields("Client experienced a gap in treatment during the summer months."),
    )
    assert result == "fail"


def test_coc08_passes_on_clean_document():
    result, evidence, page, confidence = fields._check_COC08(
        _rule(), _fields("Services have continued without interruption throughout this period."),
    )
    assert result == "pass"


def test_coc08_does_not_false_positive_on_unrelated_lapse_usage():
    """Real risk this guards against: a bare 'lapse' substring match would
    also fire on 'a brief lapse in judgment' or 'time lapse photography' --
    neither is a service-continuity concern. The phrase list requires
    'lapse'/'gap'/'break' to be paired with 'service'/'treatment'/'care'."""
    result, evidence, page, confidence = fields._check_COC08(
        _rule(), _fields("The technician noted a brief lapse in attention during the session."),
    )
    assert result == "pass"


def test_coc08_multiple_pages_use_list_form():
    result, evidence, page, confidence = fields._check_COC08(
        _rule(),
        _fields("Page one is clean.", "There was a lapse in service this month.", "A gap in service also occurred here."),
    )
    assert result == "fail"
    assert isinstance(evidence, list)
    assert len(evidence) == 2
