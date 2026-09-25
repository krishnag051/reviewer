"""Step 5 of the pipeline (Section 4): a single Claude call for every
check_type == "judgment" and active rule. Output is forced via tool-use into
the Findings schema (Section 3) — one entry required per rule_id sent in.

Model: claude-sonnet-5 (Section 5's choice for this judgment call).

Note on the "previous finalized TP" input the design doc mentions (Section 4,
step 5): this POC has no backend integration, so there is no prior-version
data to pass. The model is told plainly that no prior version is available
for this run, so it can answer prior-version-dependent rules with
"not_checkable" rather than guessing.
"""
import base64
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import anthropic
from dotenv import load_dotenv

from .model_provider import call_openrouter_with_fallback, resolve_provider_and_model

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

MODEL = "claude-sonnet-5"

FINDINGS_TOOL = {
    "name": "record_findings",
    "description": (
        "Record one finding per rule_id given in the judgment rule list. "
        "You must return exactly one entry for every rule_id provided — no "
        "more, no fewer."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "evidence": {
                            "anyOf": [
                                {
                                    "type": "string",
                                    "description": (
                                        "A specific, quoted or closely-paraphrased justification grounded in "
                                        "the document. Never a restatement of the rule. Work out your "
                                        "reasoning here BEFORE choosing a result below — do not decide the "
                                        "result first and write justifying evidence afterward. "
                                        "Round 77: state the finding directly and stop — one or two tight "
                                        "sentences, the minimum quote/reference needed to support it. No "
                                        "restating the question, no hedging preamble ('It appears that...', "
                                        "'Upon review of...'), no throat-clearing before the actual point. "
                                        "This is about HOW MANY WORDS per point, not how many points: if a "
                                        "problem genuinely recurs on several pages, still name every one (see "
                                        "the array form below) — conciseness means cutting filler per finding, "
                                        "never cutting real coverage. If you need to cite a page number "
                                        "inside this text (in addition to the structured `page` field below), "
                                        "use exactly the tag [Page N] — e.g. '[Page 15]' — never 'page 15', "
                                        "'pages 15-18', a comma list, or any other phrasing; one [Page N] tag "
                                        "per distinct page, repeated if more than one page applies to the same "
                                        "sentence."
                                    ),
                                },
                                {
                                    "type": "array",
                                    "description": (
                                        "Use this array form instead of a single string when the SAME problem "
                                        "shows up as a genuinely distinct, page-specific issue on more than one "
                                        "page — one entry per page, each naming that page's specific problem. "
                                        "Never collapse multiple pages into one summary sentence like 'pages "
                                        "13, 15, 35, 40-48 are missing X' — a reviewer needs to see each page's "
                                        "actual issue individually. Each entry's own `detail` text follows the "
                                        "same concise style as the string form above."
                                    ),
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "page": {"type": "integer", "description": "1-indexed page number."},
                                            "detail": {
                                                "type": "string",
                                                "description": "The specific problem found on this exact page — not a shared generic description reused across pages. Short and direct, same style as the string evidence form.",
                                            },
                                        },
                                        "required": ["page", "detail"],
                                    },
                                },
                            ],
                        },
                        "result": {
                            "type": "string",
                            "enum": ["pass", "fail", "uncertain", "not_applicable", "not_checkable"],
                            "description": "Choose this AFTER writing the evidence above, and make sure it's the conclusion that evidence actually points to — not a categorical judgment made before working through the reasoning.",
                        },
                        "evidence_supports_result": {
                            "type": "boolean",
                            "description": (
                                "Must be true. Re-read your own evidence text and confirm it actually "
                                "supports the result you chose before setting this — if your evidence "
                                "describes something as absent, resolved, or not applicable, result "
                                "cannot be 'fail'; if it names an unresolved problem, result cannot be "
                                "'pass.' If you cannot honestly mark this true, change result to "
                                "'uncertain' instead of submitting a contradiction — do not set this "
                                "to false and submit anyway, it will be rejected and re-asked."
                            ),
                        },
                        "page": {
                            "anyOf": [
                                {"type": "integer", "description": "A single 1-indexed page number."},
                                {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "minItems": 2,
                                    "description": (
                                        "Use this array form when the SAME finding genuinely depends on "
                                        "or references more than one specific page together — e.g. a "
                                        "reviewer comment on one page pointing to content established on "
                                        "an earlier page, or an issue only visible by comparing two pages "
                                        "against each other. This is different from the {page, detail} "
                                        "list form above: that form is for the same problem recurring "
                                        "independently on many pages (one row per page); this form is one "
                                        "finding whose evidence spans a specific, small set of pages "
                                        "together. Only include the pages actually load-bearing to this "
                                        "finding, not every page the topic happens to appear on."
                                    ),
                                },
                                {
                                    "type": "null",
                                    "description": (
                                        "Not page-specific. For a fail/uncertain/not_checkable result "
                                        "specifically, treat null as a last resort, not a default: a "
                                        "reviewer needs to open the document to that exact page to verify "
                                        "one of these three results, so first make a genuine effort to "
                                        "find and cite the real page before concluding none applies."
                                    ),
                                },
                            ],
                            "description": (
                                "1-indexed page number(s) the evidence came from — a single integer for "
                                "the common case, an array of 2+ integers when the finding genuinely spans "
                                "multiple specific pages together, or null if not page-specific. Must be "
                                "null when evidence is the {page, detail} array form above (each item "
                                "already carries its own page). NON-PASS RESULTS (fail/uncertain/"
                                "not_checkable): a real, correct page number here is what lets a reviewer "
                                "actually verify the problem — this matters far more than on a pass, "
                                "since a pass usually needs no follow-up. Do not leave this null for a "
                                "non-pass result just because it's more convenient; if you genuinely "
                                "cannot pin the finding to a specific page, that is itself worth "
                                "reconsidering (see the top-level instructions below)."
                            ),
                        },
                        "confidence": {"type": "number", "description": "0.0-1.0"},
                        # Fix Round (2026-09-11), item 3 -- REAL, STRUCTURAL
                        # enforcement, not another prose instruction: `page`
                        # above already allows null "as a last resort," which
                        # a model can (and confirmed live, does) reach for
                        # out of convenience rather than genuine absence.
                        # This field makes the model commit to WHICH case it
                        # is, checkably -- see _findings_dict_from_list's own
                        # enforcement of it below.
                        "nothing_relevant_found_anywhere": {
                            "type": "boolean",
                            "description": (
                                "Only meaningful when result is 'not_applicable' or 'not_checkable' -- "
                                "must be true ONLY if you searched and found NO real, relevant "
                                "information anywhere in the document for this rule (there is genuinely "
                                "nothing to cite a page for). Set it to false if you found SOME relevant "
                                "information -- a partial field, a related mention, anything real -- even "
                                "if it wasn't enough to fully resolve the rule; in that case `page` above "
                                "must still cite where that partial information came from. For 'pass'/"
                                "'fail'/'uncertain' results this field is ignored -- those always came "
                                "from real evidence, so `page` is always required for them regardless of "
                                "this field."
                            ),
                        },
                    },
                    "required": [
                        "rule_id", "evidence", "result", "evidence_supports_result", "page", "confidence",
                        "nothing_relevant_found_anywhere",
                    ],
                },
            }
        },
        "required": ["findings"],
    },
}


