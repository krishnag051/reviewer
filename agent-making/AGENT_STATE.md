# Agent State — TP Rule-Engine POC

## 🛑 HARD RULE (2026-07-31, permanent, effective immediately) — NO REAL API CALLS WITHOUT EXPLICIT PER-INSTANCE PERMISSION

> Hard rule, effective immediately and permanent: no real API calls without my explicit, per-instance permission
>
> Real Anthropic API credits are being spent by a paying account, and the last round's full real-content backend test suite (multiple files, real agent calls per test case, self-consistency doubling/tripling each one) burned a large amount of money without that cost being visible or approved in advance. That cannot happen again.
>
> Going forward:
>
> Never run anything that makes a real call to the Anthropic API — not a live document review, not a "real content" test file, not a diagnostic probe, not a background verification pass — without stopping first and telling me exactly what you want to run and why, including your best estimate of how many calls/how much it will cost. Wait for explicit approval before running it.
> If a task seems to need real-API verification to be considered "done," don't run it yourself. Tell me the exact command to run, and I will run it myself, or explicitly tell you to proceed. Default to reporting code as complete-but-unverified-against-real-API rather than spending money to verify it without asking.
> Mock/synthetic tests, tsc, linters, and anything that costs nothing stay exactly as encouraged as before — this rule is only about real Anthropic API spend, not about testing rigor in general. Keep doing thorough non-live verification; just stop short of the real-API step and ask.

This is exactly the mistake this document's own §5 (ground-truth harness) already warned about cost-wise ("the judgment tier costs real money... should be run periodically... not on every change") — this rule tightens that from "use judgment, but be careful" to "never without asking first, no exceptions." Applies to every real call this repo can make: `run_full_pipeline`, `pipeline/api.py::review_treatment_plan`, the judgment-tier ground-truth tests, `test.py`'s own credential check, all of it. See the identical copy of this rule in the root `CLAUDE.md`, `agent-making/INTEGRATION_PLAN.md`, and `frontend/FRONTEND_STATE.md`.

**Structural guardrail (2026-07-31, Round 44 — enforced on the backend side of the seam, not here).** The backend's test suite (`backend/tests/conftest.py::_block_real_api_calls`) now patches out `app.rule_engine.client.review_treatment_plan` — the exact import of this repo's `pipeline/api.py::review_treatment_plan` that `client.py` calls into — for every backend test by default, so no backend test can reach this repo's real pipeline (and therefore the real Anthropic API) at all, regardless of which test file runs. The one opt-out is `@pytest.mark.real_api` on a specific backend test, which still requires this same hard rule's explicit per-instance approval before use — the marker existing is not permission. This repo (`agent-making/`) has no test suite of its own that calls the real API unguarded today, but if one is ever added here, it should get the identical treatment (patch `review_treatment_plan` or whatever the real call site is, autouse, opt-out via marker) rather than relying on anyone remembering to check fixtures first — see `backend/tests/test_real_api_guardrail.py` for the pattern.

**Hard spend ceiling (2026-07-31, Round 45, also enforced backend-side) + standing policy (Round 47).** `backend/tests/conftest.py`'s `MAX_REAL_API_CALLS_PER_SESSION` (default 4, env-overridable) caps total real calls across a whole pytest session, counted in raw Anthropic API requests (not per-`review_treatment_plan`-invocation — one document review is itself 2+ real calls via this repo's own self-consistency pass). Once hit, any further real call in that session is blocked before the request goes out, same as the guardrail above. **This is permanent, standing policy, not specific to the round that built it: every real-API test run, no matter how small, must run under the active session spend ceiling, with the exact command, call count, and cost estimate stated and approved before execution — every future round, no exceptions.** If a real-call-making test or script is ever added directly to this repo (`agent-making/`) rather than only reached via the backend, it must get the identical ceiling treatment, not just the guardrail's block/opt-out marker.

---

Cold-start reference for this standalone agent. Written 2026-07-28. If
you're a future Claude Code session (or a human) picking this up with no
memory of how it got here, this document is meant to be enough on its own —
you shouldn't need prior chat history to understand what's built, what
isn't, and what's still shaky.

