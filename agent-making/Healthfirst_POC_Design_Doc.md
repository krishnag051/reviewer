# Healthfirst Rule-Engine POC — End-to-End Design

Standalone prototype. Lives in its own folder, outside the main backend repo, until it proves out. Claude only. Healthfirst only, for now — expand to the other 8 payors once this payor is validated against enough real TPs.

## 1. Scope

Build and test, in isolation: upload a TP → extract its content → run all 114 Healthfirst rules against it (deterministic + LLM-judgment) → display a structured pass/fail/flag/uncertain result per rule, with evidence and page citations. No integration with the real backend, no email drafting, no facilitator routing UI yet. Just: does the rule engine work, and is it accurate enough to trust.

## 2. Folder structure

```
agent/
  rules/
    healthfirst.json          # the 114 rules, same schema as Rules Studio will use
  pipeline/
    extract.py                # text extraction (pypdf)
    flag_pages.py              # find image-only pages
    render.py                  # render flagged pages to PNG (PyMuPDF)
    fields.py                  # deterministic field extraction + all DET rule checks
    judge.py                   # single Claude call for HYBRID/LLM rules, structured output
    integrity.py               # rule-id coverage check, reject/retry on gaps
    merge.py                   # combine layer 1 + layer 2 into one findings object
  app.py                       # Streamlit front end
  sample_tps/                  # a couple of redacted real TPs for repeatable testing
  tests/
    test_pipeline.py
  requirements.txt
```

Each `pipeline/` module is one function with a typed input and output. That's the "graph node" shape your instinct is pointing at — implemented as plain functions for now. If a real conditional branch shows up later (e.g., "if session note missing, fetch from Central Reach"), that becomes a new node with its own input/output contract, dropped into the same pipeline — not a rewrite.

## 3. Data contracts

**Rule** (one row per rule, matches the classification spreadsheet already built):
`rule_id, category, applies_to_payor, applies_to_plan_type, applies_to_condition, check_type (deterministic|judgment), pass_fail_logic, action_lane, action_tag`

**Extracted fields** (output of `fields.py`, input to both rule layers): a flat structured object — dates, hours by CPT code, ages, POS, provider credentials, counts (number of goals, number of parent-training goals, etc.) — everything a deterministic rule needs, pulled by code, not by the model.

**Findings** (final output): one entry per rule_id — `{result, evidence, page, confidence}`. `result` is one of `pass | fail | uncertain | not_applicable | not_checkable`. This is a first-class schema value, not something buried in free text.

## 4. Pipeline steps

1. **Extract** — `pypdf`, page-by-page `.extract_text()`. Free, deterministic, no LLM.
2. **Flag** — any page under ~100 characters of extracted text is marked "image-only." In the Zyaan Ullah test document this caught the ABLLS grid, every goal graph, the signature page, and — critically — three pages containing unresolved reviewer highlights that a text-only pipeline would have completely missed.
3. **Render** — flagged pages only, via PyMuPDF (`page.get_pixmap(dpi=120)`), saved as PNG.
4. **Deterministic layer** — code runs every `check_type: deterministic` rule against the extracted fields. No LLM call. This covered 56 of Healthfirst's 114 rules in testing.
5. **Judgment layer** — one Claude Sonnet 5 call. Input: extracted fields, all page text, all rendered images (in page order), the subset of rules where `check_type: judgment`, plus the previous finalized TP's relevant fields (pulled from your own version-history data, not fetched by the model). Output forced via tool-use into the Findings schema above — one entry required per rule_id sent in.
6. **Integrity check** — diff the rule_ids returned against the rule_ids sent. Anything missing: reject and retry. Non-negotiable; this is the exact gap this design doc's author (me) shipped in the first pass on this project before being corrected.
7. **Merge** — combine layers 4 and 5, split into BCBA-fix vs. Facilitator-assign per each rule's `action_lane`/`action_tag`.

## 5. Model choice

Claude Sonnet 5 for the judgment call — best speed/intelligence tradeoff for a classification task, 1M context (a 48-page TP with embedded images is nowhere near the ceiling), and it's the model that already produced a correct 114-rule pass in testing. Optionally, Haiku 4.5 for pure field extraction if cost matters at volume — cheaper, and extraction is mechanical enough not to need Sonnet-level reasoning. Don't reach for Opus 4.8 or Fable 5 as the default; save them, if ever, for a narrow escalation path when Sonnet 5's own output says `uncertain` on a specific rule. Use the Batch API — a facilitator uploading a TP doesn't need a sub-second answer, and batch pricing is roughly half of standard.

## 6. Line graphs / charts — feasibility

Confirmed working, not theoretical. In testing, goal-progress graphs and the BIP behavior-tracking graph exist only as embedded images with no text layer at all — a pure OCR/text pipeline sees nothing on those pages. Rendering the page to an image and sending it to Claude directly worked: it correctly read axis values, trend direction, and date ranges off the chart. The one nuance to build in: whether a trend is "good" or "bad" depends on the goal type (a rising line is good for a skill-acquisition goal, bad for a behavior-reduction goal) — the judgment prompt needs to pass along which kind of goal each graph belongs to, not just the image.

## 7. Testing harness

A single-page Streamlit app (`app.py`): file upload for a TP PDF, a "Run Review" button, and a results table (rule_id, category, result, evidence, page) color-coded the same way as the classification spreadsheet. This is purely for eyeballing pipeline output during development — it is not the facilitator-facing product UI, which lives in the real backend later.

## 8. Orchestration

No LangGraph in this POC. The pipeline above is a fixed sequence with no runtime-decided branches — nothing for a graph library to route between yet. Build the steps as clean, separately-callable functions with the input/output contracts in Section 3. That's the future-proofing: when a real branch shows up (Central Reach lookups, the facilitator human-in-the-loop approval step), it plugs in as a new node against the same contracts, whether the eventual glue is plain code, a hand-rolled state machine, or LangGraph. Decide the orchestration library when you have an actual graph to draw, not before.

## 9. Success criteria before expanding past Healthfirst

Run the pipeline against several more real Healthfirst TPs (mixed clean/flagged, both plan types). For each: confirm the integrity check passes (every rule_id returned), and manually review a sample of the `judgment`-type results against what a human reviewer would flag. Once that holds up, replicate the same folder structure with the other 8 payors' rule sets.