def _build_prompt(judgment_rules: list[dict], fields: dict, rendered_images: dict[int, bytes]) -> list[dict]:
    rules_summary = [
        {
            "rule_id": r["rule_id"],
            "category": r["category"],
            "description": r["description"],
            "notes": r.get("notes"),
            # Rules escalated from the deterministic layer (no checker
            # implemented, or low-confidence) often carry their real
            # pass/fail thresholds in params rather than notes — send it
            # through explicitly so the model isn't relying on whatever
            # numbers happen to already be in the free-text description.
            "params": r.get("params"),
            # Fix Round (2026-08-27): real, additional data for this
            # specific rule -- e.g. the upload's own Patient Central Reach
            # Information intake answer -- injected by a caller via
            # review_treatment_plan's extra_rule_context param (see that
            # function's own docstring). None for every rule this isn't
            # set for; omitted from the summary entirely only in the sense
            # that json.dumps below will still show the key as null, which
            # is fine -- the point is this is never silently missing for a
            # rule that DOES have real extra context to offer.
            "additional_real_data": r.get("extra_context"),
        }
        for r in judgment_rules
    ]

    content: list[dict] = [
        {
            "type": "text",
            "text": (
                "You are reviewing an ABA Treatment Plan (TP) against a set of "
                "compliance rules. For each rule below, determine pass / fail / uncertain / "
                "not_applicable / not_checkable, grounded in the actual document text and "
                "images provided — never guess, and use 'uncertain' rather than a confident-"
                "sounding guess when the evidence is genuinely ambiguous.\n\n"
                "Where a rule includes a 'params' object, treat those values as the exact, "
                "authoritative thresholds for that rule (e.g. an age cutoff or a numeric cap) — "
                "use them directly rather than re-deriving numbers from the prose description.\n\n"
                "Where a rule includes a non-null 'additional_real_data' value, that is real data "
                "collected specifically for this upload (e.g. a reviewer's own typed intake answer) — "
                "not part of the TP document itself, but genuinely real, current information you "
                "should actually compare against/reason with for that rule, not ignore. This is "
                "different from the 'named external source not provided to you' caveat below — "
                "'additional_real_data' IS provided to you, right here, so use it.\n\n"
                "IMPORTANT: no previous finalized version of this patient's TP is available "
                "for this run (standalone prototype, no backend integration yet). Any rule "
                "that depends on comparing against a prior TP version must be answered "
                "'not_checkable' with evidence saying so — do not fabricate a prior version.\n\n"
                "RELATED, MORE GENERAL POINT (Round 84): if a rule's own description or notes "
                "describe checking a value against a NAMED EXTERNAL SOURCE that is not itself "
                "provided to you anywhere in this prompt — a maintained CPT billing-code "
                "reference guide, CentralReach, a coordinator's email, the Learning Tree, an "
                "insurance/payor verification system, a provider credentialing roster, or any "
                "other named external system or document — you were not given that resource. "
                "Recognizing that a code or value LOOKS like a generically plausible/standard "
                "one (from your own general knowledge) is NOT the same as having actually "
                "checked it against the specific source the rule names, and reporting a "
                "confident 'pass' on that basis overstates what you verified. For a rule like "
                "this, you may still report what you CAN genuinely verify — e.g. that two "
                "values are internally consistent throughout the document, or that a code is a "
                "real, generically-valid one — but state that plainly in the evidence and set "
                "the result to 'uncertain' or 'not_checkable' for the rule's actual external-"
                "comparison claim, not a 'pass' that implies the named external source was "
                "checked. This does NOT apply to a rule that only needs you to read/reason "
                "about the document's OWN text or images (presence, internal consistency, "
                "narrative plausibility, etc.) — only to rules whose own notes name a specific "
                "external resource this prompt does not include.\n\n"
                "Before finalizing each finding, check that your evidence text is consistent "
                "with the result you chose — if your evidence describes something as absent, "
                "resolved, or not applicable, the result cannot be 'fail'; if your evidence "
                "names an unresolved problem, the result cannot be 'pass.' Set "
                "evidence_supports_result to true only when this check genuinely passes for "
                "that finding. If it doesn't, don't set evidence_supports_result to false and "
                "submit anyway — instead change result to 'uncertain' (and update the evidence "
                "to match) so the finding is honest the first time. This check is about LOGICAL "
                "CONTRADICTION between your own evidence and result, not about your overall "
                "certainty — a well-supported pass or fail should stay pass or fail even if some "
                "peripheral detail is ambiguous. Reserve 'uncertain' for when the evidence itself "
                "genuinely doesn't point to any single result; don't downgrade a finding you can "
                "actually support just because the rule involves some subjective judgment.\n\n"
                "If a rule's problem shows up as a distinct, page-specific issue on more than one "
                "page, set evidence to a list of {page, detail} objects — one entry per page, each "
                "naming that exact page's specific problem — instead of a single summary string. "
                "Only use the plain string form when the finding is confined to one page or is "
                "genuinely page-agnostic.\n\n"
                "When a rule's violation is a REPEATING PATTERN across many pages (e.g. the same "
                "stale date, the same missing field, the same malformed value recurring throughout "
                "the document), enumerate every page where it actually recurs using the list form "
                "above — do not cite only one or a few representative examples with phrasing like "
                "'e.g., pages X, Y, Z' while pages you also saw the pattern on go unlisted. A "
                "reviewer reading this finding needs the complete scope of the problem, not a "
                "sample of it; under-citing makes a document-wide issue look narrower than it is.\n\n"
                "WRITING STYLE (Round 77): write every evidence/detail string short and direct — "
                "state the finding, back it with the minimum quote or reference needed, then stop. "
                "No restating the rule/question, no hedging preamble ('It appears that...', 'Upon "
                "review of the document, it seems...'), no multi-sentence throat-clearing before the "
                "actual point. One or two tight sentences is normally enough. This is entirely "
                "separate from the REPEATING PATTERN instruction just above — conciseness means "
                "fewer words per page cited, never fewer pages cited; a document-wide pattern still "
                "gets every one of its real occurrences listed, just each in a short sentence "
                "instead of a long one.\n\n"
                "PAGE CITATIONS INSIDE EVIDENCE TEXT: the structured `page` field (and the "
                "{page, detail} array form) already carries the real page number(s) for a finding — "
                "you do not need to repeat that number in prose for the pipeline to know which page "
                "it is. If you DO want to name a page inside the evidence/detail text itself (e.g. "
                "'the signature is missing [Page 12]'), use exactly one format, every time: the tag "
                "[Page N] — e.g. [Page 12]. Never write 'page 12', 'pages 12-14', 'p. 12', or a "
                "comma/range list. If a sentence touches more than one page, repeat the tag once per "
                "page (e.g. '...missing on [Page 12] and [Page 14]'), never a single tag covering a "
                "range or list.\n\n"
                "PAGE NUMBERS MATTER MOST ON NON-PASS RESULTS (Next Round, Part 4): the structured "
                "`page` field is not a formality — it is what lets a human reviewer actually go open "
                "the document and verify a finding, and that verification is exactly what a fail, "
                "uncertain, or not_checkable result requires from a reviewer (a pass usually needs no "
                "follow-up, so a page number there, while still worth including, is less urgent). For "
                "every fail/uncertain/not_checkable finding, make a genuine, specific effort to attach "
                "the real page(s) the problem is actually on before considering `page` null — null "
                "should mean 'this genuinely isn't tied to one physical page' (e.g. a document-wide "
                "absence with no single page to point to), never 'I didn't look for one.' If, after "
                "real effort, you still cannot identify a page for a fail/uncertain/not_checkable "
                "finding, treat that inability itself as a signal, not a footnote: a finding you "
                "can't point to a specific page for is often a finding you can't fully ground either. "
                "In that situation, prefer downgrading a shaky-feeling 'fail' to 'uncertain' and say "
                "plainly in the evidence that no specific page could be identified — do not report a "
                "confident fail/uncertain/not_checkable with an unexplained null page when a real "
                "effort to locate one was skipped.\n\n"
                "Rules to check (JSON):\n" + json.dumps(rules_summary, indent=2)
            ),
        },
        {"type": "text", "text": "Full extracted page text, in page order:"},
    ]

    # Round 55: the Round 52 blanket injection of the supporting document's
    # extracted fields into EVERY judgment call (regardless of which rule)
    # was removed here -- replaced with the scoped, two-phase design in
    # pipeline/supporting_doc_resolution.py. Phase 1 (this function) is
    # clean of supporting_doc context for all ~120 rules, same as before
    # Round 52; only a small, known set of rules that come back uncertain/
    # not_checkable get tagged for a conditional, much smaller phase-2
    # follow-up call that sends just their relevant supporting-doc fields --
    # see that module's own docstring for why.

    for page in fields["pages"]:
        low_text_note = " [LOW TEXT — likely image-only; see rendered image if provided below]" if page.get("low_text") else ""
        content.append({
            "type": "text",
            "text": f"--- Page {page['page_number']}{low_text_note} ---\n{page['text']}",
        })

    if rendered_images:
        # Fix Round, item 5: this used to be strictly true (rendered_images
        # only ever held low-text pages). It no longer is -- a page can also
        # be rendered because a rule opted into vision input for a section
        # that lives partly in an embedded image (grids, legends, graphs)
        # even though the page around it has plenty of real extractable
        # text. The wording below covers both reasons without claiming one
        # or the other for a given page.
        content.append({
            "type": "text",
            "text": (
                "Rendered images of pages that either have little/no extractable text, or "
                "contain grid/legend/graph content embedded as an image that the text above "
                "this line cannot capture, in page order:"
            ),
        })
        for page_number in sorted(rendered_images):
            content.append({"type": "text", "text": f"--- Rendered page {page_number} ---"})
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(rendered_images[page_number]).decode("utf-8"),
                },
            })

    return content


