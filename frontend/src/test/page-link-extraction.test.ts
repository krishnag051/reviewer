import { describe, it, expect } from "vitest";
import { extractPageNumbersFromText } from "@/components/tp/RuleResultCard";

// Round 79, Item 3: real regression coverage for "no missed or
// double-counted pages" -- using ACTUAL real evidence text captured from
// this backend across earlier rounds (Round 77's real, free-tier
// verification of the new "[Page N]" format on the deterministic
// checkers this round is wiring page-jump links for), not fabricated
// placeholder strings.

describe("extractPageNumbersFromText", () => {
  it("extracts every distinct [Page N] tag, real QA-TEMP-03 evidence text", () => {
    // Real output captured in Round 77's verification of _check_TEMP03.
    const text = "Highlight annotation(s) found: [Page 1] [Page 3]. Highlighter-colored fill(s) found: [Page 1] [Page 3].";
    const pages = extractPageNumbersFromText(text).sort((a, b) => a - b);
    expect(pages).toEqual([1, 3]); // deduped -- each page mentioned twice in the real string, counted once
  });

  it("extracts a single trailing [Page N] tag, real QA-RPT-01 evidence text", () => {
    // Real output captured in Round 77's verification of _check_RPT01.
    const text = "Possible unfilled field(s): ['Baseline:']. [Page 5]";
    expect(extractPageNumbersFromText(text)).toEqual([5]);
  });

  it("extracts a real 17-distinct-page finding with no misses", () => {
    // Real shape from the original QA-TEMP-03 multi-page bug this exact
    // mechanism was built to fix (Round 72), now in the standardized
    // Round 77 format instead of the old Python-repr tuple list.
    const pages17 = [6, 9, 10, 14, 15, 16, 17, 21, 22, 23, 24, 25, 26, 27, 28, 29, 37];
    const text = `Highlighter-colored fill(s) found: ${pages17.map(p => `[Page ${p}]`).join(" ")}.`;
    expect(extractPageNumbersFromText(text).sort((a, b) => a - b)).toEqual(pages17);
  });

  it("does not double-count when the same page appears via [Page N] AND a legacy bare 'page N' mention", () => {
    const text = "Grid missing [Page 9]. See also page 9 for the same issue.";
    expect(extractPageNumbersFromText(text)).toEqual([9]);
  });

  it("still supports legacy formats for older, pre-Round-77 evidence text already in the DB", () => {
    expect(extractPageNumbersFromText("pages 21-23 are affected.").sort((a, b) => a - b)).toEqual([21, 22, 23]);
    expect(extractPageNumbersFromText("pages 4, 5, 6 are affected.").sort((a, b) => a - b)).toEqual([4, 5, 6]);
    expect(extractPageNumbersFromText("found on page(s): [(6, ['hit'])].")).toEqual([6]);
  });

  it("returns nothing for evidence text with no page reference at all", () => {
    expect(extractPageNumbersFromText("Central Reach integration is out of scope; cannot verify.")).toEqual([]);
  });
});
