"""Fix Round (2026-08-27), Part 4: a real, distinct, testable pass that
rewrites already-generated evidence/context text for tone and length right
before a result is returned -- ma'am's team's real, recurring feedback:
this text reads too long, too clinical/AI-sounding, and overuses commas
and special characters, not how a person would actually explain it.

DELIBERATE CHOICE, flagged rather than silently decided: this is a plain
DETERMINISTIC rewrite (regex-based cleanup), not a new LLM call. A fully
general "make arbitrary long prose sound like a person said it out loud"
rewrite genuinely wants a language model in the general case -- this
round's own cost constraint (no new real Anthropic calls, and a new LLM
call site at all is a real spend/design decision even on the free
OpenRouter tier) is the reason a model-based version wasn't built or run
here. What this DOES do, for real, on every evidence string this pipeline
already produces:
  - Strips a trailing ".0" off whole numbers (a Python float artifact --
    "8.0" reads like a person wrote "8", never "eight point zero").
  - Converts a bracketed Python list repr (`['1578293197']`) into plain
    prose ("1578293197", or "1578293197 and 9999999999" for two).
  - Lowercases a mid-sentence "AND"/"OR" that was only capitalized because
    it was written as a boolean-logic connective, not for real emphasis.
  - Drops a small set of confirmed-redundant clinical filler
    parentheticals that just restate a fact already stated plainly right
    before them (e.g. "(inclusive)" right after a date range that's
    already unambiguous without it).
  - Normalizes semicolons to periods (a real sentence break, not a
    clinical list-joiner) and collapses doubled punctuation/whitespace
    left behind by the above.

Deliberately NEVER touches: a `[Page N]` citation tag (judge.py's own
exact format, load-bearing for the frontend's clickable page links), a
quoted verbatim source_quote, or any digit sequence that isn't a whole-
number float artifact (a real date, a real ID, a real percentage stays
exactly as reported -- this is a tone/length rewrite, never a fact
change, per this round's own explicit instruction).
"""
from __future__ import annotations

import re

# Preserves [Page N] tags untouched -- see judge.py::EXACT_PAGE_TAG_RE,
# duplicated here (not imported) so this module has no import-time
# dependency on judge.py, matching this pipeline's existing convention of
# small, independently-testable modules (e.g. schedule_hours.py,
# session_note_comparison.py) that don't reach into judge.py.
_PAGE_TAG_RE = re.compile(r"\[Page \d{1,4}\]")

_WHOLE_NUMBER_FLOAT_RE = re.compile(r"(?<!\d)(\d+)\.0\b")
_PYTHON_LIST_REPR_RE = re.compile(r"\[\s*((?:'[^']*'|\"[^\"]*\")(?:\s*,\s*(?:'[^']*'|\"[^\"]*\"))*)\s*\]")
_LIST_ITEM_RE = re.compile(r"['\"]([^'\"]*)['\"]")
# Lowercases a mid-sentence "AND"/"OR" -- anywhere EXCEPT right at the very
# start of the string or right after a sentence-ending ". " (both of which
# are real sentence starts, where it's grammatically a real capital, not a
# boolean-logic artifact).
_MIDSENTENCE_BOOLEAN_WORD_RE = re.compile(r"(?<!^)(?<!\. )(\bAND\b|\bOR\b)")

# Confirmed-redundant, safe to drop outright -- each of these only ever
# appears immediately after the exact fact it restates (checked against
# every current real call site in fields.py/schedule_hours.py/
# session_note_comparison.py, not a general ban on the phrase everywhere).
_REDUNDANT_PARENTHETICALS = (
    " (inclusive)",
)


def _delist(match: "re.Match[str]") -> str:
    items = _LIST_ITEM_RE.findall(match.group(1))
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def humanize_evidence(text: str) -> str:
    """Pure function, no I/O, no model call -- safe to run on every
    evidence string unconditionally. Idempotent (running it twice gives
    the same result as running it once), so it's safe to apply at more
    than one point in the pipeline without double-mangling text.

    Splits the text on [Page N] tags first and only transforms the
    segments BETWEEN them, so a tag is never itself touched or split.
    """
    if not text:
        return text

    segments = _PAGE_TAG_RE.split(text)
    tags = _PAGE_TAG_RE.findall(text)

    cleaned_segments = [_humanize_segment(seg) for seg in segments]

    result = cleaned_segments[0]
    for tag, seg in zip(tags, cleaned_segments[1:]):
        result += tag + seg
    return result.strip()


