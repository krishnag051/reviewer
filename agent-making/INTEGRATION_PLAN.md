# Front-End/Back-End Integration Plan

Proposal only — no code has been written against this yet. Nothing in
`agent-making/` is modified by this plan; the hard requirement going in is
that `agent-making/` stays completely standalone, called into from outside
via a stable wrapper, never modified or restructured to accommodate the
front end/back end.

---

## ⚠️ OPEN QUESTION — UNRESOLVED, BLOCKING before the wrapper's input side is built

**Should the wrapper accept an optional `payor`/`plan_type` override for
when detection comes back `"Unknown"`?**

The current pipeline auto-detects both payor and plan type from the
document's own page-1 text (`fields.py::_detect_payor`,
`_detect_plan_type`) — there's no existing input for either today, and the
proposed wrapper signature below doesn't take them as parameters either.
But detection can fail (`"Unknown"` payor, `None` plan type), and when it
does, whether the wrapper should let a caller supply a manual override is
a real product decision, not something to default silently one way or the
other. **Not answered in this document — needs a real answer before the
wrapper's input side is finalized.**

---

## 🐛 SEPARATE, ALREADY-EXISTING GAP — worth fixing on its own, independent of this integration

**Bad/corrupt PDF paths and exhausted judgment-layer retries currently
raise uncaught exceptions, with nothing in the pipeline catching them.**

Today, if `pdf_path` doesn't exist or isn't a valid PDF, `pypdf` raises a
raw parse error (or `FileNotFoundError`) that propagates all the way up —
nothing in `pipeline/__init__.py`, `extract.py`, or anywhere else catches
it. Same for `pipeline/integrity.py::IntegrityError` once retries are
exhausted, and for `pipeline/call_tracker.py::ApiCallCapExceeded`. Right
now the only consumer is `app.py`'s Streamlit UI, which happens to only
explicitly catch `IntegrityError` around its one call site — a bad file
upload today would surface as a raw Streamlit stack trace, not a
handled error state.

This is a real gap in the pipeline itself, not something introduced by the
integration work — it should be fixed regardless of whether or when
front-end/back-end work actually starts. It's called out again below
because the wrapper interface's `error` field depends on it being fixed
(or the wrapper doing the catching itself, per the discussion below).

---

## ⭐ RELIABILITY PRIORITIES — noted now, not yet built, do not lose before real backend work starts

**"Finalize as V[n]" must be the single most reliable operation in the
whole system.** It is the one action that turns a disposable draft into a
permanent record (see the frontend's `finalizeAttempt` and the
project-level invariant that finalize is irreversible) — once real backend
wiring exists, this write must always succeed and be durably saved, even
in states where other, lower-stakes actions (Generate Correction Email,
the mock "Send for Correction" draft action added on the frontend, etc.)
fail outright or aren't fully wired up yet. Finalize should not share a
failure mode with those actions, and should not be blocked or made
flaky by any of them being broken, slow, or unimplemented. This has no
code implication yet — mock frontend state has no real persistence to be
reliable about — but it needs to be a hard design constraint (transaction
boundaries, retry/idempotency, error isolation from secondary actions) by
the time the real wrapper/backend integration in this document is built.

---

## 📐 FRONTEND REALITY CHECK — updated 2026-07-30, read before trusting §1's async proposal

This document was originally written before the frontend had any real
concept of a draft vs. a finalized record, and before the backend's own
upload/job model had been walked through in detail (Step 1 exploration).
Both now exist. This section reconciles what's below against that current
reality — nothing below is redesigned, this just flags what's now stale or
needs a real decision before backend wiring starts. Full detail on the
frontend side: `frontend/FRONTEND_STATE.md`. Full detail on the backend
side: `docs/BACKEND_IMPLEMENTATION_SUMMARY.md`.

- **The backend already has a real version of the exact shape §1's
  "Progress/status for a long-running check" proposes as a
  not-yet-built job pattern — it isn't hypothetical.** `uploads.status`
  (`processing` → `ready`/`error`), driven by
  `app/services/upload_pipeline.py::run_upload_pipeline` as a FastAPI
  `BackgroundTask`, is already exactly "submit → job_id (the upload row) →
  poll(job_id) → status." The wrapper proposed in §1 doesn't need to invent
  its own job/poll abstraction — it needs to be callable from *inside* that
  existing `BackgroundTask`, in the same slot where `rule_engine.run_rule_checks`
  (the deliberately hollow stub — see root `CLAUDE.md`) is called today.
