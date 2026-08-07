"""Section 7: a single-page Streamlit app for eyeballing pipeline output
during development. Not the facilitator-facing product UI -- this is
Krishna's own private testing tool for the agent, entirely separate from
the real BrightPath product (the React/FastAPI app on localhost:5173).
Clients never see this page.

Round 61: adds real Q&A text inputs, a one-click quick-fill for Yisroel
Leibowitz's real intake data, a multi-file session-notes uploader, and
wires Round 59's session-note extraction (Step 1) + comparison (Step 2)
into the SAME "Run Review" click that already runs the TP rule-check --
reusing session_note_extraction.py / session_note_comparison.py /
model_provider.py exactly as built, not duplicating any of that logic
here.

Cost control (Round 61, critical): both the TP rule-check and the
session-note extraction now default to Round 59's free OpenRouter model
for every run triggered from this UI. The real, billed Anthropic API is
reachable ONLY behind an explicit "Use real Anthropic API" toggle PLUS a
second, separate confirm checkbox that shows the exact call count and an
estimated cost first -- mirroring the standing per-instance-approval rule,
implemented here as a live UI gate since this is an interactive tool, not
an automated test suite. `model_override` is computed ONCE, right after
those two checkboxes, and is the ONLY value ever passed down into the
pipeline -- there is no other code path in this file that can reach
"anthropic" without both boxes checked.
"""
import json
import tempfile
from pathlib import Path

import streamlit as st

from pipeline import run_full_pipeline
from pipeline.call_tracker import ApiCallTracker
from pipeline.fields import extract_acf_fields, extract_fields
from pipeline.extract import extract_pdf_text
from pipeline.fields import _find_labeled_date_range
from pipeline.integrity import IntegrityError
from pipeline.model_provider import CallTracker, DEFAULT_ANTHROPIC_MODEL, DEFAULT_OPENROUTER_MODEL
from pipeline.session_note_comparison import compare_session_notes_to_tp, select_matching_session_note
from pipeline.session_note_extraction import extract_session_note_file

RULES_PATH = Path(__file__).parent / "rules" / "rules.json"

RESULT_COLORS = {
    "pass": "#1e8e3e",
    "fail": "#d93025",
    "uncertain": "#f9ab00",
    "not_applicable": "#9aa0a6",
    "not_checkable": "#9aa0a6",
}

# Round 61: Yisroel Leibowitz's real Q&A/authorization data, verbatim from
# the round's own task -- nothing invented. Only ever applied when this
# button is explicitly clicked; never auto-filled on page load.
EXAMPLE_YISROEL_ANSWERS = {
    "client_insurance": "Molina Healthcare – Medicaid, ID GY19564A",
    "bcba_name_credentials_npi": "Chaya Gold, BCBA/LBA, License 1-20-41828/001952-01, NPI 1225644313",
    "authorization_dates": "08/17/2026 – 02/17/2027",
    "pos_schedule_vs_97153_hours": (
        "31 hrs/week scheduled (Sun 3hrs Home; Mon-Fri 28hrs Office) = 31 hrs/week requested — MATCH"
    ),
    "hours_requesting": (
        "97151 Assessment 8 hrs/auth period; 97153 Direct Care 31 hrs/week; "
        "97155 Supervision/BTM 3 hrs/week; 97156 Parent Training 1 hr/week"
    ),
}

QA_FIELDS = [
    ("client_insurance", "Client Insurance"),
    ("bcba_name_credentials_npi", "BCBA Name, Credentials & NPI"),
    ("authorization_dates", "Authorization Dates"),
    ("pos_schedule_vs_97153_hours", "POS/Schedule vs. 97153 Hours Requesting"),
    ("hours_requesting", "Hours Requesting"),
]

if "qa_answers" not in st.session_state:
    st.session_state.qa_answers = {key: "" for key, _ in QA_FIELDS}
for _key, _ in QA_FIELDS:
    # Each text_input below is keyed and reads/writes session_state
    # directly -- this is the ONE place its initial value is set, so the
    # widget itself is never also given a conflicting `value=` argument
    # (Streamlit raises if both a widget's session_state key and its
    # `value=` parameter are set in the same run).
    if f"qa_input_{_key}" not in st.session_state:
        st.session_state[f"qa_input_{_key}"] = ""