def _humanize_segment(text: str) -> str:
    text = _PYTHON_LIST_REPR_RE.sub(_delist, text)
    text = _WHOLE_NUMBER_FLOAT_RE.sub(r"\1", text)
    text = _MIDSENTENCE_BOOLEAN_WORD_RE.sub(lambda m: m.group(1).lower(), text)
    for phrase in _REDUNDANT_PARENTHETICALS:
        text = text.replace(phrase, "")
    # Semicolon -> period: a real sentence break reads more like speech
    # than a clinical list-joiner. Re-capitalize the word right after, to
    # keep the new sentence looking like a real sentence.
    text = re.sub(
        r";\s*([a-z])",
        lambda m: ". " + m.group(1).upper(),
        text,
    )
    # Collapse whitespace left behind by any of the above -- deliberately
    # NOT .strip()'d here: this runs per-segment, between [Page N] tags
    # that keep their own surrounding spaces in the segments beside them
    # (see humanize_evidence's own docstring) -- stripping a segment's own
    # leading/trailing space here would eat the real space next to an
    # adjacent tag once rejoined. The whole result gets one real .strip()
    # in humanize_evidence, after rejoining.
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,])", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Next Round (2026-08-27), Part 1: the real LLM rewrite, approved with an
# explicit $4 hard cap for this whole round including testing.
#
# Model choice: claude-haiku-4-5 -- this repo's own already-established
# cheap/fast real-Anthropic model (see model_provider.py's
# ANTHROPIC_FALLBACK_MODEL, same model, same reasoning: "a fallback whose
# whole point is get a real answer anyway shouldn't itself become the
# slow/expensive path" -- a short rewrite task is the same shape of
# problem). Real, current pricing: $1.00/Mtok input, $5.00/Mtok output.
#
# This is a SECOND pass, layered ON TOP of the free, deterministic
# humanize_evidence above -- never a replacement. Order matters: the
# deterministic pass runs first (kills float artifacts, list-reprs, etc.
# for $0), THEN this function sends the already-cleaned text to the model
# for the harder tone/length rewrite the deterministic pass can't do
# generically.
#
# [Page N] tags are protected structurally, not just by instruction: every
# tag is swapped for a plain, unmistakable placeholder token BEFORE the
# text ever reaches the model, and swapped back verbatim AFTER -- the
# model literally never sees the string "[Page" at all, so it can't
# rephrase, drop, or renumber a tag even if it tried.
import anthropic

REWRITE_MODEL = "claude-haiku-4-5"
_INPUT_COST_PER_MTOK = 1.00
_OUTPUT_COST_PER_MTOK = 5.00

# REDESIGNED after a real, caught-cheap test run: an earlier version of
# this used exotic private-use Unicode characters (e.g. "\ue0000\ue001")
# as placeholders. Real result against claude-haiku-4-5: it did NOT copy
# them through -- it "explained" them as if they were meaningful content
# ("in location 0", "location 1 came up empty"), silently destroying the
# real page reference. Confirmed by literally running it (cost: under a
# tenth of a cent) before committing to this design, not assumed. Switched
# to a plain, unmistakable ASCII token instead -- a small, cheap model is
# far more likely to recognize "keep PAGEREF0 exactly as-is" as a literal
# copy instruction than to treat oddball Unicode as something to describe.
# Fix Round (2026-08-27): REAL BUG FOUND AND FIXED, confirmed via a real
# completed review (30 of 181 findings across a wide, unrelated spread of
# rule_ids showed raw, un-restored "PAGEREF0PAGEREF1PAGEREF2"-style tokens
# directly in reviewer-facing evidence). Root cause: the OLD template
# ("PAGEREF{i}") relied on \b word-boundary anchors on both sides, which
# silently fails whenever two placeholders sit directly adjacent with no
# separator -- e.g. a source evidence string with "[Page 1][Page 4][Page
# 71]" (no whitespace between citations, a real, common shape -- tie-
# break/merge summaries in particular concatenate sub-evidence strings
# that may already end and begin with a page tag) becomes
# "PAGEREF0PAGEREF1PAGEREF2" once protected. Confirmed directly:
# re.compile(r"\bPAGEREF(\d+)\b").findall("PAGEREF0PAGEREF1PAGEREF2")
# returns [] -- a digit immediately followed by the next token's leading
# "P" is a word-char-to-word-char transition, so \b never matches there,
# for ANY of the tokens except possibly ones at the very start/end of the
# whole string. _restore_page_tags's own re.sub() silently performs ZERO
# substitutions in this case (no error raised) -- the placeholders simply
# pass through unrestored. WORSE: the safety net below couldn't catch it
# either, for the exact same reason (it uses this same regex to scan for
# stray tokens) -- an empty findall() looks identical to "nothing to worry
# about," not "the tokens are unreadable." Fixed by making the template
# self-delimiting -- a fixed non-digit terminator ("X") after the number
# means adjacent tokens are still unambiguous with NO boundary check
# needed at all, so this can never happen regardless of how many
# citations are adjacent or where in the string they fall.
_PLACEHOLDER_TEMPLATE = "PAGEREF{i}X"
_PLACEHOLDER_RE = re.compile(r"PAGEREF(\d+)X")

