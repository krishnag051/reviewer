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
  // Round 79, Item 1: real "rule_name" column -- res.question_text is
  // already the real, human-readable rule text (Round 70, version-pinned
  // to rule_version_used, from the SAME rules.json content this backend
  // seeds from) already loaded on screen for every result. Adding it here
  // makes each exported row self-contained: readable and independently
  // verifiable without cross-referencing rules.json separately for what
  // e.g. "QA-PAR-01" actually means.
  //
  // Next Round, Part 2: three new columns give the CSV a full audit trail
  // that the live UI deliberately doesn't show all at once --
  // "evidence" stays the current/latest text (unchanged from before, so
  // nothing downstream that already parses this column breaks), and
  // "evidence_pre_humanize" / "evidence_post_humanize" / "evidence_human_edited"
  // are the three real, separate stages: the raw pre-humanize text, the
  // humanized text the model actually produced, and (only when
  // r.is_overridden) the human-edited replacement -- blank otherwise, since
  // "overridden" already tells the reader whether that column means
  // anything for this row.
  const header = [
    "rule_id", "rule_name", "category", "status", "page", "evidence", "overridden",
    "evidence_pre_humanize", "evidence_post_humanize", "evidence_human_edited",
  ];
  const rows = results.map(r => [
    r.rule_code,
    r.question_text,
    r.category,
    STATUS_LABELS[r.final_status],
    r.final_pages.join("; "),
    r.final_finding,
    r.is_overridden ? "yes" : "no",
    r.model_finding_raw ?? "",
    r.model_finding,
    r.is_overridden ? r.final_finding : "",
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
