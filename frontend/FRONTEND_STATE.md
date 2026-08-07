# Frontend State — TP Review System (React / TanStack Start)

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

As of Round 42 this frontend is no longer 100% mock — see §0 immediately below for what's actually real now. A real click-through (frontend → real backend → real agent) still makes a real Anthropic API call the moment an upload's background pipeline actually runs to completion — treat any request to exercise that path the same as a live-API request: ask first. See the identical copy of this rule in the root `CLAUDE.md`, `agent-making/AGENT_STATE.md`, and `agent-making/INTEGRATION_PLAN.md`.

---

## 0. Round 41 / Round 42 update — what's actually real now

The rest of this document (§1 onward) was written before Round 41 and
describes the ORIGINAL all-mock architecture. It's kept below because most
of it is still accurate for the surfaces it hasn't touched (Rules Studio,
Reports, Dashboard, Admin Settings, correction email) — but where it
conflicts with this section, THIS section wins.

**Real (hits the actual FastAPI backend over real HTTP, real JWT auth):**
- Login (`login.tsx`, `auth-context.tsx`) — real `POST /auth/login` +
  `GET /auth/me`, JWT in `localStorage`, real per-user role
  (admin/user/developer) read from the live DB, not a client-side toggle.
  The old "View as: Admin / Standard User" mock switch described in §2/§5
  below no longer exists.
- `plans.index.tsx`, `plans.$refId.index.tsx` — real `GET /patients`,
  `GET /patients/:id/versions`, `GET /versions/:id`, `GET /uploads/:id`.
  Round 42 adds the real PDF pane (`GET /uploads/:id/file`, via
  `PdfViewer.tsx`) alongside the real rule results, for both a draft's
  latest upload and a finalized version's final upload.
- `dev.tsx` — real diagnostics, gated on the real `developer` role.
- `upload.tsx` — Round 42: real `POST /patients` (new-patient mode),
  real `POST /patients/:id/versions`, real `POST /versions/:id/uploads`
  (the actual pipeline trigger). The old BCBA/Reviewer selector is gone —
  the real `VersionCreate` body has no `reviewer_id` field at creation time
  (that's a Stage 3 `PATCH /versions/:id` concern), so there was nothing
  real left for it to do. **Round 51: a second, mandatory file — the
  "supporting document" — is now required alongside the TP in both modes;
  submit is disabled until both are selected. Storage/display only (see
  below), no parsing.**
- `plans.$refId.index.tsx` — Round 43 (Stage 3) added real override
  (`PATCH /rule_results/:id`) and real finalize (`POST /uploads/:id/
  finalize`, typed reference_id confirmation) — this page is no longer
  read-only; it's the correction below "Still mock" further down in this
  doc, which was never updated when Stage 3 landed. **Round 51** adds a
  "Helping Document" button (opens `GET /uploads/:id/supporting-file` in a
  new tab, never inline) for both draft and finalized views.
- `rules.tsx` (Rules Studio) — **Round 50**: real `GET/POST/PATCH /rules`
  + `/rules/:id/(de)activate`, real payor-scoped metadata. Editing here is
  metadata-only — see §4 below, itself now partially stale, corrected here:
  Rules Studio is real, not mock.
- `real-data.ts` / `api-client.ts` — the only two files that know the
  backend's real route shapes; every real hook/fetch in the app goes
  through them.

**Still mock** (§1-§5 below describe these accurately, EXCEPT §4's Rules
Studio section, superseded above, AND "Escalate to BCBA," superseded by
the Round 70-73 note below): Reports, Dashboard's activity feed for
anything not covered above, Admin Settings' non-user-provisioning tabs
(Organization/Notifications/Integrations/Billing), correction email
*send* specifically, mark-reviewed.

Not yet exercised for real by this frontend's own automated verification,
by design: a real upload actually completing its pipeline run (zero
Anthropic credit, per the hard rule above) — see
`src/test/lifecycle.test.tsx`'s Round 42 wiring test, which proves the
request/response shape using content the pipeline rejects at the parse
step, before it would ever reach the real agent. (A real end-to-end run
was later approved and completed in Round 48 — see that round's report;
this doc's "not yet exercised" caveat is about this file's own automated
test suite, not the system overall.)

**Round 51 — mandatory supporting document (Mrs. Ungar's confirmed
requirement).** Every real upload now requires a second file, alongside
the TP, in both new-patient and existing-patient flows — no exceptions.
Stored and retained permanently, exactly like the TP's own file (same
backend lifecycle, see `CLAUDE.md`). **Currently display-only**: a
"Helping Document" button on the review page opens the real file in a new
browser tab via `GET /uploads/:id/supporting-file` — it is never rendered
inline (the main PDF/rule-results area is untouched), never parsed, and
not fed into `review_treatment_plan` or any part of the rule-checking
pipeline. Extraction/sub-agent consumption of this document is planned for
a future round, not yet built — don't describe this document as
influencing any rule result today.

