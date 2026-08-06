# TP Review System

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

This applies everywhere in this repo — `backend/`, `frontend/`, and `agent-making/` alike — not just wherever it happened to be violated. See the identical copy of this rule in `agent-making/AGENT_STATE.md`, `agent-making/INTEGRATION_PLAN.md`, and `frontend/FRONTEND_STATE.md`.

**Structural guardrail (2026-07-31, Round 44) — this is enforced, not just remembered.** A round before this one ran two pre-existing backend test files without reading their fixtures first; a shared `_ready_upload()` helper created a real upload and, under `TestClient`, ran the pipeline's background task synchronously — making ~30 real (if pre-flight-rejected) calls to the real Anthropic API. To make that structurally impossible going forward:

- `backend/tests/conftest.py::_block_real_api_calls` is an **autouse** fixture that patches `app.rule_engine.client.review_treatment_plan` — the exact seam `client.py` imports agent-making's real function into — to raise immediately, for **every test in the suite, by default**, before any HTTP request is ever constructed. This isn't "the API key is invalid so the call fails" (that still sends a real request to Anthropic's real servers and gets a real, logged rejection — confirmed that's exactly what happened the round this was written in response to); this is "the Python call site itself never runs," so zero bytes reach Anthropic regardless of which test file runs or whether anyone read its fixtures.
- The **one deliberate escape hatch**: `@pytest.mark.real_api` on a specific test. When present, the autouse fixture stands down entirely for that test. **Never add this marker to a test, or run a test that already has it, without the user's explicit, per-instance approval first** (exact command + call count + cost estimate, same as this rule always requires) — the marker existing is not itself permission.
- Proof this works, and evidence it's actually being enforced every run: `backend/tests/test_real_api_guardrail.py`.

**Hard spend ceiling (2026-07-31, Round 45) — permanent, applies whenever `@pytest.mark.real_api` tests run.** The guardrail above stops an *unmarked* test cold, but a marked, approved test could previously still make more real calls than approved (a longer-than-expected run, a retry, a second real_api test added later) — there was nothing capping total session spend, only per-test approval. This closes that:

