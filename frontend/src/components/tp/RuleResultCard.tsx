import { useState } from "react";
import { ChevronDown, ChevronRight, Pencil } from "lucide-react";
import type { RuleResultOut } from "@/lib/api-client";
import { StatusBadge, CategoryTag } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";

export const STATUS_LABELS: Record<RuleResultOut["final_status"], string> = {
  pass: "Yes", fail: "No", na: "N/A", uncertain: "Uncertain", not_checkable: "Not checkable",
};

const BADGE_STATUS: Record<RuleResultOut["final_status"], "Pass" | "Fail" | "N/A"> = {
  pass: "Pass", fail: "Fail", na: "N/A", uncertain: "N/A", not_checkable: "N/A",
};

/** Round 72, Item 2 -- REAL BUG FOUND AND FIXED: Round 70 only ever
 * rendered a link per entry in `res.final_pages` (the structured column).
 * Confirmed live: QA-TEMP-03's own evidence text is a Python-repr-style
 * list of per-match tuples -- "found on page(s): [(6, [...]), (9, [...]),
 * (14, [...]), ... (37, [...])]" -- naming many real, distinct pages the
 * detector actually found, but `final_pages` for that result only ever
 * held `[6]`. Not an agent-making bug to route around (per this round's
 * own scope discipline) and not touched here -- the fuller page list was
 * ALREADY present in the evidence text agent-making returns; this just
 * makes real use of data that was always there instead of ignoring it.
 * Scans the evidence/context text itself for every distinct page number
 * actually mentioned, unions it with `final_pages`, and renders a real,
 * working link for each -- not just the first one found. */