MAX_TOKENS = 32000

# Round 62: the OpenRouter free-tier path gets its own, much smaller
# max_tokens -- 32000 is sized for Anthropic's actual observed output on
# the FULL ~120-rule batch; the free model doesn't need that headroom for
# the small, ad-hoc test documents this path is actually exercised with,
# and asking a free/rate-limited model for up to 32000 tokens made a real
# click-through test against a 2-page synthetic document take 20+ minutes
# with no error (the model was simply given room to ramble) before this
# was caught and fixed. If a real judgment batch on this path ever
# legitimately needs more room, judge.py's own max_tokens truncation
# check below will say so explicitly rather than silently hanging.
OPENROUTER_MAX_TOKENS = 8000


def _flatten_prompt_text(content: list[dict]) -> str:
    """Collapses this module's multi-block prompt (text + rendered page
    images) into plain text for a provider that can't accept images —
    Round 61's OpenRouter free-tier default model is text-only. Only used
    on that path; the Anthropic path below keeps sending the full
    multi-block content (including images) exactly as it always has.
    """
    return "\n\n".join(b["text"] for b in content if b.get("type") == "text")


def _run_judgment_checks_once(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    tracker=None,
    call_reason: str = "call",
    model_override: str | None = None,
) -> dict[str, dict]:
    """A single real judgment-layer call. Returns {rule_id: {"result",
    "evidence", "page", "confidence"}} — one entry per rule_id the model
    both answered and self-confirmed (see _findings_dict_from_list).

    `tracker` (an ApiCallTracker) is optional but should always be passed in
    production paths — it's the only thing standing between "run this" and
    silently making an unbounded number of real, billed API calls. See
    pipeline/call_tracker.py for why this exists.

    Round 61: `model_override` is a new, OPTIONAL parameter, defaulting to
    None. When None (every existing caller — backend/client.py's real
    integration, this module's own pre-existing test suite, and any script
    that doesn't pass it explicitly), this function's behavior is
    BYTE-IDENTICAL to before this round: same anthropic.Anthropic() client,
    same MODEL constant, same streaming call. The ONLY caller that passes a
    non-None override this round is the Streamlit POC (app.py), which
    defaults its own UI toggle to "openrouter" (Round 59's free model) and
    only reaches "anthropic" when a developer explicitly flips a toggle and
    confirms — see app.py and pipeline/model_provider.py's own docstring
    for the standing-rule reasoning behind that default.
    """
    if not judgment_rules:
        return {}

    rule_ids = [r["rule_id"] for r in judgment_rules]

    if tracker is not None:
        tracker.check_before_call()

    content = _build_prompt(judgment_rules, fields, rendered_images)

    provider, model = ("anthropic", MODEL) if model_override is None else resolve_provider_and_model(model_override)

    if provider == "openrouter":
        # OpenRouter's free-tier default model is text-only (no vision) —
        # rendered page images (used for image-only/low-text pages) can't
        # be sent on this path. Disclosed, not silent: printed here, and
        # app.py's UI shows the same caveat next to the provider toggle.
        if rendered_images:
            print(
                f"[judge] NOTE: {len(rendered_images)} rendered page image(s) present for this batch, but "
                f"the OpenRouter free-tier path is text-only — images are dropped for this call; judgment "
                f"for any image-only pages relies on their extracted text alone under this provider. Flip "
                f"'Use real Anthropic API' to include rendered images."
            )
        # 2026-08-13: was a bare `_call_openrouter(...)` -- no retry, no
        # fallback, so a single OpenRouter gateway blip failed the whole
        # judgment batch outright. Now goes through the same general
        # retry-with-backoff + Anthropic-fallback mechanism
        # session_note_extraction.py's own call site uses (see
        # model_provider.py::call_openrouter_with_fallback's own docstring
        # for the real incident and full design) -- NOTE this fallback
        # call still uses the flattened, text-only prompt (same limitation
        # the primary OpenRouter attempt already has -- rendered images
        # are dropped either way on this branch, not just on the first
        # attempt); recovering FROM a failed OpenRouter call is this fix's
        # job, not also upgrading what that recovered call can see.
        or_result = call_openrouter_with_fallback(
            model=model,
            prompt_text=_flatten_prompt_text(content),
            tool_name="record_findings",
            tool_description=FINDINGS_TOOL["description"],
            input_schema=FINDINGS_TOOL["input_schema"],
            max_tokens=OPENROUTER_MAX_TOKENS,
            call_reason=call_reason,
            tracker=tracker,
        )
        print(
            f"[judge] this judgment batch was served by provider={or_result['provider_used']!r} "
            f"model={or_result['model_used']!r} (reason={call_reason!r})."
        )
        if tracker is not None:
            tracker.record(reason=call_reason, rule_ids=rule_ids, usage=SimpleNamespace(**or_result["usage"]))
        tool_input = or_result["arguments"]
        if "findings" not in tool_input:
            raise RuntimeError(
                f"Judgment call ({or_result['provider_used']}:{or_result['model_used']}) returned without a "
                f"'findings' key; got keys: {list(tool_input.keys())}."
            )
        return _findings_dict_from_list(tool_input["findings"])

    # provider == "anthropic" — unchanged code path (same seam
    # test_call_tracker_wiring.py / test_supporting_doc_extraction.py mock
    # via judge.anthropic.Anthropic).
    client = anthropic.Anthropic()

    # thinking disabled: this is a bounded classification/extraction task, not
    # open-ended reasoning, and Sonnet 5 runs adaptive thinking by default —
    # those tokens come out of the same max_tokens budget as the tool call
    # itself, and previously starved the JSON output before it could complete.
    # max_tokens > ~16000 needs streaming (SDK HTTP timeout guard).
    with client.messages.stream(
        model=model,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        tools=[FINDINGS_TOOL],
        tool_choice={"type": "tool", "name": "record_findings"},
        messages=[{"role": "user", "content": content}],
    ) as stream:
        response = stream.get_final_message()

    if tracker is not None:
        tracker.record(reason=call_reason, rule_ids=rule_ids, usage=response.usage)

    if response.stop_reason == "max_tokens":
        raise RuntimeError(
            f"Judgment call hit max_tokens ({MAX_TOKENS}) before finishing its tool "
            f"call — the findings JSON is truncated/incomplete. Raise judge.MAX_TOKENS "
            f"or send fewer judgment rules per call."
        )

    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use is None:
        raise RuntimeError(
            f"No tool_use block in the judgment response (stop_reason={response.stop_reason!r}). "
            f"Content blocks returned: {[b.type for b in response.content]}."
        )
    if "findings" not in tool_use.input:
        raise RuntimeError(
            f"Judgment tool call returned without a 'findings' key "
            f"(stop_reason={response.stop_reason!r}); got keys: {list(tool_use.input.keys())}."
        )
    findings_list = tool_use.input["findings"]
    return _findings_dict_from_list(findings_list)