**Rounds 70-73 — results panel rebuilt, real (draft-only) BCBA escalation,
🔒 integration structure now LOCKED (2026-08-08).** `plans.$refId.index.tsx`'s
review panel is no longer the Round 43-era "raw rule_id + status dropdown"
UI described above:
- Real, plain-English `question_text`/`category`/`rule_code` per result
  (Round 70) — never a bare rule_id again.
- Real, working page-jump (`[View Page N]` links actually navigate the PDF
  pane) — Round 70 built it, Round 72 found and fixed the real bug (a
  same-document `src` hash update doesn't re-trigger the browser's PDF
  viewer; fixed via a forced remount), **confirmed working live by
  Krishna, not just claimed**.
- Real editing of a result's evidence/pages (Round 70), extending the same
  override mechanism, not a second one.
- Round 73: each result card is now collapsed by default (question +
  Answer only), independently expandable per card via a chevron — not an
  accordion — matching the Brellium reference's density.
- **"Escalate to BCBA" is real, not a toast placeholder** (superseding the
  "Still mock" line above) — Round 70 wired it to the real, pre-existing
  `POST /versions/:id/correction-email` endpoint; Round 71 gave it a real
  modal (same pattern as the Intake Q&A modal) with editable To/Cc/Bcc and
  every non-Pass item listed. **Still draft-only** — no send capability
  exists anywhere in this codebase; actually sending is a separate,
  unapproved decision.
- Session Notes page (`session-notes.$uploadId.tsx`) now renders each
  attached file inline via the same `PdfViewer` component the main review
  page uses (generalized in Round 72 to accept any blob-fetcher), not just
  a download link.

**Per Round 73's explicit instruction: this integration structure — the
frontend/backend/agent-wrapper wiring built across Rounds 66-73 — is now
considered stable and locked.** See the identical lock note in
`agent-making/AGENT_STATE.md` and `agent-making/INTEGRATION_PLAN.md`.
Future rounds improving agent-making's own internal judgment/detection
logic should not need to restructure any of this frontend wiring, as long
as the existing `RuleResult` contract shape keeps being honored.

---

Cold-start reference for this frontend. Written 2026-07-30. If you're a
future Claude Code session (or a human) picking this up with no memory of
how it got here, this document is meant to be enough on its own — you
shouldn't need prior chat history to understand what's built, what isn't,
and what's still mock.

Tone note, same spirit as `agent-making/AGENT_STATE.md`: this is written to
be accurate, not to look good. Where something is still mock, still a
placeholder, or not connected to anything real, it says so plainly.

Scope note: this document describes `frontend/` only. For the backend
(FastAPI + Postgres), see `docs/BACKEND_IMPLEMENTATION_SUMMARY.md`. For the
standalone rule-checking agent, see `agent-making/AGENT_STATE.md`. For how
these three are meant to eventually connect, see
`agent-making/INTEGRATION_PLAN.md`.

---

## 1. The U/V data model, as it exists today

Everything lives in two files: `src/lib/tp-mock.ts` (types + seeded mock
data) and `src/lib/tp-context.tsx` (the one `TPProvider` React Context that
holds all mutable state and every mutating action).

