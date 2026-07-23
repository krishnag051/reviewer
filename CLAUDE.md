# TP Review System

Healthcare-compliance review tool: Treatment Plans checked against a rule
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
- **An override on an already-finalized upload recomputes
  `versions.score`/`audit_result` synchronously**, in the same transaction as
  the override, with its own audit entry.
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
  touching anything else. Both the override recompute-on-final path
  (`app/services/rule_results.py`) and finalize (`app/services/finalize.py`)
  call this same function — never inline this formula anywhere else in the
  codebase.

## Auth

- Real per-user login — never a shared/fixed dev user. The audit log
  attributes actions to named users, which a fixed user would break from
  day one.
- Passwords hashed with bcrypt/argon2 via `passlib`; never stored plain.
- JWT with the `role` claim embedded, 12-hour expiry. No refresh token in v1.
- No public signup route. Users are created only via
  `POST /admin/users` (Admin > Users & Roles), matching the route spec.

## Boundaries

- `app/rule_engine/` is a **deliberately hollow stub** — it returns
  `model_status="na"` for every rule, on purpose. The real rule-checking agent
  is built in a separate repo against `app/rule_engine/contract.py`. Never
  implement real rule-checking logic inside this backend. Never change
  `contract.py`'s shape without flagging it — it's a cross-repo contract, and
  the agent repo mirrors it.
- Don't restructure `/frontend` as part of backend work unless explicitly asked.

## When something in a task conflicts with an invariant above

Stop and say so — don't silently pick a side. This is a healthcare-compliance
product; the invariants exist for specific, deliberate reasons documented in
`docs/TP_Review_Gap_Analysis.md`. If a request seems to require breaking one,
that's a signal to ask, not to route around it quietly.