# Item 5 (2026-07-28 round 3): the 3-way majority vote (run_judgment_checks_
# majority_vote, below) measurably improved Fail-catch rate on rules with
# confirmed self-consistency instability, but at a real, permanent 1.5x
# call-count cost per batch. Applying it to every judgment rule would pay
# that cost everywhere for no benefit on the ~65 judgment rules that have
# never shown a live disagreement. This is a small, explicitly tracked
# allow-list -- NOT wired into any production code path yet (run_judgment_
# checks below is untouched and still makes exactly 2 calls for every rule,
# including these) -- of exactly which rule_ids have confirmed real
# instability across this project's rounds, each with its own evidence:
#
# - QA-GIP-06 ("General goals fully completed and include a rationale"):
#   the single most-confirmed unstable rule_id across this project --
#   flagged as a self-consistency tie-break miss on BOTH Reeda and Charny
#   in an earlier round, caught again live this round's ground-truth
#   harness run (came back "uncertain" on Charny in one run, "fail" in
#   another, both against the identical document/code).
# - QA-HRS-07 ("Increase in hours -> compared against previous mastery
#   criteria"): confirmed self-consistency tie-break miss on Reeda in an
#   earlier round (first call correctly said "fail," second call
#   disagreed, downgraded to "uncertain").
# - QA-HRS-09 ("Overlap with home health aide/speech/OT -> goals
#   differentiated"): confirmed tie-break miss on BOTH Reeda and Charny in
#   an earlier round -- the only rule_id besides GIP-06 to show instability
#   on both documents independently.
# - QA-GIP-07 ("Goals open >6mo have rationale reviewed by Eliana"):
#   confirmed tie-break miss on Charny in an earlier round.
# - QA-PROB-01 ("At least 3 Social/3 Communication/2 Behavior entries,
#   narrative format" -- Master Fix Round, 2026-09-08: this comment's own
#   numbers were stale/wrong, fixed to match the rule's real, confirmed
#   asymmetric split, see rules.json's own notes): confirmed unstable THIS
#   round, live -- came back
#   "fail" in one ground-truth harness run and "uncertain" in a later run
#   against the identical document and code, after its notes fix already
#   landed (see rules.json) -- instability survived the content fix, which
#   is exactly the shape self-consistency ties produce regardless of how
#   good the rule's prompt is.
#
# QA-GIP-10 deliberately NOT here despite being in the original tie-break
# list -- it moved to check_type "deterministic" this round (item 1) and no
# longer goes through the judgment layer at all, so a majority vote over it
# is meaningless.
#
# To actually apply the 3rd call to just this list in production would mean
# wiring a lookup here into integrity.py's dispatch -- not done yet, since
# that's a real behavior/cost change warranting its own explicit go-ahead,
# same discipline as every other production-switch decision this project
# has deferred until asked for directly.
MAJORITY_VOTE_RULE_IDS = {
    "QA-GIP-06",
    "QA-HRS-07",
    "QA-HRS-09",
    "QA-GIP-07",
    "QA-PROB-01",
}


def should_use_majority_vote(rule_id: str) -> bool:
    return rule_id in MAJORITY_VOTE_RULE_IDS