_REWRITE_SYSTEM_PROMPT = (
    "You rewrite a compliance checklist's evidence text so it reads the way a BCBA would explain the finding "
    "to a colleague out loud, in one breath. Rules, no exceptions:\n"
    "1. Keep every real fact already in the text -- every date, number, name, and page reference. Never drop, "
    "round, or change a fact. This is a tone and length rewrite, never a summary that loses information.\n"
    "2. Some tokens look like PAGEREF0X, PAGEREF1X, etc. (always ending in the letter X). These are literal "
    "placeholder tokens standing in for a page citation. Treat each one as an opaque, unbreakable word -- copy it "
    "through byte-for-byte, in the same position relative to the surrounding words, exactly as spelled (same digits, same capitalization, no space "
    "inside it). Never describe, explain, translate, renumber, or refer to what a PAGEREF token 'means' -- it is "
    "not a location number or an index for you to interpret, it is a literal string you must reproduce unchanged.\n"
    "3. SHORT. Your rewrite's word count must not exceed the original's word count -- shorter is the goal, "
    "never longer. If the original is one sentence, your rewrite is one sentence, not a longer sentence "
    "stitched together with 'and'/'which'/'that'. Cut connecting words; don't add them.\n"
    "4. Minimal punctuation -- avoid semicolons, em-dashes, and bracket/parenthetical asides where a plain "
    "sentence says the same thing. Do not join two facts into one comma-heavy sentence with 'and' or 'which' -- "
    "either keep them as two short separate sentences, or drop a connecting clause that isn't adding new "
    "information.\n"
    "5. Example of the target style -- input: 'Patient age 17. Authorization range 07/30/2026 to 10/30/2026 "
    "(92 days) matches the expected 13-week range for age > 13.' Good output (keeps every fact, still short): "
    "'Patient's 17, and the 07/30/2026 to 10/30/2026 range matches the 13-week expectation for that age.' "
    "Bad output (too long, too many joined clauses, even though it also keeps the facts): 'The patient is 17 "
    "years old and the authorization runs from 07/30/2026 to 10/30/2026 for 92 days, which is the right "
    "13-week range we'd expect for someone over 13.'\n"
    "6. Output ONLY the rewritten text. No preamble, no quotes around it, nothing else."
)


def _protect_page_tags(text: str) -> tuple[str, list[str]]:
    tags: list[str] = []

    def _replace(m: "re.Match[str]") -> str:
        tags.append(m.group(0))
        return _PLACEHOLDER_TEMPLATE.format(i=len(tags) - 1)

    return _PAGE_TAG_RE.sub(_replace, text), tags


def _restore_page_tags(text: str, tags: list[str]) -> str:
    return _PLACEHOLDER_RE.sub(lambda m: tags[int(m.group(1))], text)