- `backend/tests/conftest.py`'s `_real_api_call_counter` is a module-level counter that survives across every real_api test in one pytest session (independent of each test's own monkeypatch teardown). `_block_real_api_calls` wraps whatever the real `review_treatment_plan` currently is — via `_make_ceiling_enforced_real_call` — for every real_api-marked test, so every real call, from any test, counts against the SAME shared total.
- The ceiling is `MAX_REAL_API_CALLS_PER_SESSION`, read from that env var with an explicit default of **4** — never silently absent. Once hit, the next real call in that same pytest session raises immediately, **before** the request goes out — not a warning logged after the fact.
- Counts in units of raw Anthropic API requests (`result["usage"]["api_calls"]`), not "one `review_treatment_plan` invocation" — one document review is itself 2+ real HTTP calls (agent-making's self-consistency pass; confirmed live, Round 45: exactly 2 per document). Counting invocations instead would silently let the ceiling mean half its stated number.
- Prints a running count after every real call (`[real-api-ceiling] real API calls this session: N/MAX`) so spend is visible live in the terminal, not just in a final report.
- Proof: `backend/tests/test_real_api_guardrail.py`'s two ceiling tests — one confirms the (N+1)th call is blocked before the underlying function ever runs, the other confirms the raw-call-count (not invocation-count) accounting specifically.
- To deliberately run more real calls than the default ceiling allows: raise `MAX_REAL_API_CALLS_PER_SESSION` explicitly for that invocation, and only with the user's explicit, per-instance approval for the higher count — same as every other real-API decision this file governs.

**Standing policy (2026-07-31, Round 47) — this ceiling requirement is permanent and applies to every future round, not just the ones that built it.** Every real-API test run, no matter how small, must run under the active session spend ceiling, with the exact command, call count, and cost estimate stated and approved before execution. This applies to all future rounds, not just the round that built the ceiling. Never run a real-API test — even a single named one, even one that's been run before — unbounded or without the ceiling active; the ceiling being present in `conftest.py` is not itself standing permission, the same per-instance approval this whole rule requires is still needed every time.


library, with mandatory human review. Frontend (React) in `/frontend`, backend
(FastAPI + Postgres) in `/backend`. Full blueprint:
`docs/TP_Review_Master_Build_Document.md` — read it before any structural
change, new table, or new route.

Other reference docs in `/docs`, useful for background on *why*, not just
*what*: `TP_Review_Backend_Architecture.md`, `TP_Review_End_to_End_Trial.md`,
`TP_Review_Gap_Analysis.md`. Current build progress: `docs/BUILD_STATUS.md` —
update it at the end of every build-order step.

The backend build (steps 1-11) is complete. For what's actually built and
how it actually behaves — not the plan, the implementation —
see `docs/BACKEND_IMPLEMENTATION_SUMMARY.md`. For the exact seam the future
rule-checking agent repo builds against, see
`docs/AGENT_INTEGRATION_CONTRACT.md`.

## Invariants — never violate these, ever, regardless of what a task seems to ask for

- **Human override is paramount.** Every consumer of a rule result (score,
  audit result, reports, correction email, lists) reads `final_status` /
  `final_finding` / `final_pages` on `rule_results` — never `model_status` /
  `model_finding` / `model_pages`. The model_* columns are written once by the
  pipeline and never updated again, by anyone, for any reason.
- **Finalize (uF) is irreversible.** There is no un-finalize endpoint. Do not
  add one, even if asked to "just add a quick admin override" — surface that
  request back to the user instead of building it. This is final, not up for
  revisiting. The only levers against a mistaken finalize are on the
  retention/purge side, decided and fixed as follows:
  - `app_config.retention_days` default is **30**, not 10 — a wider window to
    notice a finalize mistake before sibling PDFs are actually purged.
  - The finalize endpoint (`POST /uploads/:id/finalize`) must accept and
    validate an echoed `reference_id` in the request body, matching the
    upload's patient — reject with **409** if it doesn't match or is
    missing (2026-07-21: corrected from an earlier 400 here, to stay
    consistent with the other four finalize guards, which are all 409 —
    a reference_id mismatch is a state conflict, not a malformed request).
    This is a backend-enforced guard, not just a frontend confirmation
    dialog; the frontend UI requires the user to type the reference_id
    before the call fires, but the server must not trust that it did.
- **No hard deletes**, except PDF blobs past their retention window. Everything
  else is a flag: `voided`, `active=false`, `file_purged=true`. Never `DELETE`
  a row that represents something that happened.
- **Every mutating endpoint writes an audit_log entry** with a field-level
  diff (`{field: {from, to}}`), in the same transaction as the change, via the
  single shared helper (`app/audit.py::record`). Don't write audit rows ad hoc
  elsewhere.
- **Published rule_snapshots never change** once created. A rule edit updates
  the live `rules` row and history immediately, but only reaches new uploads
  after the next scheduled sync tick publishes a fresh snapshot.
- **version_number / upload_number are system-assigned**, sequential per
  parent, transactional, never manual, never reused.
- **Rule creation writes `rule_version_history` version 1** in the same
  transaction as the insert — not just edits.
- **Overrides are draft-only (2026-07-30, corrected — this is the final
  answer).** This is the real workflow: the agent flags each rule
  pass/fail/N-A with a finding and page number; a human reviewer goes
  through the draft, corrects whatever the agent got wrong, and routes
  what needs fixing to BCBA or wherever it belongs — all of this happens
  only while `upload.is_final == false`. The moment an upload is finalized
  into a version, it is the final, locked document: no further overrides,
  no edits, nothing changes after that point. `PATCH /rule_results/:id`
  rejects an override attempt on an already-final upload (409). This
  reverses two earlier, now-wrong statements of this same invariant (one
  said override was finalized-only, the next said both) — neither was
  correct. Because an override can no longer happen on an already-final
  upload, the "recompute `versions.score`/`audit_result` on override"
  behavior this bullet used to describe no longer applies: a finalized
  version's score is fixed at finalize time and never recomputed
  afterward, by an override or anything else.
- **Finalize is blocked while any `rule_result.final_status = uncertain`** on
  that upload — every uncertain must be human-resolved first.
- **Mark Reviewed requires the version to already be finalized.**

## Decided policy (was pending, now locked in)

- **No rule severity tiers.** Every rule is mandatory, full stop — there is
  no `critical` vs `normal` distinction anywhere (2026-07-21, user decision).
  `rules.severity` / `rule_version_history.severity` and the
  `rule_severity` Postgres enum are gone (migration `3f5a3ad541db`).
- Scoring: `pass / (pass + fail)`, NA excluded from both sides. **No
  critical-fail override clause** — with severity removed, there is no
  condition left for one to trigger on. This lives in exactly one place,
  `app/services/scoring.py::compute_score`, so it can still change without
  touching anything else. Only `finalize.py` calls this function today —
  `rule_results.py`'s override path no longer does, since overrides are
  draft-only and a draft has no `version.score` to recompute (see the
  corrected override invariant above). Never inline this formula anywhere
  else in the codebase.
- **Mandatory supporting document (2026-08-02, Round 51, Mrs. Ungar's
  confirmed requirement).** Every real TP upload — both the new-patient and
  existing-patient flows, no exceptions — now requires a SECOND file
  alongside the TP itself. `uploads.supporting_document_path` (migration
  `c3e7b1a94f56`) mirrors `file_path`'s exact storage/retention lifecycle
  (same directory convention, same `file_purged`/`purge_after`, retained
  permanently once finalized, purged only when a sibling draft's window
  elapses — see `app/services/retention.py`). `POST /versions/:id/uploads`
  422s if it's missing (FastAPI's own `File(...)` requiredness, not custom
  validation). Served via `GET /uploads/:id/supporting-file`, same auth
  guard as every other review endpoint. **Display-only, currently** — opened
  in a new browser tab via the frontend's "Helping Document" button, never
  rendered inline, never parsed, never read by `review_treatment_plan` or
  any part of the rule-checking pipeline. Extraction/sub-agent consumption
  of this document is planned for a future round, not yet built — do not
  assume this document influences any rule result today.