def run_judgment_checks(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    tracker=None,
    call_reason: str = "call",
    model_override: str | None = None,
) -> dict[str, dict]:
    """Self-consistency wrapper (2026-07-28 round): calls
    _run_judgment_checks_once TWICE with identical inputs and reconciles.
    Where both calls agree on a rule_id's result, that result is kept.
    Where they disagree... temperature/top_p/top_k are not available as a
    cheaper fix on this model — confirmed live, not just from docs:
    passing a non-default temperature returns a 400
    ("`temperature` is deprecated for this model"); only the model's own
    default is accepted, as a no-op.

    Round 93 (2026-08-14), item 1: BEST-OF-3 TIE-BREAKER added. Where the
    two calls disagree on a rule_id, this used to downgrade straight to
    "uncertain" and stop there. Confirmed live (real ground-truth
    comparison across 3 real patients, agreement improved 69-71% ->
    70-75% after Round 92's fixes) that a large share of these
    disagreements have one of the two calls already matching ground
    truth -- throwing both away as "uncertain" discards a correct answer
    roughly as often as it discards a wrong one. Now: only for the
    SPECIFIC rule_id(s) that disagreed between call 1 and call 2 (never
    for rule_ids that already agreed -- zero extra cost on those), sends
    ONE additional batched 3rd call covering just that disagreeing
    subset, then majority-votes among all 3 answers for each. If the 3rd
    call fails to return an answer for one of those rule_ids (dropped,
    rejected via evidence_supports_result, whatever), that rule_id falls
    back to exactly the same two-call "uncertain" finding this function
    already produced before this round -- never silently dropped, never
    left unset. See _two_way_uncertain_finding (the extracted, unchanged
    fallback) and _three_way_majority_finding (the new reconciliation)
    below.

    COST, EXPLICIT: +1 real API call per document, ONLY IF at least one
    rule_id in the batch disagreed between calls 1 and 2 -- not one extra
    call per disagreeing rule_id (all disagreeing rule_ids for a
    document are sent together in that single 3rd call, same batching
    principle integrity.py's own missing-rule_id retry already uses). Zero
    extra cost when calls 1 and 2 fully agree (unchanged from before this
    round: exactly 2 calls total).

    RISK, EXPLICIT, NOT ELIMINATED BY THIS CHANGE: a 2-of-3 majority is
    more-likely-correct, not guaranteed-correct -- this trades some of
    the old policy's conservative "when in doubt, flag for human review"
    safety margin for higher average correctness, in both directions.
    Some previously-safe "uncertain" findings will now confidently land
    on a WRONG pass/fail, not just a right one. Given the confirmed real
    evidence above (one of the two calls is usually already right), this
    trade looks favorable on net, but it is a real trade, not a pure win.
    """
    if not judgment_rules:
        return {}
    first = _run_judgment_checks_once(
        judgment_rules, fields, rendered_images, tracker=tracker,
        call_reason=f"{call_reason} (consistency check 1/2)", model_override=model_override,
    )
    second = _run_judgment_checks_once(
        judgment_rules, fields, rendered_images, tracker=tracker,
        call_reason=f"{call_reason} (consistency check 2/2)", model_override=model_override,
    )

    reconciled: dict[str, dict] = {}
    disagreed_ids: list[str] = []
    for rule_id in set(first) & set(second):
        f, s = first[rule_id], second[rule_id]
        if f["result"] == s["result"]:
            # Fix Round: same unguarded-raw-dict gap as
            # _three_way_majority_finding's majority branch (see
            # _coerce_evidence_to_string's own docstring for the real
            # crash this fixes) -- the plain 2-call agreement path had the
            # identical exposure, just not the one that actually crashed
            # this time. _coerce_evidence_for_finding (not
            # _coerce_evidence_to_string) -- this is a pass-through
            # branch, so a legitimate list-shaped evidence must survive
            # unflattened (see that function's own docstring for the real
            # bug this distinction fixes).
            # Fix Round (2026-09-11 evening), "maximize real page
            # coverage": prefer whichever of f/s actually carries a real
            # page -- same preference _reconcile_majority_vote/
            # _three_way_majority_finding now both apply.
            winner = f if f.get("page") is not None else (s if s.get("page") is not None else f)
            reconciled[rule_id] = {**winner, "evidence": _coerce_evidence_for_finding(winner["evidence"])}
        else:
            disagreed_ids.append(rule_id)

    if not disagreed_ids:
        return reconciled

    rules_by_id = {r["rule_id"]: r for r in judgment_rules}
    tiebreak_rules = [rules_by_id[rid] for rid in disagreed_ids]
    third = _run_judgment_checks_once(
        tiebreak_rules, fields, rendered_images, tracker=tracker,
        call_reason=f"{call_reason} (tie-break 3/3, {len(disagreed_ids)} disagreeing rule_id(s))",
        model_override=model_override,
    )

    for rule_id in disagreed_ids:
        f, s = first[rule_id], second[rule_id]
        t = third.get(rule_id)
        if t is None:
            # 3rd call didn't answer this rule_id -- fall back to the
            # existing, unchanged two-call behavior. Never silently drop.
            reconciled[rule_id] = _two_way_uncertain_finding(f, s)
        else:
            reconciled[rule_id] = _three_way_majority_finding(f, s, t)
    return reconciled


# Fix Round (2026-08-27): REAL BUG FOUND AND FIXED, confirmed via a real
# completed review's own exported CSV -- tie-break summary text below used
# to interpolate the raw internal result token straight into reviewer-
# facing evidence ("first call said 'not_applicable'", "call 3 said
# 'not_checkable'"), exposing this pipeline's own internal vocabulary
# instead of plain language. This is a pure text-formatting fix -- the
# underlying result values/logic are completely unchanged.
_RESULT_TO_NATURAL_PHRASE = {
    "pass": "pass",
    "fail": "fail",
    "uncertain": "this is uncertain",
    "not_applicable": "this doesn't apply",
    "not_checkable": "this can't be checked",
}


def _natural_result_phrase(result: str) -> str:
    return _RESULT_TO_NATURAL_PHRASE.get(result, result)


def _evidence_preview(evidence, *, max_len: int = 220) -> str:
    """One plain-text preview of a finding's own evidence, for folding
    into a disagreement summary -- handles all 3 real shapes this codebase's
    evidence field can take (plain string, the {page, detail} multi-page
    list form, or a malformed non-string/non-list value), truncated so one
    side of a disagreement can't swamp the whole message."""
    text = _coerce_evidence_for_finding(evidence)
    if isinstance(text, list):
        # {page, detail} form -- join each item's own detail, dropping the
        # per-item page (the caller already cites this entry's own overall
        # page separately) so this stays one flat sentence, not a nested list.
        text = " ".join(_coerce_evidence_to_string(item.get("detail", item)) if isinstance(item, dict) else str(item) for item in text)
    elif not isinstance(text, str):
        text = _coerce_evidence_to_string(text)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def _short_uncertain_summary(entries: list[dict], *, split_desc: str) -> str:
    """Fix Round (2026-09-10), item 4: an Uncertain result's evidence used
    to be a raw multi-call transcript dump -- "call 1 said Fail (<call 1's
    full evidence text>); call 2 said Pass (<call 2's full evidence
    text>); ..." -- confirmed a real usability complaint (too long, reads
    like internal debugging output). Replaced that round with a vote-count
    summary instead.

    Fix Round (2026-09-15), "Language Regression": the vote-count summary
    itself was still internal language a BCBA reviewer wouldn't use ("3 of
    5 calls said Fail") -- replaced with one plain sentence naming neither
    side's actual content.

    Fix Round (2026-09-19), "Uncertain Results Must Show Real Evidence" --
    REAL FIX, reversing the over-correction above: that plain sentence was
    honest about the tone but threw away the one thing a reviewer actually
    needs -- the real substance each side of the disagreement was looking
    at. Confirmed the real complaint: a reviewer landing on Uncertain had
    to open the source document cold and re-derive everything, which
    defeats the point of the tool for exactly the findings a human has to
    act on. Now surfaces each DISTINCT result's own real, representative
    evidence text (with page, when available) -- e.g. "Some reviews found:
    fail -- '<real evidence>' (page 12). Others found: pass -- '<real
    evidence>' (page 9)." `split_desc` still isn't shown verbatim (that
    stays internal-only phrasing like "2-call disagreement") -- only the
    plain-English result label and the real evidence text reach the
    reviewer.
    """
    groups: dict[str, dict] = {}
    for e in entries:
        result = e.get("result")
        if result not in groups or (e.get("page") is not None and groups[result].get("page") is None):
            groups[result] = e  # first entry for this result, or the first one with a real page

    # Fix Round (Round 9, real quality bug found -- and Round 12, REAL
    # ROOT CAUSE FOUND, the Round 9 fix didn't actually close it): Round
    # 9 removed the literal "Some reviews found.../Others found..."
    # template, but the replacement ("N of 5 reviews concluded X") still
    # describes raw vote mechanics -- confirmed real evidence this round
    # phrased the SAME complaint differently ("Reviewers split three
    # ways... two said uncertain, two said pass, one said fail"), which
    # is structurally the identical problem: a count of how many calls
    # landed on which answer, not a synthesized clinical explanation.
    # This rewrite drops every vote-count/reviewer-tally word entirely --
    # "one assessment"/"a separate assessment", never a number of
    # reviewers or a fraction -- and describes only the real substantive
    # disagreement: what each distinct real conclusion actually found and
    # why. Still keeps every distinct result's own real evidence text
    # (the actual 2026-09-19 fix this function exists for -- throwing
    # that away was the ORIGINAL bug); only the FRAMING around it changes.
    sides = []
    labels = ["One assessment", "A separate assessment", "Another assessment", "A further assessment"]
    for i, (result, entry) in enumerate(groups.items()):
        preview = _evidence_preview(entry.get("evidence"))
        page = entry.get("page")
        page_str = f" (page {page})" if page is not None else ""
        phrase = _natural_result_phrase(result)
        label = labels[i] if i < len(labels) else "Another assessment"
        if preview:
            sides.append(f"{label} concluded {phrase} -- \"{preview}\"{page_str}")
        else:
            sides.append(f"{label} concluded {phrase}{page_str}")

    if not sides:
        return "The automated review could not reach a clear, consistent answer for this item. Please confirm manually."
    summary = "This item genuinely came back uncertain: " + "; ".join(sides) + "."
    return f"{summary} Please confirm manually."


