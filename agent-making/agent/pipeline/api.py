"""Additive-only integration wrapper, per agent-making/INTEGRATION_PLAN.md
Section 1's interface contract. Zero changes to pipeline/__init__.py,
fields.py's SIGNATURES, judge.py's function SIGNATURES, merge.py, or
rules.json's SHAPE — this file (plus supporting_doc_extraction.py and
supporting_doc_resolution.py) is the *entire* surface a caller (the
backend's app/rule_engine/client.py, or anything else) needs to touch.
(Round 52 gave judge.py's `_build_prompt` a body addition that blanket-
injected supporting_doc into every judgment prompt; Round 55 REMOVED that
body addition entirely -- judge.py is now back to its pre-Round-52 body,
byte for byte, for the prompt-construction path. Round 54 also added a
Round-54-specific instruction to QA-HRS-01/QA-BIO-01's own `notes` in
rules.json; Round 55 reverted those two notes fields to their original
pre-Round-54 text too. See pipeline/supporting_doc_resolution.py's module
docstring for the two-phase design that replaced both.)

`review_treatment_plan(pdf_path)` is the one public entry point. It:
- loads rules.json internally (a caller no longer needs to know that path
  or its shape),
- owns its own ApiCallTracker (a caller no longer needs to import a
  pipeline-internal class to get cost data back out),
- catches every known failure mode (bad/corrupt PDF, IntegrityError,
  ApiCallCapExceeded, anything else) and returns a structured `error`
  instead of letting a raw exception reach the caller — this is exactly
  the separately-flagged, already-existing pipeline gap
  (INTEGRATION_PLAN.md's "SEPARATE, ALREADY-EXISTING GAP" callout) that
  said the wrapper should do this catching if the pipeline itself doesn't,
  and the pipeline itself still doesn't,
- resolves the plan's previously-open question: yes, `payor_override`/
  `plan_type_override` are supported (see `_run_pipeline_with_extras` below
  for why that requires a bit of orchestration duplication rather than
  just calling run_full_pipeline directly),
- accepts an optional `supporting_doc_path` — when given, runs the
  mandatory second-file extraction (pipeline/supporting_doc_extraction.py)
  and stores its result in `extracted_fields["supporting_doc"]` before
  either rule-checking layer runs (same orchestration-duplication
  technique `_run_pipeline_with_extras` already used for payor/plan_type
  overrides). Round 55: phase 1 (the normal 120-rule check) no longer
  reads this at all for judgment rules — QA-PPI-05's deterministic
  checker still reads it directly (fields.py, zero extra cost), and a
  small, conditional phase-2 follow-up call (pipeline/
  supporting_doc_resolution.py) reads it for exactly the rules phase 1
  tagged as unresolved dead ends. See that module's docstring for the
  full design and its explicit "not yet validated against Ms. Yachnes's
  real example set" limitation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import fields as fields_module
from . import integrity as integrity_module
from . import merge as merge_module
from . import run_full_pipeline
from .call_tracker import ApiCallCapExceeded, ApiCallTracker
from .extract import extract_pdf_text
from .flag_pages import flag_image_only_pages, flagged_page_numbers
from .humanize import humanize_evidence as _humanize_evidence
from .integrity import IntegrityError
from .render import render_flagged_pages
from .supporting_doc_extraction import extract_supporting_document
from .supporting_doc_resolution import find_taggable_findings, resolve_tagged_findings

SCHEMA_VERSION = "1.0"

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "rules.json"

# The 5 result values agent-making's pipeline actually produces
# (merge.py/judge.py) — kept here as the wrapper's own explicit contract
# with itself, not inferred from whatever happens to show up in one run.
RESULT_VALUES = ("pass", "fail", "uncertain", "not_applicable", "not_checkable")


def _load_rules() -> list[dict]:
    data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    return data["rules"]


def _run_pipeline_with_extras(
    pdf_path: str,
    rules: list[dict],
    tracker: ApiCallTracker,
    *,
    payor_override: str | None,
    plan_type_override: str | None,
    supporting_doc_path: str | None,
    source_filename: str | None = None,
    extra_fields: dict[str, str] | None = None,
) -> dict:
    """Duplicates run_full_pipeline's orchestration (pipeline/__init__.py)
    so a manual payor/plan_type override, and/or the Round 52 supporting-
    document extraction, can be applied to `extracted_fields` before
    scope-filtering and both rule-checking layers run. There's no
    parameter on extract_fields/run_full_pipeline to inject either of
    these — adding one would mean editing pipeline/__init__.py or
    fields.py, which is off the table (see this file's module docstring).
    Every function called below is an EXISTING, unmodified pipeline
    function; only this orchestration glue is duplicated. If the base
    pipeline ever grows native support for either, this function should be
    deleted and callers should go back to plain run_full_pipeline(...).

    (Round 52, named/widened from the original `_run_with_field_override`):
    confirmed via direct investigation that injecting supporting-document
    context does NOT require touching pipeline/__init__.py — both
    `fields_module.run_deterministic_checks` and (via judge.py's
    `_build_prompt`) `integrity_module.run_judgment_with_integrity_check`
    already receive the SAME `extracted_fields` dict by reference and read
    it by key, with no fixed positional signature — so a new
    `extracted_fields["supporting_doc"]` key flows into both layers
    automatically, the same way `payor`/`plan_type` overrides already do
    above. The real cost of this approach, stated plainly rather than
    hidden: because supporting_doc_path is now supplied on every real
    backend call (Round 51 made the second file mandatory), THIS function
    -- not the bare `run_full_pipeline` passthrough below in
    `review_treatment_plan` — is now the orchestration path real production
    traffic actually takes. `api.py` duplicates a larger share of
    pipeline/__init__.py's 90 lines than it did before Round 52, even
    though no line of __init__.py itself changed.
    """
    pages = extract_pdf_text(pdf_path)
    pages = flag_image_only_pages(pages)
    extracted_fields = fields_module.extract_fields(pdf_path, pages)

    # Fix Round, item 5 (2026-08-12) -- REAL BUG FOUND AND FIXED: this
    # function is a hand-duplicated copy of pipeline/__init__.py::
    # run_full_pipeline's orchestration (see this function's own docstring
    # above for why), and it kept computing `to_render` from
    # flagged_page_numbers(pages) ALONE, never unioning in
    # fields_module.vision_eligible_pages(...) the way run_full_pipeline
    # was fixed to do this same round. Since supporting_doc_path is
    # mandatory on every real backend upload (Round 51), THIS function --
    # not run_full_pipeline -- is the orchestration path every real upload
    # actually takes, confirmed live: a real QA-ACF-03 run against Blythe
    # Diaz's document through the backend's own code path came back
    # "no visible legend... would need direct visual inspection" even
    # after the __init__.py fix, because it never touched this duplicate.
    # Same fix, same reasoning as __init__.py's own comment on this line.
    to_render = sorted(set(flagged_page_numbers(pages)) | fields_module.vision_eligible_pages(rules, extracted_fields))
    rendered_images = render_flagged_pages(pdf_path, to_render) if to_render else {}

    if payor_override is not None:
        extracted_fields["payor"] = payor_override
    if plan_type_override is not None:
        extracted_fields["plan_type"] = plan_type_override
    if supporting_doc_path is not None:
        extracted_fields["supporting_doc"] = extract_supporting_document(supporting_doc_path, tracker=tracker)
    if source_filename is not None:
        # Round 82, item 1: the reviewer/facilitator's ORIGINAL uploaded
        # filename (not `pdf_path`, which today is a caller-generated
        # storage-key path with the real filename already discarded --
        # confirmed by reading backend/app/storage.py::save_blob's own
        # docstring: "by upload_id, not the client-supplied filename, to
        # avoid collisions"). Same additive-key convention as payor/
        # plan_type/supporting_doc above -- `extracted_fields` has no fixed
        # positional shape, so a new key here flows into
        # fields.py::_check_PPI03 (the only reader) with zero change to
        # fields.py's own function signature, per this file's module
        # docstring. `None` (the default, and every pre-Round-82 caller)
        # means _check_PPI03 falls back to `Path(pdf_path).name` instead --
        # see that function's own docstring for why that fallback is
        # deliberately inert against today's real backend traffic (a
        # storage-key filename carries no name-like tokens to compare) until
        # a future backend round wires the real original filename through.
        extracted_fields["source_filename"] = source_filename
    if extra_fields:
        # Fix Round (2026-08-27): same additive-key convention as
        # payor/plan_type/supporting_doc/source_filename above -- real,
        # per-upload data (currently: the Patient Central Reach
        # Information intake answers) that a deterministic checker can
        # read by key, same as _check_PPI05's new
        # intake_bcba_name_credentials_npi read.
        extracted_fields.update(extra_fields)

    applicable_rules, excluded_findings = fields_module.partition_rules_by_scope(rules, extracted_fields)
    det_results = fields_module.run_deterministic_checks(applicable_rules, extracted_fields)
    rules_by_id = {r["rule_id"]: r for r in rules}

    escalated_ids = [rid for rid, r in det_results.items() if fields_module.needs_escalation(r)]
    escalated_rules = [rules_by_id[rid] for rid in escalated_ids]
    judgment_rules = [r for r in applicable_rules if r["check_type"] == "judgment" and r["active"]]
    full_judgment_batch = judgment_rules + escalated_rules

    judgment_results = integrity_module.run_judgment_with_integrity_check(
        full_judgment_batch, extracted_fields, rendered_images, tracker=tracker
    )

    # Round 55: scoped, two-phase supporting-document resolution -- see
    # pipeline/supporting_doc_resolution.py's module docstring. Phase 1
    # above already ran completely clean of supporting_doc (judge.py no
    # longer injects it into any prompt). This tags the known small set of
    # rules that came back uncertain/not_checkable AND have a usable
    # supporting-doc field, and — ONLY if anything was tagged — makes
    # exactly one additional, scoped call to try to resolve just those.
    # Zero additional calls when nothing is tagged (the common case for
    # ~118 of 120 rules, and even for the 2 candidate rules whenever
    # phase 1 already resolved them or the supporting document has
    # nothing relevant).
    supporting_doc = extracted_fields.get("supporting_doc")
    tagged = find_taggable_findings(judgment_results, supporting_doc)
    for rule_id in tagged:
        judgment_results[rule_id]["needs_supporting_doc_check"] = True
    if tagged:
        resolved = resolve_tagged_findings(tagged, rules_by_id, supporting_doc, tracker=tracker)
        for rule_id, resolution in resolved.items():
            judgment_results[rule_id] = {
                **judgment_results[rule_id],
                **resolution,
                "needs_supporting_doc_check": True,
                "resolved_via_supporting_doc": True,
            }

    for rule_id in escalated_ids:
        det_attempt = det_results[rule_id]
        merged = {**judgment_results[rule_id], "det_attempt": det_attempt}
        if (
            det_attempt.get("page") is not None
            and isinstance(merged.get("evidence"), str)
            and not isinstance(merged.get("page"), list)
        ):
            merged["page"] = det_attempt["page"]
        det_results[rule_id] = merged

    for rule_id, finding in excluded_findings.items():
        rule = rules_by_id[rule_id]
        if rule["check_type"] == "deterministic":
            det_results[rule_id] = finding
        else:
            judgment_results[rule_id] = finding

    result = merge_module.merge_findings(rules, det_results, judgment_results)
    result["detected_payor"] = extracted_fields.get("payor")
    result["detected_plan_type"] = extracted_fields.get("plan_type")
    # Round 52: surfaced additively, same pattern as detected_payor/
    # detected_plan_type above -- None when no supporting_doc_path was
    # given (the override-only case), never a KeyError for callers that
    # don't know about this yet.
    result["supporting_doc_extraction"] = extracted_fields.get("supporting_doc")
    return result


def _usage(tracker: ApiCallTracker) -> dict:
    return {
        "api_calls": tracker.count,
        "input_tokens": tracker.total_input_tokens,
        "output_tokens": tracker.total_output_tokens,
        "estimated_cost_usd": round(tracker.estimated_cost(), 6),
    }


def _error_result(code: str, message: str, tracker: ApiCallTracker) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "failed",
        "detected_payor": None,
        "detected_plan_type": None,
        "supporting_doc_extraction": None,
        "findings": [],
        "summary": {
            "bcba_fix_rule_ids": [],
            "facilitator_assign_rule_ids": [],
            "counts_by_result": {},
        },
        "usage": _usage(tracker),
        "error": {"code": code, "message": message},
    }


def _to_review_result(raw: dict, tracker: ApiCallTracker) -> dict:
    counts_by_result = dict.fromkeys(RESULT_VALUES, 0)
    for row in raw["export_rows"]:
        counts_by_result[row["result"]] = counts_by_result.get(row["result"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "detected_payor": raw.get("detected_payor") or "Unknown",
        "detected_plan_type": raw.get("detected_plan_type"),
        # Round 52 — None when no supporting_doc_path was passed to
        # review_treatment_plan (the pre-Round-52 caller shape still
        # works unchanged); otherwise a dict keyed by
        # supporting_doc_extraction.SUPPORTING_DOC_FIELDS.
        "supporting_doc_extraction": raw.get("supporting_doc_extraction"),
        "findings": [
            {
                "rule_id": row["rule_id"],
                "category": row["category"],
                "result": row["result"],
                "page": row["page"],
                # Fix Round (2026-08-27), Part 4: the real, distinct
                # humanize pass -- see pipeline/humanize.py's own module
                # docstring. Runs here, in this ONE centralized spot,
                # right before a finding is returned -- both orchestration
                # paths (run_full_pipeline / _run_pipeline_with_extras)
                # already converge on this exact "export_rows" shape by
                # the time execution reaches here, so this covers every
                # real finding regardless of which path produced it,
                # without needing two call sites.
                "detail": _humanize_evidence(row["detail"]),
                "confidence": row["confidence"],
                "action_lane": row["action_lane"],
                "action_tag": row["action_tag"],
            }
            for row in raw["export_rows"]
        ],
        "summary": {
            "bcba_fix_rule_ids": raw["bcba_fix"],
            "facilitator_assign_rule_ids": raw["facilitator_assign"],
            "counts_by_result": counts_by_result,
        },
        "usage": _usage(tracker),
        "error": None,
    }


def review_treatment_plan(
    pdf_path: str,
    *,
    supporting_doc_path: str | None = None,
    payor_override: str | None = None,
    plan_type_override: str | None = None,
    source_filename: str | None = None,
    max_calls: int | None = None,
    extra_rule_context: dict[str, str] | None = None,
    extra_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The one public entry point. Runs the full pipeline against `pdf_path`
    and returns a JSON-serializable `ReviewResult` dict — see
    INTEGRATION_PLAN.md Section 1 for the exact shape this implements.

    `supporting_doc_path` (Round 52): path to the mandatory second file
    (Round 51's backend requirement) — free-form, whatever the reviewer
    attached. When given, this makes ONE ADDITIONAL real API call (on top
    of the existing judgment-layer self-consistency pair) to extract
    Mrs. Ungar's 8 required fields (see
    pipeline/supporting_doc_extraction.py), then makes that extraction
    available to BOTH the deterministic checkers and the judgment-layer
    prompt for every rule in this same run — not limited to a narrow
    subset. `None` (the default, and the only shape every pre-Round-52
    caller still uses unchanged) skips extraction entirely: zero behavior
    change, zero additional call, for anyone not passing this.

    `payor_override`/`plan_type_override`: optional manual overrides for
    when auto-detection would otherwise be trusted blindly, or is expected
    to fail (e.g. a payor name spelled unusually on page 1). `None` (the
    default) means "trust auto-detection", not "use some default payor".

    `source_filename` (Round 82, item 1): the reviewer/facilitator's
    ORIGINAL uploaded filename, e.g. "Zohran Hossain TP.pdf" — deliberately
    separate from `pdf_path`, which is typically a caller-generated
    storage-key path with the real filename already discarded (confirmed:
    this backend's own `save_blob` does exactly that, "to avoid
    collisions"). When given, makes `_check_PPI03` (patient-name
    consistency) additionally compare the document's own extracted patient
    name against this filename, flagging a near-typo mismatch as
    `uncertain` rather than a confident `fail` (a filename can legitimately
    differ for innocuous reasons — a date, "_v2", staff-added label — see
    `fields.py::_name_token_mismatch_detail`'s own docstring). `None` (the
    default) falls back to `Path(pdf_path).name`, which is inert against
    today's real backend traffic (a storage-key filename has no name-like
    tokens to compare against) until a future round threads the true
    original filename through from the backend's Upload record.

    `max_calls`: forwarded to this call's own ApiCallTracker — pass a real
    cap in any context where a runaway retry loop making unbounded billed
    calls would be unacceptable (e.g. a shared/multi-tenant backend
    process). `None` means uncapped, matching the tracker's own default.
    The supporting-document extraction call (when requested) is checked
    against and counted into this SAME tracker/cap, not a separate one —
    see supporting_doc_extraction.py's own docstring.

    Never raises — every failure mode this pipeline is known to produce
    (bad/corrupt PDF path, IntegrityError after retries exhausted,
    ApiCallCapExceeded, anything else) comes back as
    `{"status": "failed", "error": {...}}` instead. A missing/bad
    supporting_doc_path is caught the same way, before any real call.

    `extra_rule_context` (Fix Round, 2026-08-27): optional {rule_id: text}
    map -- when a rule_id here matches one of the rules actually loaded,
    that rule's own entry sent to the judgment layer (judge.py::
    _build_prompt) carries this text as real, additional context, right
    alongside its existing description/notes/params. Built for the
    confirmed gap where the upload's Patient Central Reach Information
    intake answers were collected but never reached the judgment call at
    all (a rule like QA-SCH-02 was judging blind) -- but generic, not
    QA-SCH-02-specific: any rule_id can be a key. This rides the SAME
    already-happening real judgment call every rule already goes through
    -- zero new API-call surface, just richer input to the existing one.
    `None` (every caller before this round) is the exact byte-identical
    behavior this function always had.

    `extra_fields` (Fix Round, 2026-08-27): {key: text} merged directly
    into `extracted_fields` -- reaches a DETERMINISTIC checker (which
    reads `fields[...]` by key, e.g. `_check_PPI05`'s new
    `intake_bcba_name_credentials_npi` read), unlike `extra_rule_context`
    above, which only reaches the judgment layer's prompt. Same additive-
    key convention `_run_pipeline_with_extras` already uses for payor/
    plan_type/supporting_doc/source_filename.
    """
    tracker = ApiCallTracker(max_calls=max_calls)

    if not Path(pdf_path).is_file():
        return _error_result("pdf_not_found", f"No file at path: {pdf_path}", tracker)

    if supporting_doc_path is not None and not Path(supporting_doc_path).is_file():
        return _error_result("supporting_doc_not_found", f"No file at path: {supporting_doc_path}", tracker)

    try:
        rules = _load_rules()
    except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
        return _error_result("rules_load_failed", f"{type(exc).__name__}: {exc}", tracker)

    if extra_rule_context:
        rules = [
            {**r, "extra_context": extra_rule_context[r["rule_id"]]} if r["rule_id"] in extra_rule_context else r
            for r in rules
        ]

    try:
        if (
            payor_override is not None or plan_type_override is not None
            or supporting_doc_path is not None or source_filename is not None
            or extra_fields is not None
        ):
            raw = _run_pipeline_with_extras(
                pdf_path, rules, tracker,
                payor_override=payor_override, plan_type_override=plan_type_override,
                supporting_doc_path=supporting_doc_path, source_filename=source_filename,
                extra_fields=extra_fields,
            )
        else:
            raw = run_full_pipeline(pdf_path, rules, tracker=tracker)
    except IntegrityError as exc:
        return _error_result("integrity_check_failed", str(exc), tracker)
    except ApiCallCapExceeded as exc:
        return _error_result("api_call_cap_exceeded", str(exc), tracker)
    except FileNotFoundError as exc:
        return _error_result("pdf_not_found", str(exc), tracker)
    except Exception as exc:  # noqa: BLE001 — this IS the catch-all the plan calls for
        # A bad/corrupt PDF today raises a raw pypdf parse error with
        # nothing in the pipeline catching it (INTEGRATION_PLAN.md's
        # separately-flagged, already-existing gap) — this is exactly the
        # place that gap said should do the catching if the pipeline
        # itself never does.
        return _error_result("pipeline_error", f"{type(exc).__name__}: {exc}", tracker)

    return _to_review_result(raw, tracker)
