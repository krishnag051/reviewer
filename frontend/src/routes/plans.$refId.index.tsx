import { createFileRoute, Link, useNavigate, notFound } from "@tanstack/react-router";
import { useMemo, useRef, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, rules as allRules, type RuleStatus } from "@/lib/tp-mock";
import { StatusBadge, ReviewedBadge, CategoryTag } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Check, Pencil, Mail, Eye } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/plans/$refId/")({
  component: PlanDetail,
});

function PlanDetail() {
  const { refId } = Route.useParams();
  const nav = useNavigate();
  const { patients, markReviewed, overrideRuleStatus } = useTP();
  const patient = patients.find(p => p.refId === refId);
  if (!patient) throw notFound();

  const sortedVersions = [...patient.versions].sort((a, b) => b.version - a.version);
  const [versionNum, setVersionNum] = useState(sortedVersions[0].version);
  const version = patient.versions.find(v => v.version === versionNum)!;
  const reviewer = reviewers.find(r => r.id === version.reviewerId)!;
  const totalPages = version.pdf.length;

  const [filter, setFilter] = useState<"all" | RuleStatus>("all");
  const [zoom, setZoom] = useState(100);
  const [currentPage, setCurrentPage] = useState(1);
  const [highlighted, setHighlighted] = useState<number | null>(null);
  const pdfScrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const [summaryOpen, setSummaryOpen] = useState(false);

  const counts = useMemo(() => ({
    all: version.results.length,
    Pass: version.results.filter(r => r.status === "Pass").length,
    Fail: version.results.filter(r => r.status === "Fail").length,
    "N/A": version.results.filter(r => r.status === "N/A").length,
  }), [version]);

  const filteredResults = version.results.filter(r => filter === "all" || r.status === filter);

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
                <StatusBadge status={version.auditResult} />
                <ReviewedBadge reviewed={version.reviewed} />
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-slate-600">
                <div><span className="text-slate-400">Payor:</span> {patient.payor}</div>
                <div><span className="text-slate-400">Assessment:</span> {version.assessmentDate}</div>
                <div><span className="text-slate-400">Reviewer:</span> {reviewer.name}, {reviewer.credentials}</div>
                <div><span className="text-slate-400">Score:</span> <span className="font-medium">{version.score}%</span></div>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Select value={String(versionNum)} onValueChange={v => setVersionNum(Number(v))}>
                <SelectTrigger className="w-56 h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {sortedVersions.map((v, i) => (
                    <SelectItem key={v.version} value={String(v.version)}>
                      v{v.version} — {v.uploadedAt}{i === 0 ? " (latest)" : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="sm" onClick={() => setSummaryOpen(true)}><Eye className="h-3.5 w-3.5 mr-1.5" />View Summary</Button>
              <Button variant="outline" size="sm" onClick={() => {
                if (version.reviewed) { toast.info("Already marked reviewed."); return; }
                markReviewed(patient.refId, version.version);
                toast.success("Marked as reviewed");
              }}>
                <Check className="h-3.5 w-3.5 mr-1.5" />Mark Reviewed
              </Button>
              <Button size="sm" onClick={() => nav({ to: "/plans/$refId/email", params: { refId: patient.refId } })}>
                <Mail className="h-3.5 w-3.5 mr-1.5" />Generate Correction Email
              </Button>
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
            {version.pdf.map(pg => (
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
                    <span>{patient.name} — {patient.refId} — v{version.version}</span>
                    <span>{pg.page} / {totalPages}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Rules */}
        <div className="w-1/2 flex flex-col bg-white">
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
                        {rule.severity === "Critical" && (
                          <span className="text-[10px] font-medium uppercase tracking-wide text-red-700 bg-red-50 border border-red-200 rounded px-1.5 py-0.5">Critical</span>
                        )}
                        {res.overridden && <span className="text-[10px] font-medium uppercase tracking-wide text-blue-700">Overridden</span>}
                      </div>
                      <div className="text-sm font-medium text-slate-900">{rule.question}</div>
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
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-slate-900"><Pencil className="h-3 w-3" /></Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          {(["Pass", "Fail", "N/A"] as const).map(s => (
                            <DropdownMenuItem key={s} onClick={() => {
                              overrideRuleStatus(patient.refId, version.version, res.ruleId, s);
                              toast.success(`${rule.id} overridden to ${s}`);
                            }}>
                              Override to {s}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </div>
                </div>
              );
            })}
            {filteredResults.length === 0 && (
              <div className="p-10 text-center text-sm text-slate-500">No rules match this filter.</div>
            )}
          </div>
        </div>
      </div>

      {/* Summary Dialog */}
      <Dialog open={summaryOpen} onOpenChange={setSummaryOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader><DialogTitle>{patient.name} — v{version.version} Summary</DialogTitle></DialogHeader>
          <div className="text-sm space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div><div className="text-xs text-slate-500">Reference ID</div><div className="font-mono">{patient.refId}</div></div>
              <div><div className="text-xs text-slate-500">Payor</div><div>{patient.payor}</div></div>
              <div><div className="text-xs text-slate-500">Score</div><div className="font-medium">{version.score}%</div></div>
              <div><div className="text-xs text-slate-500">Result</div><StatusBadge status={version.auditResult} /></div>
            </div>
            <div className="pt-3 border-t">
              <div className="text-xs text-slate-500 mb-2">Failed rules ({counts.Fail})</div>
              <ul className="space-y-2">
                {version.results.filter(r => r.status === "Fail").map(r => {
                  const rule = allRules.find(x => x.id === r.ruleId)!;
                  return <li key={r.ruleId} className="text-sm"><span className="font-mono text-xs">{r.ruleId}</span> — {rule.question}<div className="text-slate-600 text-xs mt-0.5">{r.finding}</div></li>;
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
