# Judgment Rules Reference

Written 2026-10-08, directly against the real, current codebase (`agent-making/agent/pipeline/judge.py`, `pipeline/__init__.py`, `pipeline/fields.py`, `rules/rules.json`) — not from memory. Permanent, standing reference. Updated 2026-10-09 (Round 20) to reflect real fixes made that round — see the dated notes inline below.

**Scope of this file**: every rule that goes through the AI judgment layer at all. As of Round 20, that's **93 rule_ids**: the **88 rules genuinely labeled `check_type: "judgment"`** in `rules.json`, plus **5 rules labeled `deterministic` with no real checker built** (`QA-MAST-01`, `QA-MAST-02`, `QA-COC-03`, `QA-COC-05`, `EMP-02`) — these always escalate to this same layer on every run, so for behavioral purposes they belong here, not in `DETERMINISTIC_RULES_REFERENCE.md`. (`QA-ACF-01` moved OUT of this list in Round 20 — a real checker now exists, see `_check_ACF01` in `fields.py`; it no longer always escalates.) Of the remaining 5, `QA-COC-03`/`QA-COC-05`/`EMP-02` each carry their own `blocked_status` note in `rules.json` explaining a real, confirmed reason no safe deterministic checker exists yet (an unconfirmed field shape, a garbled/unparseable real source field, or a genuine scope ambiguity confirmed against real documents) — this is a deliberate, documented decision, not an overlooked gap; only `QA-MAST-01`/`QA-MAST-02` resolve deterministically some of the time (via `previous_tp_comparison.py`, see §5).

## 1. The real, literal prompt text sent to the model

This is **not a paraphrase** — it is the literal text built by `pipeline/judge.py::_build_prompt`, sent once per judgment call (the SAME text for every rule in the batch; only the `rules_summary` JSON block at the end differs per rule). Quoted here verbatim, from the function's own source:

> You are reviewing an ABA Treatment Plan (TP) against a set of compliance rules. For each rule below, determine pass / fail / uncertain / not_applicable / not_checkable, grounded in the actual document text and images provided — never guess, and use 'uncertain' rather than a confident-sounding guess when the evidence is genuinely ambiguous.
>
> Where a rule includes a 'params' object, treat those values as the exact, authoritative thresholds for that rule (e.g. an age cutoff or a numeric cap) — use them directly rather than re-deriving numbers from the prose description.
>
> Where a rule includes a non-null 'additional_real_data' value, that is real data collected specifically for this upload (e.g. a reviewer's own typed intake answer) — not part of the TP document itself, but genuinely real, current information you should actually compare against/reason with for that rule, not ignore.
>
> IMPORTANT: no previous finalized version of this patient's TP is available for this run (standalone prototype, no backend integration yet). Any rule that depends on comparing against a prior TP version must be answered 'not_checkable' with evidence saying so — do not fabricate a prior version.
>
> **(Round 20, 2026-10-09, REAL FIX — Part C item 1):** this paragraph is now SCOPED, not sent on every call. Confirmed via direct code read: it used to be sent on every single judgment call, for all ~93 rule_ids that ever reach this function, including the ~88 that have nothing to do with a previous TP at all. `judge.py::_build_prompt` now builds this paragraph conditionally — it appears in a batch's prompt only when at least one of the 5 rule_ids that genuinely need it (`_PREVIOUS_TP_DEPENDENT_RULE_IDS` = `QA-MAST-01`, `QA-MAST-02`, `QA-RPT-05`, `QA-ACF-04`, `QA-PROB-04`) is actually in that batch. Verified directly: a batch containing only `QA-AI-01` no longer includes this sentence; a batch containing `QA-MAST-01` still does.
>
> RELATED, MORE GENERAL POINT: if a rule's own description or notes describe checking a value against a NAMED EXTERNAL SOURCE that is not itself provided to you anywhere in this prompt — a maintained CPT billing-code reference guide, CentralReach, a coordinator's email, the Learning Tree, an insurance/payor verification system, a provider credentialing roster, or any other named external system or document — you were not given that resource. Recognizing that a code or value LOOKS like a generically plausible/standard one is NOT the same as having actually checked it against the specific source the rule names. For a rule like this, report what you CAN genuinely verify, but set the result to 'uncertain' or 'not_checkable' for the rule's actual external-comparison claim.
>
> Before finalizing each finding, check that your evidence text is consistent with the result you chose... Set evidence_supports_result to true only when this check genuinely passes for that finding. If it doesn't, change result to 'uncertain' (and update the evidence to match) so the finding is honest the first time.
>
> If a rule's problem shows up as a distinct, page-specific issue on more than one page, set evidence to a list of {page, detail} objects... When a rule's violation is a REPEATING PATTERN across many pages, enumerate every page where it actually recurs... do not cite only one or a few representative examples.
>
> WRITING STYLE: write every evidence/detail string short and direct — state the finding, back it with the minimum quote or reference needed, then stop. No restating the rule/question, no hedging preamble.
>
> PAGE CITATIONS INSIDE EVIDENCE TEXT: ... use exactly one format, every time: the tag [Page N] — e.g. [Page 12]. Never write 'page 12', 'pages 12-14', 'p. 12', or a comma/range list.

Followed by the literal rules JSON block (`rule_id`, `category`, `description`, `notes`, `params`, `additional_real_data` for every rule in this batch), then the full extracted page text in page order (`--- Page {N} ---\n{page text}`), then — only when at least one page was rendered as an image for this batch — a labeled block of rendered page images (`--- Rendered page {N} ---` followed by the actual PNG).

## 2. What context is handed alongside the prompt

- **Every page's extracted text** (via `pypdf`), always, for every judgment call — the model sees the whole document's text, not just the rule-relevant section, every time.
- **Rendered page images** (PyMuPDF, 120 DPI) — but only for a SUBSET of pages: (a) pages flagged "low-text" by a text-length heuristic (likely scanned/image-only — this heuristic does not itself look at the image, it just measures how little extractable text a page has), and (b) pages registered in `fields.py::VISION_ELIGIBLE_RULE_SECTIONS` for a rule that's active in this batch (see §4 below) — regardless of whether that page is otherwise text-heavy.
- **`params`** — the rule's own exact thresholds from `rules.json`, sent as structured data, not just prose.
- **`additional_real_data`** — rule-specific extra context injected by a caller (e.g. a reviewer's own typed intake answer) via `review_treatment_plan`'s `extra_rule_context` parameter. `None` for the large majority of rules.
- **Supporting-document fields** — NOT sent to every rule by default (a deliberate design choice, Round 55): only a small, specific set of rules that come back uncertain/not_checkable on their first pass get a scoped, second follow-up call carrying just the supporting-document fields relevant to THAT rule (`pipeline/supporting_doc_resolution.py`).

## 3. Single call vs. 5-way consensus vs. stabilized (never calls the model at all)

Three genuinely different mechanisms decide a judgment-type rule's final answer, and which one applies depends on which list a rule_id is in:

1. **The production default — 5-way majority vote.** `pipeline/__init__.py`'s real call site uses `judge.run_judgment_checks_majority_vote(..., n_calls=5, min_agreement=4)`. Every rule_id in the batch gets the SAME 5 independent calls (same prompt, same images, no caching between them). For each rule_id, if 4 or more of the 5 calls agree on the same `result`, that result wins (the specific finding kept is whichever of the 4+ agreeing calls has a real page citation, preferred over one without). If fewer than 4 agree, the rule resolves to `"uncertain"`, with evidence synthesized from the real, actual disagreement (what each distinct side concluded) — never a placeholder.
2. **Stabilized rules — zero model calls, ever.** `pipeline/__init__.py::STABILIZED_UNCERTAIN_RULE_IDS` (currently **17 active rule_ids** — see the table below) are pulled OUT of the real judgment call entirely before it's even made. Each resolves to a fixed `"uncertain"` finding via `_stabilized_uncertain_finding`, with a zero-cost, deterministic text-scan preview of the document's own real relevant data (via `fields.py::CONTEXT_PREVIEW`, e.g. each goal's own Baseline/Current Data/Mastery Criteria/Status fields) appended so a reviewer isn't starting from nothing — but the VERDICT itself is always `"uncertain"`, never actually decided by a real call. This list exists because these specific rule_ids were directly measured (a real, multi-call experiment) to be genuinely unstable — flipping verdict across repeated identical calls — and a stable, honest "needs human review" was judged better than an unstable pass/fail for a compliance tool. Rules get added to or removed from this list only after a real, measured stability check against a real document.
3. **A separate, legacy list — REMOVED (Round 20, 2026-10-09, Part C item 2).** `judge.py::MAJORITY_VOTE_RULE_IDS` (5 rule_ids: `QA-GIP-06`, `QA-HRS-07`, `QA-GIP-07`, `QA-HRS-09`, `QA-PROB-01`) and its `should_use_majority_vote()` helper used to exist in the codebase but were never read by any real call site (confirmed by direct code search, not just the function's own comment). The idea this represented — apply extra self-consistency calls only to rule_ids with confirmed real instability, not uniformly — was superseded by a different, simpler design that DID ship: the universal 5-way vote (mechanism 1 above) applies to every rule in every batch, so a selective allow-list for a cheaper partial version of that idea had nowhere left to plug into. Dead code deleted, along with its dedicated test file (`tests/test_majority_vote_scoping.py`, which also asserted the stale "exactly 2 calls" figure this file's own history has separately flagged as outdated).

### The 17 currently stabilized rule_ids (zero model calls, always `"uncertain"`)

`QA-GIP-14`, `QA-AI-03`, `QA-BIP-09`, `QA-BIP-10`, `QA-BIP-12`, `QA-COC-07`, `QA-GIP-02`, `QA-GIP-20`, `QA-GIP-23`, `QA-GIP-25`, `QA-GIP-27`, `QA-GIP-34`, `QA-GIP-35`, `HF-05`, `QA-ACF-03`, `QA-PPI-05`, `QA-GIP-11`

Round 19 (2026-10-08) found a real, confirmed-tolerable spelling-typo mismatch behind part of why `QA-BIP-09`/`QA-BIP-10` keep landing here (a document spelling "Aggression" as "Agression" in one of the two fields these rules compare) — a narrow, targeted fix (`_fold_doubled_letters`) was added to the ADJACENT deterministic rule this shares a root cause with (`QA-BIP-08`), but `QA-BIP-09`/`QA-BIP-10` themselves were deliberately left on this stabilized list this round (per that round's own explicit scope decision) rather than built out as full new deterministic checkers — they still resolve to a fixed `"uncertain"` today.

**Important cross-file nuance, confirmed directly against `pipeline/__init__.py` (not from the generated table below, which under-reports this):** the 17 stabilized rule_ids above are not all `check_type: "judgment"` in `rules.json`. Two of them — `QA-PPI-05` and `QA-GIP-23` — are labeled `check_type: "deterministic"` and DO have a real checker function registered in `fields.py::DET_CHECKS` (confirmed directly: both are present, so they count toward the 84 deterministic-with-checker figure in `DETERMINISTIC_RULES_REFERENCE.md`). But per that stabilization list's own code comment (`pipeline/__init__.py`, Round "Eliminate Coin-Flipping, For Real, Before Production"), these two checkers' real, confirmed-on-a-real-document behavior is to escalate almost every time (`needs_escalation()` — confidence below threshold, or a not_checkable/uncertain result), and whenever they do, the stabilization filter forces the final answer to `"uncertain"` regardless of what the judgment layer would have said. Net effect: for practical purposes, these 2 rule_ids behave like fixed-`"uncertain"` rules too, even though they're nominally deterministic — a reader of only the Deterministic file would not know this without this cross-reference.

## 4. Vision/image access — full, specific honesty per vision-eligible rule

`fields.py::VISION_ELIGIBLE_RULE_SECTIONS` is the ONLY mechanism that gets a rule's own relevant page rendered as an image and attached to the judgment call, for a reason OTHER than the page being generically low-text. **16 rule_ids are currently registered**:

| Rule ID | Registered section | What this actually means |
|---|---|---|
| QA-ACF-03 | (via stabilized context) | Assessment grid/legend image — stabilized (always uncertain, see §3); the image IS sent, but the verdict is never actually decided by reading it, only previewed as context text. |
| QA-ACF-04 | milestone-grid image | Previous-TP score comparison — a REAL vision call: `previous_tp_comparison.py::_extract_acf_score_vision` renders the milestone grid and asks the model to read a numeric score directly off the image, falling back to narrative-text extraction only if the vision read fails. This is a genuinely different, narrower call than the main judgment batch. |
| QA-ACF-06 | — | Has a real deterministic checker (see other file) — vision registration here is a secondary fallback path only reached if the deterministic checker itself escalates. |
| QA-ACF-07 | — | Same as ACF-06: primarily deterministic. |
| QA-ACF-11 | (via stabilized context) | Vineland-legend image — stabilized. |
| QA-GIP-02 | goal graph | 3mo/6mo graph-data-vs-auth-length check — stabilized (§3): the graph image is sent, but this rule never actually resolves past "uncertain" on its own; a reviewer must read the graph themselves. |
| QA-GIP-28 | goal graph | "Fewer than 3 real data points" — stabilized. The model IS shown the real rendered graph image for this goal, but real production evidence (confirmed, Round "Judgment Layer Stability" era) shows genuine disagreement between independent calls reading the SAME image (one call: "only 1 data point visible"; another: "well over 3, no rationale needed") — this is the strongest direct evidence in this codebase that the vision read itself, not just the verdict logic around it, is inconsistent call-to-call for small/ambiguous graphs. |
| QA-GIP-29 | goal graph | "If no graph, rationale provided" — NOT stabilized; a real, live judgment call reads the rendered image to confirm graph presence/absence. Confirmed working in the sense that it resolves to a real pass/fail/uncertain rather than always escalating, but — like every vision-dependent rule here — has not been independently re-verified call-to-call for consistency this round. |
| QA-PAR-03 | goal graph (Parent Training) | "Parent Training goal data-point count" — same shape as GIP-28/HF-05, reused. |
| HF-05 | goal graph (Parent Training, filtered) | Stabilized — same `_goal_context_preview(parent_training_only=True)` text-only preview as the generic case, PLUS the real rendered graph image for Parent/Caregiver Training goal blocks specifically (filtered via `_find_parent_training_goal_blocks`, a two-tier real/fallback goal-domain matcher). Verdict still always `"uncertain"`. |
| QA-GIP-32 | goal graph (every goal) | **"Flag if a graph has fewer than 4 data points for this authorization period."** NOT stabilized — a real, live call is supposed to count real data points off the rendered image. **Round 19's own real-document evidence (`Fix Round 19` task text, Part A item 15) is the most direct, current honesty check available here**: on a real document with ~39 goal graphs, the judgment layer's reported counts ("roughly 15+", "roughly 10", "only 2-3") read as rough visual estimates, not precise counts, and the task's own framing explicitly asks "whether real vision/image access is actually wired up for these two rules specifically, and if so, why it's producing wrong or incomplete answers" — this file states plainly: **images ARE wired up and ARE sent** (confirmed via `VISION_ELIGIBLE_RULE_SECTIONS` registration and `render.py`'s real PyMuPDF rendering), but whether the model's READ of those images is reliably precise enough for an exact "fewer than 4" threshold has not been independently re-verified against ground truth this round — this is the single most important open honesty gap this file flags. |
| QA-GIP-34 | goal graph (every goal) | "Final data point matches Current Data section" — stabilized. Same open question as GIP-32/35: image is sent, read is not independently verified for precision. |
| QA-GIP-35 | goal graph (every goal), name vs. graph title | **Target name matches the graph's own title/x-axis text.** NOT stabilized. This is the other rule Round 19 specifically asked about. Same honest answer as GIP-32: the rendered image is genuinely sent (confirmed via code registration), but whether the model reliably reads a graph's title text correctly (vs. the much coarser "count the visible markers" task GIP-32/34 ask for) has not been independently verified against a real document's actual graph titles this round. The one CONFIRMED real success in this exact area: a pronoun/name mismatch in a graph's own rendered TITLE text ("...to increase HIS intraverbal skills" for a female patient) was caught by a DIFFERENT rule, `QA-AI-05` (a judgment-only grammar/spelling rule, not GIP-35), on a real document — which at least confirms the model CAN read graph title text correctly in some real cases; it does not confirm GIP-35 itself is reliable. |
| ANT-02 | goal graph | Empire/Anthem "graph data within 30 days of auth start" — same registration mechanism, not independently investigated this round. |
| EMP-02 | goal graph | One of the 6 "deterministic, no checker" rules (always escalates) — vision-eligible because the underlying question needs the graph image. |
| CIG-01 | (ABLLS A-Z completion) | Not a goal-graph registration — a different document section; not independently investigated this round. |

**Bottom line on vision, stated once, plainly**: the mechanism is real (rendering happens via PyMuPDF, images are genuinely attached to the API call, confirmed by direct code inspection) — this is not a stub or a placeholder. What is **not** independently confirmed this round is whether the model's visual READ of a graph (exact data-point counts, exact title text) is reliably precise on every real document, as opposed to a usually-right rough estimate. The one piece of hard, real evidence available (GIP-28's confirmed real disagreement between two calls reading the same image) points toward "usually right, not always precise" — which is also the entire reason GIP-28 and several siblings are on the stabilized list rather than trusted to resolve past "uncertain" on their own.

## 5. Previous-TP comparison — the 5 real rule_ids, and how it's actually combined

Despite the main judgment prompt's own text claiming "no previous finalized version... is available" (see §1's note), **previous-TP comparison is a real, live, separate mechanism** — `pipeline/previous_tp_comparison.py::compare_previous_tp_to_tp`, called from the backend layer (`app/agent_client.py::review_previous_tp`), not from inside the main judgment prompt at all. Exactly **5 rule_ids** depend on it:

- **`QA-MAST-01`/`QA-MAST-02`** — treated as **pure overrides**: their own TP-only phase-1 answer (from the main judgment batch, since these are 2 of the 6 "deterministic, no checker" rules) is always a blind guess without a previous TP, so when one IS available, `previous_tp_comparison.py`'s own answer simply replaces it entirely.
- **`QA-RPT-05`, `QA-ACF-04`, `QA-PROB-04`** — treated as **compound**: each has a real, meaningful TP-only phase-1 half (RPT-05's existing 26-week-default checker; ACF-04/PROB-04's existing judgment-layer attempt) which is COMBINED with the previous-TP-derived half via `session_note_comparison.py::combine_compound_rule_result` — the same combine function the session-notes comparison path also uses (see that module for the exact precedence rules: either side resolving a genuinely-uncertain other side wins; both-fail wins; both-not_checkable stays not_checkable).

`QA-ACF-04`'s own previous-TP half can itself make a real, narrow model call (vision-first, text-fallback — see §4) when the previous TP's own assessment score lives in an embedded image rather than text. `QA-PROB-04`'s own half (`_prob04_comparison_blocks` + a `call_tool_json` semantic read) can also make a real call. These are genuinely separate real API calls from the main 5-way judgment batch — not covered by that batch's own call count.

## 6. Full table — every rule_id, scope, and known mechanism flags

### Rules labeled `deterministic` with NO real checker (always escalate to judgment)

| Rule ID | Category | Scope |
|---|---|---|
| QA-ACF-01 | Assessment of Current Functioning | ALL/Both |
| QA-COC-03 | Coordination of Care | ALL/Initial only |
| QA-COC-05 | Coordination of Care | ALL/Both |
| EMP-02 | Empire/Anthem Specific | Empire/Both |
| QA-MAST-01 | Mastered Goals | ALL/Both |
| QA-MAST-02 | Mastered Goals | ALL/Both |

### Genuine `judgment`-type rules

| Rule ID | Category | Scope | Stabilized (never calls model)? | Vision-eligible section |
|---|---|---|---|---|
| QA-AI-01 | AI-Generated Content & Template Artifacts | ALL/Initial only |  |  |
| QA-AI-02 | AI-Generated Content & Template Artifacts | ALL/Both |  |  |
| QA-AI-03 | AI-Generated Content & Template Artifacts | ALL/Both | YES |  |
| QA-AI-04 | AI-Generated Content & Template Artifacts | ALL/Both |  |  |
| QA-AI-05 | AI-Generated Content & Template Artifacts | ALL/Both |  |  |
| QA-ACF-02 | Assessment of Current Functioning | ALL/Both |  |  |
| QA-ACF-03 | Assessment of Current Functioning | ALL/Both | YES | acf |
| QA-ACF-04 | Assessment of Current Functioning | ALL/Both |  | acf |
| QA-ACF-08 | Assessment of Current Functioning | ALL/Both |  |  |
| QA-ACF-10 | Assessment of Current Functioning | ALL/Both |  |  |
| QA-BIP-02 | BIP | ALL/Both |  |  |
| QA-BIP-03 | BIP | ALL/Both |  |  |
| QA-BIP-07 | BIP | ALL/Both |  |  |
| QA-BIP-09 | BIP | ALL/Both | YES |  |
| QA-BIP-10 | BIP | ALL/Both | YES |  |
| QA-BIP-11 | BIP | ALL/Both |  |  |
| QA-BIP-12 | BIP | ALL/Both | YES |  |
| QA-BIP-13 | BIP | ALL/Both |  |  |
| QA-BIP-14 | BIP | ALL/Both |  |  |
| QA-BIP-15 | BIP | ALL/Both |  |  |
| QA-BIO-05 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-07 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-09 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-10 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-11 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-12 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-14 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-15 | Biopsychosocial | ALL/Both |  |  |
| QA-BIO-17 | Biopsychosocial | ALL/Both |  |  |
| CIG-01 | Cigna-Specific | Cigna/Both |  | ablls_grid |
| QA-CI-01 | Clinical Interpretation | ALL/Both |  |  |
| QA-COC-01 | Coordination of Care | ALL/Both |  |  |
| QA-COC-02 | Coordination of Care | ALL/Both |  |  |
| QA-COC-07 | Coordination of Care | ALL/Both | YES |  |
| QA-DS-02 | Data Sheets | ALL/Both |  |  |
| QA-DISC-01 | Discharge Criteria | ALL/Both |  |  |
| QA-DISC-02 | Discharge Criteria | ALL/Both |  |  |
| QA-DISC-03 | Discharge Criteria | ALL/Both |  |  |
| EMB-02 | Emblem-Specific | Emblem/Both |  |  |
| EMP-04 | Empire-Specific | Empire/Both |  |  |
| ANT-02 | Empire/Anthem Specific | Anthem/Both |  | gip_graph |
| QA-GIP-01 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-02 | Goals in Progress | ALL/Both | YES | gip_graph |
| QA-GIP-06 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-08 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-09 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-11 | Goals in Progress | ALL/Both | YES |  |
| QA-GIP-12 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-14 | Goals in Progress | ALL/Both | YES |  |
| QA-GIP-15 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-18 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-20 | Goals in Progress | ALL/Both | YES |  |
| QA-GIP-24 | Goals in Progress | ALL/Both |  |  |
| QA-GIP-25 | Goals in Progress | ALL/Both | YES |  |
| QA-GIP-27 | Goals in Progress | ALL/Both | YES |  |
| QA-GIP-28 | Goals in Progress | ALL/Both |  | gip_graph |
| QA-GIP-29 | Goals in Progress | ALL/Both |  | gip_graph |
| QA-GIP-32 | Goals in Progress | ALL/Both |  | gip_graph |
| QA-GIP-34 | Goals in Progress | ALL/Both | YES | gip_graph |
| QA-GIP-35 | Goals in Progress | ALL/Both | YES | gip_graph |
| HF-03 | Healthfirst-Specific | Healthfirst/Both |  |  |
| HF-05 | Healthfirst-Specific | Healthfirst/Both | YES | gip_graph |
| HF-07 | Healthfirst-Specific | Healthfirst/Both |  |  |
| QA-HRS-04 | Hours Requesting | ALL/Both |  |  |
| QA-HRS-09 | Hours Requesting | ALL/Both |  |  |
| QA-HRS-10 | Hours Requesting | ALL/Both |  |  |
| MOL-01 | Molina-Specific | Molina/Both |  |  |
| QA-OBS-02 | Observations | ALL/Initial only |  |  |
| QA-OBS-03 | Observations | ALL/Initial only |  |  |
| QA-OBS-04 | Observations | ALL/Initial only |  |  |
| QA-PAR-01 | Parent/Caregiver Involvement | ALL/Both |  |  |
| QA-PAR-03 | Parent/Caregiver Involvement | ALL/Both |  | gip_graph |
| QA-PPI-01 | Patient/Provider Info | ALL/Both |  |  |
| QA-PPI-04 | Patient/Provider Info | ALL/Both |  |  |
| QA-PROB-03 | Problem Areas | ALL/Both |  |  |
| QA-RPT-03 | Report Information | ALL/Both |  |  |
| QA-PREF-01 | Results of Preference Assessment | ALL/Both |  |  |
| QA-PREF-02 | Results of Preference Assessment | ALL/Both |  |  |
| QA-SCH-02 | School & ABA Schedule | ALL/Both |  |  |
| QA-SCH-08 | School & ABA Schedule | ALL/Both |  |  |
| QA-SCH-10 | School & ABA Schedule | ALL/Both |  |  |
| QA-SIG-01 | Signatures | ALL/Both |  |  |
| QA-SIG-05 | Signatures | ALL/Both |  |  |
| QA-SIG-06 | Signatures | ALL/Both |  |  |
| QA-TEMP-02 | Template | ALL/Both |  |  |
| QA-TRANS-01 | Transition Plan | ALL/Both |  |  |
| QA-TRANS-02 | Transition Plan | ALL/Both |  |  |
| QA-TRANS-03 | Transition Plan | ALL/Both |  |  |

## Honest gaps in this file

- This file documents the REAL MECHANISM (prompt, context, vote structure, vision wiring) in full, direct detail — it does **not** claim to have independently re-verified every one of the 94 rule_ids' actual real-document accuracy this round; that is a separate, ongoing, document-by-document ground-truth exercise (see `final-documents/02_Accuracy_Results.md`).
- The per-rule table below gives scope/stabilization/vision flags only — it does not repeat each rule's own `description`/`notes` (already fully, accurately listed in `rules.json` itself and in the Deterministic file's sister table for cross-reference); duplicating ~94 descriptions here verbatim was judged lower-value than keeping this file focused on MECHANISM, which is the part that isn't already visible elsewhere.
- §4's vision honesty section is the most carefully-hedged part of this file by design — it is the one area Krishna specifically asked for full honesty on, and this file errs toward stating "not independently verified" rather than implying confidence that hasn't been earned.