- **The frontend's mock U/V draft model maps reasonably well onto the
  backend's real `versions`(`in_progress`/`finalized`)/`uploads`
  (`processing`/`ready`/`error`, `upload_number` sequential per version)
  tables** — a frontend `UAttempt` ≈ a backend `upload` row, a frontend
  `PlanVersion` ≈ a backend `versions` row once `status="finalized"`. But
  one real mismatch to resolve, not just a naming difference: **the
  backend creates the `versions` row — with a real, already-assigned
  `version_number` — up front, in `in_progress` status, before the first
  upload even happens.** The frontend today does the opposite: it creates
  no version-shaped record at all until finalize; the "V0" label used for
  a not-yet-finalized first slot (see `FRONTEND_STATE.md` §1) is a pure UI
  string with nothing backing it. Once wired to the real backend, that
  slot will already have a real `version_number` (e.g. `1`) the moment the
  first upload happens — the frontend's locally-computed "next slot is
  `versions.length + 1`" logic and its "V0" convention will both need to
  be replaced by reading the real in-progress version's assigned number
  from the backend, not deriving it client-side.
- **Siblings-on-finalize: the frontend's speculative "should probably be
  soft-retained later" note is now confirmed correct, not just a guess.**
  The backend's real `finalize_upload` sets non-chosen sibling uploads'
  `purge_after` rather than deleting them — matching `CLAUDE.md`'s
  "no hard deletes" invariant. The frontend's current mock behavior
  (`finalizeAttempt` in `tp-context.tsx` drops every sibling `UAttempt`
  outright) is a mock-only simplification that should NOT carry over
  as-is when this connects to the real backend.