st.set_page_config(page_title="Treatment Plan Rule-Engine POC", layout="wide")
st.title("Treatment Plan Rule-Engine POC")
st.caption(
    "This is a private developer testing tool for the rule-checking agent -- separate from the real "
    "BrightPath product (the actual app runs at localhost:5173). Clients never see this page."
)

rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
n_universal = sum(1 for r in rules if r["applies_to_payor"] == "ALL")
n_payor_specific = len(rules) - n_universal
st.caption(
    f"Loaded {len(rules)} rules from {RULES_PATH.name} "
    f"({n_universal} universal + {n_payor_specific} payor-specific). "
    f"Payor and plan type are detected per-document below, not assumed."
)

# ------------------------------------------------------------- Cost control

st.subheader("Model provider (cost control)")
st.caption(
    f"Default: Round 59's free OpenRouter model ({DEFAULT_OPENROUTER_MODEL}), $0 regardless of call volume. "
    f"Used for BOTH the TP rule-check below and any session-note extraction, unless you explicitly opt into "
    f"the real Anthropic API."
)
use_real_anthropic = st.checkbox(
    f"Use real Anthropic API ({DEFAULT_ANTHROPIC_MODEL}) instead of the free OpenRouter model",
    value=False,
    key="use_real_anthropic",
)

real_confirmed = False
if use_real_anthropic:
    st.warning(
        f"This will make REAL, BILLED calls to the Anthropic API (model: {DEFAULT_ANTHROPIC_MODEL}, "
        f"pricing ${2.00}/${10.00} per Mtok input/output, intro rate). A single TP rule-check run makes "
        f"**2 real calls** (the self-consistency pair over the whole judgment batch), up to 6 if the "
        f"integrity-check layer has to retry missing rule_ids twice. Each uploaded session note adds "
        f"**1 more real call** if extracted under this same toggle. Rough estimate for one typical TP: "
        f"a few cents up to roughly $0.50, depending on document length and how many retries happen -- "
        f"this is an estimate, not a guarantee; the exact real call count and tokens used are shown after "
        f"the run completes, same as the standing per-instance-approval rule requires everywhere else in "
        f"this project."
    )
    real_confirmed = st.checkbox(
        "Yes, I confirm — run using the real Anthropic API for this click.",
        key="real_anthropic_confirmed",
    )
    if not real_confirmed:
        st.info("Not confirmed yet -- Run Review will still use the free OpenRouter model until this is checked.")

# This is the ONLY place in this file model_override is ever set to
# "anthropic" -- both use_real_anthropic AND real_confirmed must be True.
# Every other branch (box unchecked, or checked-but-not-confirmed) falls
# through to "openrouter", the free default.
model_override = "anthropic" if (use_real_anthropic and real_confirmed) else "openrouter"

st.caption(f"This run will use: **{model_override}**" + (f" ({DEFAULT_ANTHROPIC_MODEL})" if model_override == "anthropic" else f" ({DEFAULT_OPENROUTER_MODEL})"))

max_real_calls = st.number_input(
    "Real-call ceiling for the TP rule-check this run (applies to either provider — an accidental retry "
    "loop can never exceed this many real calls, checked BEFORE each call, not after)",
    min_value=1, max_value=50, value=10, step=1,
)
max_session_note_calls = st.number_input(
    "Real-call ceiling for session-note extraction this run (separate from the above — one call per "
    "uploaded session-note file, per Round 59's own OpenRouter ceiling mechanism)",
    min_value=1, max_value=50, value=10, step=1,
)

st.divider()

# ------------------------------------------------------------------ Inputs

st.subheader("Upload a Treatment Plan PDF")
uploaded_tp = st.file_uploader("Treatment Plan PDF", type=["pdf"], key="tp_uploader")

st.subheader("Intake Q&A (5 fields)")
if st.button("Use example data (Yisroel Leibowitz)"):
    # Round 62 fix: a keyed widget's `value=` argument is only honored on
    # its FIRST render -- once a key exists in st.session_state, Streamlit
    # reads the widget's live value from there on every rerun and ignores
    # `value=` entirely. Writing to session_state.qa_answers (a separate,
    # unrelated dict) therefore did nothing after the first render -- a
    # real bug, caught by Round 62's actual click-through test, not just
    # eyeballing the code. The fix is to write directly to each widget's
    # OWN session_state key, before that widget is instantiated below.
    for key, _ in QA_FIELDS:
        st.session_state[f"qa_input_{key}"] = EXAMPLE_YISROEL_ANSWERS[key]

