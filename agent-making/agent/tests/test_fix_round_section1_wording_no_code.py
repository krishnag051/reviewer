"""Fix Round, Section 1 (2026-08-27): "wording changed but no real code" --
20 rules whose description/notes were updated in earlier rounds without
anyone confirming real code enforces the new wording. One test group per
rule_id below, using synthetic fixture text only -- zero real API spend.

For the 7 rules that got a genuinely NEW deterministic checker
(QA-BAR-01, HF-05, QA-COC-06, QA-RPT-07, QA-SCH-06, QA-GIP-19, QA-GIP-26)
and the 2 that got an EXISTING checker fixed in place (QA-RPT-05,
QA-HRS-02) plus one extended (QA-GIP-16): real pass/fail fixture pairs.

For the 8 rules confirmed to correctly stay judgment (QA-HRS-09,
QA-COC-02, CIG-01, QA-PAR-03, QA-BIP-14, QA-BIP-02, QA-GIP-07, QA-TEMP-04)
plus the 1 flagged genuinely ambiguous/blocked (QA-MAST-04): a lightweight
"state lock-in" test confirming check_type and DET_CHECKS registration
match what this round's report says, rather than a functional test against
non-existent code.
"""
import json
from pathlib import Path

from pipeline import fields

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
_RULES_BY_ID = {r["rule_id"]: r for r in json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]}


def _rule_json(rule_id: str) -> dict:
    return _RULES_BY_ID[rule_id]


def _rule(params: dict | None = None) -> dict:
    return {"params": params or {}}


def _fields(*page_texts: str, payor: str | None = None) -> dict:
    pages = [{"page_number": i + 1, "text": t} for i, t in enumerate(page_texts)]
    return {"pages": pages, "full_text": "\n".join(page_texts), "payor": payor}


# --- 1. QA-BAR-01 -----------------------------------------------------------

def test_bar01_below_threshold_is_not_applicable():
    text = "23 hours per week.\n97153-Direct Care\n"
    result, evidence, page, confidence = fields._check_BAR01(_rule_json("QA-BAR-01")["params"] and _rule(_rule_json("QA-BAR-01")["params"]), _fields(text))
    assert result == "not_applicable"


def test_bar01_above_threshold_escalates_to_judgment():
    text = "30 hours per week.\n97153-Direct Care\n"
    result, evidence, page, confidence = fields._check_BAR01(_rule(_rule_json("QA-BAR-01")["params"]), _fields(text))
    assert result == "not_checkable"  # escalates -- the semantic "barrier mentioned" question stays judgment


# --- 2. HF-05 ----------------------------------------------------------------

def test_hf05_compares_approved_vs_requested_and_always_flags_the_occurred_gap():
    text = "1 hour per week.\n97156-Parent Training\nBCBA/LBA\n\n97156-Parent Training\n1 hour per week\n"
    result, evidence, page, confidence = fields._check_HF05(_rule(), _fields(text))
    assert result == "not_checkable"
    assert "occurred" in evidence.lower()
    assert "match" in evidence.lower()


def test_hf05_not_checkable_when_either_figure_missing():
    result, evidence, page, confidence = fields._check_HF05(_rule(), _fields("Nothing relevant here."))
    assert result == "not_checkable"


# --- 3. QA-COC-06 -------------------------------------------------------------

def test_coc06_passes_when_fax_date_within_report_range():
    text = "faxed to Dr. Smith on 7/2/2026\nDate of Current Report: 07/01/2026 to 07/31/2026\n"
    result, evidence, page, confidence = fields._check_COC06(_rule(), _fields(text))
    assert result == "pass"


def test_coc06_fails_when_fax_date_outside_report_range():
    text = "faxed to Dr. Smith on 7/2/2026\nDate of Current Report: 01/01/2026 to 01/31/2026\n"
    result, evidence, page, confidence = fields._check_COC06(_rule(), _fields(text))
    assert result == "fail"


def test_coc06_not_checkable_when_year_missing_matching_current_wording():
    """Year is no longer required per this rule's current wording -- a
    year-less date can't be range-checked, so this must be not_checkable,
    never a fail just for lacking a year."""
    text = "faxed to Dr. Smith on 7/2\nDate of Current Report: 07/01/2026 to 07/31/2026\n"
    result, evidence, page, confidence = fields._check_COC06(_rule(), _fields(text))
    assert result == "not_checkable"


