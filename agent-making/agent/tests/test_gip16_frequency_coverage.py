"""Locks in the QA-GIP-16 content fix found via Reeda Bint Shaheen's real
document: the rule's own notes never told the model that frequency-based
mastery criteria ("0 occurrences per session", "near 0 levels per session")
are equivalent violations to a percentage-based "0%" — so goals like the
Tantrum/Elopement reduction targets (Sampling Method: Frequency) were
treated as out of scope and the rule passed a document that had two real
zero-equivalent mastery criteria. No live document, no live API — this
just locks in that the rule definition itself now says so explicitly.
"""
import json
from pathlib import Path

RULES_PATH = Path(__file__).parent.parent / "rules" / "rules.json"
RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]


def _gip16():
    return next(r for r in RULES if r["rule_id"] == "QA-GIP-16")


def test_gip16_notes_cover_frequency_based_zero_equivalents():
    notes = _gip16()["notes"].lower()
    assert "frequency" in notes
    assert "0 occurrences" in notes or "occurrences" in notes
    assert "near 0" in notes


def test_gip16_notes_state_the_ban_applies_regardless_of_sampling_method():
    notes = _gip16()["notes"].lower()
    assert "percent" in notes and "frequency" in notes
    assert "not exempt" in notes or "do not treat" in notes