## Auth

- Real per-user login — never a shared/fixed dev user. The audit log
  attributes actions to named users, which a fixed user would break from
  day one.
- Passwords hashed with bcrypt/argon2 via `passlib`; never stored plain.
- JWT with the `role` claim embedded, 12-hour expiry. No refresh token in v1.
- No public signup route. Users are created only via
  `POST /admin/users` (Admin > Users & Roles), matching the route spec.

## Boundaries

- `app/rule_engine/client.py::run_rule_checks` is no longer hollow
  (2026-07-30) — it calls into `agent-making/agent/pipeline/api.py`'s
  `review_treatment_plan` wrapper, per `agent-making/INTEGRATION_PLAN.md`.
  **This is delegation, not logic** — the boundary still holds: no
  rule-checking logic itself lives in this backend, `client.py` only
  translates between agent-making's rule_id/status vocabulary and this
  backend's `RuleResultDraft` contract. `contract.py`'s shape changed once
  as part of this wiring (added `"not_checkable"` to `model_status`) —
  flagged here rather than done quietly, per the rule below. Any further
  change to `contract.py`'s shape still needs the same flagging — it's a
  cross-repo contract, and the agent repo mirrors it.
- Don't restructure `/frontend` as part of backend work unless explicitly asked.

## When something in a task conflicts with an invariant above

Stop and say so — don't silently pick a side. This is a healthcare-compliance
product; the invariants exist for specific, deliberate reasons documented in
`docs/TP_Review_Gap_Analysis.md`. If a request seems to require breaking one,
that's a signal to ask, not to route around it quietly.
