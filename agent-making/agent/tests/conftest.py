"""Shared pytest fixtures.

synthetic_tp_pdf is a synthetic, generated-on-the-fly placeholder used by
tests that check specific pipeline mechanics against known, controlled
content (e.g. exact page-flagging behavior) — keep using it for those.

real_tp_pdf points at the actual Zyaan Ullah TP now that it's in the repo
(agent/sample_tps/Ullah_Zyaan_Redacted.pdf) — this is what the regression
snapshot test uses, since a real document is what makes that test a
meaningful gate instead of one that runs on near-empty synthetic pages.

reeda_tp_pdf / charny_tp_pdf back test_regression_ground_truth.py (2026-07-28
round, item 4). Deliberately NOT copied into the repo like Ullah_Zyaan's
file: unlike that one (filename says "_Redacted"), these two documents
contain real, unredacted PHI (real patient name, DOB, insurance ID) — these
fixtures point at their existing external location instead, and skip (not
fail) if that location isn't present on the machine running the suite. If
these should become permanent, durable, repo-committed fixtures the way
Ullah_Zyaan's is, that needs a deliberate redaction pass first and is a call
for a human to make, not something to do silently while building a test
harness.
"""
from pathlib import Path

import fitz
import pytest

REAL_TP_PDF_PATH = Path(__file__).parent.parent / "sample_tps" / "Ullah_Zyaan_Redacted.pdf"
REEDA_TP_PDF_PATH = Path(r"C:\Users\DELL\OneDrive - Master Faster\Desktop\Re_ Examples of the TP's required\Reeda B S Review.pdf")
CHARNY_TP_PDF_PATH = Path(r"C:\Users\DELL\OneDrive - Master Faster\Desktop\charmy\Charny Gluck TP Feedback.pdf")


@pytest.fixture
def real_tp_pdf() -> str:
    if not REAL_TP_PDF_PATH.exists():
        pytest.skip(f"Real TP not present at {REAL_TP_PDF_PATH} — drop it in to run this test.")
    return str(REAL_TP_PDF_PATH)


@pytest.fixture
def reeda_tp_pdf() -> str:
    if not REEDA_TP_PDF_PATH.exists():
        pytest.skip(f"Reeda's TP not present at {REEDA_TP_PDF_PATH} on this machine.")
    return str(REEDA_TP_PDF_PATH)


@pytest.fixture
def charny_tp_pdf() -> str:
    if not CHARNY_TP_PDF_PATH.exists():
        pytest.skip(f"Charny's TP not present at {CHARNY_TP_PDF_PATH} on this machine.")
    return str(CHARNY_TP_PDF_PATH)


@pytest.fixture
def synthetic_tp_pdf(tmp_path) -> str:
    """A minimal multi-page PDF: two pages with real text, one nearly-blank
    page standing in for an image-only page (e.g. a goal graph).
    """
    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "Treatment Plan\nPage 1")
    page1.insert_text((72, 100), "Patient: Test Patient. RBT will provide services. Signature: BCBA, John Smith, 01/02/2026.")
    page1.insert_text((72, 750), "Page 1 of 3")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Treatment Plan\nPage 2")
    page2.insert_text(
        (72, 100),
        "Place of service: home. 97151: 4 hrs. Current level: baseline. "
        "This page also documents observation notes and preference assessment results for the review.",
    )
    page2.insert_text((72, 750), "Page 2 of 3")

    # Nearly-blank page — stands in for an image-only page (e.g. a goal graph)
    doc.new_page()

    path = tmp_path / "synthetic_tp.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)