# --- 4. QA-HRS-09 (stays judgment, confirm state) -----------------------------

def test_hrs09_stays_judgment_with_no_checker():
    assert _rule_json("QA-HRS-09")["check_type"] == "judgment"
    assert "QA-HRS-09" not in fields.DET_CHECKS


# --- 5. QA-RPT-07 --------------------------------------------------------------

def test_rpt07_fails_when_requested_range_short_of_26_weeks():
    text = "Authorization Dates Requested: 01/01/2026 to 03/01/2026\n"
    result, evidence, page, confidence = fields._check_RPT07(_rule(_rule_json("QA-RPT-07")["params"]), _fields(text))
    assert result == "fail"


def test_rpt07_passes_when_requested_range_meets_26_weeks():
    text = "Authorization Dates Requested: 01/01/2026 to 07/03/2026\n"
    result, evidence, page, confidence = fields._check_RPT07(_rule(_rule_json("QA-RPT-07")["params"]), _fields(text))
    assert result == "pass"


def test_rpt07_self_excludes_healthfirst_deferring_to_hf01():
    """REAL BUG FOUND AND FIXED before shipping: confirmed on the real
    Zyaan Ullah sample TP (Healthfirst, real requested range 12.9 weeks)
    that without this exclusion, the universal 26-week default would
    falsely fail every Healthfirst patient correctly on their own real
    13-week cycle (already validated by HF-01)."""
    text = "Authorization Dates Requested: 01/01/2026 to 03/01/2026\n"  # would fail the universal default
    result, evidence, page, confidence = fields._check_RPT07(
        _rule(_rule_json("QA-RPT-07")["params"]), _fields(text, payor="Healthfirst"),
    )
    assert result == "not_applicable"


# --- 6. QA-COC-02 (stays judgment, confirm state) -----------------------------

def test_coc02_stays_judgment_with_no_checker():
    assert _rule_json("QA-COC-02")["check_type"] == "judgment"
    assert "QA-COC-02" not in fields.DET_CHECKS


# --- 7. QA-RPT-05 (fixed: month -> week math) --------------------------------

def test_rpt05_uses_week_based_params_not_month_based():
    assert "max_weeks_after_report_end" in _rule_json("QA-RPT-05")["params"]
    assert "max_months_after_report_end" not in _rule_json("QA-RPT-05")["params"]


def test_rpt05_passes_within_26_week_default():
    text = (
        "Date of Current Report: 07/01/2026 to 07/17/2026\n"
        "Authorization Dates Requested: 08/01/2026 to 12/28/2026\n"  # ~24.5 weeks after report end
    )
    result, evidence, page, confidence = fields._check_RPT05(_rule(_rule_json("QA-RPT-05")["params"]), _fields(text))
    assert result == "pass"


def test_rpt05_fails_beyond_26_week_default():
    text = (
        "Date of Current Report: 07/01/2026 to 07/17/2026\n"
        "Authorization Dates Requested: 08/01/2026 to 03/01/2027\n"  # well beyond 26 weeks after report end
    )
    result, evidence, page, confidence = fields._check_RPT05(_rule(_rule_json("QA-RPT-05")["params"]), _fields(text))
    assert result == "fail"


# --- 8. QA-HRS-02 (fixed: stale evidence text) --------------------------------

def test_hrs02_fail_evidence_no_longer_mentions_eliana():
    text = "25 hours per week.\n97153-Direct Care\n"
    result, evidence, page, confidence = fields._check_HRS02(_rule(_rule_json("QA-HRS-02")["params"]), _fields(text))
    assert result == "fail"
    assert "eliana" not in evidence.lower()
    assert "review email" not in evidence.lower()


def test_hrs02_pass_case_unchanged():
    text = "15 hours per week.\n97153-Direct Care\n"
    result, evidence, page, confidence = fields._check_HRS02(_rule(_rule_json("QA-HRS-02")["params"]), _fields(text))
    assert result == "pass"


# --- 9. CIG-01 (stays judgment, vision-eligible) ------------------------------