def _coerce_evidence_for_finding(evidence):
    """Fix Round (Judgment Layer Stability) -- REAL BUG FOUND AND FIXED,
    caught by this round's own test suite the moment
    run_judgment_checks_majority_vote's reconciliation path was actually
    wired into the real pipeline for the first time: `_coerce_evidence_
    to_string` below is correct for embedding evidence INSIDE a natural-
    language summary sentence (must always be a plain string there), but
    it was ALSO being applied, wrongly, to the WINNING/pass-through
    branches of `_three_way_majority_finding`, `_reconcile_majority_vote`,
    and `run_judgment_checks`'s plain-agreement path -- flattening a
    genuinely legitimate `[{page, detail}, ...]` multi-page evidence list
    (FINDINGS_TOOL's own documented alternate shape, explicitly handled
    downstream by merge.py::_explode_to_rows's own `isinstance(...,
    list)` branch) into a single JSON string, silently discarding the
    real per-page evidence breakdown a reviewer needs. Those three call
    sites now use THIS function instead: only coerce a genuinely
    unexpected shape (the real dict-instead-of-string crash this round
    already fixed); a legitimate `str` or `list` passes through exactly
    as the model returned it, same as this whole reconciliation mechanism
    always did before `_coerce_evidence_to_string` existed.
    """
    if isinstance(evidence, (str, list)):
        return evidence
    return _coerce_evidence_to_string(evidence)


def _coerce_evidence_to_string(evidence) -> str:
    """REAL BUG FOUND AND FIXED (Fix Round, this round): confirmed live,
    real production crash -- QA-PROB-01, a 2-of-3 tie-break majority
    (_three_way_majority_finding's own majority branch, below) returned one
    of the three raw per-call finding dicts completely unvalidated, and
    that call's own `evidence` value was some non-string shape (not the
    FINDINGS_TOOL schema's advertised str, and not even that schema's own
    {page, detail} list-item shape) -- crashed downstream in
    humanize.py's `_PAGE_TAG_RE.split(text)` (expects a str), discarding
    the whole review's results, ~$1.17 of real spend already made.

    The schema (FINDINGS_TOOL, below) is advisory to the model, not
    runtime-enforced on the response side -- exactly the same class of gap
    merge.py::_format_page_display already found and fixed for the `page`
    field in a previous round (its own docstring documents an earlier,
    separate real crash from this same root cause). This is that same fix
    for `evidence`: every finding-dict consumer in this file must coerce
    through this, not silently trust the model's shape.

    Order of preference: already a string -> unchanged. A dict with its
    own "detail" key (the one shape this schema's OWN docs teach the model
    for the list-evidence form, so a mis-shaped single-value response most
    plausibly still uses this key) -> that string, if it itself is a
    string. Otherwise -> a JSON dump, so a reviewer sees the real raw
    content instead of a crash.
    """
    if isinstance(evidence, str):
        return evidence
    if isinstance(evidence, dict) and isinstance(evidence.get("detail"), str):
        return evidence["detail"]
    return json.dumps(evidence)


def _page_for_uncertain_fallback(entries: list[dict]):
    """Fix Round (2026-09-11), page-number enforcement gap, part 2 -- REAL
    BUG FOUND AND FIXED: `_two_way_uncertain_finding` and
    `_three_way_majority_finding`'s no-majority branch used to hardcode
    `"page": None` unconditionally for a synthetic "uncertain" finding
    built by reconciling disagreeing per-call results -- even when one or
    more of those underlying calls DID cite a real page (each individual
    call's own finding already passed `_findings_dict_from_list`'s
    page-required enforcement before reaching here, so a non-null `page`
    on any of them is real, reviewer-usable evidence, not a guess). This
    was confirmed as a real, live contributor to the missing-page bug on
    a real document run -- these two call sites build findings AFTER the
    per-call enforcement runs, so they silently bypassed it entirely.

    Picks the first non-null page among the disagreeing calls, in call
    order, so the reviewer still gets pointed at a real page whenever any
    call found one -- only true when every disagreeing call itself found
    nothing page-specific (e.g. all disagreed while examining a
    genuinely page-agnostic aspect of the rule) does this still return
    None, which is the same "genuinely nothing to cite" case the
    non-uncertain enforcement already treats as legitimate.
    """
    for e in entries:
        if e.get("page") is not None:
            return e["page"]
    return None


def _two_way_uncertain_finding(f: dict, s: dict) -> dict:
    """The original (pre-Round-93) two-call disagreement fallback,
    extracted unchanged so both run_judgment_checks' own two-call path and
    the Round 93 best-of-3 tie-breaker's "3rd call didn't answer" fallback
    produce byte-identical output for the same two-call disagreement --
    the explicit requirement approved for item 1: a dropped/missing 3rd
    call must fall back to today's existing "uncertain" behavior, not a
    new or different one.
    """
    fallback_page = _page_for_uncertain_fallback([f, s])
    return {
        "result": "uncertain",
        # Fix Round (2026-09-10), item 4: short vote-count summary, not a
        # per-call evidence dump -- see _short_uncertain_summary's own
        # docstring.
        "evidence": _short_uncertain_summary([f, s], split_desc="2-call disagreement"),
        "page": fallback_page,
        "confidence": 0.0,
        # Fix Round (2026-09-11 evening): flag for integrity.py's
        # page-recovery pass, same as every other accepted-but-pageless
        # finding -- an "uncertain" verdict deserves a page-recovery
        # attempt just as much as a pass/fail does.
        **({} if fallback_page is not None else {"page_unresolved": True}),
    }


