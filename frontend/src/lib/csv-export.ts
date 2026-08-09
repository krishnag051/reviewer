import type { RuleResultOut } from "@/lib/api-client";
import { STATUS_LABELS } from "@/components/tp/RuleResultCard";

// Round 76, Item 2: real "Download CSV" export -- client-side, built
// straight from the SAME rule_results array already rendered on screen
// (uploadDetailQuery.data.rule_results in plans.$refId.index.tsx), not a
// second query that could drift from what's actually displayed. Column
// shape matches the CSVs already produced during agent-making's own
// testing (rule_id, category, status/result, page, evidence/detail) --
// `rule_id` here is the human-readable code (res.rule_code, e.g.
// "QA-TEMP-03"), matching that reference convention, not this backend's
// internal UUID (which would be meaningless in a spreadsheet next to
// agent-making's own CSVs).

function csvEscape(value: string): string {
  // RFC 4180: wrap in quotes if the value contains a comma, quote, or
  // newline, doubling any embedded quotes. Applied unconditionally isn't
  // wrong either, but only quoting when needed keeps the output readable
  // for the common case (most evidence text has no embedded comma/quote).
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function buildResultsCsv(results: RuleResultOut[]): string {
  const header = ["rule_id", "category", "status", "page", "evidence", "overridden"];
  const rows = results.map(r => [
    r.rule_code,
    r.category,
    STATUS_LABELS[r.final_status],
    r.final_pages.join("; "),
    r.final_finding,
    r.is_overridden ? "yes" : "no",
  ]);
  return [header, ...rows].map(row => row.map(cell => csvEscape(String(cell))).join(",")).join("\r\n");
}

export function downloadResultsCsv(results: RuleResultOut[], filename: string): void {
  const csv = buildResultsCsv(results);
  // BOM so Excel opens this as UTF-8 rather than guessing a legacy
  // codepage and mangling any non-ASCII evidence text.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
