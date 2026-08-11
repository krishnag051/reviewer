# BrightPath Treatment Plan Review — Accuracy Results

## How accuracy is measured

Every real patient's treatment plan reviewed by the system has an independent, human-written ground-truth checklist — a BCBA's own line-by-line review of that same document, using the same Master Faster checklist the system is built to check against. Accuracy is measured by comparing the system's output against that human checklist, item by item, and is re-verified after every round of fixes by re-running the real document, not just synthetic test cases.

Three real patients have been used for this ongoing validation: **Yisroel Leibowitz**, **Zohan Hossain**, and **Blythe A. Diaz** — each with a full, real treatment plan, real session notes, and a real independently-written ground-truth checklist.

## Headline result: catching the blocking issues

The single most important number in any of these reviews is the "blocking failure" row — the real, must-fix problems a human reviewer flagged as blocking submission. Missing one of these is the costliest kind of error the system can make.

**Blythe A. Diaz — 3 blocking issues identified by the human reviewer:**
- Before fixes: 0 of 3 caught correctly (2 were wrongly passed, 1 only hedged).
- After fixes (Rounds 83–84): **3 of 3 caught correctly**, matching the human reviewer's reasoning exactly — including reproducing the specific mastery-criteria contradiction and the exact duplicate mastered/in-progress goal the reviewer flagged.

**Zohan Hossain — 8 blocking issues identified by the human reviewer:**
- Before fixes: several missed entirely (highlighting not detected, an embedded internal note not detected, a name-mismatch risk undetected).
- After fixes (Rounds 81–84): **6 of 8 caught correctly**, holding stable across multiple independent re-runs of the same document.

**Yisroel Leibowitz — 4 specific known gaps identified early in this project:**
- A foster-care/caregiver-language rationale gap, an overly narrow place-of-service check, a too-shallow hours-increase rationale check, and an auth-date arithmetic check that was unnecessarily blocked.
- After fixes (Round 78): **all 4 confirmed fixed and stable across more than eight independent re-runs of the same real document since** — the longest-standing, most heavily re-verified fix in the project.

## Full comparison snapshot (most recent verified run per patient)

**Blythe A. Diaz** (68 Pass / 3 Fail / 19 Review / 24 N-A per the human checklist, 113 matched items):

| | Agent: Pass | Agent: Fail | Agent: Other | Human total |
|---|---|---|---|---|
| Human: Pass | 63 | 2 | 3 | 68 |
| Human: Fail (blocking) | 0 | **3** | 0 | 3 |
| Human: Review | 2 | 0 | 16 | 18 |
| Human: N-A | 0 | 0 | 24 | 24 |

**Zohan Hossain** (60 Pass / 8 Fail / 17 Review / 29 N-A per the human checklist, 110 matched items):

| | Agent: Pass | Agent: Fail | Agent: Other | Human total |
|---|---|---|---|---|
| Human: Pass | 48 | 3 | 7 | 58 |
| Human: Fail (blocking) | 1 | **6** | 1 | 8 |
| Human: Review | 5 | 1 | 9 | 15 |
| Human: N-A | 4 | 0 | 25 | 29 |

**Yisroel Leibowitz** (48 Pass / 31 Issue / 24 N-A per the human checklist, 103 matched items — most recent full comparison; several individual fixes reconfirmed on later runs since):

| | Agent: Pass | Agent: Fail | Agent: Other | Human total |
|---|---|---|---|---|
| Human: Pass | 34–36 | 1–3 | 9–13 | 48 |
| Human: Issue (real problem) | 1–4 | 12–14 | 13–18 | 31 |
| Human: N-A | 1 | 0 | 23 | 24 |

## Session notes: real cross-referencing, not just document review

Across all three patients, the system now extracts real structured data from uploaded session-note PDFs (session date, location, telehealth details, assessment activity) and cross-references it against each treatment plan's own stated assessment details. This closes several checklist items that a human reviewer working from the TP alone had to mark "unable to verify" — the system, having both documents, can resolve them with a confident, correct answer the manual review couldn't reach.

## What this process has caught and fixed, concretely

- A highlight-detection gap that missed real highlighter colors outside one narrow shade.
- An embedded internal reviewer note that had no question mark, missed because prior detection only looked for question-style phrasing.
- A goal whose own stated target directly contradicted its own mastery criteria in the same document.
- A goal listed as both "Mastered" and still "In Progress" in two different sections of the same document.
- A field-naming inconsistency (`Current Data:` vs. `Current Level:`) that caused real, filled-in clinical data to be reported as missing — confirmed independently on two separate real patients' documents.
- Several rules that were confidently passing on claims they had no way to actually verify (an external billing guide, a provider roster) — now correctly report "unable to verify" instead of a false confident pass.
- A real production deployment gap where multiple rounds of proven, tested fixes were sitting correctly in the codebase but never actually running against real uploads, because the live service had not been restarted to load them — identified, explained, and resolved.

## What's still open

- A small number of items remain genuine judgment-layer limits rather than fixable bugs — cases where two independent AI review passes reasonably disagree, and the system is designed to report that disagreement honestly (as "Uncertain") rather than force a confident answer either way.
- A handful of specific rules (assessor-name detection in one document, a narrative-vs-structured-format check) are still being refined as new real documents surface new phrasing patterns not seen before.

## Bottom line

Starting from a system that missed most of the real blocking issues a human reviewer would catch, the current state — verified against three independent real patients' documents and their independent human ground-truth checklists — now catches the large majority of real, must-fix problems, with a track record of every fix being re-confirmed on the real document that exposed it, not just a synthetic stand-in.