**Core distinction**: a `PlanVersion` (V) is the permanent, sequential,
finalized TP record — V1, V2, ... — never renumbered, never deleted. A
`UAttempt` (U) is a disposable draft upload made while working toward the
next open V-slot — U1, U2, U3... as many revise-and-reupload cycles as
needed, none of them permanent on their own. `Patient` holds both:
`versions: PlanVersion[]` and `uAttempts: UAttempt[]`.

- **`UAttempt`** — `id`, `attemptNumber` (1, 2, 3... scoped to the current
  open slot only, resets to 1 once that slot is finalized), `uploadedAt`,
  `assessmentDate`, `reviewerId`, `pdf`, `status: "processing" | "complete"`,
  `results`/`score`/`auditResult`. No `reviewed` field — that's a
  post-finalize, V-only concept. `results`/`score`/`auditResult` are
  actually computed synchronously at creation time (the mock scripted
  findings logic isn't time-based) — `status` only gates whether the UI is
  *allowed to show them yet*, standing in for a real backend job that
  hasn't finished (see §1's processing-delay note below).
- **`PlanVersion`** — `version`, `finalizedAt`, `assessmentDate`,
  `reviewerId`, `pdf`, `results`/`score`/`auditResult`, `reviewed: boolean`,
  `finalizedFromAttemptId` (traceability back to which `UAttempt` became
  this version).
- **`addPatient({refId, name, payor})`** — creates the patient shell only:
  `versions: []`, `uAttempts: []`. No shortcut to an instant V1.
- **`addAttempt(refId, reviewerId, pdf, assessmentDate)`** — appends a new
  `UAttempt` with `status: "processing"`, then schedules a `setTimeout`
  (5–10s, `randomProcessingDelayMs()`) that flips it to `"complete"`. The
  timer lives inside `TPProvider` at the app root, so it survives
  navigating away from `/upload` (which now happens immediately on
  submit — see §3). Fire-and-forget by design: the created attempt's ID is
  generated *before* calling `setPatients`, independent of any patient
  lookup, specifically so the delayed-completion timer can target it later
  without ever depending on a stale `patients` closure. (This file also
  documents a real bug that was found and fixed live: `addAttempt` used to
  look up the patient in the outer `patients` closure *before* calling
  `setPatients`, which silently failed when `upload.tsx`'s New Patient flow
  called `addPatient()` then `addAttempt()` in the same synchronous
  handler — fixed by moving the lookup inside `addAttempt`'s own functional
  `setPatients` updater.)
- **`finalizeAttempt(refId, attemptId)`** — promotes one attempt into the
  next `PlanVersion` and clears *every* draft for that patient, including
  sibling attempts that weren't chosen. Returns the new version number (or
  `null` if the attempt was already superseded).