def _three_way_majority_finding(f: dict, s: dict, t: dict) -> dict:
    """Round 93, item 1: reconciles the 3rd, tie-breaking call against the
    first two for ONE rule_id that already disagreed between calls 1/2.
    A strict majority (2 of 3 sharing the same result) wins, keeping
    whichever of the matching pair's own finding dict (evidence/page/
    confidence) came first. No majority (all 3 disagree) falls back to
    "uncertain", same honesty principle as the two-call and
    run_judgment_checks_majority_vote's own N-way versions -- a 3-way
    split is not this function's job to force a pick on.
    """
    entries = [f, s, t]
    counts = Counter(e["result"] for e in entries)
    winning_result, winning_count = counts.most_common(1)[0]
    if winning_count >= 2:
        # Fix Round: this is the exact line that crashed downstream in a
        # real production run (see _coerce_evidence_to_string's own
        # docstring) -- the winning call's raw dict, `evidence` included,
        # was returned completely unvalidated. Return a coerced COPY, not
        # the original dict mutated in place (it may still be referenced
        # elsewhere via `first`/`second`/`third`).
        # Fix Round (2026-09-11 evening), "maximize real page coverage":
        # same preference as _reconcile_majority_vote -- among the entries
        # sharing the winning result, prefer one with a real page.
        winning_entries = [e for e in entries if e["result"] == winning_result]
        winner = (
            next((e for e in winning_entries if e.get("page") is not None), None)
            or next((e for e in winning_entries if not e.get("page_unresolved")), None)
            or winning_entries[0]
        )
        # Pass-through branch -- _coerce_evidence_for_finding, not
        # _coerce_evidence_to_string, so a legitimate list-shaped evidence
        # (FINDINGS_TOOL's own {page, detail} multi-page form) survives
        # unflattened (real bug found and fixed this round -- see that
        # function's own docstring).
        return {**winner, "evidence": _coerce_evidence_for_finding(winner["evidence"])}
    fallback_page = _page_for_uncertain_fallback(entries)
    return {
        "result": "uncertain",
        "evidence": _short_uncertain_summary(
            entries, split_desc="2-call disagreement plus its own tie-breaking 3rd call, no majority",
        ),
        "page": fallback_page,
        "confidence": 0.0,
        # Fix Round (2026-09-11 evening): same page-recovery flag as
        # _two_way_uncertain_finding -- see that function's own comment.
        **({} if fallback_page is not None else {"page_unresolved": True}),
    }


def _reconcile_consistency_check(first: dict[str, dict], second: dict[str, dict]) -> dict[str, dict]:
    """Retained standalone (2026-08-14, Round 93) for any caller/test that
    wants the plain two-call reconciliation without the best-of-3
    tie-breaker run_judgment_checks now applies -- byte-identical
    behavior to before this round, via the same extracted
    _two_way_uncertain_finding helper the tie-breaker's own fallback uses.
    """
    reconciled = {}
    for rule_id in set(first) & set(second):
        f, s = first[rule_id], second[rule_id]
        if f["result"] == s["result"]:
            reconciled[rule_id] = f
            continue
        reconciled[rule_id] = _two_way_uncertain_finding(f, s)
    return reconciled


def run_judgment_checks_majority_vote(
    judgment_rules: list[dict],
    fields: dict,
    rendered_images: dict[int, bytes],
    n_calls: int = 3,
    tracker=None,
    call_reason: str = "call",
    min_agreement: int | None = None,
    model_override: str | None = None,
) -> dict[str, dict]:
    """Fix Round (Judgment Layer Stability) -- REAL BUG CONFIRMED (not by
    theory, by direct measurement): a real-data investigation this round
    (see this round's own report) found that at the RAW single-call level,
    11 of 14 known-unstable rules already produced 2-3 DIFFERENT verdicts
    across just 7 independent calls with identical input and zero code
    change -- confirming genuine per-call sampling variance (temperature=0
    is not available on this model, confirmed in an earlier round) as a
    real, dominant cause, on top of (not instead of) the small-sample-size
    problem this function's own original docstring already flagged: with
    only 2-3 samples, a rule sitting near a real decision boundary flips
    on essentially every run.

    Was previously an untested, not-wired-in alternative to the production
    2-call `run_judgment_checks` -- this round wires it in for real (see
    `pipeline/__init__.py`'s own call site) after measuring real flip-rate
    reductions at n_calls=5 and n_calls=7 against a pool of independent raw
    calls (this round's own report has the exact numbers).

    Makes n_calls real API calls per batch (default 3, vs. the old
    production default's 2 + conditional 3rd) — a real, larger cost
    increase per document, traded for real, measured stability.

    `min_agreement` (new this round): the minimum number of the n_calls
    that must agree before their shared result is trusted, instead of the
    old, implicit "simple majority" (`> n_calls/2`) every time. `None`
    (the default) preserves that exact original behavior byte-for-byte --
    passing an explicit stricter threshold (e.g. `min_agreement=4` with
    `n_calls=5`, this round's own "4-of-5, else uncertain" ask) requires
    MORE than a bare majority before committing to an answer, falling back
    to "uncertain" more readily on a genuinely close call rather than
    picking whichever side narrowly won this particular sample.

    For each rule_id present in ALL n_calls responses: if `min_agreement`
    (or the default simple-majority bar) is met, that result wins (kept
    from whichever call first produced it). Otherwise falls back to
    "uncertain" — same honesty principle as the 2-way version, just with a
    configurable bar before giving up. A rule_id missing from any single
    call is left out of the returned dict entirely, same as the 2-way
    version — integrity.py's retry logic handles it.
    """
    if not judgment_rules:
        return {}
    # Fix Round (Performance, 2026-09-11): the n_calls vote calls are
    # independent and stateless (identical input, no ordering dependency
    # between them -- _reconcile_majority_vote below only ever counts
    # votes, it doesn't care which call produced which result), so they
    # run concurrently now instead of one-at-a-time. Bounded to n_calls
    # workers -- this pool covers only ONE rule-batch's own vote, not the
    # whole judgment run, so this doesn't fire more concurrent requests
    # than the vote's own call count regardless of how many times this
    # function is invoked. `tracker` (CallTracker) is shared across the
    # workers -- made thread-safe (a lock around its two mutating methods)
    # specifically for this change, see model_provider.py.
    #
    # Results are collected in call-index order (via list comprehension
    # over futures, not as_completed) purely so a fixed ordering is
    # preserved for anything downstream that might log/inspect them by
    # position -- _reconcile_majority_vote itself is order-independent.
    with ThreadPoolExecutor(max_workers=n_calls) as pool:
        futures = [
            pool.submit(
                _run_judgment_checks_once,
                judgment_rules, fields, rendered_images, tracker=tracker,
                call_reason=f"{call_reason} (majority vote {i + 1}/{n_calls})", model_override=model_override,
            )
            for i in range(n_calls)
        ]
        all_results = [f.result() for f in futures]
    return _reconcile_majority_vote(all_results, min_agreement=min_agreement)