qa_values = {}
for key, label in QA_FIELDS:
    qa_values[key] = st.text_input(label, key=f"qa_input_{key}")
st.session_state.qa_answers = qa_values

st.subheader("Session notes (optional, multiple files)")
uploaded_notes = st.file_uploader(
    "Session note file(s) — PDF or plain text",
    type=["pdf", "txt"],
    accept_multiple_files=True,
    key="session_notes_uploader",
)

run_clicked = st.button("Run Review", disabled=uploaded_tp is None)

if run_clicked and uploaded_tp is not None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(uploaded_tp.getvalue())
        tmp_path = tmp.name

    tracker = ApiCallTracker(max_calls=int(max_real_calls))

    with st.spinner(f"Running TP rule-check pipeline ({model_override})..."):
        try:
            result = run_full_pipeline(tmp_path, rules, tracker=tracker, model_override=model_override)
        except IntegrityError as e:
            st.error(f"Integrity check failed: {e}")
            st.stop()

    # Round 63, items 1 & 2: a second, cheap (zero model calls, deterministic)
    # extraction pass over the same TP -- run_full_pipeline doesn't hand back
    # its own internal extracted_fields dict, so this repeats that one text-
    # extraction step to get the two TP-side facts the session-note
    # comparison below actually needs: the TP's own "Date of Current Report"
    # range (item 1 -- NOT its "Authorization Dates Requested" range, a
    # different field) and its own extracted ACF section values (item 2 --
    # previously always None here, with a comment claiming this extraction
    # "doesn't exist yet"; it's now built, see fields.py::extract_acf_fields).
    tp_pages = extract_pdf_text(tmp_path)
    tp_fields = extract_fields(tmp_path, tp_pages)
    tp_current_report_period = _find_labeled_date_range(tp_fields["full_text"], "Date of Current Report")
    tp_current_report_period_str = (
        f"{tp_current_report_period[0]} to {tp_current_report_period[1]}" if tp_current_report_period else None
    )
    tp_acf_fields = extract_acf_fields(tp_fields)

    detected_payor = result.get("detected_payor")
    detected_plan_type = result.get("detected_plan_type")
    st.subheader("Detected from this document")
    detect_col1, detect_col2 = st.columns(2)
    if detected_payor == "Unknown":
        detect_col1.warning(
            "Payor: Unknown — could not be read from the document's own text. "
            "Payor-specific rules were marked not_checkable, not skipped silently."
        )
    else:
        detect_col1.metric("Payor", detected_payor or "Unknown")
    detect_col2.metric("Plan type", detected_plan_type or "Unknown")

    st.subheader("API usage this run — TP rule-check")
    cost_col1, cost_col2, cost_col3 = st.columns(3)
    cost_col1.metric("Real API calls", tracker.count)
    cost_col2.metric("Tokens (in / out)", f"{tracker.total_input_tokens:,} / {tracker.total_output_tokens:,}")
    if model_override == "anthropic":
        cost_col3.metric("Est. cost (real Anthropic)", f"${tracker.estimated_cost():.4f}")
    else:
        cost_col3.metric("Est. cost", "$0.00 (OpenRouter free tier)")
        st.caption("Verify actual $0 usage any time at https://openrouter.ai/activity")

    # export_rows is already one row per page-level issue for multi-page
    # findings (and one row per rule_id otherwise) — render this directly,
    # not `findings`, so a reviewer sees "Page 49: <specific problem>"
    # instead of a collapsed page-range summary.
    export_rows = result["export_rows"]

    st.subheader(f"Results ({len(result['findings'])} rules checked, {len(export_rows)} rows)")

    df_rows = sorted(export_rows, key=lambda r: (r["result"] != "fail", r["result"] != "uncertain", r["rule_id"]))
    st.dataframe(
        [
            {
                "Rule ID": r["rule_id"],
                "Category": r["category"],
                "Result": r["result"],
                "Page": r["page"],
                "Detail": r["detail"],
            }
            for r in df_rows
        ],
        use_container_width=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        st.metric("BCBA-fix items", len(result["bcba_fix"]))
        st.write(result["bcba_fix"])
    with col2:
        st.metric("Facilitator-assign items", len(result["facilitator_assign"]))
        st.write(result["facilitator_assign"])

    # ---------------------------------------------- Session notes (Round 61)
    if uploaded_notes:
        st.divider()
        st.subheader("Session notes — extraction (Round 59 Step 1) + comparison (Round 59 Step 2)")
        note_tracker = CallTracker(max_calls=int(max_session_note_calls))

        # Round 65, item 2b: extract Step 1 for EVERY uploaded note first,
        # then run the comparison ONCE across all of them via
        # compare_session_notes_to_tp -- QA-ACF-02/QA-ACF-08 are computed
        # only against whichever note's own date matches the TP's stated
        # Assessment Date (select_matching_session_note), not against
        # every uploaded note independently. QA-RPT-03 still checks every
        # note on its own merits. Previously this looped per-file and
        # called compare_session_note_to_tp (singular) for EVERY note,
        # which ran ACF-02/ACF-08 against notes that don't back the stated
        # assessment at all.
        extractions_by_file: dict[str, dict] = {}
        for note_file in uploaded_notes:
            suffix = Path(note_file.name).suffix or ".txt"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_note:
                tmp_note.write(note_file.getvalue())
                note_path = tmp_note.name

            st.markdown(f"**{note_file.name}**")
            with st.spinner(f"Extracting {note_file.name} ({model_override})..."):
                try:
                    extraction = extract_session_note_file(
                        note_path, tracker=note_tracker, model_override=model_override,
                    )
                except Exception as e:
                    st.error(f"Extraction failed for {note_file.name}: {e}")
                    continue

            extractions_by_file[note_file.name] = extraction
            st.caption("Step 1 — extraction")
            st.json(extraction)

        if extractions_by_file:
            st.markdown("**Step 2 — comparison against the TP's own extracted data (deterministic, zero model calls)**")
            # Round 63 fix (items 1 & 2): both TP-side values now come from
            # the TP document itself, extracted above -- tp_current_report_
            # period is the TP's real "Date of Current Report" range
            # (QA-RPT-03's actual field, not its "Authorization Dates
            # Requested" range), and tp_acf_fields are the TP's own real
            # extracted ACF section values. Either can still legitimately
            # be None if that section/field genuinely isn't present in
            # this TP -- the comparison already reports that as
            # "uncertain," never a guessed pass/fail.
            if tp_current_report_period_str is None:
                st.caption("⚠️ Could not find this TP's 'Date of Current Report' range — QA-RPT-03 will be uncertain.")
            matched_filename, _ = select_matching_session_note(
                extractions_by_file, tp_acf_fields["assessment_date"],
            )
            if matched_filename:
                st.caption(f"QA-ACF-02/QA-ACF-08 are computed against **{matched_filename}** — the uploaded note whose own date matches the TP's stated Assessment Date ({tp_acf_fields['assessment_date']!r}).")
            else:
                st.caption(f"⚠️ No uploaded note's date matches the TP's stated Assessment Date ({tp_acf_fields['assessment_date']!r}) — QA-ACF-02/QA-ACF-08 will be uncertain.")
            comparison = compare_session_notes_to_tp(
                extractions_by_file,
                tp_current_report_period=tp_current_report_period_str,
                tp_assessment_date=tp_acf_fields["assessment_date"],
                tp_pos=tp_acf_fields["pos"],
                tp_patient_location=tp_acf_fields["patient_location"],
                tp_assessment_tool=tp_acf_fields["assessment_tool"],
            )
            st.json(comparison)

        st.subheader("API usage this run — session notes")
        snote_col1, snote_col2, snote_col3 = st.columns(3)
        snote_col1.metric("Real API calls", note_tracker.count)
        snote_col2.metric(
            "Tokens (in / out)", f"{note_tracker.total_input_tokens:,} / {note_tracker.total_output_tokens:,}",
        )
        if model_override == "anthropic":
            snote_col3.metric("Provider", "anthropic (real, billed)")
        else:
            snote_col3.metric("Provider", "openrouter (free)")
            st.caption("Verify actual $0 usage any time at https://openrouter.ai/activity")
