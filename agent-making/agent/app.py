"""Section 7: a single-page Streamlit app for eyeballing pipeline output
during development. Not the facilitator-facing product UI.
"""
import json
import tempfile
from pathlib import Path

import streamlit as st

from pipeline import run_full_pipeline
from pipeline.call_tracker import ApiCallTracker
from pipeline.integrity import IntegrityError

RULES_PATH = Path(__file__).parent / "rules" / "rules.json"

RESULT_COLORS = {
    "pass": "#1e8e3e",
    "fail": "#d93025",
    "uncertain": "#f9ab00",
    "not_applicable": "#9aa0a6",
    "not_checkable": "#9aa0a6",
}

st.set_page_config(page_title="Treatment Plan Rule-Engine POC", layout="wide")
st.title("Treatment Plan Rule-Engine POC")

rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))["rules"]
n_universal = sum(1 for r in rules if r["applies_to_payor"] == "ALL")
n_payor_specific = len(rules) - n_universal
st.caption(
    f"Loaded {len(rules)} rules from {RULES_PATH.name} "
    f"({n_universal} universal + {n_payor_specific} payor-specific). "
    f"Payor and plan type are detected per-document below, not assumed."
)

uploaded = st.file_uploader("Upload a Treatment Plan PDF", type=["pdf"])
run_clicked = st.button("Run Review", disabled=uploaded is None)

if run_clicked and uploaded is not None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = tmp.name

    tracker = ApiCallTracker(max_calls=None)  # no cap for a single deliberate, user-clicked run

    with st.spinner("Running pipeline..."):
        try:
            result = run_full_pipeline(tmp_path, rules, tracker=tracker)
        except IntegrityError as e:
            st.error(f"Integrity check failed: {e}")
            st.stop()

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

    st.subheader("API usage this run")
    cost_col1, cost_col2, cost_col3 = st.columns(3)
    cost_col1.metric("Real API calls", tracker.count)
    cost_col2.metric("Tokens (in / out)", f"{tracker.total_input_tokens:,} / {tracker.total_output_tokens:,}")
    cost_col3.metric("Est. cost", f"${tracker.estimated_cost():.4f}")

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
