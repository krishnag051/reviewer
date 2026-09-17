# TP Review System

Healthcare-compliance treatment-plan review tool. BCBAs upload a treatment
plan (plus a required supporting/session-notes document); the system checks
it against a compliance rule set, surfaces pass/fail/uncertain findings with
page citations, and routes anything that needs a human decision to a
reviewer before a version can be finalized.

Three repos in this monorepo:

- **`backend/`** — FastAPI + Postgres. Auth, patients, uploads, versions,
  rule authoring/sync, audit log, reports.
- **`agent-making/`** — the standalone rule-checking pipeline (deterministic
  checks + AI judgment layer). Called by the backend through exactly one
  seam: `backend/app/agent_client.py`.
- **`frontend/`** — React (TanStack Start/Router) SPA.

**Start here:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the full
pipeline, rule-sync model, safety-net mechanism, previous-TP comparison,
reports, and deployment, verified against current code. Then
[`CLAUDE.md`](CLAUDE.md) for the permanent invariants and hard rules
(human-override, finalize irreversibility, no real API calls without
explicit approval) that must never be violated regardless of what a task
seems to ask for.

Other docs in `docs/` and `agent-making/` predate large parts of the current
system (pre-real-agent-wiring, pre-severity-removal, pre-previous-TP
comparison) — files that are now historical carry a banner at the top saying
so and pointing back to `docs/ARCHITECTURE.md`.
