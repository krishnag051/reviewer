"""Confirms item 5/6 of the 2026-07-27 round: Learning Tree is confirmed
dead scope (Project1_Full_Build_Scope.docx) and QA-BIO-04/QA-ACF-05 (both
already inactive, both entirely defined by the retired Learning-Tree
comparison with no independently meaningful residual) were moved to
rules/archive/ rather than left sitting inactive in rules.json. QA-TRANS-01
already had its Learning-Tree clause correctly stripped in an earlier round
(confirmed here, not re-touched). No live document, no live API.

QA-ACF-05 was restored 2026-07-28 (see test_acf05_restoration.py) as a real
blank-field check unrelated to Learning Tree, and is intentionally no
longer archived -- this file's expectations were updated to match.
QA-BIO-04 remains archived; no equivalent real check has been found for it.
"""
import json
from pathlib import Path

RULES_DIR = Path(__file__).parent.parent / "rules"
RULES = json.loads((RULES_DIR / "rules.json").read_text(encoding="utf-8"))["rules"]
ARCHIVE_PATH = RULES_DIR / "archive" / "learning_tree_deprecated_rules.json"


def test_bio04_is_gone_from_the_active_rule_set_but_acf05_is_restored():
    active_ids = {r["rule_id"] for r in RULES}
    assert "QA-BIO-04" not in active_ids
    assert "QA-ACF-05" in active_ids


def test_archive_file_exists_and_contains_only_bio04_now():
    assert ARCHIVE_PATH.exists(), "expected rules/archive/learning_tree_deprecated_rules.json to exist"
    archived = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    archived_ids = {r["rule_id"] for r in archived["rules"]}
    assert archived_ids == {"QA-BIO-04"}


def test_archived_bio04_is_not_silently_lost():
    """Moved, not deleted -- full original content is preserved."""
    archived = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    by_id = {r["rule_id"]: r for r in archived["rules"]}
    assert "learning tree" in by_id["QA-BIO-04"]["description"].lower()
    assert by_id["QA-BIO-04"]["active"] is False


def test_restored_acf05_no_longer_references_learning_tree():
    acf05 = next(r for r in RULES if r["rule_id"] == "QA-ACF-05")
    assert "learning tree" not in acf05["description"].lower()
    assert "learning tree" not in (acf05.get("notes") or "").lower() or "retired" in acf05["notes"].lower()
    assert acf05["check_type"] == "deterministic"
    assert acf05["active"] is True


def test_no_active_rule_depends_on_learning_tree_anymore():
    """QA-TRANS-01 and QA-ACF-05 both mention "Learning Tree" in their
    notes, but neither DEPENDS on it: QA-TRANS-01's notes explicitly say
    the wording is ignored and describe an independently meaningful check
    in its place (stripped in an earlier round); QA-ACF-05's notes mention
    it only as historical context for why this checklist item was rebuilt
    (see test_restored_acf05_no_longer_references_learning_tree above for
    the actual check-logic assertion). Confirm no OTHER active rule
    mentions it at all -- description text especially, since that would
    mean the actual check logic still depends on it."""
    trans01 = next(r for r in RULES if r["rule_id"] == "QA-TRANS-01")
    assert "learning tree" in trans01["notes"].lower()
    assert "ignored" in trans01["notes"].lower()

    KNOWN_HISTORICAL_MENTIONS = {"QA-TRANS-01", "QA-ACF-05"}
    other_rules_with_learning_tree = [
        r["rule_id"] for r in RULES
        if r["rule_id"] not in KNOWN_HISTORICAL_MENTIONS
        and (
            "learning tree" in r["description"].lower()
            or "learning tree" in (r.get("notes") or "").lower()
        )
    ]
    assert other_rules_with_learning_tree == []

    # No active rule's *description* (the terse, always-sent-to-the-model
    # summary) should ever mention Learning Tree, including these two --
    # if the description says it, the check logic depends on it.
    assert "learning tree" not in trans01["description"].lower()
