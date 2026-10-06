# TP Review System — Technical Summary & Interview Prep

*Prepared 2026-09-30. All facts below are drawn directly from this repository (code, docs, git history, config). Anything not directly verifiable is marked **needs confirmation**.*

---

## 1. What the system does

A healthcare-compliance review tool for ABA (Applied Behavior Analysis) treatment plans (TPs). Reviewers upload a TP PDF (plus a mandatory second "supporting document"), and the system runs it through 189 compliance rules (178 currently active) — checking things like goal-tracking data, coordination-of-care documentation, hours requested vs. justified, payor-specific requirements, signatures, and AI/template-artifact leakage — producing a pass/fail/uncertain/not-applicable finding with page citations and evidence text for each rule. A human reviewer then works through the draft (correcting the agent's findings where needed) before the document is **finalized** into an immutable, versioned record with a compliance score.

It is explicitly **not** an autonomous approval system — every result is a draft until a human signs off, and human overrides always win over the model's own output (see Invariants, §12).

## 2. Complete workflow / data flow

1. **Intake** — PDF uploaded (pypdf for text extraction); a second, mandatory "supporting document" is uploaded alongside it (422 if missing).
2. **Supporting-doc extraction** — one real Anthropic call extracts structured fields from the supporting document.
3. **Image-only page flagging** — a text-length heuristic (not real image/vision analysis) flags pages that are likely scanned images with little/no extractable text.
4. **Selective page rendering** — PyMuPDF renders only the pages that need vision input (120 DPI), plus specific vision-eligible sections that always render regardless of the heuristic.
5. **Field extraction** — structured fields pulled from the rendered/extracted content.
6. **Scope filtering** — rules are filtered by payor and plan type (e.g., Healthfirst-specific, Cigna-specific rules only apply to those payors).
7. **Deterministic checks** — rules tagged `deterministic` run through `DET_CHECKS`, a dispatch table of Python checker functions (regex/field-comparison logic, no model call, no cost).
8. **Escalation** — any deterministic rule with low confidence, an uncertain result, a `not_checkable` result, or no checker function at all, escalates to the AI judgment layer. All `judgment`-type rules go there by default.
9. **AI judgment layer** — a 5-way majority vote (`n_calls=5, min_agreement=4`) using `claude-sonnet-5`. If 4+ of 5 calls agree, that's the result; if they don't converge, the rule is marked genuinely uncertain (with evidence showing the real disagreement, not a placeholder).
10. **Page-number recovery** — up to 2 retry passes to recover/verify the page citation for a finding.
11. **Humanization** — deterministic regex rewriting of evidence text into plain, reviewer-friendly language (an LLM-based rewrite pass exists in code but is **not wired into production** — needs confirmation if this has changed since).
12. **Merge/export** — results merge into `rule_results`, feeding the reviewer UI, score computation, and reports.
13. **Human review** — a reviewer reads the draft, corrects wrong findings/pages (override, draft-only), and routes issues to BCBA/wherever needed.
14. **Finalize** — once no rule is left `uncertain`, the reviewer finalizes the upload/version; this locks it permanently (no un-finalize endpoint exists, by design).

## 3. Architecture and tech stack

**Three-repo monorepo:**
- `backend/` — FastAPI + Postgres, owns auth, uploads, rule storage/versioning, audit log, finalize/override workflow.
- `agent-making/` — standalone Python rule-checking pipeline (the actual PDF-to-findings engine described above).
- `frontend/` — React SPA.

**Backend:** FastAPI 0.139.2, SQLAlchemy 2.0.51, Alembic 1.18.5 (18 migrations, head `fa88ba8840b9`), Postgres via psycopg2-binary, Pydantic 2.13.4, passlib[bcrypt] + PyJWT for auth, APScheduler 3.11.3 for the rule-sync tick, pypdf 6.14.2 + PyMuPDF 1.28.0 for PDF handling, `anthropic` SDK 0.120.2.

**Frontend:** React 19.2.0, TanStack Router 1.170.16 / Query 5.101.1, Tailwind v4, Radix UI primitives, Vite, Vitest.

**Integration boundary:** `backend/app/rule_engine/client.py::run_rule_checks` calls into `agent-making/agent/pipeline/api.py`'s `review_treatment_plan`. This is a translation layer only — no rule-checking logic lives in the backend itself; `client.py` just converts between agent-making's rule_id/status vocabulary and the backend's `RuleResultDraft` contract.

**Deployment:** No CI/CD — a manual deploy sequence (build → push to Docker Hub → SSH → `docker compose pull/up` → conditional Alembic migration + rule sync). Production runs zero-trust (SSH-only server, no published DB port), routed through a Cloudflare Tunnel. Staging is a fully separate compose stack with a simulated-completion dev-only mode that requires zero real API spend.

## 4. My exact contribution

Verified from git history: **36 commits, single author (`Krishna Kumar <K.kumar@masterfaster.org>`, also appearing as `krishnag051` — same email), spanning 2026-07-20 to 2026-09-25 (~2 months)**. No other contributors appear in git history.

The commit and doc history (CLAUDE.md's own dated invariant history, the Round-numbered fix commits, `02_Accuracy_Results.md`'s ground-truth re-verification cycle) shows a consistent pattern: **you directed requirements, made the compliance/business policy calls** (retention window, severity-tier removal, finalize/override semantics, mandatory supporting document, the real-API spend-approval rule itself), **approved real API spend on a per-instance basis**, and **drove verification against real documents and a real human BCBA ground-truth checklist** across repeated fix rounds — while implementation was carried out by an AI coding agent (this tool) under your direction and review.

*needs confirmation: your formal job title/role and whether "Master Faster" is your own company or a client engagement — inferred only from the `masterfaster.org` email domain and git authorship, not stated anywhere in the repo.*

## 5. LLM/AI approach and why it was used

- Model: `claude-sonnet-5`, called through the official `anthropic` Python SDK — never a workaround or a different provider.
- Used only where deterministic logic genuinely can't decide: judgment-type rules requiring reading comprehension, cross-referencing multiple document sections, or subjective clinical-language assessment — not for anything a regex/field-comparison could resolve reliably and cheaply.
- **Why a majority vote instead of one call**: LLM judgment on ambiguous clinical text is not perfectly reproducible call-to-call. A single call risks a false-confident wrong answer; running 5 calls and requiring 4 to agree turns "the model was unsure" into a visible, honest `uncertain` result with real disagreement evidence shown to the reviewer — rather than silently picking whichever answer came back first.
- A **stabilization safety net** (`STABILIZED_UNCERTAIN_RULE_IDS`) exists for rules where even majority voting doesn't produce reliable signal (genuinely graph/image-dependent or genuinely subjective rules) — those are forced to a deterministic "uncertain, needs human review" result rather than spending money on a vote that won't resolve cleanly either way. This list has been added to and pruned across rounds as real fixes were found for individual rules.

## 6. Deterministic rules + AI judgment (current numbers, verified directly against `rules.json` on 2026-09-30)

- **189 total rules, 178 active** (11 inactive/retired), across **31 active categories**.
- **90 active rules are `deterministic`**, of which **84 have a real Python checker function** in `DET_CHECKS`; the remaining **6** (`QA-ACF-01`, `QA-MAST-01`, `QA-MAST-02`, `QA-COC-03`, `QA-COC-05`, `EMP-02`) are labeled deterministic but have no checker built, so they auto-escalate to the judgment layer every time.
- **88 active rules are `judgment`** — always go to the AI layer.
- **5 rule_ids** additionally depend on previous-TP comparison logic (comparing the current upload against a prior version for the same patient) — a live, working feature, not aspirational.

*Note on internal document drift: an older report file in this repo (`report.md`) states different figures (173 active / 64 deterministic / 109 judgment / 29 categories), and `docs/ARCHITECTURE.md` states yet another set (188 total / 179 active) "last verified 2026-09-17." Both predate later rule-fix rounds in this session. The numbers above are a fresh, direct query against the current `rules.json` and `pipeline/fields.py::DET_CHECKS` and should be treated as the current, authoritative figures — flagging the discrepancy rather than silently picking one.*

## 7. Evaluation / ground truth and accuracy

- Ground truth comes from **independent human BCBA review checklists for 3 real patients** (documented in `final-documents/02_Accuracy_Results.md`), re-run after every fix round against the same real source documents.
- The key tracked metric is **blocking failures** — real compliance issues that would have blocked payor approval, not general accuracy percentage.
- After fixes: one patient's plan reached **3/3** resolved blocking issues; another reached **6/8**; a third had **all 4** known gaps fixed and reconfirmed stable across 8+ re-runs.
- Real gaps found and fixed across rounds (per that document): a highlight-detection gap, an embedded-note-without-question-mark gap, a mastery-criteria self-contradiction, a mastered/in-progress duplicate-goal bug, a `Current Data:` vs. `Current Level:` field-naming mismatch, and false-confident passes on unverifiable claims. One documented incident: a round of real fixes sat correctly in the codebase but never took effect against real uploads because the running service was never restarted — a real deployment-process gap, not a code bug.
- *needs confirmation: the source document itself (`02_Accuracy_Results.md`) contains internal row-sum inconsistencies in its own comparison tables (e.g., a patient's "Review" row sums to 18 against a stated total of 19; another's "Pass" row sums to 58 against a stated 60) — these are flagged here rather than silently corrected, since I can't determine which number in the source is the typo.*

## 8. Production deployment

No CI/CD pipeline — deploys are a manual, documented sequence: build the Docker image → push to Docker Hub → SSH to the server → `docker compose pull && docker compose up` → run an Alembic migration and rule-sync only if needed for that release. Production is zero-trust: SSH-only access, no publicly reachable database port, all external traffic routed through a Cloudflare Tunnel. Staging is a fully separate compose stack, and includes a simulated-completion mode for testing the UI/workflow without spending real API money.

## 9. Monitoring and error handling

- **Audit logging**: every mutating endpoint writes an `audit_log` row with a field-level diff (`{field: {from, to}}`), in the same DB transaction as the change, through one shared helper (`app/audit.py::record`) — never written ad hoc.
- **Real-API cost guardrails** act as a spend-safety mechanism: an autouse pytest fixture blocks all real Anthropic calls in the test suite by default; a hard per-session ceiling (`MAX_REAL_API_CALLS_PER_SESSION`, default 4) stops runaway real-call spend mid-test-run, counted in raw API calls (not review invocations) and printed live as it accumulates.
- Whole-review result caching by content hash avoids re-billing identical resubmissions.
- *needs confirmation: no dedicated APM/alerting/observability tool (e.g. Sentry, Datadog) was found in the repo — monitoring beyond audit logs and the spend ceiling could not be verified.*
- *needs confirmation: exact HIPAA/PHI compliance certification or framework — not documented anywhere found; only inferable from the retention/audit/access-control design choices themselves.*

## 10. Important real problems solved (representative, from git/commit history)

- **QA-COC-01 evidence/status contradiction** (Round 14): a resolved Pass/Fail result could still show leftover "genuinely uncertain" phrasing from the disagreement-synthesis code path, because evidence text from both sides of a compound check was concatenated unconditionally regardless of which side actually won. Fixed so the resolving side's evidence leads.
- **QA-GIP-12 regression + page-citation gaps** (Rounds 11-13): real judgment-layer outputs came back in shapes the merge logic didn't anticipate — a single bare-int `page` with list-shaped `evidence`, or a clean single-page result when more real supporting pages existed — causing valid citations to be dropped or under-reported. Fixed by widening the merge logic to handle every real shape found via live testing against the real reconstructed PDF, including a hallucination check that removes a cited page if it doesn't actually contain the claimed text.
- **Deployment-vs-reality gap**: a round of real, tested, verified fixes existed correctly in the codebase and in git but never reached production because the service process was never restarted — later paralleled by a separate discovery that 5 rounds of committed fixes had never been pushed to `origin/main` at all (existed only in the local working copy). Both are documented, real incidents about the gap between "fixed in code" and "actually running," not just implementation bugs.
- **PAGEREF leak / disagreement-dump / BAR-01 gap** (Round 12): root-caused and fixed a set of related real defects — a Word-generated `PAGEREF` field code leaking into evidence text, raw vote-disagreement internals leaking into reviewer-facing text instead of plain language, and a rule category with no real coverage.

## 11. Key performance/business results

- 3 independently ground-truth-verified real patient plans, each converging to near-complete blocking-issue resolution after iterative fixing (3/3, 6/8, 4/4 — see §7).
- 178 active compliance rules enforced automatically per upload, spanning payor-specific, template-artifact, and clinical-content checks.
- 36 real commits / ~2 months of active development by a single owner-operator.
- *needs confirmation: no throughput, latency, or cost-per-review numbers were found in the repo (e.g., average $ spent per real document review, average turnaround time) — only the per-session real-call ceiling (default 4) and the "5-way vote is materially more than 2 calls per review" correction in CLAUDE.md were found regarding cost.*

## 12. Security/data considerations

- **Real per-user authentication** — no shared/fixed dev user, so every audited action is attributable to a named person. Passwords hashed with bcrypt/argon2 via `passlib`, never stored plain. JWT with an embedded `role` claim, 12-hour expiry, no refresh token in v1.
- **No public signup** — users are created only via `POST /admin/users`.
- **No hard deletes** anywhere except PDF blobs past their retention window — everything else is a soft flag (`voided`, `active=false`, `file_purged=true`); nothing that happened is ever erased from the record.
- **Human override is paramount** — every downstream consumer (score, reports, correction emails) reads the `final_*` columns, never the original `model_*` columns; the model's raw output is preserved once and never touched again.
- **Finalize is irreversible by design** — there is deliberately no un-finalize endpoint. The only safety net is a 30-day retention window (widened from an earlier default of 10) before sibling draft PDFs are purged, giving time to notice a mistaken finalize.
- **Finalize guard specifics**: rejects with 409 if the upload isn't `ready`, if it's voided, if a sibling upload in the same version is already final, or if any rule result is still `uncertain`; also requires an echoed `reference_id` matching the patient, checked server-side (409 on mismatch), not just via a frontend confirmation dialog.
- **Mandatory supporting document**: every real TP upload requires a second file; today it's display-only (opened in a new tab, never parsed or fed into the rule pipeline) — extraction/use of it by the pipeline is planned but not yet built.

## 13. Important technical decisions and why

- **Draft-only overrides, no override after finalize** — reversed twice before landing on this as final: the workflow is agent-flags → human-corrects-while-draft → finalize-locks-forever. This removed an entire recompute-on-override code path once finalize became the only place a score is ever computed.
- **No rule severity tiers** — every rule is mandatory, full stop. A prior `critical` vs `normal` distinction (and the critical-fail override clause in scoring) was deliberately removed by explicit user decision; scoring is now the single formula `pass / (pass + fail)` (NA excluded from both sides), living in exactly one function (`compute_score`) so it can change without touching anything else.
- **5-way majority vote over a single call** — chosen specifically to convert model uncertainty into a visible, honest "uncertain" state with real disagreement evidence, rather than a confident-looking wrong answer.
- **Selective page rendering instead of rendering every page** — a text-length heuristic decides which pages need image rendering at all, keeping vision-model cost down while still covering vision-eligible sections unconditionally.
- **Explicit, mandatory human-approval gate on all real API spend** (a hard rule in `CLAUDE.md`, reinforced by an autouse test fixture and a hard per-session call ceiling) — a direct, structural response to a real incident where a full real-content test suite burned money without prior visibility or approval.
- **Zero-trust, no-public-DB-port production deployment via Cloudflare Tunnel, no CI/CD** — a deliberate choice to keep the deploy surface small and manually controlled, appropriate for a small, single-operator healthcare-compliance system rather than a large team needing pipeline automation.

---

## Q&A

**Q: What does this system actually do, in one sentence?**
It automatically reviews ABA treatment-plan PDFs against ~178 compliance rules and produces a draft, human-reviewable pass/fail/uncertain finding set with page citations, which a human then corrects and finalizes into a locked, scored record.

**Q: Why not just have a human do 100% of the review?**
Humans still do — the system produces a draft to speed that review up and catch things consistently (data-entry mismatches, missing fields, payor-specific requirements) rather than replace clinical judgment. Nothing is final until a human signs off.

**Q: Why use an LLM at all instead of pure rules?**
Many of the ~88 active judgment-type rules require reading comprehension or cross-referencing prose across a document — things regex/field-comparison genuinely can't do reliably. Deterministic checks are used everywhere they can be, and only escalate to the model when they can't decide (low confidence, uncertain, or no checker exists).

**Q: How do you know the AI isn't just confidently wrong?**
Every judgment call is a 5-way majority vote requiring 4/5 agreement; if the model doesn't converge, the rule surfaces as `uncertain` with the real disagreement shown, not silently resolved. A further stabilization list forces genuinely unreliable rule types straight to a human-review state instead of trusting a vote at all. On top of that, every case is human-reviewed before anything is final.

**Q: What happens if a human disagrees with the AI's finding?**
They override it — while the upload is still a draft. `PATCH /rule_results/:id` lets a reviewer correct status/finding/pages; the original model output is preserved separately and never overwritten. Once the upload is finalized, no further changes are possible, by anyone, ever — there's no un-finalize endpoint.

**Q: Isn't "no un-finalize" risky?**
It's a deliberate irreversibility choice for a healthcare-compliance record — the only safety net is a 30-day retention window on sibling drafts before purge, giving a real window to catch a mistake before the underlying PDFs are gone, without allowing the finalized record itself to ever be edited.

**Q: What stops this from running up a huge API bill?**
A hard, standing rule requires explicit per-instance human approval before any real API call is made in development — enforced structurally, not just by policy: a pytest fixture blocks all real Anthropic calls by default, and a hard ceiling caps real calls per test session, printing a running count live.

**Q: How was accuracy actually measured?**
Against independent human BCBA-authored ground-truth checklists for 3 real patients, re-verified after every fix round against the same real documents, tracking blocking compliance failures as the headline metric — not a generic accuracy percentage.

**Q: What's the biggest real bug you found and fixed?**
Several judgment-layer output-shape bugs where valid page citations were being dropped or under-merged because the merge code didn't anticipate every real shape the model could return (e.g., a bare int page next to list-shaped evidence) — found via live runs against a real reconstructed PDF, not synthetic tests, and fixed by widening the merge logic plus adding a hallucination check that removes any cited page that doesn't actually contain the claimed text.

**Q: Who built this?**
One person, over about two months (36 commits, 2026-07-20 to 2026-09-25), directing requirements, compliance/business policy decisions, and real-document verification, using an AI coding agent for implementation under that direction.

---

## 30-second explanation

"I built a healthcare-compliance review system for ABA treatment plans. It runs uploaded PDFs through ~178 compliance rules — some deterministic code checks, some AI judgment calls using a 5-way majority vote for reliability — and produces a draft review a human then corrects and finalizes into a locked, scored record. Human override always wins, and finalize is permanent by design."

## 1-minute explanation

"It's a three-part system: a FastAPI/Postgres backend, a React frontend, and a standalone Python pipeline that does the actual document analysis. A reviewer uploads a treatment plan plus a required supporting document; the pipeline extracts fields, runs deterministic checks where possible, and escalates anything ambiguous to Claude, using a 5-way majority vote so a single flaky model call can't produce a false-confident wrong answer. The result is a draft: a human reviewer works through it, corrects anything wrong, and only then finalizes it — which locks the record permanently, since there's no un-finalize by design. Every mutation is audit-logged, nothing is hard-deleted, and I built in a hard rule plus enforced ceiling so real API spend never happens without my explicit approval. I verified accuracy against real BCBA-authored ground truth on 3 real patients across multiple fix rounds."

## 2-minute technical explanation

"The pipeline: intake via pypdf → a real Anthropic call to extract the mandatory supporting document's fields → a text-length heuristic flags likely image-only pages → PyMuPDF selectively renders only those pages plus vision-required sections at 120 DPI → field extraction → rule scope filtering by payor/plan type → 189 total rules (178 active), split into 90 deterministic (84 with real Python checkers, 6 auto-escalating) and 88 judgment-only. Deterministic checks run for free; anything low-confidence, uncertain, `not_checkable`, or judgment-typed escalates to Claude Sonnet 5 under a 5-way majority vote requiring 4/5 agreement — real disagreement surfaces as an honest 'uncertain' with actual evidence shown, not a coin-flip. A stabilization list forces genuinely unreliable rule types (image/graph-dependent or subjective ones) to a deterministic uncertain template instead of spending on an unstable vote. Results go through page-recovery retries and deterministic-regex humanization, then merge into `rule_results`. On the backend side: real per-user JWT auth, no hard deletes, same-transaction audit logging via one shared helper, immutable published rule snapshots that only new uploads pick up, draft-only overrides, and an irreversible finalize gated on zero remaining `uncertain` results plus an echoed reference_id check. Deployment is manual (build → push → SSH → compose up → conditional migration), zero-trust, Cloudflare-Tunnel-routed, no CI/CD. Real API spend is structurally capped in tests via an autouse pytest fixture and a per-session call ceiling, on top of a standing rule requiring my explicit per-instance approval for any real call."

---

## Important numbers to remember

| Fact | Number |
|---|---|
| Total rules | 189 |
| Active rules | 178 |
| Active categories | 31 |
| Active deterministic rules | 90 |
| ...with a real code checker | 84 |
| ...deterministic but no checker (auto-escalate) | 6 |
| Active judgment rules | 88 |
| Rules dependent on previous-TP comparison | 5 |
| Judgment-layer vote | 5 calls, need 4 agreeing |
| Page-recovery retry attempts | up to 2 |
| Default retention window before purge | 30 days |
| JWT expiry | 12 hours |
| Default real-API test-session call ceiling | 4 |
| Alembic migrations | 18 (head `fa88ba8840b9`) |
| Git commits (this project) | 36, single author, ~2 months (2026-07-20 to 2026-09-25) |

## Technologies to be able to explain

FastAPI, SQLAlchemy, Alembic, Postgres, Pydantic, JWT auth (PyJWT + passlib/bcrypt), APScheduler, pypdf, PyMuPDF, the `anthropic` Python SDK, React 19, TanStack Router/Query, Tailwind v4, Radix UI, Vite, Vitest, Docker Compose, Cloudflare Tunnel.

## Difficult follow-up questions and good answers

**Q: What's your actual measured accuracy rate, as a single number?**
There isn't one clean aggregate number in the project — accuracy is tracked per real patient against BCBA ground truth, with the headline metric being blocking-issue resolution (3/3, 6/8, and 4/4 across the three tracked patients after fixes), not a single percentage. *(needs confirmation if a blended number is wanted for a specific audience.)*

**Q: How do you handle model non-determinism / hallucination risk?**
5-way majority voting for judgment calls, a page-recovery retry pass, and a hallucination check that strips any cited page that doesn't actually contain the claimed evidence text — plus mandatory human review before anything is final.

**Q: What was the hardest bug, technically?**
The judgment-layer merge logic assuming a fixed output shape from the model when the model's real output varied (single int vs. list pages, string vs. list evidence) — found only by running against real documents, not synthetic tests, which is why the fix rounds emphasized live verification over assumed correctness.

**Q: Why no CI/CD?**
A deliberate scope/scale decision for a small, single-operator system — deploys are manual and documented rather than automated, trading automation for tight, direct control given no team to coordinate across.

**Q: What would you build next if you kept going?**
The supporting document is currently display-only — extraction and pipeline consumption of it is a planned, not-yet-built next step (explicitly noted as such in the project's own invariants doc).

**Q: Isn't 5x the API calls for every judgment rule expensive?**
Yes, materially more than a single call — and that tradeoff was made deliberately for reliability, with the real cost governed by explicit per-instance spend approval and a hard per-session ceiling in testing, rather than left uncontrolled.
