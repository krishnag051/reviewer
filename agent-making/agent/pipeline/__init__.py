"""Orchestrates the pipeline steps in Section 4's fixed sequence. Plain
functions, no orchestration library — see Section 8 of the design doc.
"""
from . import fields as fields_module
from . import integrity
from . import merge as merge_module
from .extract import extract_pdf_text
from .flag_pages import flag_image_only_pages, flagged_page_numbers
from .render import render_flagged_pages


def run_full_pipeline(pdf_path: str, rules: list[dict], tracker=None, model_override: str | None = None) -> dict:
    """Runs extract -> flag -> render -> scope filter -> deterministic ->
    (escalate weak det findings into) judgment (with integrity check) ->
    merge, and returns merge.merge_findings's output.

    `tracker` (an ApiCallTracker, see pipeline/call_tracker.py) is optional
    but should be passed by any caller that runs this more than once in a
    script (a consistency probe, a batch of test documents, etc.) — it's
    what makes every real API call visible and cappable, since a single
    call to this function can itself make 1-3+ real calls internally via
    integrity.py's retry loop.

    `model_override` (Round 61) is forwarded, unchanged, all the way down to
    judge.py's real judgment call. Defaults to None, which keeps this
    function's behavior identical to every round before this one — the only
    caller that passes a non-None value is the Streamlit POC (app.py),
    whose own UI defaults to Round 59's free OpenRouter model and only
    reaches the real Anthropic API when a developer explicitly flips and
    confirms a toggle. See judge.py's docstring on this same parameter.
    """
    pages = extract_pdf_text(pdf_path)
    pages = flag_image_only_pages(pages)

    to_render = flagged_page_numbers(pages)
    rendered_images = render_flagged_pages(pdf_path, to_render) if to_render else {}

    extracted_fields = fields_module.extract_fields(pdf_path, pages)

    # Rules whose applies_to_plan_type/applies_to_payor doesn't match this TP
    # never reach either layer — they come back pre-filled as not_applicable.
    applicable_rules, excluded_findings = fields_module.partition_rules_by_scope(rules, extracted_fields)

    det_results = fields_module.run_deterministic_checks(applicable_rules, extracted_fields)

    rules_by_id = {r["rule_id"]: r for r in rules}

    # Any deterministic finding that came back not_checkable/uncertain, or
    # with confidence below the escalation threshold, gets a second look from
    # the judgment layer in the same call — it has the rendered images and
    # can reason about ambiguous text, where the regex-based checkers can't.
    escalated_ids = [rid for rid, r in det_results.items() if fields_module.needs_escalation(r)]
    escalated_rules = [rules_by_id[rid] for rid in escalated_ids]

    judgment_rules = [r for r in applicable_rules if r["check_type"] == "judgment" and r["active"]]
    full_judgment_batch = judgment_rules + escalated_rules

    judgment_results = integrity.run_judgment_with_integrity_check(
        full_judgment_batch, extracted_fields, rendered_images, tracker=tracker, model_override=model_override,
    )

    # For escalated rules, the judgment result wins (more context to work
    # with) — but the original deterministic attempt is kept as a secondary
    # "det_attempt" field so a disagreement between the two layers is visible
    # for debugging, not silently overwritten. If judgment also comes back
    # not_checkable, that's a real confirmation the rule needs external data
    # this POC doesn't have — not a gap in either layer's code.
    for rule_id in escalated_ids:
        det_attempt = det_results[rule_id]
        merged = {**judgment_results[rule_id], "det_attempt": det_attempt}
        # The deterministic layer's page number is computed directly from
        # scanning fields["pages"] for a specific match — it isn't guessed.
        # Judgment's page comes from the model counting through a long,
        # multi-page prompt, which is exactly what produced a confirmed
        # off-by-one on QA-RPT-01 against CS TP.pdf. When the det layer
        # found a specific page, prefer it over judgment's re-derived one.
        # Doesn't apply when judgment's evidence is the multi-page list
        # form — that form already carries its own per-item pages and a
        # single det page wouldn't fit its shape. Also doesn't apply when
        # judgment's own `page` is itself a multi-page list (2026-07-28
        # multi-page-finding support): that's genuine information a
        # single-page det checker structurally cannot produce, and forcing
        # det's one page into that slot would silently discard it — proven
        # by a real fixture where judgment's evidence explicitly discussed
        # two specific pages and det's unrelated single page overwrote both.
        if (
            det_attempt.get("page") is not None
            and isinstance(merged.get("evidence"), str)
            and not isinstance(merged.get("page"), list)
        ):
            merged["page"] = det_attempt["page"]
        det_results[rule_id] = merged

    # Route each excluded rule's not_applicable finding into the dict
    # matching its own check_type, so merge_findings's existing det/judgment
    # dispatch picks it up without any change to merge.py.
    for rule_id, finding in excluded_findings.items():
        rule = rules_by_id[rule_id]
        if rule["check_type"] == "deterministic":
            det_results[rule_id] = finding
        else:
            judgment_results[rule_id] = finding

    result = merge_module.merge_findings(rules, det_results, judgment_results)
    # Surfaced so callers (app.py) can display what was actually detected —
    # never assumed — for this specific document, instead of hardcoding a
    # payor name anywhere in the UI.
    result["detected_payor"] = extracted_fields.get("payor")
    result["detected_plan_type"] = extracted_fields.get("plan_type")
    return result
