// Fix Round, Item 6 verification: a real, automated render of RuleResultCard
// for each of the 5 real final_status values, asserting the outer card's
// actual className carries the intended border color and that the existing
// badge/pill (StatusBadge) is untouched -- border-only, per the round's own
// instruction.
//
// This is NOT a substitute for the round's own explicitly required
// screenshot of the real results panel with a real run containing one of
// each status -- that step needs a real browser and is reported separately,
// unchecked, in the final report (no browser/screenshot tool is available
// in this environment). What this DOES prove, for real: the actual
// STATUS_BORDER_CLASS mapping renders correctly on the actual component for
// every status value the type allows, and doesn't disturb the pill.
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { RuleResultCard } from "@/components/tp/RuleResultCard";
import type { RuleResultOut } from "@/lib/api-client";

afterEach(cleanup);

function makeResult(status: RuleResultOut["final_status"]): RuleResultOut {
  return {
    id: `res-${status}`,
    rule_id: "rule-1",
    rule_version_used: 1,
    final_status: status,
    final_finding: `Finding text for ${status}.`,
    final_pages: [],
    is_overridden: false,
    updated_at: new Date(0).toISOString(),
    question_text: `Question for ${status}?`,
    category: "Test Category",
    rule_code: "QA-TEST-01",
    model_status: status,
    model_finding: `Finding text for ${status}.`,
    model_pages: [],
  };
}

const EXPECTED_BORDER: Record<RuleResultOut["final_status"], string> = {
  pass: "border-green-400",
  fail: "border-red-400",
  uncertain: "border-blue-400",
  na: "border-slate-300",
  not_checkable: "border-blue-400",
};

const EXPECTED_BADGE_TEXT: Record<RuleResultOut["final_status"], string> = {
  pass: "Pass", fail: "Fail", na: "N/A", uncertain: "N/A", not_checkable: "N/A",
};

describe("RuleResultCard border colors (Item 6)", () => {
  for (const status of ["pass", "fail", "uncertain", "na", "not_checkable"] as const) {
    it(`renders the ${status} card with border ${EXPECTED_BORDER[status]} and an unchanged "${EXPECTED_BADGE_TEXT[status]}" badge`, () => {
      const res = makeResult(status);
      render(
        <RuleResultCard
          res={res}
          isDraft={false}
          overridePending={false}
          pageLabelMap={{}}
          onGoToPage={() => {}}
          onOverrideStatus={() => {}}
          onSaveEdit={() => {}}
        />,
      );
      // The outer card is the one with aria-expanded -- find it directly by
      // that attribute rather than assuming it's the only [role=button]
      // (the expand/collapse chevron button is one too).
      const outerCard = document.querySelector('[aria-expanded]')!;
      expect(outerCard.className).toMatch(new RegExp(EXPECTED_BORDER[status]));
      // Every OTHER status's border class must be absent -- proves this is
      // status-specific, not just always-present boilerplate classes.
      for (const other of Object.values(EXPECTED_BORDER)) {
        if (other !== EXPECTED_BORDER[status]) expect(outerCard.className).not.toMatch(new RegExp(other));
      }
      // Badge/pill unchanged: still shows the expected collapsed BADGE_STATUS
      // text -- getAllByText, not getByText, since for na/uncertain/
      // not_checkable the "Answer: N/A" line legitimately repeats the same
      // text as the pill itself.
      expect(screen.getAllByText(EXPECTED_BADGE_TEXT[status]).length).toBeGreaterThan(0);
    });
  }
});
