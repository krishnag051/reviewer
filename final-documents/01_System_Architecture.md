# BrightPath Treatment Plan Review — System Architecture

## What the system does

BCBAs upload a treatment plan (TP) PDF for a patient, along with the session notes that back the assessment portion of that TP. The system automatically reviews the document against 120 real compliance rules spanning every section of a Master Faster treatment plan — template formatting, report information, patient/provider info, hours requesting, school and ABA schedule, biopsychosocial information, problem areas, assessment of current functioning, clinical interpretation, barriers to treatment, the behavior intervention plan, preference assessment results, mastered goals, goals in progress, parent/caregiver involvement, coordination of care, transition plan, discharge criteria, signatures, and data sheets — plus payor-specific rules for Healthfirst, Emblem, Empire, Aetna, and Straight Medicaid.

Each of the 120 rules produces one of five outcomes: Pass, Fail, Uncertain, Not Checkable, or N/A — each with a specific evidence quote and exact page citation, so a reviewer can verify any finding without re-reading the whole document.

## The three layers

**1. Deterministic checkers.** A large portion of rules — anything that's a factual, structural, or arithmetic question (are the hours consistent, is the signature date within range, is a field blank, does a highlighter color appear on the page) — are answered by Python code that extracts the relevant field and computes the answer directly. No model call, no cost, no ambiguity. Examples: hours-vs-schedule matching, auth-date 6-month window arithmetic, blank-field detection, highlight-color detection, embedded-reviewer-comment detection.

**2. Judgment layer (real Claude, self-consistency checked).** Rules that require actual clinical or contextual judgment — is this rationale specific enough, is this goal written in proper behavioral terms, are two service types clearly differentiated — are answered by a real call to Claude. Every judgment-tier rule is checked twice, independently, with identical input. If both calls agree, that's the answer. If they disagree, the rule is reported as Uncertain rather than guessing — the system is designed to say "I don't know" honestly rather than produce a false-confident wrong answer.

**3. Hybrid checks.** Some rules use a deterministic pre-check to catch the clear-cut cases (an exact contradiction between two fields, a literal duplicate) and fall back to judgment only for the ambiguous remainder — combining the reliability of code with the flexibility of a model where it's actually needed.

## Session notes cross-referencing

Separately from the TP itself, uploaded session-note PDFs are parsed to extract session date, session location, telehealth location (clinician and patient), and assessment activity — each field tagged with a confidence level and the exact source quote it came from. These extracted fields are then cross-referenced against the TP's own stated assessment date and testing tool, closing several rules that would otherwise be marked "unable to verify" in a manual review.

## Cost discipline

Every rule's real judgment call uses paid, production-grade Claude — this is what actually reviews a real patient's document. All development and regression testing, by contrast, is run against OpenRouter's free tier, so that iterating on the rule logic itself never costs real money. This separation has been enforced consistently across every round of development.

## Stack

- **Agent-making pipeline** (Python): deterministic field checkers, the judgment-layer prompt and self-consistency wrapper, session-note extraction, and the full rule set (`rules.json`).
- **Backend** (Python/FastAPI, PostgreSQL): stores patients, versions, uploads, and rule results; orchestrates a real upload through the pipeline; exposes the review data to the frontend via REST endpoints.
- **Frontend** (React/Vite): the reviewer-facing UI — upload flow, collapsible result cards per rule across Pass/Fail/Uncertain/N-A tabs, page-jump links tied to each evidence citation, CSV export, session-notes panel, and a dashboard of real (not mock) review activity.

## How a real review flows end to end

1. A BCBA uploads a TP PDF (and any session notes) through the frontend.
2. The backend stores the files, creates an `Upload` record, and calls into the agent-making pipeline.
3. The pipeline extracts the document's text and structured fields, runs all 120 deterministic and hybrid checks, and dispatches the judgment-tier rules to Claude with self-consistency checking.
4. Results — one row per rule, each with a status, page citation, and evidence quote — are written back to the database.
5. The frontend renders the results as collapsible cards per status tab, lets a reviewer override any finding, and can export the full result set as a CSV (rule ID, rule name, category, status, page, evidence, override flag) for offline review.

## Accuracy verification methodology

Every material change to the rule-checking logic is verified two ways before being considered done: first, on synthetic test documents built specifically to prove the fix works in both directions (catches the real problem, doesn't false-positive on legitimate content); second, by re-running an actual real patient's treatment plan and comparing the system's output line by line against that same document's independently-written, human BCBA ground-truth checklist. See the companion accuracy report for the real numbers from this process.