def _reconcile_majority_vote(
    all_results: list[dict[str, dict]], *, min_agreement: int | None = None,
) -> dict[str, dict]:
    if not all_results:
        return {}
    common_ids = set.intersection(*(set(r) for r in all_results))
    reconciled = {}
    for rule_id in common_ids:
        entries = [r[rule_id] for r in all_results]
        counts = Counter(e["result"] for e in entries)
        winning_result, winning_count = counts.most_common(1)[0]
        required = min_agreement if min_agreement is not None else (len(all_results) / 2)
        meets_bar = winning_count >= required if min_agreement is not None else winning_count > required
        if meets_bar:
            # Fix Round (2026-09-11 evening), "maximize real page coverage":
            # among the entries sharing the winning result, prefer one that
            # actually carries a real page (or the legitimate list-evidence/
            # nothing-found-anywhere shapes) over "whichever came first" --
            # a real page from even ONE of the n_calls votes is real,
            # reviewer-usable evidence and shouldn't be thrown away just
            # because it wasn't the first vote counted.
            winning_entries = [e for e in entries if e["result"] == winning_result]
            winner = (
                next((e for e in winning_entries if e.get("page") is not None), None)
                or next((e for e in winning_entries if not e.get("page_unresolved")), None)
                or winning_entries[0]
            )
            # Pass-through branch -- _coerce_evidence_for_finding, not
            # _coerce_evidence_to_string (real bug found and fixed this
            # round, the moment this function was actually wired into the
            # real pipeline for the first time: a legitimate list-shaped
            # evidence was being silently flattened here -- see that
            # function's own docstring).
            reconciled[rule_id] = {**winner, "evidence": _coerce_evidence_for_finding(winner["evidence"])}
            continue
        bar_desc = f"needed {int(required)}+ agreeing" if min_agreement is not None else "no majority"
        fallback_page = _page_for_uncertain_fallback(entries)
        reconciled[rule_id] = {
            "result": "uncertain",
            "evidence": _short_uncertain_summary(entries, split_desc=bar_desc),
            # Fix Round (2026-09-11), page-number enforcement gap: same
            # real bug as _two_way_uncertain_finding/_three_way_majority_
            # finding's no-majority branch -- this is the ACTUAL production
            # majority-vote path (run_judgment_checks_majority_vote, wired
            # in Round "Judgment Layer Stability"), so this hardcoded None
            # was the dominant real contributor among the judgment-layer
            # (non-DET_CHECKS) rule_ids confirmed missing a page on the
            # real Dayland run (QA-ACF-02, QA-ACF-08, QA-COC-01, QA-MAST-01,
            # QA-PROB-04, QA-RPT-03, QA-SCH-02).
            "page": fallback_page,
            "confidence": 0.0,
            **({} if fallback_page is not None else {"page_unresolved": True}),
        }
    return reconciled


def _findings_dict_from_list(findings_list: list[dict]) -> dict[str, dict]:
    """Converts the tool call's raw findings array into {rule_id: finding}.

    Structural enforcement of change #3: a finding the model itself marked
    evidence_supports_result=False is rejected, not recorded — it's simply
    left out of the returned dict, which makes it look identical to a
    rule_id the model dropped entirely. integrity.py's existing missing-
    rule_id retry logic (built for exactly that case) picks it back up and
    re-asks automatically, then raises IntegrityError if it's still
    inconsistent after max_retries — no separate error path needed.

    Confirmed live: despite the tool schema requiring each `findings` array
    item to be an object, a real model response has come back with a bare
    string in that array position instead (tool-call formatting slip, not
    reproduced deterministically). Treating every non-dict entry as
    malformed-and-dropped (same "retried as if missing" path as a rejected
    evidence_supports_result) turns that into an honest retry instead of an
    AttributeError crash — the model gets asked again for whichever
    rule_id(s) it garbled, same as any other dropped finding.
    """
    malformed = [f for f in findings_list if not isinstance(f, dict)]
    if malformed:
        print(
            f"[judge] Dropping {len(malformed)} malformed (non-dict) findings-array entr"
            f"{'y' if len(malformed) == 1 else 'ies'} (will be retried as if missing): {malformed!r}"
        )
    findings_list = [f for f in findings_list if isinstance(f, dict)]

    # Fix Round (2026-09-11), page-number enforcement gap, item 3: a finding
    # is rejected (retried as if missing, same mechanism as
    # evidence_supports_result=False below) when it has NO page number and
    # isn't a genuine "nothing relevant found anywhere" case.
    #
    # Fix Round (2026-09-11 evening) -- REAL REGRESSION FOUND AND FIXED:
    # confirmed live against a real document run, dropping a missing-page
    # finding here (same "retried as if missing" bucket as a rejected
    # evidence_supports_result) meant that when the model kept answering
    # the RULE correctly but never managed to also cite a page across every
    # retry, integrity.py's exhaustion path had no way to tell "never
    # answered at all" apart from "answered every time but never got a
    # page" -- both looked identical (rule_id absent from this dict), so a
    # real, repeatedly-reaffirmed Pass/Fail/Uncertain got thrown away and
    # replaced with a guessed-nothing "not_checkable" after retries ran out.
    # Confirmed real: QA-BIO-17/QA-GIP-32/QA-GIP-14/QA-GIP-28/QA-AI-02/
    # QA-AI-03/QA-AI-04 all did this on a real run, all sharing the
    # identical NOT_CHECKABLE_AFTER_RETRIES_TEMPLATE evidence text.
    #
    # Fix: a missing-page finding is no longer dropped from the returned
    # dict -- it's kept, `page: None`, flagged `page_unresolved: True` so
    # integrity.py's separate, targeted page-recovery pass (see that
    # module) knows to try again for a page specifically, WITHOUT this
    # rule_id ever looking "missing" to the exhaustion-to-not_checkable
    # path. Answer-acceptance (does this rule_id have a real, evidenced
    # judgment) and page-citation (does that judgment also cite a page) are
    # now two independent questions -- not_checkable means "the underlying
    # data genuinely doesn't exist," never "we got an answer but couldn't
    # also get a page for it."
    #
    # Also exempts genuinely list-shaped evidence (the {page, detail}
    # multi-page form) from this check -- FINDINGS_TOOL's own schema
    # requires the top-level `page` to be null for that shape (each item
    # already carries its own page), so a null top-level page there was
    # never actually missing anything; the original enforcement never
    # accounted for this and would have wrongly flagged it too, a latent
    # gap in this same round's own earlier fix.
    page_unresolved_ids = set()
    for f in findings_list:
        if f.get("page") is not None or isinstance(f.get("evidence"), list):
            continue
        result = f.get("result")
        if result in ("not_applicable", "not_checkable") and f.get("nothing_relevant_found_anywhere") is True:
            continue  # genuine "nothing to cite" -- no page required
        page_unresolved_ids.add(f.get("rule_id"))
    if page_unresolved_ids:
        print(
            f"[judge] {len(page_unresolved_ids)} finding(s) accepted without a page number (no "
            f"confirmed 'nothing relevant found anywhere' either) -- keeping the real judgment, "
            f"flagged for a separate page-recovery retry rather than discarded: {sorted(page_unresolved_ids)}"
        )

    rejected = [f for f in findings_list if not f.get("evidence_supports_result", False)]
    if rejected:
        # Log the actual result/evidence text for each rejected finding, not
        # just its rule_id — a rule_id alone is undiagnosable after the fact:
        # a prior round hit exactly this dead end (a rule rejected twice on
        # what looked like an unambiguous fact pattern) and had no way to
        # tell, from the log, what the model actually said that it then
        # disowned. This is what makes that diagnosable from the first
        # report instead of needing a live re-run just to see what happened.
        print(f"[judge] Rejecting {len(rejected)} finding(s) with evidence_supports_result=False (will be retried as if missing):")
        for f in rejected:
            evidence = f.get("evidence")
            evidence_str = evidence if isinstance(evidence, str) else json.dumps(evidence)
            print(
                f"  - {f.get('rule_id')!r}: result={f.get('result')!r}, "
                f"confidence={f.get('confidence')!r}, evidence={evidence_str!r}"
            )

    return {
        f["rule_id"]: {
            "result": f["result"],
            "evidence": f["evidence"],
            "page": f.get("page"),
            "confidence": f.get("confidence"),
            **({"page_unresolved": True} if f["rule_id"] in page_unresolved_ids else {}),
        }
        for f in findings_list
        if f.get("evidence_supports_result", False)
    }