def test_cig01_stays_judgment_but_is_vision_eligible():
    assert _rule_json("CIG-01")["check_type"] == "judgment"
    assert "CIG-01" not in fields.DET_CHECKS
    assert fields.VISION_ELIGIBLE_RULE_SECTIONS.get("CIG-01") == "ablls_grid"


def test_ablls_grid_page_range_finds_the_real_phrase():
    f = _fields("Below you will find the ABLLS grid:\nSome content.", "Grid image page (no extractable text).")
    pages = fields._ablls_grid_page_range(f)
    assert pages == {1, 2}


# --- 10. QA-PAR-03 (stays judgment, reuses gip_graph) -------------------------

def test_par03_stays_judgment_but_reuses_gip_graph_vision_section():
    assert _rule_json("QA-PAR-03")["check_type"] == "judgment"
    assert "QA-PAR-03" not in fields.DET_CHECKS
    assert fields.VISION_ELIGIBLE_RULE_SECTIONS.get("QA-PAR-03") == "gip_graph"


# --- 11. QA-MAST-04 (flagged genuinely ambiguous, not built) ------------------

def test_mast04_stays_judgment_flagged_as_ambiguous_not_built():
    assert _rule_json("QA-MAST-04")["check_type"] == "judgment"
    assert "QA-MAST-04" not in fields.DET_CHECKS
    assert "ambiguous" in _rule_json("QA-MAST-04")["notes"].lower()


# --- 12. QA-SCH-06 (real gap: was labeled deterministic, zero checker) -------

def test_sch06_was_a_silent_gap_now_has_a_real_checker():
    assert _rule_json("QA-SCH-06")["check_type"] == "deterministic"
    assert "QA-SCH-06" in fields.DET_CHECKS


def test_sch06_not_applicable_when_no_other_therapy_mentioned():
    result, evidence, page, confidence = fields._check_SCH06(_rule(), _fields("Nothing relevant here."))
    assert result == "not_applicable"


def test_sch06_passes_when_other_therapy_has_nearby_schedule_info():
    text = "Zyaan receives OT 2x per week for 30 minutes on Monday 10am-11am."
    result, evidence, page, confidence = fields._check_SCH06(_rule(), _fields(text))
    assert result == "pass"


def test_sch06_uncertain_when_other_therapy_mentioned_with_no_schedule_info():
    """Real confirmed shape: background-context mentions of another
    therapy (e.g. 'Zyaan currently receives OT 2x per week for 30
    minutes') often carry NO day/time info at all in a real document."""
    text = "Zyaan currently receives OT 2x per week for 30 minutes."
    result, evidence, page, confidence = fields._check_SCH06(_rule(), _fields(text))
    assert result == "uncertain"


# --- 13. QA-BIP-14 (stays judgment, confirm state) ----------------------------

def test_bip14_stays_judgment_with_no_checker():
    assert _rule_json("QA-BIP-14")["check_type"] == "judgment"
    assert "QA-BIP-14" not in fields.DET_CHECKS


# --- 14. QA-HRS-03 (confirm correct, flag paraphrase mismatch) ---------------

def test_hrs03_existing_checker_unaffected_by_this_round():
    """Confirms this rule's real logic (ceiling not floor, escalates on
    exceed) is still intact -- no removal was made without a confirmed
    real ask matching this rule's actual wording."""
    params = _rule_json("QA-HRS-03")["params"]
    text = "25 hours per week.\n97153-Direct Care\n2.5 hours per week.\n97155-Supervision\n"
    result, evidence, page, confidence = fields._check_HRS03(_rule(params), _fields(text))
    assert result == "pass"  # 2.5/25 = 0.10, under the 0.15 ceiling


# --- 15. QA-BIP-02 (confirm already done) -------------------------------------

def test_bip02_stays_judgment_confirmed_already_correct():
    assert _rule_json("QA-BIP-02")["check_type"] == "judgment"
    assert "no exceptions" in _rule_json("QA-BIP-02")["description"].lower()


# --- 16. QA-GIP-07 (confirm already done) -------------------------------------

def test_gip07_stays_judgment_confirmed_already_correct():
    assert _rule_json("QA-GIP-07")["check_type"] == "judgment"
    assert "eliana" not in _rule_json("QA-GIP-07")["description"].lower()


