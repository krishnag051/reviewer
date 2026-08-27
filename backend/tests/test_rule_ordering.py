"""Next Round, Part 3: fixed rule-list order -- pure unit tests against
app/services/rule_ordering.py, no DB needed. Fakes just enough of
RuleResult's shape (`.rule.payor`, `.category`) for the sort key to read.
"""
from types import SimpleNamespace

from app.services.rule_ordering import sort_rule_results


def _rr(rule_code: str, category: str, payor: str | None = None):
    return SimpleNamespace(rule_id=rule_code, category=category, rule=SimpleNamespace(payor=payor))


def test_payor_specific_rules_lead_when_they_match_this_versions_payor():
    rrs = [
        _rr("QA-RPT-01", "Report Information"),
        _rr("HF-02", "Healthfirst-Specific", payor="Healthfirst"),
        _rr("AET-01", "Aetna-Specific", payor="Aetna"),
        _rr("HF-01", "Healthfirst-Specific", payor="Healthfirst"),
    ]
    sorted_rrs = sort_rule_results(rrs, payor="Healthfirst")
    # Both Healthfirst rules lead (in their original relative order --
    # stable sort), the Aetna-specific rule (a DIFFERENT payor, never this
    # TP's) is NOT promoted, and falls back to its own category's rank.
    assert [rr.rule_id for rr in sorted_rrs[:2]] == ["HF-02", "HF-01"]
    assert "AET-01" not in [rr.rule_id for rr in sorted_rrs[:2]]


def test_template_category_comes_right_after_payor_specific_rules():
    rrs = [
        _rr("QA-RPT-01", "Report Information"),
        _rr("QA-TEMP-01", "Template"),
        _rr("HF-01", "Healthfirst-Specific", payor="Healthfirst"),
    ]
    sorted_rrs = sort_rule_results(rrs, payor="Healthfirst")
    assert [rr.rule_id for rr in sorted_rrs] == ["HF-01", "QA-TEMP-01", "QA-RPT-01"]


def test_remaining_categories_follow_the_fixed_verbatim_order():
    rrs = [
        _rr("QA-SIG-01", "Signatures"),
        _rr("QA-RPT-01", "Report Information"),
        _rr("QA-BIP-01", "BIP"),
    ]
    sorted_rrs = sort_rule_results(rrs, payor=None)
    assert [rr.rule_id for rr in sorted_rrs] == ["QA-RPT-01", "QA-BIP-01", "QA-SIG-01"]


def test_no_payor_on_this_version_means_no_promotion_but_no_error():
    rrs = [_rr("HF-01", "Healthfirst-Specific", payor="Healthfirst"), _rr("QA-RPT-01", "Report Information")]
    sorted_rrs = sort_rule_results(rrs, payor=None)
    # Report Information (rank 0) comes before Healthfirst-Specific
    # (unrecognized category -> sorts last) when there's no payor match to
    # promote it.
    assert [rr.rule_id for rr in sorted_rrs] == ["QA-RPT-01", "HF-01"]


def test_sort_is_stable_same_input_same_output_every_time():
    rrs = [
        _rr("QA-BIP-01", "BIP"),
        _rr("QA-BIP-02", "BIP"),
        _rr("QA-RPT-01", "Report Information"),
    ]
    first = [rr.rule_id for rr in sort_rule_results(rrs, payor=None)]
    second = [rr.rule_id for rr in sort_rule_results(rrs, payor=None)]
    assert first == second == ["QA-RPT-01", "QA-BIP-01", "QA-BIP-02"]


def test_unrecognized_category_sorts_after_every_named_category_not_before():
    rrs = [
        _rr("QA-X-01", "Some Future Category Nobody Added To The List Yet"),
        _rr("QA-SIG-01", "Signatures"),  # second-to-last in the fixed list
    ]
    sorted_rrs = sort_rule_results(rrs, payor=None)
    assert [rr.rule_id for rr in sorted_rrs] == ["QA-SIG-01", "QA-X-01"]


def test_does_not_mutate_the_input_list():
    rrs = [_rr("QA-SIG-01", "Signatures"), _rr("QA-RPT-01", "Report Information")]
    original_order = list(rrs)
    sort_rule_results(rrs, payor=None)
    assert rrs == original_order