def humanize_evidence_with_llm(
    text: str, *, client: "anthropic.Anthropic | None" = None,
) -> tuple[str, dict]:
    """Runs the free deterministic pass first, then one real Haiku call for
    the tone/length rewrite. Returns (rewritten_text, usage) where usage is
    {"input_tokens": int, "output_tokens": int, "cost_usd": float} -- real,
    measured numbers from the real response, never estimated after the
    fact. `client` is injectable for tests (mock the boundary, same
    standing convention as every other real-Anthropic test in this repo);
    `None` (the default, every real caller) constructs a real
    anthropic.Anthropic().

    Returns the deterministically-cleaned text UNCHANGED (usage all zeros)
    for empty/None input or input with no non-tag content to rewrite --
    never spends a real call on nothing.

    `usage["pre_humanize_text"]` (Next Round, Part 2) is always the
    deterministically-cleaned text this call started from -- the real
    "before" a caller needs to keep alongside the rewritten "after" for a
    real audit trail (e.g. a CSV export column), regardless of whether the
    rewrite below succeeded or was rejected by the page-ref safety net.
    """
    cleaned = humanize_evidence(text)
    if not cleaned or not cleaned.strip():
        return cleaned, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "pre_humanize_text": cleaned}

    protected, tags = _protect_page_tags(cleaned)

    real_client = client or anthropic.Anthropic()
    # Fix Round (2026-08-27): REAL BUG FOUND AND FIXED -- confirmed on a
    # real completed review, several genuinely long tie-break/merge
    # disagreement summaries (which concatenate 2-3 calls' own evidence
    # into one string) got cut off mid-sentence with no ellipsis or any
    # indication, because the rewrite call's own max_tokens=200 was too
    # small for a real 3-way summary's rewritten length, and nothing
    # checked whether the response actually finished. Raised to a
    # genuinely comfortable ceiling for the longest real inputs this
    # pipeline produces (a 3-way disagreement summary joining three real
    # evidence strings) -- still bounded, just no longer tight enough to
    # bite on a real, common case.
    response = real_client.messages.create(
        model=REWRITE_MODEL,
        max_tokens=500,
        system=_REWRITE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": protected}],
    )
    rewritten_protected = "".join(b.text for b in response.content if b.type == "text")

    input_tokens = getattr(response.usage, "input_tokens", 0)
    output_tokens = getattr(response.usage, "output_tokens", 0)
    cost_usd = (input_tokens / 1_000_000) * _INPUT_COST_PER_MTOK + (output_tokens / 1_000_000) * _OUTPUT_COST_PER_MTOK
    usage = {
        "input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": cost_usd,
        "pre_humanize_text": cleaned,
    }

    # Hard safety net, not just a hopeful instruction: every PAGEREF token
    # sent in must come back in the response, exactly once each, or this
    # rewrite is rejected outright and the (still real, still cleaned-up)
    # deterministic-only text is returned instead. A rewrite that tightens
    # tone but loses a page reference is a regression, not an improvement
    # -- never ship one, no matter how good the rest of the rewrite reads.
    #
    # Fix Round (2026-08-27): REAL BUG FOUND AND FIXED, confirmed via an
    # actual crash on a real staging upload -- this used to check only
    # ONE direction (every real token present, exactly once) and never
    # checked the other: the model inventing a STRAY, out-of-range token
    # that was never sent to it (e.g. echoing PAGEREF4 when only
    # PAGEREF0-PAGEREF3 existed). That passed the old check fine (every
    # real token was still there, exactly once), so _restore_page_tags
    # went ahead and crashed with an uncaught IndexError trying
    # tags[4] on a 4-element list. Now checks BOTH directions before
    # ever calling _restore_page_tags: every expected token present
    # exactly once, AND every placeholder-shaped token actually in the
    # response has an index that's genuinely in range.
    expected_tokens = [_PLACEHOLDER_TEMPLATE.format(i=i) for i in range(len(tags))]
    all_expected_present_once = all(rewritten_protected.count(tok) == 1 for tok in expected_tokens)
    found_indices = [int(m) for m in _PLACEHOLDER_RE.findall(rewritten_protected)]
    has_stray_out_of_range_token = any(i < 0 or i >= len(tags) for i in found_indices)
    # Fix Round (2026-08-27): REAL BUG FOUND AND FIXED -- a response cut
    # off by hitting max_tokens mid-sentence (Bug 2, above) could still
    # pass BOTH the checks above if the cutoff happened to land after
    # every page tag was already restated (a genuinely real case -- a
    # trailing clause with no further citation in it). The two checks
    # above alone are not a complete safety net; a truncated response is
    # its own real problem regardless of whether the page tags survived,
    # and must never ship silently either.
    was_truncated = response.stop_reason == "max_tokens"
    if all_expected_present_once and not has_stray_out_of_range_token and not was_truncated:
        rewritten = _restore_page_tags(rewritten_protected, tags).strip()
        usage["rejected_missing_page_ref"] = False
        usage["rejection_reason"] = None
        return rewritten, usage
    usage["rejected_missing_page_ref"] = True
    # Next Round (2026-08-27), item 3: a specific, loud reason, not just a
    # boolean -- lets a caller log/report WHY a rewrite was rejected
    # (missing vs. stray vs. truncated are different failure modes worth
    # telling apart), rather than only knowing that it was.
    if was_truncated:
        usage["rejection_reason"] = "truncated"
    elif has_stray_out_of_range_token:
        usage["rejection_reason"] = "stray_page_ref"
    else:
        usage["rejection_reason"] = "missing_page_ref"
    return cleaned, usage