# --- 17. QA-GIP-19 ------------------------------------------------------------

def test_gip19_passes_when_behavior_goal_and_summary_both_present():
    text = "Skill Domain: Functional Behavior Skills\nBehavioral Summary: Amir engages in several behaviors.\n"
    result, evidence, page, confidence = fields._check_GIP19(_rule(), _fields(text))
    assert result == "pass"


def test_gip19_fails_when_either_is_missing():
    text = "Skill Domain: Social\nBehavioral Summary:\n"
    result, evidence, page, confidence = fields._check_GIP19(_rule(), _fields(text))
    assert result == "fail"


# --- 18. QA-TEMP-04 (confirm correct, flag paraphrase mismatch) --------------

def test_temp04_existing_checker_unaffected_confirmed_correct():
    text = "Why are hours remaining the same?\n"
    result, evidence, page, confidence = fields._check_TEMP04(_rule(), _fields(text))
    assert result == "fail"


def test_temp04_description_has_nothing_to_do_with_page_numbers():
    """Confirms this round's own paraphrase mismatch was real -- this
    rule's actual description is about BCBA correspondence, not page
    numbers (that's QA-TEMP-02, out of this round's scope)."""
    assert "page number" not in _rule_json("QA-TEMP-04")["description"].lower()


# --- 19. QA-GIP-26 -------------------------------------------------------------

def test_gip26_passes_when_no_goal_is_ot_pt_speech_flavored():
    text = "Target Goal: Zyaan will attend.\nSkill Domain: Functional Behavior Skills\n"
    result, evidence, page, confidence = fields._check_GIP26(_rule(), _fields(text))
    assert result == "pass"


def test_gip26_fails_when_a_goal_is_ot_pt_speech_flavored():
    text = "Target Goal: Zyaan will improve gait.\nSkill Domain: Physical Therapy\n"
    result, evidence, page, confidence = fields._check_GIP26(_rule(), _fields(text))
    assert result == "fail"


def test_gip26_does_not_false_positive_on_unrelated_background_mention():
    """The real false-pass bug's own mirror image: a normal background
    narrative mention of another therapy (confirmed real text: 'Zyaan
    currently receives OT 2x per week for 30 minutes') must NOT be
    treated as an ABA goal violation -- only a GOAL's own text counts."""
    text = (
        "Zyaan currently receives OT 2x per week for 30 minutes, PT 2x per week for 30 minutes "
        "and Speech 3x per week for 30 minutes.\n"
        "Target Goal: Zyaan will attend to instructions.\nSkill Domain: Functional Behavior Skills\n"
    )
    result, evidence, page, confidence = fields._check_GIP26(_rule(), _fields(text))
    assert result == "pass"


# --- 20. QA-GIP-16 (extended for current level) -------------------------------

def test_gip16_still_flags_zero_mastery_criteria_unchanged():
    text = "Target Goal: X\nMastery Criteria: 0%\nCurrent Data: 56% Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP16(_rule(), _fields(text))
    assert result == "fail"


def test_gip16_now_also_flags_zero_current_data():
    text = "Target Goal: X\nMastery Criteria: 80% accuracy\nCurrent Data: 0 Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP16(_rule(), _fields(text))
    assert result == "fail"
    assert "current data" in evidence.lower()


def test_gip16_does_not_fail_a_blank_current_data_unlike_blank_mastery_criteria():
    """Deliberate asymmetry: a blank Current Data commonly just means no
    data collected yet for a newly-started goal -- different from a
    blank Mastery Criteria, which is a real setup problem regardless of
    goal age."""
    text = "Target Goal: X\nMastery Criteria: 80% accuracy\nCurrent Data:\n"
    result, evidence, page, confidence = fields._check_GIP16(_rule(), _fields(text))
    assert result == "pass"


def test_gip16_passes_when_neither_field_has_a_zero_endpoint():
    text = "Target Goal: X\nMastery Criteria: 80% accuracy\nCurrent Data: 45% Percent Correct\n"
    result, evidence, page, confidence = fields._check_GIP16(_rule(), _fields(text))
    assert result == "pass"
