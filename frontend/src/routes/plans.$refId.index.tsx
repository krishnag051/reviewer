import { createFileRoute, useNavigate, notFound } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, rules as allRules, pendingSlotLabel, type RuleStatus } from "@/lib/tp-mock";
import { StatusBadge, ReviewedBadge, CategoryTag, LaneTag } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectGroup, SelectLabel, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Check, Pencil, Mail, Eye, CheckCircle2, Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/plans/$refId/")({
  component: PlanDetail,
});

// One review interface for BOTH a finalized PlanVersion and a draft
// UAttempt -- a draft is not a lesser, bare-summary thing, it's the same
// full PDF + rule-results review surface, just not permanent yet. The
// switcher (below) lists finalized versions and pending drafts together;
// selecting either resolves to the same shape here, and only the toolbar
// actions differ (Mark Reviewed / Generate Correction Email are V-only;
// Finalize as V[n] takes their place for a draft; View Summary works for
// both).
function selectValueForVersion(version: number) { return `v-${version}`; }
function selectValueForAttempt(id: string) { return `u-${id}`; }

function PlanDetail() {
  const { refId } = Route.useParams();
  const nav = useNavigate();
  const { patients, markReviewed, overrideRuleStatus, finalizeAttempt } = useTP();
  const patient = patients.find(p => p.refId === refId);
  if (!patient) throw notFound();

  const sortedVersions = [...patient.versions].sort((a, b) => b.version - a.version);
  const sortedAttempts = [...patient.uAttempts].sort((a, b) => b.attemptNumber - a.attemptNumber);

  // A freshly-created draft is the thing the user almost certainly just
  // came here to look at (see /upload's auto-navigate-on-submit), so the
  // newest draft wins the initial selection over an older finalized
  // version. Once nothing is in progress, the latest finalized version is
  // the sensible default, same as before this rebuild.
  const [selectedValue, setSelectedValue] = useState<string>(() => {
    if (sortedAttempts[0]) return selectValueForAttempt(sortedAttempts[0].id);
    if (sortedVersions[0]) return selectValueForVersion(sortedVersions[0].version);
    return "";
  });

  // `selectedValue` can go stale (e.g. it pointed at a draft that just got
  // cleared by finalizing a sibling) -- resolve against LIVE data every
  // render and fall back to the latest available item rather than trusting
  // the stored string blindly. Never both defined at once: a value always
  // starts with exactly one of "v-"/"u-".
  let selectedVersion = selectedValue.startsWith("v-")
    ? patient.versions.find(v => selectValueForVersion(v.version) === selectedValue)
    : undefined;
  let selectedAttempt = selectedValue.startsWith("u-")
    ? patient.uAttempts.find(a => selectValueForAttempt(a.id) === selectedValue)
    : undefined;
  if (!selectedVersion && !selectedAttempt) {
    selectedVersion = sortedVersions[0];
    selectedAttempt = selectedVersion ? undefined : sortedAttempts[0];
  }
  const effectiveSelectedValue = selectedVersion
    ? selectValueForVersion(selectedVersion.version)
    : selectedAttempt
    ? selectValueForAttempt(selectedAttempt.id)
    : "";

  const reviewer = selectedVersion
    ? reviewers.find(r => r.id === selectedVersion!.reviewerId)
    : selectedAttempt
    ? reviewers.find(r => r.id === selectedAttempt!.reviewerId)
    : undefined;

  // Shared fields both a PlanVersion and a UAttempt have -- this is what
  // the PDF viewer and rule-results panel below actually render from, so
  // they don't need to know which kind is selected. `processing` is always
  // false for a version (nothing to wait on once it's finalized).
  const item = selectedVersion
    ? {
        pdf: selectedVersion.pdf, results: selectedVersion.results, score: selectedVersion.score,
        auditResult: selectedVersion.auditResult, assessmentDate: selectedVersion.assessmentDate,
        processing: false,
      }
    : selectedAttempt
    ? {
        pdf: selectedAttempt.pdf, results: selectedAttempt.results, score: selectedAttempt.score,
        auditResult: selectedAttempt.auditResult, assessmentDate: selectedAttempt.assessmentDate,
        processing: selectedAttempt.status === "processing",
      }
    : null;
  const totalPages = item?.pdf.length ?? 0;

  const [filter, setFilter] = useState<"all" | RuleStatus>("all");
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const pdfScrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [summaryOpen, setSummaryOpen] = useState(false);

  const counts = useMemo(() => ({
    all: item?.results.length ?? 0,
    Pass: item?.results.filter(r => r.status === "Pass").length ?? 0,
    Fail: item?.results.filter(r => r.status === "Fail").length ?? 0,
    "N/A": item?.results.filter(r => r.status === "N/A").length ?? 0,
  }), [item]);

  const filteredResults = (item?.results ?? []).filter(r => filter === "all" || r.status === filter);

  // Every pending draft is competing for the same open slot, and
  // finalizing any one of them clears the rest (per the confirmed
  // decision), so this label is the same no matter which draft is
  // selected.
  const nextVersionNumber = patient.versions.length + 1;

  function handleFinalize(attemptId: string) {
    const v = finalizeAttempt(patient!.refId, attemptId);
    if (v == null) { toast.error("Could not finalize — this attempt may have already been superseded."); return; }
    toast.success(`Finalized as V${v} for ${patient!.name}.`);
    setSelectedValue(selectValueForVersion(v));
  }

  if (!item) {
    return (
      <div className="h-full flex flex-col">
        <div className="shrink-0 border-b border-slate-200 bg-white px-6 py-4">
          <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
            <button onClick={() => nav({ to: "/plans" })} className="hover:text-slate-900">Treatment Plans</button>
            <span>/</span>
            <span className="font-mono">{patient.refId}</span>
          </div>
          <h1 className="text-xl font-semibold">{patient.name}</h1>
          <div className="mt-1 text-xs text-slate-600">{patient.payor} · no finalized version yet</div>
        </div>
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center max-w-sm">
            <div className="text-lg font-medium text-slate-900">No draft attempts yet</div>
            <div className="mt-1 text-sm text-slate-500">
              Upload a draft for {patient.name} to get started on {pendingSlotLabel(patient.versions.length)}.
            </div>
            <Button className="mt-4" onClick={() => nav({ to: "/upload" })}>Go to Upload</Button>
          </div>
        </div>
      </div>
    );
  }

  function jumpToPage(p: number) {
    const el = pageRefs.current[p];
    const scroll = pdfScrollRef.current;
    if (!el || !scroll) return;
    scroll.scrollTo({ top: el.offsetTop - scroll.offsetTop - 8, behavior: "smooth" });
    setHighlighted(p);
    setCurrentPage(p);
    setTimeout(() => setHighlighted(null), 1600);
  }

  function onPdfScroll() {
    const scroll = pdfScrollRef.current;
    if (!scroll) return;
    // Find topmost visible page
    let closest = 1;
    let closestDist = Infinity;
    Object.entries(pageRefs.current).forEach(([p, el]) => {
      if (!el) return;
      const dist = Math.abs(el.offsetTop - scroll.scrollTop - scroll.offsetTop);
      if (dist < closestDist) { closestDist = dist; closest = Number(p); }
    });
    setCurrentPage(closest);
  }

  const label = selectedVersion
    ? `v${selectedVersion.version} — ${selectedVersion.finalizedAt}`
    : `U${selectedAttempt!.attemptNumber} — uploaded ${selectedAttempt!.uploadedAt}`;

  return (
    <div className="h-full flex flex-col">
      {/* Sticky header */}
      <div className="shrink-0 border-b border-slate-200 bg-white">
        <div className="px-6 py-4">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
                <button onClick={() => nav({ to: "/plans" })} className="hover:text-slate-900">Treatment Plans</button>
                <span>/</span>
                <span className="font-mono">{patient.refId}</span>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-xl font-semibold">{patient.name}</h1>
                {item.processing ? (
                  <span className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">
                    <Loader2 className="h-3 w-3 animate-spin" />Agent reviewing…
                  </span>
                ) : (
                  <StatusBadge status={item.auditResult} />
                )}
                {selectedVersion && <ReviewedBadge reviewed={selectedVersion.reviewed} />}
                {selectedAttempt && (
                  <span className="text-[10px] uppercase tracking-wide rounded bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5">
                    Draft · pending {pendingSlotLabel(patient.versions.length)}
                  </span>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-slate-600">
                <div><span className="text-slate-400">Payor:</span> {patient.payor}</div>
                <div><span className="text-slate-400">Assessment:</span> {item.assessmentDate}</div>
                <div><span className="text-slate-400">Reviewer:</span> {reviewer?.name}, {reviewer?.credentials}</div>
                <div>
                  <span className="text-slate-400">Score:</span>{" "}
                  {item.processing
                    ? <span className="font-medium text-blue-700">Agent reviewing…</span>
                    : <span className="font-medium">{item.score}%</span>}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              {/* Combined switcher: finalized versions AND pending drafts,
                  grouped, resolving to the same rich view either way. */}
              <Select value={effectiveSelectedValue} onValueChange={setSelectedValue}>
                <SelectTrigger className="w-64 h-9"><SelectValue>{label}</SelectValue></SelectTrigger>
                <SelectContent>
                  {sortedVersions.length > 0 && (
                    <SelectGroup>
                      <SelectLabel>Finalized</SelectLabel>
                      {sortedVersions.map((v, i) => (
                        <SelectItem key={v.version} value={selectValueForVersion(v.version)}>
                          v{v.version} — {v.finalizedAt}{i === 0 ? " (latest)" : ""}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  )}
                  {sortedAttempts.length > 0 && (
                    <SelectGroup>
                      <SelectLabel>Drafts pending {pendingSlotLabel(patient.versions.length)}</SelectLabel>
                      {sortedAttempts.map(a => (
                        <SelectItem key={a.id} value={selectValueForAttempt(a.id)}>
                          U{a.attemptNumber} — uploaded {a.uploadedAt}{a.status === "processing" ? " (reviewing…)" : ""}
                        </SelectItem>
                      ))}
                    </SelectGroup>
                  )}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={() => setSummaryOpen(true)}><Eye className="h-3.5 w-3.5 mr-1.5" />View Summary</Button>
              {selectedVersion && (
                <>
                  <Button variant="outline" size="sm" onClick={() => {
                    if (selectedVersion!.reviewed) { toast.info("Already marked reviewed."); return; }
                    markReviewed(patient.refId, selectedVersion!.version);
                    toast.success("Marked as reviewed");
                  }}>
                    <Check className="h-3.5 w-3.5 mr-1.5" />Mark Reviewed
                  </Button>
                  <Button size="sm" onClick={() => nav({ to: "/plans/$refId/email", params: { refId: patient.refId } })}>
                    <Mail className="h-3.5 w-3.5 mr-1.5" />Generate Correction Email
                  </Button>
                </>
              )}
              {selectedAttempt && (
                <>
                  {/* Mock/placeholder for now -- routes the draft to whoever
                      the failing rules' lane points at (BCBA-fix or
                      Facilitator-assign) instead of jumping straight from
                      "look at it" to "finalize it". No real backend effect
                      yet, same as Mark Reviewed is mock state today. */}
                  <Button variant="outline" size="sm" disabled={item.processing} onClick={() => {
                    toast.success(`${patient.name}'s draft sent for correction. The reviewer will be notified.`);
                  }}>
                    <Send className="h-3.5 w-3.5 mr-1.5" />Send for Correction
                  </Button>
                  <Button size="sm" disabled={item.processing} onClick={() => handleFinalize(selectedAttempt!.id)}>
                    <CheckCircle2 className="h-3.5 w-3.5 mr-1.5" />Finalize as V{nextVersionNumber}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Split view */}
      <div className="flex-1 min-h-0 flex">
        {/* Left: PDF */}
        <div className="w-1/2 border-r border-slate-200 flex flex-col bg-slate-100">
          <div className="h-11 shrink-0 border-b border-slate-200 bg-white px-4 flex items-center justify-between text-sm">
            <div className="flex items-center gap-1.5">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => jumpToPage(Math.max(1, currentPage - 1))}><ChevronLeft className="h-4 w-4" /></Button>
              <div className="text-xs text-slate-600 tabular-nums">Page {currentPage} of {totalPages}</div>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => jumpToPage(Math.min(totalPages, currentPage + 1))}><ChevronRight className="h-4 w-4" /></Button>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom(z => Math.max(60, z - 10))}><ZoomOut className="h-4 w-4" /></Button>
              <div className="text-xs tabular-nums w-10 text-center">{zoom}%</div>
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom(z => Math.min(160, z + 10))}><ZoomIn className="h-4 w-4" /></Button>
            </div>
          </div>
          <div ref={pdfScrollRef} onScroll={onPdfScroll} className="flex-1 min-h-0 overflow-y-auto p-6 space-y-4">
            {item.pdf.map(pg => (
              <div
                key={pg.page}
                ref={el => { pageRefs.current[pg.page] = el; }}
                className={cn(
                  "mx-auto bg-white shadow-sm rounded-sm border transition-all",
                  highlighted === pg.page ? "border-blue-500 ring-2 ring-blue-300" : "border-slate-200",
                )}
                style={{ width: `${(zoom / 100) * 612}px`, minHeight: `${(zoom / 100) * 792}px` }}
              >
                <div className="p-10 text-slate-900 space-y-4" style={{ fontSize: `${(zoom / 100) * 12}px`, lineHeight: 1.6 }}>
                  <div className="pb-3 border-b border-slate-200">
                    <div className="text-[10px] uppercase tracking-widest text-slate-400">Page {pg.page}</div>
                    <div className="text-lg font-semibold mt-1">{pg.title}</div>
                  </div>
                  {pg.body.map((line, i) => (
                    <p key={i} className="text-slate-700">{line}</p>
                  ))}
                  <div className="pt-6 mt-6 border-t border-slate-100 text-[10px] text-slate-400 flex justify-between">
                    <span>{patient.name} — {patient.refId} — {label}</span>
                    <span>{pg.page} / {totalPages}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Rules */}
        <div className="w-1/2 flex flex-col bg-white">
          {item.processing ? (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="text-center">
                <Loader2 className="h-6 w-6 text-blue-500 animate-spin mx-auto mb-3" />
                <div className="text-sm font-medium text-slate-900">Agent is reviewing this attempt…</div>
                <div className="mt-1 text-xs text-slate-500">Results will appear here automatically once the review finishes.</div>
              </div>
            </div>
          ) : (
            <>
              <div className="shrink-0 border-b border-slate-200 px-4 py-3">
                <div className="text-xs text-slate-500 mb-2">Rule check results</div>
                <div className="flex gap-2">
                  {([
                    { key: "all", label: "All", count: counts.all, color: "border-slate-300 bg-white text-slate-700" },
                    { key: "Pass", label: "Pass", count: counts.Pass, color: "border-emerald-300 bg-emerald-50 text-emerald-800" },
                    { key: "Fail", label: "Fail", count: counts.Fail, color: "border-red-300 bg-red-50 text-red-800" },
                    { key: "N/A", label: "N/A", count: counts["N/A"], color: "border-slate-300 bg-slate-100 text-slate-700" },
                  ] as const).map(f => (
                    <button
                      key={f.key}
                      onClick={() => setFilter(f.key as typeof filter)}
                      className={cn(
                        "flex-1 rounded-md border px-3 py-2 text-sm font-medium transition-colors flex items-center justify-center gap-2",
                        filter === f.key ? `${f.color} ring-1 ring-offset-1 ring-slate-400` : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50",
                      )}
                    >
                      <span>{f.label}</span>
                      <span className="rounded bg-slate-900/10 px-1.5 py-0.5 text-xs tabular-nums">{f.count}</span>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex-1 min-h-0 overflow-y-auto divide-y divide-slate-100">
                {filteredResults.map(res => {
                  const rule = allRules.find(r => r.id === res.ruleId)!;
                  return (
                    <div key={res.ruleId} className="px-5 py-4 hover:bg-slate-50">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-2 mb-1.5">
                            <span className="text-xs font-mono font-semibold text-slate-700">{rule.id}</span>
                            <CategoryTag>{rule.category}</CategoryTag>
                            {res.status === "Fail" && <LaneTag lane={rule.actionLane} tag={rule.actionTag} />}
                            {res.overridden && <span className="text-[10px] font-medium uppercase tracking-wide text-blue-700">Overridden</span>}
                          </div>
                          <div className="text-sm font-medium text-slate-900">{rule.description}</div>
                          <div className="mt-1.5 text-sm text-slate-600">{res.finding}</div>
                          <div className="mt-2 flex items-center gap-1.5">
                            {res.pages.map(p => (
                              <button
                                key={p}
                                onClick={() => jumpToPage(p)}
                                className="text-[11px] font-mono rounded border border-slate-200 bg-slate-50 hover:bg-slate-900 hover:text-white hover:border-slate-900 px-1.5 py-0.5 transition-colors"
                              >p.{p}</button>
                            ))}
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <StatusBadge status={res.status} />
                          {/* Override stays a V-only action -- a draft's correct
                              fix path is revise-and-reupload, not an override
                              on something disposable. */}
                          {selectedVersion && (
                            <DropdownMenu>
                              <DropdownMenuTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-slate-900"><Pencil className="h-3 w-3" /></Button>
                              </DropdownMenuTrigger>
                              <DropdownMenuContent align="end">
                                {(["Pass", "Fail", "N/A"] as const).map(s => (
                                  <DropdownMenuItem key={s} onClick={() => {
                                    overrideRuleStatus(patient.refId, selectedVersion!.version, res.ruleId, s);
                                    toast.success(`${rule.id} overridden to ${s}`);
                                  }}>
                                    Override to {s}
                                  </DropdownMenuItem>
                                ))}
                              </DropdownMenuContent>
                            </DropdownMenu>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
                {filteredResults.length === 0 && (
                  <div className="p-10 text-center text-sm text-slate-500">No rules match this filter.</div>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Summary Dialog */}
      <Dialog open={summaryOpen} onOpenChange={setSummaryOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{patient.name} — {label} Summary</DialogTitle></DialogHeader>
          <div className="text-sm space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><div className="text-xs text-slate-500">Reference ID</div><div className="font-mono">{patient.refId}</div></div>
              <div><div className="text-xs text-slate-500">Payor</div><div>{patient.payor}</div></div>
              <div><div className="text-xs text-slate-500">Score</div><div className="font-medium">{item.processing ? "Agent reviewing…" : `${item.score}%`}</div></div>
              <div><div className="text-xs text-slate-500">Result</div>{item.processing ? <span className="text-xs text-blue-700">Pending</span> : <StatusBadge status={item.auditResult} />}</div>
            </div>
            <div className="pt-3 border-t">
              <div className="text-xs text-slate-500 mb-2">Failed rules ({counts.Fail})</div>
              <ul className="space-y-2">
                {item.results.filter(r => r.status === "Fail").map(r => {
                  const rule = allRules.find(x => x.id === r.ruleId)!;
                  return <li key={r.ruleId} className="text-sm"><span className="font-mono text-xs">{r.ruleId}</span> — {rule.description}<div className="text-slate-600 text-xs mt-0.5">{r.finding}</div></li>;
                })}
                {counts.Fail === 0 && <li className="text-slate-500 text-sm">None</li>}
              </ul>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
