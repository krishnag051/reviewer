# Rule Methodology Report

Generated directly from `agent-making/agent/rules/rules.json` (the single source of truth), cross-referenced against `pipeline/fields.py`'s real `DET_CHECKS` registry and `pipeline/judge.py`'s `MAJORITY_VOTE_RULE_IDS`. Every rule below is currently `active: true`. Each deterministic entry's mechanism summary is drawn from that checker function's own docstring (first paragraph, round/date references stripped) — not a generic restatement of the checklist wording.

**173 active rules total** — **64 deterministic** (51 with a real code checker, 13 labeled deterministic but with no checker built — these escalate to judgment automatically every time), **109 judgment**.

**Note on category count**: this rule set currently spans **29 categories** (listed below in the order used throughout this report), not 26 — flagged as a real, current discrepancy rather than silently matching an outdated number; see the accompanying message for detail.

---

## Table of contents
- [Template](#template) (6)
- [Report Information](#report-information) (7)
- [Patient/Provider Info](#patientprovider-info) (7)
- [Biopsychosocial](#biopsychosocial) (15)
- [Assessment of Current Functioning](#assessment-of-current-functioning) (12)
- [Problem Areas](#problem-areas) (4)
- [Goals in Progress](#goals-in-progress) (29)
- [Mastered Goals](#mastered-goals) (4)
- [BIP](#bip) (14)
- [Barriers to Treatment](#barriers-to-treatment) (1)
- [Discharge Criteria](#discharge-criteria) (3)
- [Transition Plan](#transition-plan) (3)
- [Hours Requesting](#hours-requesting) (10)
- [School & ABA Schedule](#school--aba-schedule) (9)
- [Coordination of Care](#coordination-of-care) (7)
- [Data Sheets](#data-sheets) (2)
- [Observations](#observations) (4)
- [Parent/Caregiver Involvement](#parentcaregiver-involvement) (3)
- [Results of Preference Assessment](#results-of-preference-assessment) (2)
- [Clinical Interpretation](#clinical-interpretation) (1)
- [Signatures](#signatures) (6)
- [AI-Generated Content & Template Artifacts](#ai-generated-content--template-artifacts) (5)
- [Healthfirst-Specific](#healthfirst-specific) (8)
- [Cigna-Specific](#cigna-specific) (1)
- [Molina-Specific](#molina-specific) (1)
- [Aetna-Specific](#aetna-specific) (1)
- [Emblem-Specific](#emblem-specific) (2)
- [Empire-Specific](#empire-specific) (4)
- [Straight Medicaid-Specific](#straight-medicaid-specific) (2)

---

## Template

### `QA-TEMP-01` — Limited permit holder -> correct template used, credentials correct throughout
*check_type: deterministic*

Converted from judgment to deterministic : the rule's own notes already split this into "LLM extracts credential type + all credential mentions; DET compares them for consistency" -- the extraction half is itself a fixed pattern (a 'Certification:' or 'Provider Credentials:' labeled field), so there's no LLM step needed at all.

### `QA-TEMP-02` — TP includes header and page numbers on all pages
*check_type: judgment*

Asks the model: *TP includes header and page numbers on all pages*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-TEMP-03` — All highlights removed
*check_type: deterministic*

(`_check_TEMP03`'s docstring just restates the rule text, adding no real mechanism detail beyond it — code-level detail not available without reading the function body directly.)

### `QA-TEMP-04` — All correspondence with BCBA removed
*check_type: deterministic*

Converted from judgment to deterministic -- fixing a confirmed regression where this rule's behavior had narrowed to only recognizing email-header-style text. See _find_embedded_reviewer_comments's own docstring for the full diagnosis and mechanism. ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-TEMP-05` — 'RBT' changed to 'RBT/BT' or 'BT'
*check_type: deterministic*

(`_check_TEMP05` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *'RBT' changed to 'RBT/BT' or 'BT'*.)

### `QA-TEMP-06` — Empty fields should be marked N/A rather than left blank
*check_type: judgment*

Asks the model: *Empty fields should be marked N/A rather than left blank*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Report Information

### `QA-RPT-01` — All fields completed
*check_type: deterministic*

Round 94, item 1: _find_blank_labels now returns (label, debug_suffix) pairs rather than bare label strings -- the debug_suffix (surrounding text context + is_last_line_of_page) is folded directly into this rule's own evidence/Detail text below, so it reaches the CSV export automatically on a real run with zero extra steps.

### `QA-RPT-02` — Date of initial assessment pulled onto TP
*check_type: deterministic*

(`_check_RPT02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Date of initial assessment pulled onto TP*.)

### `QA-RPT-03` — Dates of current report match 97151 session notes
*check_type: judgment*

Asks the model: *Dates of current report match 97151 session notes*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-RPT-04` — Auth dates requested within 2 days of submission
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-RPT-04` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Auth dates requested within 2 days of submission*).

### `QA-RPT-05` — Auth dates accurate (6-month default, based on previous auth end or new insurance start)
*check_type: deterministic*

Round 78, Item 4 -- REAL BUG FOUND AND FIXED: this rule was unconditionally marked not_checkable, citing "needs backend prior-TP/ auth data" -- but Ms. Yachnes's own real ground-truth review proved that's the wrong blocker: she computed the 6-month default window herself directly from THIS document's own two dates (current report end + 6 months, vs. the requested auth end),… ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-RPT-06` — End date of current report before start of auth dates requested
*check_type: deterministic*

(`_check_RPT06` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *End date of current report before start of auth dates requested*.)

### `QA-RPT-07` — Flag if requested auth range is less than a full authorization period (3-month or 6-month cycle, depending on payor)
*check_type: judgment*

Asks the model: *Flag if requested auth range is less than a full authorization period (3-month or 6-month cycle, depending on payor)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Patient/Provider Info

### `QA-PPI-01` — Patient info matches Central Reach
*check_type: judgment*

Asks the model: *Patient info matches Central Reach*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PPI-02` — Patient age correct and consistent throughout TP
*check_type: deterministic*

Converted from judgment to deterministic : the rule's own notes already describe this as "extract every age/DOB mention, compare" -- a uniqueness check over pattern-extractable fields, same shape as GIP-10/GIP-16.

### `QA-PPI-03` — Patient legal name spelled correctly throughout
*check_type: deterministic*

Converted from judgment to deterministic : the rule's own notes already say "Internal consistency = DET" -- this just builds it. Extracts every 'Patient Name:' value (both the page-1 header form 'Patient Name: X AKA: Y Patient DOB: Z' and the repeated footer form 'Patient Name: X Patient DOB: Y Patient Insurance: Z') and checks they all agree.

### `QA-PPI-04` — Patient Payor and Insurance ID correct
*check_type: judgment*

Asks the model: *Patient Payor and Insurance ID correct*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PPI-05` — Provider Credentials/NPI/License correct
*check_type: deterministic*

Converted from judgment to deterministic : the rule's own notes already say "Internal consistency = DET" -- this just builds it. Extracts every NPI and License mention and checks each set agrees. *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)* ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-PPI-06` — Narrative sections do not name a person who isn't accounted for in this document's own structured fields
*check_type: deterministic*

Fix Round, item 2 -- REAL BUG FOUND AND FIXED (general mechanism): runs spaCy NER over every narrative section this document has (see _extract_narrative_sections), collects every detected PERSON entity, and flags any whose name tokens have ZERO overlap with this document's OWN allow-list (built fresh per document, see _document_name_allow_list --…

### `QA-PPI-07` — If patient has an AKA/alias, it is included and spelled correctly alongside legal name
*check_type: deterministic*

Round 91 (169-rule reconciliation): a brand-new rule_id, deliberately NOT a repoint of QA-PPI-06 (that rule keeps its own, unrelated, already-shipped meaning -- narrative name-contamination -- see this round's own discussion).

---

## Biopsychosocial

### `QA-BIO-01` — All info completed, matches diagnostic report
*check_type: judgment*

Asks the model: *All info completed, matches diagnostic report*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-02` — Date of most recent diagnosis pulled onto TP
*check_type: deterministic*

(`_check_BIO02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Date of most recent diagnosis pulled onto TP*.)

### `QA-BIO-03` — Includes any other diagnosis if applicable; double-check against developmental history
*check_type: deterministic*

'Includes any other diagnosis if applicable' -- confirmed against real documents this is a plain presence check on the 'Secondary Diagnosis:' field, not a clinical-applicability judgment (see the rule's own notes for why the old BIO-01-derived dependency didn't actually apply here).

### `QA-BIO-05` — Developmental history and diagnosis do not contradict
*check_type: judgment*

Asks the model: *Developmental history and diagnosis do not contradict*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-06` — Medication listed -> reason stated; ADHD med = secondary diagnosis
*check_type: judgment*

Asks the model: *Medication listed -> reason stated; ADHD med = secondary diagnosis*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-07` — Educational history chronological, matches coordinator info
*check_type: judgment*

Asks the model: *Educational history chronological, matches coordinator info*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-08` — Patients <5, community daytime hours -> 'school' replaced with community/daycare/preschool
*check_type: judgment*

Asks the model: *Patients <5, community daytime hours -> 'school' replaced with community/daycare/preschool*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-09` — Patients 5+ in Special Ed -> TP indicates IEP
*check_type: judgment*

Asks the model: *Patients 5+ in Special Ed -> TP indicates IEP*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-10` — Educational history and COC do not contradict
*check_type: judgment*

Asks the model: *Educational history and COC do not contradict*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-11` — Includes any other service child is receiving
*check_type: judgment*

Asks the model: *Includes any other service child is receiving*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-12` — Includes all EI services received; if child did not receive EI, TP states that they did not receive EI
*check_type: judgment*

Asks the model: *Includes all EI services received; if child did not receive EI, TP states that they did not receive EI*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-13` — First day of ABA with MF pulled onto TP
*check_type: deterministic*

(`_check_BIO13` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *First day of ABA with MF pulled onto TP*.)

### `QA-BIO-14` — History of ABA therapy with other providers completed
*check_type: judgment*

Asks the model: *History of ABA therapy with other providers completed*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-15` — Includes school name
*check_type: judgment*

Asks the model: *Includes school name*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIO-16` — School name matches Central Reach
*check_type: judgment*

Asks the model: *School name matches Central Reach*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Assessment of Current Functioning

### `QA-ACF-01` — Date/location/patient location completed
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-ACF-01` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Date/location/patient location completed*).

### `QA-ACF-02` — Note backing assessment matches date/location
*check_type: judgment*

Asks the model: *Note backing assessment matches date/location*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-03` — Grid with legend (colors/dates/assessor) present and matches the dates of the assessment
*check_type: judgment*

Asks the model: *Grid with legend (colors/dates/assessor) present and matches the dates of the assessment*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-04` — Score lower than previous assessment -> Director tag
*check_type: judgment*

Asks the model: *Score lower than previous assessment -> Director tag*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-05` — Assessment Summary Statement is documented (not blank) and matches assessment results
*check_type: deterministic*

Assessment Summary Statement presence check -- replaces the retired Learning-Tree comparison this checklist item used to describe (see rules/archive/learning_tree_deprecated_rules.json).

### `QA-ACF-06` — Testing tool includes assessor's name
*check_type: deterministic*

Round 83, item 1 follow-up: converted from judgment to deterministic. Investigated whether the confirmed real miss (ground-truth reviewer found an assessor name -- "Administered by [name]" -- that this rule reported as not found) shared _find_acf_section's root cause above, or was a separate, narrower gap: SEPARATE. ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-ACF-07` — TP includes both old and new testing tool
*check_type: deterministic*

Converted from judgment to deterministic : diagnosed as a real, previously-unfixed bug -- the earlier "schema reorder" fix (evidence_supports_result, an earlier round) was never actually related to this rule's failure mode; that fix addressed a different, general evidence-contradicts-result problem, and this rule was never re-verified against real ground truth afterward.

### `QA-ACF-08` — Session note backs testing tool used (else forward to QA)
*check_type: judgment*

Asks the model: *Session note backs testing tool used (else forward to QA)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-09` — If a different testing tool is used than the previous auth, rationale is included
*check_type: judgment*

Asks the model: *If a different testing tool is used than the previous auth, rationale is included*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-10` — If VB-MAPP used for a child older than 5, rationale is included
*check_type: judgment*

Asks the model: *If VB-MAPP used for a child older than 5, rationale is included*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-11` — No legend should be included under the Vineland assessment
*check_type: judgment*

Asks the model: *No legend should be included under the Vineland assessment*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-ACF-12` — Assessment date is within the appropriate range (within report dates, before testing tool date, per payor guidelines)
*check_type: deterministic*

Round 92 : NEW rule -- "Assessment date is within the appropriate range (within report dates, before testing tool date, per payor guidelines)". Confirmed genuinely missing from the 171-rule set before this round (no equivalent rule_id anywhere).

---

## Problem Areas

### `QA-PROB-01` — At least 3 each of social/communication and 2 behavior, narrative format, no bullets
*check_type: deterministic*

Round 84, item 3 -- adds the one signal this rule's rubric never had: an actual narrative-vs-structured-format check on "As evidenced by:" content, via _looks_like_structured_matrix's conservative heuristic. *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)* ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-PROB-02` — 'As evidenced by' section matches goals listed
*check_type: deterministic*

Round 63, item 5: "'As evidenced by' section matches goals listed" -- deterministic pre-check ONLY for the confirmed objective violation (a leftover embedded reviewer comment counted as valid clinical evidence), reusing QA-TEMP-04's own reviewer-comment detector (_find_embedded_reviewer_comments) rather than duplicating that logic. *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)* ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-PROB-03` — Under 5: behaviors describe real ASD deficit, distinguishable from developmentally appropriate behavior
*check_type: judgment*

Asks the model: *Under 5: behaviors describe real ASD deficit, distinguishable from developmentally appropriate behavior*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PROB-04` — Problem Areas should not be identical to the previous TP unless services provided are very limited; if identical, TP should state this is because no additional services were provided
*check_type: judgment*

Asks the model: *Problem Areas should not be identical to the previous TP unless services provided are very limited; if identical, TP should state this is because no additional services were provided*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Goals in Progress

### `QA-GIP-01` — No school goals/ADL/group mentions unless requesting 97154
*check_type: judgment*

Asks the model: *No school goals/ADL/group mentions unless requesting 97154*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-02` — 3mo/6mo graph data matches auth length
*check_type: judgment*

Asks the model: *3mo/6mo graph data matches auth length*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-03` — Severity rating check (moderate min, not all mild)
*check_type: deterministic*

Converted from judgment to deterministic : shared checker for QA-BIP-01 and QA-GIP-03 -- the rules.json notes for QA-GIP-03 already call it "Duplicate of BIP-01 logic applied to goals section," so one function serves both rule_ids (same pattern as EMB-01 reusing HF-02's checker via params).

### `QA-GIP-04` — No mastery date shows 'invalid date'
*check_type: deterministic*

(`_check_GIP04`'s docstring just restates the rule text, adding no real mechanism detail beyond it — code-level detail not available without reading the function body directly.) ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-GIP-05` — Goal progress matches mastered goals (no contradiction/duplication)
*check_type: deterministic*

Round 83, item 2b -- REAL BUG FOUND AND FIXED: confirmed directly against a real document, a goal was listed BOTH in the document's own 'Mastered Goals:' section (with a Date Mastered) AND still listed as an active goal in 'Goals in Progress:' (with a 0% baseline) -- identical wording, just in two different sections with different surrounding formatting -- and the prior… *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)*

### `QA-GIP-06` — General goals fully completed and include a rationale
*check_type: judgment*

Asks the model: *General goals fully completed and include a rationale*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree). Also on the explicit allow-list of rule_ids with *confirmed* real self-consistency instability across rounds.

### `QA-GIP-07` — Goals open >6mo have rationale reviewed by Eliana
*check_type: judgment*

Asks the model: *Goals open >6mo have rationale reviewed by Eliana*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree). Also on the explicit allow-list of rule_ids with *confirmed* real self-consistency instability across rounds.

### `QA-GIP-08` — All goals match the POS; if goals are in the community (e.g., library), POS should reflect community
*check_type: judgment*

Asks the model: *All goals match the POS; if goals are in the community (e.g., library), POS should reflect community*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-09` — Goals indicate which are worked on in community
*check_type: judgment*

Asks the model: *Goals indicate which are worked on in community*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-10` — Sampling method consistent across baseline/current/sampling/mastery
*check_type: deterministic*

Converted from judgment to deterministic : 'sampling method consistent across every goal' is a uniqueness check over a list of extractable per-goal field values, not a holistic reasoning task -- exactly the shape an LLM is weak at (averaging over a big context, missing the one different item among many consistent ones), and exactly the shape code is strong at (regex-extract… ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-GIP-11` — Goals in behavioral context (SD, setting, expected response)
*check_type: judgment*

Asks the model: *Goals in behavioral context (SD, setting, expected response)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-12` — Goals include verbal operant/behavioral term
*check_type: judgment*

Asks the model: *Goals include verbal operant/behavioral term*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-13` — At least 1 goal per hour (excl. Parent Training and Behavior Reduction)
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-GIP-13` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *At least 1 goal per hour (excl. Parent Training and Behavior Reduction)*).

### `QA-GIP-14` — If data trending down, explanation provided
*check_type: judgment*

Asks the model: *If data trending down, explanation provided*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-15` — Info requested by last auth period included (per spreadsheet)
*check_type: judgment*

Asks the model: *Info requested by last auth period included (per spreadsheet)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-16` — Mastery criteria age/ASD-appropriate; no 0%, use 'fewer than one instance'
*check_type: deterministic*

Converted from judgment to deterministic : same shape as GIP-10 -- a per-goal field (Mastery Criteria) checked against a fixed banned-pattern list, not a holistic read. Shares _goal_block_starts with _check_GIP10 (both split the document the same way; this one just reads a different field per block).

### `QA-GIP-17` — Goals observable/measurable with SD, deficit, expectation
*check_type: judgment*

Asks the model: *Goals observable/measurable with SD, deficit, expectation*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-18` — Goals indicating choral responding should be revised/removed if no group hours requested
*check_type: judgment*

Asks the model: *Goals indicating choral responding should be revised/removed if no group hours requested*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-19` — Behavior goals and summary section present in review
*check_type: judgment*

Asks the model: *Behavior goals and summary section present in review*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-20` — Flag lack of a joint attention behavior goal
*check_type: judgment*

Asks the model: *Flag lack of a joint attention behavior goal*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-21` — Behavior goals include an explanation and indicate "mastered by" status
*check_type: judgment*

Asks the model: *Behavior goals include an explanation and indicate "mastered by" status*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-22` — Newly initiated goals without graphs should show status as "NEW," with current data marked "NEW" or aligned with baseline
*check_type: judgment*

Asks the model: *Newly initiated goals without graphs should show status as "NEW," with current data marked "NEW" or aligned with baseline*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-23` — Behavior reduction goals: check for upward trend without explanation (separate from downward-trend check on skill acquisition goals)
*check_type: deterministic*

Round 92 : HYBRID deterministic-then-judgment checker, same pattern as QA-PROB-02 (see that rule's own notes). *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)* ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-GIP-24` — Flag duplicate goals
*check_type: judgment*

Asks the model: *Flag duplicate goals*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-25` — Goals should be age-appropriate for the client
*check_type: judgment*

Asks the model: *Goals should be age-appropriate for the client*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-26` — No OT, PT, or speech therapy goals included
*check_type: judgment*

Asks the model: *No OT, PT, or speech therapy goals included*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-27` — If data appears mastered, goal status should indicate "met"
*check_type: judgment*

Asks the model: *If data appears mastered, goal status should indicate "met"*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-28` — If minimal data included in a graph, rationale is provided
*check_type: judgment*

Asks the model: *If minimal data included in a graph, rationale is provided*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-GIP-29` — If no graph is included, rationale is provided
*check_type: judgment*

Asks the model: *If no graph is included, rationale is provided*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Mastered Goals

### `QA-MAST-01` — Mastered goals within previous authorization dates
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-MAST-01` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Mastered goals within previous authorization dates*).

### `QA-MAST-02` — Mastered goals don't appear twice vs. previous TP
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-MAST-02` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Mastered goals don't appear twice vs. previous TP*).

### `QA-MAST-03` — If no mastered goals, rationale is provided
*check_type: judgment*

Asks the model: *If no mastered goals, rationale is provided*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-MAST-04` — If all parent goals are met, new goals are added
*check_type: judgment*

Asks the model: *If all parent goals are met, new goals are added*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## BIP

### `QA-BIP-01` — At least one severity rating >= moderate (not all 4 mild)
*check_type: deterministic*

Converted from judgment to deterministic : shared checker for QA-BIP-01 and QA-GIP-03 -- the rules.json notes for QA-GIP-03 already call it "Duplicate of BIP-01 logic applied to goals section," so one function serves both rule_ids (same pattern as EMB-01 reusing HF-02's checker via params).

### `QA-BIP-02` — No punishment procedures unless data attached + director approved
*check_type: judgment*

Asks the model: *No punishment procedures unless data attached + director approved*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-03` — Medical BIP -> all medical causes ruled out
*check_type: judgment*

Asks the model: *Medical BIP -> all medical causes ruled out*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-04` — All tantrum goals have a duration
*check_type: deterministic*

Fix Round , item 4 -- user-directed real-document verification (Yisroel Leibowitz's document, 'Reduce Crying Episodes' goal) exposed the same shape of gap this round's item 4 already fixed for QA-BIP-06: this rule ('All tantrum goals have a duration' -- i.e. every Behavior Reduction Goal's Mastery Criteria states a count/level AND a duration/consecutive-session qualifier, per…

### `QA-BIP-05` — Age-appropriate mastery criteria for behavior targets
*check_type: deterministic*

Round 81, Item 3 -- REAL BUG FOUND AND FIXED: confirmed directly against a real document, a goal's own Target Name states "fewer than 1 occurrence" while that SAME goal's own Mastery Criteria field states "1-2 occurrences" -- a direct, literal, same-goal-block contradiction (the mastery bar is looser than the goal's own stated target). *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)* ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-BIP-06` — Current level always indicated
*check_type: deterministic*

Round 82, item 2 -- REAL BUG FOUND AND FIXED: confirmed directly against a real document, a behavior target's Current Level field read literally "N/A" accompanied by a real explanatory note ("There were no direct sessions due to issues with staffing"), and this rule (then judgment-only) failed it as "not filled in." The checklist's own standard credits an anecdotal/explained… ⚠️ *Own notes flag this as narrow/pattern-specific — may not generalize to a differently-worded document.*

### `QA-BIP-07` — Plan for client to disagree appropriately (non-compliance goals)
*check_type: judgment*

Asks the model: *Plan for client to disagree appropriately (non-compliance goals)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-08` — Behaviors mentioned in Problem Areas/Reason for Referral have a corresponding BIP and behavior goal
*check_type: judgment*

Asks the model: *Behaviors mentioned in Problem Areas/Reason for Referral have a corresponding BIP and behavior goal*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-09` — All BIPs have a corresponding behavior goal and vice versa
*check_type: judgment*

Asks the model: *All BIPs have a corresponding behavior goal and vice versa*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-10` — Baseline and current level match between BIP and corresponding behavior goal
*check_type: judgment*

Asks the model: *Baseline and current level match between BIP and corresponding behavior goal*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-11` — BIP includes operational definition for each behavior (regardless of layout/format used)
*check_type: judgment*

Asks the model: *BIP includes operational definition for each behavior (regardless of layout/format used)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-12` — If multiple behaviors included in one BIP, each has a separate baseline and current level
*check_type: judgment*

Asks the model: *If multiple behaviors included in one BIP, each has a separate baseline and current level*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-13` — Behavior summary info is correct, current, and aligns with behaviors/BIPs included
*check_type: judgment*

Asks the model: *Behavior summary info is correct, current, and aligns with behaviors/BIPs included*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-BIP-14` — Gender/pronouns are consistent across BIP, goals, and summaries (check for copy-paste from other clients)
*check_type: judgment*

Asks the model: *Gender/pronouns are consistent across BIP, goals, and summaries (check for copy-paste from other clients)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Barriers to Treatment

### `QA-BAR-01` — If any barriers are mentioned throughout the report, they are present in this section too
*check_type: judgment*

Asks the model: *If any barriers are mentioned throughout the report, they are present in this section too*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Discharge Criteria

### `QA-DISC-01` — Patient-specific and realistic based on goals
*check_type: judgment*

Asks the model: *Patient-specific and realistic based on goals*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-DISC-02` — Remove extra bullets/numbers
*check_type: judgment*

Asks the model: *Remove extra bullets/numbers*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-DISC-03` — At least 4 discharge criteria per phase; criteria are long-term goals and align with client's profile
*check_type: judgment*

Asks the model: *At least 4 discharge criteria per phase; criteria are long-term goals and align with client's profile*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Transition Plan

### `QA-TRANS-01` — Patient-specific and realistic based on goals
*check_type: judgment*

Asks the model: *Patient-specific and realistic based on goals*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-TRANS-02` — Remove extra bullets/numbers
*check_type: judgment*

Asks the model: *Remove extra bullets/numbers*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-TRANS-03` — At least 4 transition goals per phase; goals align with client's actual profile (no goals for behaviors not present)
*check_type: judgment*

Asks the model: *At least 4 transition goals per phase; goals align with client's actual profile (no goals for behaviors not present)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Hours Requesting

### `QA-HRS-01` — 97153 hours match email from coordinator
*check_type: judgment*

Asks the model: *97153 hours match email from coordinator*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-HRS-02` — >20hrs of 97153 -> strong clinical rationale required
*check_type: deterministic*

(`_check_HRS02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *>20hrs of 97153 -> strong clinical rationale required*.)

### `QA-HRS-03` — Supervision hours must not exceed 1.5/10 ratio; if exceeded, needs clinical director approval
*check_type: deterministic*

This is a CEILING, not a minimum-supervision floor: the checklist says supervision must not EXCEED the ratio (1.5 hrs per 10 direct-care hrs), and if it does, needs documented clinical director approval. *(Hybrid — this pass only catches a specific, objective violation deterministically; anything less clear-cut escalates to the judgment layer for the real semantic call.)*

### `QA-HRS-04` — Group hours -> more direct hours + tailored rationale
*check_type: judgment*

Asks the model: *Group hours -> more direct hours + tailored rationale*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-HRS-05` — <10 hrs of 97153 -> confirm approved
*check_type: deterministic*

Round 92 : converted from judgment to a deterministic PRECONDITION check.

### `QA-HRS-06` — Increase in hours -> rationale in place
*check_type: deterministic*

Partially converted from judgment to deterministic : the rule's own notes already split this into "Presence = DET, adequacy of rationale = judgment" -- this builds the presence half in full, deterministically, as TWO independent checks (same "both must hold" shape as QA-PAR-01's two-criteria structure):

### `QA-HRS-07` — Increase in hours -> compared against discharge criteria/transition plan
*check_type: judgment*

Asks the model: *Increase in hours -> compared against discharge criteria/transition plan*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree). Also on the explicit allow-list of rule_ids with *confirmed* real self-consistency instability across rounds.

### `QA-HRS-08` — Codes/hours match insurance billing codes guide
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-HRS-08` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Codes/hours match insurance billing codes guide*).

### `QA-HRS-09` — Overlap with home health aide/speech/OT -> goals differentiated
*check_type: judgment*

Asks the model: *Overlap with home health aide/speech/OT -> goals differentiated*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree). Also on the explicit allow-list of rule_ids with *confirmed* real self-consistency instability across rounds.

### `QA-HRS-10` — For large hour increases, rationale must specifically address the magnitude of the increase, not just the general purpose of the code
*check_type: judgment*

Asks the model: *For large hour increases, rationale must specifically address the magnitude of the increase, not just the general purpose of the code*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## School & ABA Schedule

### `QA-SCH-01` — ABA schedule matches hours requested
*check_type: deterministic*

Round 63, item 3: "ABA schedule matches hours requested" -- compares the weekly schedule grid's real, computed total (pipeline/ schedule_hours.py -- real Python date/time arithmetic over the grid's actual time ranges) against the Hours Requesting section's stated weekly hours for the same CPT code (97153, Direct Care -- the code that's actually delivered day-to-day per the…

### `QA-SCH-02` — Confirmed with service coordinator schedule is accurate
*check_type: judgment*

Asks the model: *Confirmed with service coordinator schedule is accurate*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-SCH-03` — ABA schedule doesn't overlap school schedule (unless payor allows in-school)
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-SCH-03` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *ABA schedule doesn't overlap school schedule (unless payor allows in-school)*).

### `QA-SCH-04` — If ABA during day, school hours adjusted accordingly
*check_type: judgment*

Asks the model: *If ABA during day, school hours adjusted accordingly*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-SCH-05` — School hours match total under educational history, if applicable
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-SCH-05` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *School hours match total under educational history, if applicable*).

### `QA-SCH-06` — If overlaps related therapy, that schedule is added to TP
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-SCH-06` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *If overlaps related therapy, that schedule is added to TP*).

### `QA-SCH-07` — >3 hrs/day of 97153 -> approved by clinical director
*check_type: deterministic*

Round 63, item 3: ">3 hrs/day of 97153 -> approved by clinical director" -- a hard Director-tag trigger (Section 7.1) whenever ANY single day in the real, computed weekly schedule exceeds the threshold. Same deterministic arithmetic as _check_SCH01, applied per-day instead of as a weekly sum.

### `QA-SCH-08` — POS correct (home/office/school/community/telehealth only)
*check_type: judgment*

Asks the model: *POS correct (home/office/school/community/telehealth only)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-SCH-09` — If ABA is provided in a community-based program (e.g., day program), POS/location should name that specific community location
*check_type: judgment*

Asks the model: *If ABA is provided in a community-based program (e.g., day program), POS/location should name that specific community location*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Coordination of Care

### `QA-COC-01` — COC includes provider name/title/date; session note detailed
*check_type: judgment*

Asks the model: *COC includes provider name/title/date; session note detailed*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-COC-02` — COC completed with all related providers indicated (PCP, school, therapist)
*check_type: judgment*

Asks the model: *COC completed with all related providers indicated (PCP, school, therapist)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-COC-03` — TP indicates COC will be done once patient starts services (initial TP only)
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-COC-03` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *TP indicates COC will be done once patient starts services (initial TP only)*).

### `QA-COC-04` — TP faxed to doctor within last 6 months
*check_type: deterministic*

(`_check_COC04` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *TP faxed to doctor within last 6 months*.)

### `QA-COC-05` — Date of COC not past end date of current report
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-COC-05` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Date of COC not past end date of current report*).

### `QA-COC-06` — Date faxed to doctor includes month/day/year
*check_type: judgment*

Asks the model: *Date faxed to doctor includes month/day/year*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-COC-07` — COC content matches background info (e.g., no contradiction on related services)
*check_type: judgment*

Asks the model: *COC content matches background info (e.g., no contradiction on related services)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Data Sheets

### `QA-DS-01` — BCBA created data sheets for the patient
*check_type: judgment*

Asks the model: *BCBA created data sheets for the patient*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-DS-02` — All behavior goals should be marked at zero
*check_type: judgment*

Asks the model: *All behavior goals should be marked at zero*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Observations

### `QA-OBS-01` — Patient observation completed
*check_type: deterministic*

(`_check_OBS01` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Patient observation completed*.)

### `QA-OBS-02` — Observation location and dates fully completed
*check_type: judgment*

Asks the model: *Observation location and dates fully completed*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-OBS-03` — Observation and assessment backs the session note (else forward to QA)
*check_type: judgment*

Asks the model: *Observation and assessment backs the session note (else forward to QA)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-OBS-04` — Observation date within report dates, before testing tool date
*check_type: judgment*

Asks the model: *Observation date within report dates, before testing tool date*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Parent/Caregiver Involvement

### `QA-PAR-01` — 3+ parent training goals/auth period, no 'caregiver' wording (or rationale if used)
*check_type: judgment*

Asks the model: *3+ parent training goals/auth period, no 'caregiver' wording (or rationale if used)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PAR-02` — If family history indicates child lives elsewhere (not with parents), Parent/Caregiver Involvement summary reflects who will actually receive training
*check_type: judgment*

Asks the model: *If family history indicates child lives elsewhere (not with parents), Parent/Caregiver Involvement summary reflects who will actually receive training*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PAR-03` — For any hour increase, parent training goals should be reviewed and updated accordingly
*check_type: judgment*

Asks the model: *For any hour increase, parent training goals should be reviewed and updated accordingly*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Results of Preference Assessment

### `QA-PREF-01` — Result of preference assessment completed
*check_type: judgment*

Asks the model: *Result of preference assessment completed*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-PREF-02` — Flag if preference assessment references "client interview" when actually conducted through the parent — should say "parent interview"
*check_type: judgment*

Asks the model: *Flag if preference assessment references "client interview" when actually conducted through the parent — should say "parent interview"*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Clinical Interpretation

### `QA-CI-01` — Completed with clear and detailed rationale
*check_type: judgment*

Asks the model: *Completed with clear and detailed rationale*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Signatures

### `QA-SIG-01` — Signature includes date signed
*check_type: judgment*

Asks the model: *Signature includes date signed*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-SIG-02` — Signature includes correct credentials
*check_type: deterministic*

(`_check_SIG02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Signature includes correct credentials*.)

### `QA-SIG-03` — Signature date before start of auth dates requested
*check_type: deterministic*

(`_check_SIG03` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Signature date before start of auth dates requested*.)

### `QA-SIG-04` — Signature date not >2 days after end date of current report
*check_type: deterministic*

(`_check_SIG04` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *Signature date not >2 days after end date of current report*.)

### `QA-SIG-05` — BCBA signed the report
*check_type: judgment*

Asks the model: *BCBA signed the report*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-SIG-06` — If writing BCBA != case BCBA, both signed, clearly indicated
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `QA-SIG-06` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *If writing BCBA != case BCBA, both signed, clearly indicated*).

---

## AI-Generated Content & Template Artifacts

### `QA-AI-01` — Initial assessments should not include boilerplate language like "client made progress" / "continued intervention necessary"
*check_type: judgment*

Asks the model: *Initial assessments should not include boilerplate language like "client made progress" / "continued intervention necessary"*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-AI-02` — No AI-response artifacts left in TP (e.g., "Based on the documentation you uploaded...")
*check_type: judgment*

Asks the model: *No AI-response artifacts left in TP (e.g., "Based on the documentation you uploaded...")*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-AI-03` — No leftover template instructional prompts (e.g., "jot down something positive" text in Problem Areas, unfilled background-info prompts)
*check_type: judgment*

Asks the model: *No leftover template instructional prompts (e.g., "jot down something positive" text in Problem Areas, unfilled background-info prompts)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-AI-04` — No unfilled placeholder text (e.g., "insert grid by assessment section", "insert grid")
*check_type: judgment*

Asks the model: *No unfilled placeholder text (e.g., "insert grid by assessment section", "insert grid")*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `QA-AI-05` — Flag all spelling/grammar errors
*check_type: judgment*

Asks the model: *Flag all spelling/grammar errors*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Healthfirst-Specific

### `HF-01` — HF always has a 3-month range for authorization
*check_type: deterministic*

Confirmed root cause of the multi-round contradiction bug: this rule was labeled deterministic from the start but never had a real checker, so it always fell through to the not_checkable/0.0 escalation fallback and every finding came from the judgment layer re-deriving age/date-math from scratch.

### `HF-02` — No more than 5 hrs of 97151 (assessment) requested
*check_type: deterministic*

(`_check_HF02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *No more than 5 hrs of 97151 (assessment) requested*.)

### `HF-03` — Community hours: TP states how many hours, where, and what goals
*check_type: judgment*

Asks the model: *Community hours: TP states how many hours, where, and what goals*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `HF-04` — Flag insufficient graph data (fewer than 4 data points)
*check_type: judgment*

Asks the model: *Flag insufficient graph data (fewer than 4 data points)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `HF-05` — BCBA indicates hours PT occurred in previous auth period, and this matches PT hours requested
*check_type: judgment*

Asks the model: *BCBA indicates hours PT occurred in previous auth period, and this matches PT hours requested*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `HF-06` — Flag if Healthfirst client's testing tool/assessment is not updated within 3 months
*check_type: judgment*

Asks the model: *Flag if Healthfirst client's testing tool/assessment is not updated within 3 months*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `HF-07` — If behaviors rated moderate/severe, at least 1 behavior-based parent goal is included
*check_type: judgment*

Asks the model: *If behaviors rated moderate/severe, at least 1 behavior-based parent goal is included*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

### `HF-09` — Flag if Healthfirst auth range exceeds 3 months
*check_type: judgment*

Asks the model: *Flag if Healthfirst auth range exceeds 3 months*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Cigna-Specific

### `CIG-01` — If AFLS used, completed from A-Z
*check_type: judgment*

Asks the model: *If AFLS used, completed from A-Z*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Molina-Specific

### `MOL-01` — Utilization indicated on Molina, if applicable
*check_type: judgment*

Asks the model: *Utilization indicated on Molina, if applicable*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Aetna-Specific

### `AET-01` — Testing tool restricted to Vineland/VB-MAPP/ABLLS; AFLS not allowed
*check_type: deterministic*

Aetna: 'Vineland, VB-MAPP, and ABLLS can be used; AFLS cannot be used.' A disallowed-tool mention is a fail regardless of whether an allowed one is also present — the rule bans AFLS outright, it doesn't just require at least one allowed tool alongside it.

---

## Emblem-Specific

### `EMB-01` — No more than 3 hrs of 97151 (assessment) requested
*check_type: deterministic*

(`_check_HF02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *No more than 3 hrs of 97151 (assessment) requested*.)

### `EMB-02` — Flag eye contact goals (not preferred by this payor)
*check_type: judgment*

Asks the model: *Flag eye contact goals (not preferred by this payor)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Empire-Specific

### `EMP-01` — Date of current report within 30 days of authorization start date
*check_type: deterministic*

Empire: 'Date of current report is within 30 days of the authorization start date' — interpreted as the current report's own end date vs the new authorization's start date (see the rule's notes for why).

### `EMP-02` — Graph data within 30 days of authorization start date
*check_type: deterministic*

**No real checker built** — labeled deterministic in `rules.json`, but there is no entry for `EMP-02` in `fields.DET_CHECKS`. It escalates automatically to the judgment layer on every run (the underlying question: *Graph data within 30 days of authorization start date*).

### `EMP-03` — Signature date within 30 days of authorization start date
*check_type: deterministic*

Empire: 'Signature date is within 30 days of the authorization start date.'

### `EMP-04` — Flag eye contact goals (not preferred by this payor)
*check_type: judgment*

Asks the model: *Flag eye contact goals (not preferred by this payor)*. Runs the standard two-call self-consistency check (a third, tie-breaking call fires only if the first two disagree).

---

## Straight Medicaid-Specific

### `SM-01` — Auth start = day after current auth expires; auth end <= 6 months after current report end
*check_type: deterministic*

Straight Medicaid-specific: new auth start = day after the current report's own end date; new auth end <= N months after that same date. Both fields are page-1 text, no backend/prior-auth data needed — see the rule's own notes for why this differs from the universal QA-RPT-05.

### `SM-02` — All hours are requested per week (not per day, per month, or per auth)
*check_type: deterministic*

(`_check_SM02` has no docstring at all — code-level mechanism detail not available without reading the function body directly. Rule text: *All hours are requested per week (not per day, per month, or per auth)*.)

---