**Confirmed decisions baked into this model:**
- **Drafts vanish on finalize, today.** All sibling `uAttempts` are dropped
  the moment any one of them is finalized. This is explicitly a mock-data
  limitation, not a design intent — once this connects to a real database,
  those siblings should likely be **soft-retained** for audit history
  instead of destroyed, consistent with how this project archives rather
  than deletes elsewhere (`CLAUDE.md`'s "no hard deletes" invariant). This
  is now *confirmed*, not speculative: the real backend's `uploads` table
  already does exactly this — a sibling upload gets `purge_after` set on
  finalize, not deleted outright (see §6 and the reconciliation note in
  `INTEGRATION_PLAN.md`).
- **V1 goes through the same draft flow as every other version.** A
  brand-new patient's first version is created via `addAttempt` →
  `finalizeAttempt`, exactly like V2, V3, etc. — no special-cased "instant
  V1" path.
- **Overrides are draft-only (2026-07-30, corrected — this is the final
  answer).** `overrideRuleStatus` mutates a `UAttempt`'s results, never a
  `PlanVersion`'s — the override dropdown only renders when a draft attempt
  is selected in the unified review page, never for a finalized version.
  This is the real workflow: the agent flags each rule pass/fail/N-A with a
  finding and page number, a human reviewer corrects whatever's wrong
  while the attempt is still a draft, and finalizing locks the document —
  no further edits after that, by override or anything else. This reverses
  two earlier, now-wrong statements of this same decision (one said
  finalized-only, the next said both) and now matches the backend's real
  `override_rule_result` guard (rejects 409 once the parent upload is
  `is_final`) — see §6, this tension is now resolved, not just flagged.
- **The "V0" label is UI-only, and that's fine as designed — confirmed,
  not just asserted (2026-07-30).** `pendingSlotLabel(versionsCount)`
  returns `"V0"` only when a patient has zero finalized versions, so
  pre-finalization copy doesn't imply a V1 already exists (e.g. "Create
  Attempt U1 (against V0)"). The "Finalize as V[n]" action itself never
  uses this — it always names the real target being created, which for the
  first slot IS "V1". Checked against the real backend schema this round:
  the backend actually assigns a real `version_number` up front, before
  the first upload — so once wired up, the fix is replacing "V0" with that
  real number (read from the backend, not derived client-side), not
  restructuring anything backend-side. See §6.

---

## 2. The unified review interface

One component renders **both** a draft attempt and a finalized version:
`PlanDetail` in `src/routes/plans.$refId.index.tsx`. There is no separate,
simplified "draft card" view anymore — a draft gets the exact same PDF
viewer + full rule-results panel a finalized version does.

- **Selection**: a single `selectedValue` string (`"v-{version}"` or
  `"u-{attemptId}"`) resolved against live `patient.versions`/`patient.uAttempts`
  every render, with a fallback to the latest available item if the stored
  value goes stale (e.g. it pointed at a draft that just got cleared by
  finalizing a sibling). Initial selection prefers the newest pending draft
  over the latest finalized version — a freshly-created draft is almost
  certainly what the user just came here to look at, since `/upload` now
  auto-navigates straight to this page on submit.
- **Combined switcher**: one `<Select>` grouped into "Finalized" (v1, v2,
  ... newest labeled "(latest)") and "Drafts pending V[n]" (U1, U2, ...,
  each showing "(reviewing…)" while still processing) — switching between
  either group re-renders the same PDF + rule-results layout underneath.
- **Toolbar actions differ by kind, nothing else does**:
  - Finalized version: **View Summary**, **Mark Reviewed**, **Generate
    Correction Email**.
  - Draft attempt: **View Summary**, **Send for Correction** (mock/
    placeholder — see §5), **Finalize as V[n]** (disabled while the
    attempt is still `"processing"`).
- **PDF viewer, rule-results panel, page navigation, zoom, category/lane
  tags** — identical for both, same components (`StatusBadge`,
  `CategoryTag`, `LaneTag` in `src/components/tp/ui.tsx`).
- **One deliberate exception**: the per-rule Override dropdown (the pencil
  icon → "Override to Pass/Fail/N-A") only renders when a DRAFT attempt is
  selected, never for a finalized version — the draft-only override
  decision above (2026-07-30, corrected — this reverses an earlier version
  of this same page that had it the other way around, matching the
  override decision's own two earlier wrong statements).
- **Processing state**: while the selected draft's `status === "processing"`,
  the header shows an "Agent reviewing…" badge in place of the pass/fail
  badge, the score line shows "Agent reviewing…" instead of a number, the
  rule-results panel is replaced by a centered spinner + explanatory text,
  and Finalize/Send for Correction are disabled. The PDF itself still
  renders — there's no reason to hide the raw uploaded document while
  waiting.

---

## 3. Routes — what each one actually does today

| Route file | What it does |
|---|---|
| `upload.tsx` | New Patient / Existing Patient tabs. New Patient: `addPatient` + `addAttempt`, submit button reads "Create Attempt U1 (against V0)". Existing Patient: search by name/refId, pick a result, `addAttempt` against that patient's real next slot label. **Both flows auto-navigate straight to `/plans/$refId` on submit** — there is no confirmation banner/link step anymore; the patient page's own processing state *is* the confirmation. |
| `plans.index.tsx` | Two tables. "In progress" (amber): patients with zero finalized versions but at least one draft — shows `U[n]`, "Not finalized", and either a "Processing…" indicator or the real score/result depending on the latest draft's `status`. Below it, the normal finalized table: one row per patient using their latest `PlanVersion`, regardless of whether a newer draft is also pending (that case is visible from the patient's own page, not duplicated here). Search/payor/result filters apply to both tables. |
| `plans.$refId.index.tsx` | The unified review interface described in §2 — the only place `Finalize as V[n]` exists anywhere in the app. |
| `plans.$refId.email.tsx` | Correction-email compose page for the patient's **latest finalized version only** (`notFound()`s if the patient has zero finalized versions — a draft-only patient has no email page). Auto-generates a subject/body from that version's failed rules, grouped by section or page. "Copy" and "Send Now" are both mock — `toast` only, no real send capability. |
| `rules.tsx` | Rules Studio — described in §4. |
| `admin.tsx` | Organization / Users & Roles / Notifications / Integrations / Audit Log / Billing tabs. All mock: org settings and notification defaults are disabled inputs with a no-op "Save" once `role !== "Admin"`, "Connect" on any integration just shows a toast, the Users table is local `useState` seeded from `reviewers` (edits don't persist past a refresh), Audit Log and Billing render static arrays (`auditLog`, `invoices`) from `tp-mock.ts`. |
| `reports.tsx` | Overview tab: 3 stat cards, a weekly Pass/Fail bar "chart" (plain styled `<div>`s, not a charting library — see §5), and a per-reviewer breakdown table. Trend Data tab: a reviewer/rule-code pass-rate matrix. Everything derived live from `patients` state via `useMemo` — nothing persisted, nothing paginated. |
| `index.tsx` | Dashboard — 3 stat cards, 4 quick-action links, and a "recent activity" table of the 8 most-recently-finalized versions across all patients. |
| `dev.tsx` | **Developer Mode (added 2026-07-30)** — diagnostics only, not part of the normal review workflow. One flat, sortable-by-date list of every draft `UAttempt` AND every finalized `PlanVersion` across every patient, each as its own row (kind, U/v label, status incl. "Processing", score, date, reviewer, and up to 4 failing rule_ids so a developer can spot what's failing without opening the patient page). Clicking a row navigates to that patient's real review page. Purely additive — reads existing `patients` state, no new mock data, no mutations, nothing rebuilt from the per-patient review page. Linked from `AppShell`'s nav (last item, `Bug` icon). |

`__root.tsx` mounts `TPProvider` once at the app root (inside
`QueryClientProvider`, wrapping `AppShell`) — this is the single source of
truth every route reads via `useTP()`; there is exactly one `patients`
`useState` in the whole app, not one per route.

---

## 4. Rules Studio

`rules.tsx` renders one tab per payor — all 10 values in `PAYORS`
(`tp-mock.ts`): Aetna, Anthem, Cigna, Emblem, Empire, Healthfirst, Molina,
MVP, Straight Medicaid, New York Medicaid. Each tab shows that payor's
applicable rules (universal `"ALL"` rules + that payor's own specific
rules), with search, category filter, active/inactive toggle, and full
create/edit/delete via a dialog.

The rule *content* (all 120 rows in `tp-mock.ts`'s `rules` array — id,
category, description, `checkType`, `actionLane`, `actionTag`) was
hand-copied from `agent-making/agent/rules/rules.json` so this page reads
like the real ruleset rather than placeholder text. **This is a one-time
copy, not a live import** — `tp-mock.ts` does not read `rules.json` at
build or run time, so the two will drift the moment either changes.

**Confirm: still mock/local-state only.** `upsertRule`/`deleteRule`/
`toggleRule` in `tp-context.tsx` all mutate the same in-memory `rules`
`useState` seeded from that hand-copied array. Nothing is persisted —
refreshing the page resets every edit back to the seeded 120 rules. There
is no backend call anywhere in this flow, even though the real backend
already has a working `rules`/`rule_version_history`/`rule_snapshots`
system built (`docs/BACKEND_IMPLEMENTATION_SUMMARY.md`) that this page
isn't wired to yet.

---

## 5. Known gaps, stated plainly

- **Everything is mock data in React context.** One `useState<Patient[]>`
  and one `useState<Rule[]>` in `TPProvider` (`tp-context.tsx`), seeded from
  `initialPatients`/`rules` in `tp-mock.ts`. No network request exists
  anywhere in `frontend/` today — not to the real backend, not to
  `agent-making`. A page refresh resets all state to the seeded fixtures.
- **"Send for Correction" (the draft toolbar action added this round) is a
  placeholder.** It shows a success toast ("`{patient}`'s draft sent for
  correction...") and does nothing else — no real routing, no
  notification, no backend call, no persisted state change of any kind.
- **The upload → processing-delay → result flow is simulated, not a real
  agent call.** `addAttempt`'s `setTimeout` (5–10s) is standing in for the
  real rule-checking agent's actual run time — the "result" it reveals was
  already computed synchronously at attempt-creation via `runMockReview`/
  `SCRIPTED_FINDINGS`, not produced by any live process. There is no real
  job, no real backend, no real `agent-making` pipeline involved.
- **Charts are a known, deliberately-deprioritized gap.** `reports.tsx`'s
  "weekly Pass/Fail volume" is hand-built with styled `<div>`s sized by
  inline `style={{height}}`, not a real charting library — `recharts` is
  already a `package.json` dependency but currently unused anywhere in the
  app. This is present and functional as a rough visual, not broken, but
  it is explicitly a lower-priority known gap, not something being worked
  on right now.
- **Correction email send is mock, matching the backend's own current
  state.** "Copy"/"Send Now" on `plans.$refId.email.tsx` only `toast()` —
  this mirrors the real backend, which also has no send capability
  anywhere yet (`docs/BACKEND_IMPLEMENTATION_SUMMARY.md`'s
  `correction_email.py` note).
- **Admin Settings integrations are all placeholders.** CentralReach,
  SharePoint, Availity, Google Workspace SSO all show "Not connected" and
  "Connect" just toasts — no real integration of any kind exists.
- **Auth/roles are a mock toggle, not real login.** The "View as: Admin /
  Standard User" switch in `AppShell`'s header just flips a `role` value in
  `TPProvider` — it's a demo convenience for showing read-only UI states,
  not real per-user authentication. The real backend already has real
  per-user login with bcrypt/argon2 + JWT (`CLAUDE.md`'s Auth section) —
  the frontend isn't wired to it at all yet.
- **Rules Studio content is a one-time copy of `agent-making`'s
  `rules.json`, not a live link** — see §4. It will silently drift from
  the real ruleset the moment either side changes without the other being
  updated to match.

---

## 6. Reliability note (cross-reference)

`agent-making/INTEGRATION_PLAN.md` has a `⭐ RELIABILITY PRIORITIES`
section recording this requirement for whenever real backend wiring
happens: **"Finalize as V[n]" must be the single most reliable operation in
the whole system** — it must always succeed and be durably saved, even if
other, lower-stakes actions (Generate Correction Email, the mock "Send for
Correction" action above, etc.) fail or aren't fully wired up. This has no
code implication in the current mock frontend (there's no real persistence
to be reliable about yet), but it's recorded there — and referenced here —
so it isn't lost before real backend work starts.

**Update, 2026-07-30 — the override tension is now resolved, not open.**
An earlier round of this document flagged a real mismatch: the frontend's
then-current "overrides are V-only" decision didn't match the backend's
then-current behavior (which allowed overriding any upload, finalized or
not). That's settled now, in both places, the other direction: overrides
are **draft-only**. `overrideRuleStatus` (frontend, §1) only ever mutates a
`UAttempt`; the real backend's `override_rule_result` now rejects (409)
any override attempt once the parent upload is `is_final` — see
`CLAUDE.md`'s corrected invariant and `INTEGRATION_PLAN.md` for the backend
side. Both sides agree; nothing left open here.

**Also added this round, backend-only, not reachable from this frontend at
all**: `backend/scripts/purge_test_data.py` — a dev/test-data cleanup
script (dry-run by default, `--yes` to actually delete) for removing
`TP-TEST-*`-style dummy patients and their full upload/rule_result chain
directly from the database. Deliberately has no frontend affordance and no
API route — per this round's explicit instruction, this stays outside what
the running application exposes.
