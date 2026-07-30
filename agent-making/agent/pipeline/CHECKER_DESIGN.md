# Checker design — rule_id namespacing and the reuse-vs-new-checker decision

Written ahead of payor #2, against the Healthfirst rule set alone, so this
isn't re-derived ad hoc the first time a second payor's rules show up.

## rule_id namespacing

**Revised** after checking Molina/MVP's own QA checklists against
Healthfirst's: 111 of the 114 rules in `rules/rules.json` are
universal (`applies_to_payor: "ALL"`) — the checklist Molina and MVP
provided is the same document, word-for-word, minus the 3 genuinely
Healthfirst-specific items. An earlier round gave *every* rule_id an `HF-`
prefix, including those 111 universal ones (e.g. `HF-BIP-02`). That was
wrong, not just cosmetic: `HF-BIP-02` reads as Healthfirst-specific and
isn't — it's a rule Molina and MVP TPs must be checked against too, and the
id actively misleads anyone (including a future payor's implementer) into
thinking otherwise. The `applies_to_payor` field is what actually drives
filtering, not the id string, but the id should still tell the truth.

**Current scheme:**
- **Universal rules** (`applies_to_payor: "ALL"`, 111 of 114) carry a `QA-`
  prefix — e.g. `QA-BIP-02`. This is a neutral, payor-agnostic namespace:
  these rules apply to every payor's TPs, so no single payor's prefix
  belongs on them.
- **Genuinely payor-specific rules** (`applies_to_payor` set to one payor
  name, 3 of 114 for Healthfirst) carry that payor's own prefix — `HF-01`,
  `HF-02`, `HF-03`. These three already had a natural `HF-` prefix before
  any namespacing convention existed (coincidentally, since "HF" is also the
  Healthfirst payor's own natural abbreviation) — no rename needed for them
  beyond removing the redundant double-`HF-` an earlier round introduced.

A second payor's own payor-specific rules (if it turns out to need any) get
that payor's own two/three-letter prefix, exactly like `HF-`. Universal
rules stay under `QA-` regardless of which payor's checklist they were
cross-checked against — there's only ever one universal set.

## When a new payor's rule reuses an existing checker (+ params) vs. needs its own function

Working definition, refined by the SCH-08 case below:

- **Same document field, same comparison logic, different threshold/code/
  label** → reuse the existing checker function, add a `params` entry for
  the new rule. This is exactly what `HF-02` (max hours for a specific
  CPT code — one of the 3 genuinely Healthfirst-specific rules) demonstrates:
  `_check_HF02` reads `rule["params"]["max_hours"]`
  and `rule["params"]["cpt_code"]` — a new payor's equivalent hours-cap rule
  on a different CPT code or different cap is a new `params` block against
  the same function, not new code.
- **Different field, different document structure, or different logic
  entirely** → write a new checker function. Don't force-fit a new rule into
  an existing function via ever-more-generic params; that's how a checker
  ends up with five optional params and three of them meaningless for any
  given rule.
- **The field's real-world formatting is inconsistent enough that no fixed
  extraction pattern holds up across documents** → this isn't a
  reuse-vs-new-checker question at all; it means the rule doesn't belong in
  the deterministic layer, full stop. See below.

## The SCH-08 case: when the answer is "reclassify to judgment," not "write checker #4"

SCH-08 (POS value must be one of `home`/`office`/`school`/`community`) went
through three rounds of point-fixes, each closing exactly one false-match
pattern and missing the next:

1. **Round 1** — the original regex matched "POS" as a bare substring with
   no word boundary, so it matched inside "possess," "possible," "position,"
   etc. Fixed with `\b` word boundaries.
2. **Round 2** — with the boundary fixed, a blank POS field followed
   immediately by the next field's label on the same line (a pypdf
   extraction-order artifact) got captured whole and reported as an invalid
   POS value (e.g. "Clinical Rationale"). Fixed by detecting when the
   capture is immediately followed by a colon (meaning it swallowed the
   start of the *next* label).
3. **Round 3** — a third, still-different false-match pattern showed up
   ("are subject to change").

Three distinct failure modes in three rounds, each fix scoped exactly to the
reported case, is itself the signal — not a coincidence of unlucky test
documents. It means the field's actual formatting in this payor's TP layout
varies enough that no single regex-based extraction pattern generalizes.
**The fix in that situation is not a fourth patch — it's reclassifying the
rule from `deterministic` to `judgment`**, the same move already applied to
six other rules in an earlier round (their common problem was image-only
pages the deterministic layer can't see at all; SCH-08's problem is
inconsistent text-layout instead, but the resolution is identical: stop
trying to out-regex a document format that won't hold still, and let the
judgment layer read the same text/images with actual reasoning).

**When reclassifying a rule this way, don't just delete the checker** — move
whatever business knowledge lived in `params`/code into the rule's `notes`
field in the JSON, since the judgment layer only ever sees
`rule_id`/`category`/`description`/`notes` (see `judge.py::_build_prompt`),
never `params`. SCH-08's valid POS values, previously in
`params.valid_pos_values`, are now spelled out directly in its `notes` for
exactly this reason — the model has no other way to know what's valid.

## Rule of thumb going forward

If a second point-fix to the same checker doesn't fully close the gap, treat
the *next* failure as evidence about the field, not about the regex. Ask
"is this document field's real-world formatting even consistent enough for
code to pattern-match reliably," before writing patch attempt #3.

## Second confirmed instance: QA-TRANS-02 / QA-DISC-02 (2026-07-28)

Same resolution, a different root cause than SCH-08's inconsistent-layout
problem: the shared `_check_bullet_formatting` regex (duplicated
bullet/number marker, e.g. "1. 1.") flagged a false positive on Reeda's real
TP — "3. 3." on page 61 — that turned out to be a genuine two-column
table-layout artifact (the Goal Name column's "3." and the Mastery Criteria
column's "3." for the same row, landing textually adjacent because that
row's own descriptive text spilled onto the next page), not a leftover
copy-paste duplicate. The two cases are structurally identical in the
extracted text — nothing distinguishes "same number labeling two different
table columns for one row" from "an actually duplicated marker" without
seeing the page layout itself, which a text-only regex fundamentally can't.
Reclassified both rules to `judgment` rather than attempting a regex fix;
`_check_bullet_formatting`/`_find_repeated_bullet_markers` were deleted
outright rather than left unused, since nothing referenced them anymore.

Also worth flagging as its own lesson, independent of the false-positive
question: the two rules shared **one** checker that searched the entire
document's `full_text`, with no scoping to each rule's own actual section.
That meant a single artifact anywhere (here, in the Transition Plan section)
failed *both* QA-TRANS-02 and QA-DISC-02 together — confirmed directly:
Discharge Criteria's own section (Reeda's TP, pages 63-64) had zero matches
and would have passed cleanly on its own. If a future deterministic checker
is shared across more than one rule, make sure it's actually scoped to what
each rule is supposed to be checking, not the whole document by default.