This document describes **only** `agent-making/` — a standalone rule-engine
POC. It is a sandboxed prototype, deliberately separate from the main
`backend`/`frontend` repo this sits alongside (see the root `CLAUDE.md` for
that other project's invariants — they do not apply here).

Tone note: this is written to be accurate, not to look good. Where
something is half-built, still wrong, or hasn't been tested against real
evidence, it says so plainly.

---

## 1. Architecture — how a document flows through the system today

Entry point: `pipeline.run_full_pipeline(pdf_path, rules, tracker=None)` in
`pipeline/__init__.py`. This is the one function that runs the whole
sequence below and is what `app.py` (the Streamlit UI) and every test call.

1. **Extract** — `pipeline/extract.py::extract_pdf_text` pulls raw text
   per page via `pypdf`.
2. **Flag image-only pages** — `pipeline/flag_pages.py::flag_image_only_pages`
   marks pages with little/no extractable text (likely embedded
   images/graphs) so they get rendered as images later instead of relying
   on empty text.
3. **Render flagged pages** — `pipeline/render.py::render_flagged_pages`
   turns those specific pages into PNGs (via `fitz`/PyMuPDF) so the
   judgment layer's vision input can see them.
4. **Extract structured fields** — `pipeline/fields.py::extract_fields`
   builds a flat dict (`pages`, `full_text`, `plan_type`, `payor`, etc.)
   that every checker reads from. Plan type (Initial vs. Reassessment) and
   payor are detected here from page-1 text (`_detect_plan_type`,
   `_detect_payor` — see `KNOWN_PAYORS` for the payor name-matching table).
5. **Scope filter** — `fields.py::partition_rules_by_scope` splits rules
   into ones applicable to this TP's detected plan type/payor vs. ones that
   come back `not_applicable` (a real out-of-scope determination) or
   `not_checkable` (payor detection failed, so applicability itself is
   unknown — these are NOT treated the same).
6. **Deterministic checks** — `fields.py::run_deterministic_checks` runs
   every `check_type: "deterministic"` rule through its checker function in
   the `DET_CHECKS` dict (see §2 for current coverage). Each checker
   returns `(result, evidence, page, confidence)`.
7. **Escalation** — any deterministic finding that came back
   `not_checkable`/`uncertain`, or with confidence below
   `ESCALATION_CONFIDENCE_THRESHOLD` (0.6), gets a second look from the
   judgment layer in the same call (it has rendered images and can reason
   about ambiguous text; a regex can't). `fields.py::needs_escalation`
   decides this. When an escalated rule's judgment result comes back with a
   plain-string evidence form and the deterministic layer had its own
   computed page number, that det-layer page wins over judgment's
   re-derived one (`pipeline/__init__.py`, confirmed live once against a
   real off-by-one — see the code comment there for the specific case).
8. **Judgment layer** — `pipeline/judge.py::run_judgment_checks` is the
   **production path**: it calls `_run_judgment_checks_once` (one real
   `claude-sonnet-5` call, tool-forced structured output via the
   `record_findings` tool, `thinking` disabled) **exactly twice** with
   identical input, then `_reconcile_consistency_check` compares the two —
   agreement keeps the result, disagreement downgrades to `"uncertain"`
   rather than silently picking one. This 2-call self-consistency check is
   the actual current production behavior for every judgment rule.
9. **Scoped 3-way majority vote (built, NOT wired into production)** —
   `judge.py::run_judgment_checks_majority_vote` makes 3 calls instead of 2
   and takes a 2-of-3 majority (unanimous disagreement still falls back to
   `"uncertain"`). `judge.MAJORITY_VOTE_RULE_IDS` is a small, explicitly
   tracked allow-list of rule_ids with *confirmed* real self-consistency
   instability across rounds — currently `QA-GIP-06`, `QA-HRS-07`,
   `QA-HRS-09`, `QA-GIP-07`, `QA-PROB-01` (see the comment above that set in
   `judge.py` for the specific evidence behind each one).
   `judge.should_use_majority_vote(rule_id)` exists as a lookup helper, but
   **nothing in the actual pipeline calls it yet** — `run_full_pipeline`
   still runs every judgment rule through the plain 2-call path,
   `MAJORITY_VOTE_RULE_IDS` included. Wiring this in is a deliberate,
   not-yet-made decision (real, permanent 1.5x cost increase for the rules
   on the list).
10. **Integrity check** — `pipeline/integrity.py::run_judgment_with_integrity_check`
    diffs the rule_ids the judgment layer was asked about against what it
    actually returned. A missing rule_id triggers a retry (up to
    `max_retries`, default 2) for just the missing subset; if gaps remain
    after retrying, this raises `IntegrityError` — a hard failure, never
    silently swallowed.
11. **Merge** — `pipeline/merge.py::merge_findings` combines det + judgment
    results into one `findings` dict, an `export_rows` list (the CSV/table
    shape — one row per rule_id, or one row per page for multi-page
    findings), and two actionable-item lists split by `action_lane`:
    `bcba_fix` and `facilitator_assign` (both only include rules whose
    result is `fail` or `uncertain` — see `NEEDS_ACTION_RESULTS`).

Cost tracking: `pipeline/call_tracker.py::ApiCallTracker` — pass one shared
instance through any multi-call script (a probe, a batch run) and it
counts every real API call, checks a hard cap before each one
(`ApiCallCapExceeded`), and computes real cost from actual token usage
(`PRICING_PER_MTOK`, kept in sync with `judge.MODEL`'s current pricing —
currently `claude-sonnet-5` intro pricing through 2026-08-31, must be
updated by hand if that changes).

---

## 2. Rule coverage

**120 total rules** in `rules/rules.json` (the single source of truth —
never hand-duplicated elsewhere). Of those:

- **51 labeled `check_type: "deterministic"`**, but only **35 have a real
  checker function** registered in `fields.DET_CHECKS`. The other 16
  (`QA-ACF-01`, `QA-COC-03`, `QA-COC-05`, `QA-GIP-13`, `QA-HRS-08`,
  `QA-MAST-01`, `QA-MAST-02`, `QA-RPT-04`, `QA-RPT-05`, `QA-SCH-01`,
  `QA-SCH-03`, `QA-SCH-05`, `QA-SCH-06`, `QA-SCH-07`, `QA-SIG-06`,
  `EMP-02`) are **deliberately left unbuilt** — each blocked on something
  concrete (backend-stored prior-TP data, an unconfirmed document field, a
  CPT billing reference table that doesn't exist yet, or schedule-table
  parsing too fragile for `pypdf`'s raw text to be trusted without much
  more engineering). Each carries its own `blocked_status` note explaining
  why. `tests/test_gip10_acf07_mislabeled_deterministic.py` pins this exact
  set — it fails loudly if the count drifts without a deliberate update.
- **69 are `check_type: "judgment"`** (fully model-driven, no code
  checker). Of these:
  - **9 have a concrete, real-evidence-grounded example** in their notes
    (`QA-HRS-07`, `QA-PROB-01`, `QA-PAR-01`, `QA-TRANS-01`, `QA-TRANS-02`,
    `QA-DISC-02`, `QA-BIP-05`, `QA-GIP-11`, `QA-GIP-17`).
  - **18 got a concrete example written in this round** (`QA-BIO-08`,
    `QA-BIO-09`, `QA-OBS-02`, `QA-OBS-04`, `QA-ACF-06`, `QA-CI-01`,
    `QA-BAR-01`, `QA-BIP-04`, `QA-BIP-06`, `QA-PREF-01`, `QA-GIP-08`,
    `QA-GIP-09`, `QA-GIP-12`, `QA-COC-01`, `QA-COC-06`, `QA-DISC-01`,
    `QA-SIG-01`, `QA-SIG-05`) — these were "Quick" per a full backlog
    triage: constructable from the rule's own logic or already-known real
    document text, no new live document check needed.
  - **~19 remain description-only, classified "needs a real document
    reference"** before a good example can responsibly be written —
    notably `QA-GIP-06` (a confirmed real miss on both test documents,
    still no example) and `QA-GIP-14` (literally named in the original
    build scope as "the canonical LLM-judgment example," still doesn't
    have one). Not guessed at; left for a future round.
  - **1 is genuinely unclear**, not a documentation gap: `QA-PROB-03`, whose
    own notes already say *"Hardest rule in the whole checklist... expect
    frequent Uncertain"* — this needs a real answer from Ms. Yachnes or
    Mr. Ungar, not an invented example.
  - The rest are GAP/out-of-scope (need data this POC doesn't have — a
    prior TP version, a session-notes upload, Central Reach integration,
    an unresolved pre-upload field) or already have an adequate decision
    rule in their notes even without a worked example (e.g. `QA-SCH-08`,
    `QA-OBS-03`, `QA-BIP-02`).

**Payors**: 9 official payors per the locked project scope
(`Project1_Full_Build_Scope.docx`) — Healthfirst, Aetna, Anthem, Cigna,
Emblem, Empire, Molina, MVP, Straight Medicaid — plus New York Medicaid as
a real, working bonus payor outside that official 9. Payor-specific rules:
Healthfirst (`HF-01`, `HF-02`, `HF-03`), Straight Medicaid (`SM-01`,
`SM-02`), Empire (`EMP-01`, `EMP-02` — unbuilt, scope ambiguity, see its
`blocked_status`, `EMP-03`), Emblem (`EMB-01`), Aetna (`AET-01`). Anthem,
Cigna, Molina, MVP, and New York Medicaid have **no** payor-specific rules
— confirmed zero diff against the reference checklist, universal rules
only. `rules/generate_payor_rules.py` regenerates each payor's reference
export (`rules/*.json`) from `rules.json` — **never hand-edit those
exports**, edit `rules.json` and re-run the script. Healthfirst has no
generated export file (the master `rules.json` already reads naturally
payor-agnostic for it — see the script's own docstring).

**Archived**: `rules/archive/learning_tree_deprecated_rules.json` — rules
built around comparing against "the Learning Tree" (a prior-system
reference), retired per Section 14 of the build doc once that comparison
was confirmed out of scope; one of them (`QA-ACF-05`) was later restored
and rebuilt as a real blank-field presence check unrelated to the retired
Learning-Tree logic.

---

## 3. Known limitations — stated plainly

- **Judgment-layer non-determinism is mitigated, not solved.** The 2-call
  self-consistency check catches *some* disagreement and downgrades to
  `"uncertain"` rather than confidently guessing — but it's still a coin
  flip on borderline cases, confirmed live, more than once, on the exact
  same document with zero code change in between (`QA-GIP-06` and
  `QA-PROB-01` both flipped between `"fail"` and `"uncertain"` across
  reruns this engagement). The scoped majority-vote list (§1, item 9)
  measurably improves catch rate on the 5 rule_ids it's built for, but
  isn't wired into production, and doesn't eliminate the underlying
  problem — it narrows it for 5 out of 69 judgment rules.
- **Confirmed-wrong rules, currently open, not resolved:**
  - `QA-BIP-05` (Reeda) — comes back `pass` under every fix attempted so
    far (a notes rewrite, a system-level "lean toward flagging" posture
    instruction, and a two-stage extract-then-judge split). No confirmed
    mechanism for why it should fail at all — may be a genuinely
    subjective clinical call this system can't independently verify from
    text alone, not necessarily a bug.
  - `QA-PAR-01` (Charny) — same story. A two-stage extraction actually
    surfaced that an earlier round's own manual evidence-gathering may
    have been *wrong* (found only 1 current Parent/Caregiver Goal via an
    incomplete grep; a fuller extraction found 3, which would actually
    satisfy the rule). Whether this is still a real miss or whether the
    original "confirmed fail" premise itself needs re-checking against
    Ms. Yachnes's own stated reason is genuinely unresolved. Deliberately
    excluded from the ground-truth harness's asserted answers rather than
    guessed at either way.
  - `QA-BIO-16` — investigated and reclassified as an **accepted
    limitation, not a bug**: neither real test document shows a
    self-contained TP-text contradiction for "school name matches Central
    Reach" (Reeda's shows a normal past-vs-current school transition
    narrative; Charny's `N/A` field is plausibly correct given she
    "recently graduated"). A human reviewer with real Central Reach access
    could still catch a genuine mismatch invisible from the TP text alone
    — this is a real, structural gap this POC cannot close without that
    integration, not something to force a fake fix for.
- **Ground truth exists for exactly 2 real documents — Reeda Bint
  Shaheen's TP and Charny Gluck's TP.** Both are **Reassessment** plan
  types. **No Initial-type TP has ever been tested against this system.**
  **No Healthfirst-payor document has ever been tested** — meaning
  `HF-01`/`HF-02`/`HF-03` have never been verified against a real document
  that would actually trigger them (both real documents are NY
  Medicaid/Molina). Any confidence claimed about this system's accuracy is
  scoped to these two documents and this one plan type — it has not been
  validated more broadly than that.
- **Fixes for one document can quietly regress another, or regress
  silently over time with no code change at all** — two confirmed
  instances:
  - `QA-TEMP-04`: this rule's *judgment-only* behavior (no DET checker was
    ever built for it) narrowed over time to only recognizing
    email-header-style text, missing the actually-dominant real pattern
    (an embedded reviewer comment/question left in running narrative text)
    entirely — even though that same pattern was the real fix for THREE
    other rules this engagement (`QA-HRS-06`, `QA-TRANS-01`,
    `QA-ACF-07`'s Vineland question). No git history survives to prove the
    exact mechanism (this directory has no version control of its own,
    and no prior live-run transcript was preserved) — this is the
    best-evidenced candidate cause, not a proven one. Now converted to a
    real deterministic checker specifically to stop this from silently
    narrowing again, with a locked-in regression test using the real
    confirmed document text.
  - `QA-GIP-14`: named in the *original build scope itself* as "the
    canonical LLM-judgment example" — and still has no concrete example in
    its notes to this day. A rule can sit unaddressed indefinitely even
    while being explicitly called out as the flagship case, if nothing
    forces a revisit.
  - **The structural lesson**: any rule living purely in the judgment
    layer's notes, with no deterministic checker and no locked-in
    regression test, can silently drift in behavior between rounds with
    no signal that anything changed. The ground-truth harness (§4) is the
    only thing currently standing between "silent drift" and "caught
    immediately."
- **Overfitting risk to the 2 known documents** — audited explicitly.
  Confirmed narrow/document-specific patterns still in the codebase:
  `QA-HRS-06`'s reviewer-annotation regex includes two literal phrases
  lifted verbatim from Reeda's document ("Verifying", "Change if
  increasing") that won't generalize to a differently-worded document's
  margin notes; `QA-TEMP-04`'s new detector's imperative-verb whitelist
  (`reword`/`clarify`/`specify`/`update`/`add`) and its "please note"
  boilerplate exclusion are similarly tuned to these two documents' exact
  phrasing; `QA-PPI-03`'s name-extraction regex assumes one of exactly two
  confirmed field-order variants. None of these were fixed — they're
  flagged as real, known exposure ahead of more documents arriving, not
  quietly left unflagged.

---

## 4. What's NOT built at all

The rule-checking layer described above works reasonably well against the
2 documents it's been tested against. That is **not** the same as "V1 is
done." Per the locked project scope, the following are specified and
**none of it is built**:

- **Two-lane output routing with tags** — the `bcba_fix`/`facilitator_assign`
  split exists in `merge.py`'s return value, but there is no actual routing
  system, ticketing, or tag-based workflow around it — it's just two lists
  in a dict that `app.py` prints with `st.write()`.
- **Pre-upload metadata cross-check** — the design doc's "6 pre-upload
  fields" concept (patient legal name, DOB, payor, etc. as an independent
  ground-truth source to check the TP's own text against) does not exist
  anywhere in this codebase. Every "internal consistency" checker built so
  far (`QA-PPI-02`, `QA-PPI-03`, `QA-PPI-05`, etc.) checks the TP against
  *itself*, not against this external reference — several rules' own notes
  say as much (e.g. `QA-PPI-03`: "True 'correct' validation needs legal
  name added as a pre-upload ground-truth field, not currently one of the
  6").
- **Weekly schedule grid** — no structured parsing or validation of the
  School/ABA weekly schedule table exists; it's read as raw extracted text
  like everything else, and multiple schedule-related rules
  (`QA-SCH-01/03/05/06/07`, `QA-GIP-02`) are unbuilt specifically because
  this table's real-world layout in `pypdf` extraction is too unreliable to
  trust without dedicated table-parsing work never done here.
- **Rules Studio admin UI** — there is no interface for editing rules,
  viewing rule history, or managing payor-specific overrides. All rule
  authoring happens by hand-editing `rules.json` directly.
- **Facilitator messaging feature** — no notification, messaging, or
  communication feature of any kind exists. The `facilitator_assign` list
  is data, not a message.

Say this plainly: the rule engine's *judgment quality* is the only thing
that has had serious investment. Everything about *turning that judgment
into a working product* — routing, messaging, an admin UI, a real metadata
cross-check, real schedule-table parsing — has not been started.

**Update, 2026-08-02 (Round 51, backend-side only):** the backend now
requires and stores a second, mandatory file per upload — the "supporting
document" (`uploads.supporting_document_path`, `GET /uploads/:id/
supporting-file`) — which is exactly the kind of external ground-truth
source the "pre-upload metadata cross-check" bullet above describes
needing. **This repo (agent-making) does not read it, know about it, or
consume it in any way.** `review_treatment_plan(pdf_path, ...)` still takes
only the TP's own file path — nothing has changed here. The backend's file
is display-only (opened in a new browser tab by a reviewer), never passed
into this pipeline. If/when extraction or sub-agent consumption of this
document is built, it will need its own explicit wiring into this repo's
`review_treatment_plan` signature or a new entry point — not assumed to
already exist because the file is now stored somewhere.

---

## 5. The ground-truth regression harness

`tests/test_regression_ground_truth.py` + fixtures in `tests/conftest.py`
(`reeda_tp_pdf`, `charny_tp_pdf` — point at the real PDFs' external
location, deliberately NOT committed into this repo since they contain
real, unredacted PHI; they skip, not fail, if the files aren't present on
the machine running the suite).

- **Deterministic tier** (`DET_GROUND_TRUTH`, currently 12 rule_ids ×
  2 documents = 24 assertions): calls each `DET_CHECKS` function directly
  against extracted fields. **Free, zero API cost, runs as part of the
  normal fast test suite every time.** This tier grows every time a rule
  moves from judgment to deterministic — that's a deliberate, explicit
  goal, not incidental.
- **Judgment tier** (`REEDA_JUDGMENT_GROUND_TRUTH`,
  `CHARNY_JUDGMENT_GROUND_TRUTH`): runs the real `run_full_pipeline`
  against the real documents, scoped to just the rule_ids with confirmed
  ground truth (not all 120 rules). **Costs a real, billed API call-batch
  per document every time it runs** — order of $0.05–$0.15 per document at
  current Sonnet 5 pricing. Skipped automatically
  (`@pytest.mark.skipif`) when `ANTHROPIC_API_KEY`/`ANTHROPIC_AUTH_TOKEN`
  isn't set.
- **Deliberately excluded, not silently omitted**: `QA-BIP-05`,
  `QA-PAR-01`, `QA-BIO-16` — see `DISPUTED_NOT_SEEDED` in the test file and
  §3 above for why each is unresolved rather than asserted either way.

**This harness should be treated as a mandatory gate, not a spot-check.**
Before reporting any rule change as complete: run the full non-live suite
(which includes the free deterministic-tier ground-truth assertions) —
`python -m pytest tests/ -k "not integrity_check_passes and not
regressed_since_baseline and not test_reeda_judgment_ground_truth and not
test_charny_judgment_ground_truth"` — and confirm nothing that was
previously passing broke as a side effect. The judgment tier costs real
money and should be run periodically (before a release, or after any
change touching `judge.py`'s prompt or a judgment rule's notes), not on
every change — but if it hasn't been re-run live in the current round,
say so explicitly rather than assuming it's still clean. It has already
caught a real, previously-invisible regression once (three rules
previously reported "fixed" turned out to still be broken the first time
this harness was actually run against them) — that is exactly the failure
mode it exists to catch.