- **One real, unresolved tension, flagged here rather than silently
  decided either way:** the frontend has a confirmed product decision that
  overrides are **V-only** — a draft `UAttempt` gets no override
  affordance anywhere in the UI (see `FRONTEND_STATE.md` §1 and §2). The
  real backend's `override_rule_result` does **not** enforce that — it
  allows overriding a `rule_result` on any upload, finalized or not, and
  only *conditionally* recomputes the parent version's score if that
  particular upload happens to already be the finalized one. Which
  behavior is actually correct for the real product — restrict override to
  finalized versions only (matching the frontend's current decision,
  requiring a backend-side guard that doesn't exist today), or allow it on
  drafts too (matching the backend's current behavior, requiring the
  frontend's override UI to be extended to drafts) — is a real product
  decision that needs to be made before wiring this up, not something to
  quietly pick one way just because one side happens to already do it.

---

## 1. The interface contract

**Where it would live**: a new file, `agent-making/agent/pipeline/api.py`
— additive only, nothing inside `agent-making/` gets modified to build
this.

**Signature**:
```python
def review_treatment_plan(pdf_path: str) -> ReviewResult
```

No `payor`/`plan_type` input in this proposed signature — the pipeline
already auto-detects both from the document's own text
(`fields.py::_detect_payor`/`_detect_plan_type`) and scopes rules
internally via `partition_rules_by_scope`. Callers currently pass the
*full* `rules.json` (120 rules, all payors) into `run_full_pipeline`
regardless of payor — the payor-specific export files (`aetna.json`, etc.)
are reference copies for humans, not something the pipeline itself
consumes. So there's nothing for the wrapper to take as a payor input; it
detects it, and detection becomes an output, not an input. (See the open
question at the top of this document — this is exactly the design tension
that raises.)

**Return shape** (`ReviewResult`, JSON-serializable):
```python
{
  "schema_version": "1.0",
  "status": "complete" | "failed",
  "detected_payor": str,              # or "Unknown"
  "detected_plan_type": str | None,   # "Initial" | "Reassessment" | None
  "findings": [
    {"rule_id": str, "category": str, "result": str, "page": int | str | None,
     "detail": str, "confidence": float, "action_lane": str | None, "action_tag": str | None}
    # ... one row per rule, or per page for multi-page findings
  ],
  "summary": {
    "bcba_fix_rule_ids": [str, ...],
    "facilitator_assign_rule_ids": [str, ...],
    "counts_by_result": {"pass": int, "fail": int, "uncertain": int, "not_applicable": int, "not_checkable": int},
  },
  "usage": {
    "api_calls": int, "input_tokens": int, "output_tokens": int, "estimated_cost_usd": float,
  },
  "error": null | {"code": str, "message": str},
}
```

`findings` is essentially `merge.py`'s existing `export_rows` shape —
already close to right, kept rather than inventing something new. Added
beyond what exists today:

- **`usage`** — currently the caller has to construct an
  `ApiCallTracker` itself and read `.count`/`.estimated_cost()` off it
  after the fact. The wrapper should own tracker construction internally
  and surface the numbers directly — a front end shouldn't need to import
  a pipeline-internal class to get cost data.
- **`error`** — today, a bad/corrupt PDF path just raises a raw exception
  with nothing catching it anywhere in the pipeline (see the gap flagged
  above). The wrapper needs to catch known failure modes (bad file,
  `IntegrityError` from `integrity.py` after retries exhausted,
  `ApiCallCapExceeded`) and translate them into this structured shape
  instead of a stack trace reaching the front end.
- **`schema_version`** — so the front end can defensively check it rather
  than discover a breaking change at parse time.

**Progress/status for a long-running check**: a real gap, not just a
nice-to-have. The pipeline runs synchronously start-to-finish with no
incremental signal — `app.py` just shows a blocking `st.spinner`. A real
document with several escalations can mean 5-10+ live API calls, likely
10-60+ seconds. A synchronous HTTP request that just hangs for a minute is
a bad shape for a real product. Proposal: the wrapper should support two
calling modes — a synchronous one (fine for a background job worker), and,
for the web-facing path, a job pattern (`submit → job_id`, then
`poll(job_id) → status`) — but that's a backend design decision, not
something to bake into `review_treatment_plan`'s own signature. The
function itself should stay simple and synchronous; whatever calls it from
the backend decides whether to run it inline or hand it to a worker queue.
**Update, 2026-07-30: this "job pattern" already exists on the backend,
not just as a future decision** — see the reality-check section above.
`uploads.status` (`processing`/`ready`/`error`) via
`run_upload_pipeline`'s `BackgroundTask` is that job/poll unit already
built; the wrapper just needs to slot into it where the current hollow
`rule_engine.run_rule_checks` stub is called.

## 2. Where the boundary actually is today

`pipeline.run_full_pipeline` (in `pipeline/__init__.py`) is the real entry
point. Confirmed: `app.py` is genuinely clean — 101 lines, calls
`run_full_pipeline` exactly once, and everything after that is
`st.dataframe`/`st.metric`/`st.write` rendering the returned dict. **No
business logic is embedded in Streamlit widget code** — nothing needs to
be pulled out of the UI layer.

The one place separation isn't fully clean *for an external caller* (not a
UI-coupling problem, a convenience-boundary problem): `run_full_pipeline`
requires the caller to (a) already have loaded `rules.json` into memory
and pass it in, and (b) know to construct and inspect a
`pipeline.call_tracker.ApiCallTracker` to get cost data back out. Both are
pipeline-internal implementation details a front-end/backend integration
shouldn't need to know about.

**Smallest fix**: the one new `pipeline/api.py` file described above — it
loads `rules.json` internally, owns the tracker, calls
`run_full_pipeline`, catches exceptions, and shapes the result. Zero
changes to `pipeline/__init__.py`, `fields.py`, `judge.py`, `merge.py`, or
`rules.json` itself.

## 3. Safe vs. risky changes

**Safe — invisible to the wrapper, no coordination needed**: `rules.json`
content changes (rule count, notes rewrites, new rules), new payor
additions (a new `KNOWN_PAYORS` entry), `judge.py` prompt rewrites, new
deterministic checkers or `check_type` flips, escalation-threshold tuning,
wiring the majority-vote list into production. All of this is exactly the
kind of change this engagement has been making every round — none of it
touches `review_treatment_plan`'s signature or return shape.

**Risky — a deliberate version bump, not a silent shift**: any change to
`review_treatment_plan`'s parameters; any change to the *shape* of the
returned dict (renamed/removed/retyped keys, `findings` restructured from
a list to something else); any change to the set of possible `result`
values (`pass`/`fail`/`uncertain`/`not_applicable`/`not_checkable`) if the
front end renders each one specifically; any change to `error` shape
semantics. `schema_version` exists specifically so these are never silent.

## 4. What the front-end/backend side needs to bring

- **Upload handling**: accept a PDF upload, land it somewhere
  `review_treatment_plan(pdf_path)` can read a real file path from. Needs
  a real decision on temp-file lifecycle — delete after processing, or
  retain for re-review?
- **Async/job handling**: given real run times, a background-job pattern
  (queue + poll or webhook) rather than a blocking request, per the
  progress note above. **Already built**, not still to design — see the
  reality-check section above: `uploads.status` +
  `run_upload_pipeline`'s `BackgroundTask` is this pattern today.
- **Where results get stored**: a DB-design question that belongs
  entirely on that side — but the `findings` shape above is normalized
  enough (rule_id/category/result/page/detail/confidence/action_lane) to
  map directly onto a table without reaching back into `agent-making/`
  internals.
- **PHI handling**: uploaded documents are real, unredacted patient data
  (same caution already flagged in `AGENT_STATE.md` for the two test
  documents) — retention policy, encryption at rest, and access control
  are real requirements for whoever owns storage, not something
  `agent-making` handles today.
- **Credentials**: `ANTHROPIC_API_KEY` needs to live on the backend
  process that calls the wrapper — never exposed to the front end.
- **Cost/rate policy**: each review costs real money; a per-org budget cap
  or rate limit is a backend policy decision. `pipeline.call_tracker`'s
  cap mechanism (`ApiCallCapExceeded`) could be exposed as a configurable
  ceiling per call, but the actual business policy (who gets how much
  budget) doesn't belong in `agent-making`.

No code changes have been made against this plan — it is a proposal to
discuss, not something built yet.
