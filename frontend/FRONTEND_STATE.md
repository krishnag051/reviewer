# Frontend State — TP Review System (React / TanStack Start)

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
- **Overrides are V-only.** `overrideRuleStatus` only ever mutates a
  `PlanVersion`'s results — a draft `UAttempt` gets no override affordance
  anywhere in the UI. If a finding on a draft looks wrong, the correct
  action is to revise the document and upload a new attempt, not override
  a disposable draft. (See §6 for a real tension this creates against the
  actual backend's data model — flagged, not resolved.)
- **The "V0" label is UI-only.** `pendingSlotLabel(versionsCount)` returns
  `"V0"` only when a patient has zero finalized versions, so pre-finalization
  copy doesn't imply a V1 already exists (e.g. "Create Attempt U1 (against
  V0)"). The "Finalize as V[n]" action itself never uses this — it always
  names the real target being created, which for the first slot IS "V1".
  This is purely a frontend string convention with **no backing data
  record** — there is no "V0" row anywhere. That matters once wired to a
  real backend (see §6).

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
  icon → "Override to Pass/Fail/N-A") only renders when a finalized version
  is selected, never for a draft — preserving the V-only override decision
  above. This was a judgment call made when unifying the view, not
  something the user explicitly asked for either way; flagged here in case
  it should be revisited.
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

That same document's reconciliation pass also flags one real, unresolved
tension worth restating here: the frontend's confirmed **"overrides are
V-only"** decision (§1 above) does not currently match the real backend's
actual data model, which allows overriding a `rule_result` on *any*
upload, finalized or not — it only conditionally recomputes the parent
version's score if that upload happens to already be the finalized one.
Which behavior is correct for the real product is a real product decision,
not something either this document or the frontend code has settled.