function extractPageNumbersFromText(text: string): number[] {
  const found = new Set<number>();

  // 1. "(N, [...])" tuples -- the exact QA-TEMP-03-style evidence shape
  //    above: a page number immediately followed by ", [".
  for (const m of text.matchAll(/\((\d{1,4})\s*,\s*\[/g)) {
    found.add(Number(m[1]));
  }
  // 2. "pages N-M" / "pages N to M" ranges (capped at a 100-page span so a
  //    regex misfire elsewhere in the text can't explode into thousands
  //    of bogus links).
  for (const m of text.matchAll(/\bpages?\s+(\d{1,4})\s*(?:-|to|–|—)\s*(\d{1,4})\b/gi)) {
    const start = Number(m[1]);
    const end = Number(m[2]);
    if (end >= start && end - start <= 100) {
      for (let p = start; p <= end; p++) found.add(p);
    }
  }
  // 3. "pages N, M, K" comma lists -- the whole captured span is bounded
  //    by \b on both ends and contains only digits/commas/spaces, so this
  //    can't bleed into unrelated numbers elsewhere in the sentence.
  for (const m of text.matchAll(/\bpages\s+(\d{1,4}(?:\s*,\s*\d{1,4})*)\b/gi)) {
    for (const numStr of m[1].split(",")) found.add(Number(numStr.trim()));
  }
  // 4. A single bare "page N" mention.
  for (const m of text.matchAll(/\bpage\s+(\d{1,4})\b/gi)) {
    found.add(Number(m[1]));
  }

  return Array.from(found);
}

/** Round 70, Item 4 -- rebuilt to match the Brellium reference pattern for
 * EVERY result regardless of status: a bold, plain-English question; a
 * clear bold answer; a lighter/smaller context block underneath with real
 * clickable [View Page X] links; and an edit affordance. A passing result
 * shows its real evidence here too, not just a green badge with nothing
 * underneath -- final_finding already carries the AI's real reasoning
 * (seeded from model_finding at creation, see app/services/upload_pipeline.py). */
function renderContextWithPageLinks(
  text: string,
  structuredPages: number[],
  pageLabelMap: Record<string, string>,
  onGoToPage: (page: number) => void,
) {
  // Round 72, Item 2: union of the structured column AND every page
  // number actually mentioned in the text itself -- see
  // extractPageNumbersFromText's own docstring above.
  const pages = Array.from(new Set([...structuredPages, ...extractPageNumbersFromText(text)])).sort((a, b) => a - b);
  if (pages.length === 0) return <span>{text}</span>;
  return (
    <>
      <span>{text}</span>
      <span className="ml-1.5 inline-flex items-center gap-1 flex-wrap">
        {pages.map(p => {
          const printedLabel = pageLabelMap[String(p)];
          return (
            <button
              key={p}
              type="button"
              onClick={() => onGoToPage(p)}
              className="text-[11px] font-medium text-blue-600 hover:text-blue-800 hover:underline"
              title={
                printedLabel && printedLabel !== String(p)
                  ? `Jumps to the PDF's actual page ${p} (printed on that page as "${printedLabel}")`
                  : `Jumps to page ${p} in the PDF`
              }
            >
              [View Page {printedLabel ?? p}]
            </button>
          );
        })}
      </span>
    </>
  );
}

/** Round 71 -- the read-only core of a result's display (question, answer,
 * context with real clickable page links, and the overridden/original-
 * answer note), pulled out so the BCBA escalation modal's problem list
 * (plans.$refId.index.tsx) renders each item with the EXACT SAME
 * question/evidence/page-reference formatting as this results panel --
 * not a second, differently-styled rendering of the same rule_result data.
 * RuleResultCard below wraps this with the status badge + edit/override
 * controls that only make sense in the main results panel, not a
 * read-only escalation preview.
 *
 * Round 73, Item 1: `expanded` controls whether the Context/evidence
 * block (and the overridden/original-answer note) renders at all --
 * question + Answer always show regardless, matching the Brellium
 * reference's collapsed-row content. Defaults to `true` so the ONE
 * existing caller that predates this round (the escalation modal's
 * problem list, which has no chevron and always wants full detail
 * visible for a draft preview) keeps behaving exactly as before without
 * needing to pass anything new. RuleResultCard below is the only caller
 * that ever passes `expanded={false}`. */
export function RuleResultContent({
  res, pageLabelMap, onGoToPage, expanded = true,
}: {
  res: RuleResultOut;
  pageLabelMap: Record<string, string>;
  onGoToPage: (page: number) => void;
  expanded?: boolean;
}) {
  return (
    <div className="min-w-0 flex-1">
      <div className="flex flex-wrap items-center gap-2 mb-1">
        <CategoryTag>{res.category}</CategoryTag>
        <span className="text-[10px] font-mono text-slate-400">{res.rule_code}</span>
        {res.is_overridden && <span className="text-[10px] font-medium uppercase tracking-wide text-blue-700">Overridden</span>}
      </div>
      {/* Bold, plain-English question -- never a raw rule_id again. */}
      <div className="text-sm font-semibold text-slate-900">{res.question_text}</div>
      {/* Clear, bold answer -- always visible, collapsed or expanded. */}
      <div className="mt-0.5 text-sm">
        <span className="font-bold text-slate-800">Answer: </span>
        <span className="font-bold text-slate-800">{STATUS_LABELS[res.final_status]}</span>
      </div>
      {expanded && (
        <>
          {/* Lighter, smaller context/evidence, with real clickable page links. */}
          <div className="mt-1 text-xs text-slate-500 leading-relaxed">
            <span className="font-medium text-slate-400">Context: </span>
            {renderContextWithPageLinks(res.final_finding, res.final_pages, pageLabelMap, onGoToPage)}
          </div>
          {res.is_overridden && res.model_finding !== res.final_finding && (
            <div className="mt-1.5 text-[11px] text-slate-400 italic">
              AI's original answer: {STATUS_LABELS[res.model_status]} — {res.model_finding}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export function RuleResultCard({
  res, isDraft, overridePending, pageLabelMap, onGoToPage, onOverrideStatus, onSaveEdit,
}: {
  res: RuleResultOut;
  isDraft: boolean;
  overridePending: boolean;
  pageLabelMap: Record<string, string>;
  onGoToPage: (page: number) => void;
  onOverrideStatus: (status: RuleResultOut["final_status"]) => void;
  onSaveEdit: (finding: string, pages: number[], reason: string) => void;
}) {
  const [editOpen, setEditOpen] = useState(false);
  const [editFinding, setEditFinding] = useState(res.final_finding);
  const [editPages, setEditPages] = useState(res.final_pages.join(", "));
  const [editReason, setEditReason] = useState("");
  // Round 73, Item 1: collapsed by default (matching Brellium's own
  // density -- only question + Answer visible until the chevron is
  // clicked), independent per card -- NOT an accordion. Confirmed from
  // the reference behavior this round explicitly asked to check rather
  // than assume: Brellium lets multiple items stay expanded at once, it
  // doesn't force others shut when one opens. Local per-card state (not
  // lifted to the parent list) is exactly what gives that for free -- each
  // RuleResultCard instance owns its own `expanded`, so opening one has no
  // effect on any other.
  const [expanded, setExpanded] = useState(false);

  function openEdit() {
    setEditFinding(res.final_finding);
    setEditPages(res.final_pages.join(", "));
    setEditReason("");
    setEditOpen(true);
  }

  function submitEdit() {
    const pages = editPages
      .split(",")
      .map(s => s.trim())
      .filter(Boolean)
      .map(Number)
      .filter(n => Number.isInteger(n) && n > 0);
    onSaveEdit(editFinding, pages, editReason);
    setEditOpen(false);
  }

  return (
    <div className="px-2 py-4 hover:bg-slate-50">
      <div className="flex items-start justify-between gap-3">
        <RuleResultContent res={res} pageLabelMap={pageLabelMap} onGoToPage={onGoToPage} expanded={expanded} />
        <div className="shrink-0 flex items-center gap-1.5">
          <button
            className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100"
            onClick={() => setExpanded(e => !e)}
            title={expanded ? "Collapse" : "Expand to see context/evidence"}
            aria-label={`${expanded ? "Collapse" : "Expand"} ${res.rule_code}`}
            aria-expanded={expanded}
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
          <StatusBadge status={BADGE_STATUS[res.final_status]} />
          {isDraft && (
            <>
              <button
                className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                onClick={openEdit}
                title="Edit this answer's evidence/page references"
                aria-label={`Edit finding for ${res.rule_code}`}
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-40 text-[10px] font-medium uppercase tracking-wide border border-slate-200 px-1.5"
                    disabled={overridePending}
                    title="Override this result's status"
                  >
                    Status
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuLabel>Override status to</DropdownMenuLabel>
                  {(["pass", "fail", "na", "uncertain", "not_checkable"] as const)
                    .filter(s => s !== res.final_status)
                    .map(s => (
                      <DropdownMenuItem key={s} onClick={() => onOverrideStatus(s)}>
                        {STATUS_LABELS[s]}
                      </DropdownMenuItem>
                    ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          )}
        </div>
      </div>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit finding — {res.rule_code}</DialogTitle>
            <DialogDescription>{res.question_text}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="edit-finding">Evidence / context</Label>
              <Textarea id="edit-finding" value={editFinding} onChange={e => setEditFinding(e.target.value)} rows={5} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-pages">Page reference(s), comma-separated</Label>
              <Input id="edit-pages" value={editPages} onChange={e => setEditPages(e.target.value)} placeholder="e.g. 4, 12" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-reason">Reason (optional, saved to the audit log)</Label>
              <Input id="edit-reason" value={editReason} onChange={e => setEditReason(e.target.value)} placeholder="Why is this being corrected?" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditOpen(false)}>Cancel</Button>
            <Button onClick={submitEdit} disabled={overridePending}>Save</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
