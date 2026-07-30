import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, PAYORS as ALL_PAYORS, type Payor } from "@/lib/tp-mock";
import { StatusBadge, ReviewedBadge, PageHeader } from "@/components/tp/ui";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, FileClock, Loader2 } from "lucide-react";

export const Route = createFileRoute("/plans/")({ component: PlansList });

const PAYOR_FILTER_OPTIONS: (Payor | "all")[] = ["all", ...ALL_PAYORS];

function PlansList() {
  const { patients } = useTP();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [payor, setPayor] = useState<Payor | "all">("all");
  const [result, setResult] = useState<"all" | "Pass" | "Fail">("all");

  function matchesFilters(p: (typeof patients)[number], reviewerId: string, auditResult: "Pass" | "Fail") {
    const rev = reviewers.find(r => r.id === reviewerId)!;
    const matchQ = !q || p.name.toLowerCase().includes(q.toLowerCase()) || p.refId.toLowerCase().includes(q.toLowerCase()) || rev.name.toLowerCase().includes(q.toLowerCase());
    const matchP = payor === "all" || p.payor === payor;
    const matchR = result === "all" || auditResult === result;
    return matchQ && matchP && matchR;
  }

  // Finalized rows: unchanged from before -- one row per patient using
  // their latest finalized version, regardless of whether a newer draft is
  // also pending against the next slot. That case needs no special
  // handling here: the patient still has a real finalized version, so it
  // belongs in this table exactly as it always did; the pending draft is
  // visible on the patient's own detail page, not duplicated here.
  const rows = useMemo(() => {
    return patients.filter(p => p.versions.length > 0).map(p => {
      const latest = [...p.versions].sort((a, b) => b.version - a.version)[0];
      return { p, latest };
    }).filter(({ p, latest }) => matchesFilters(p, latest.reviewerId, latest.auditResult));
  }, [patients, q, payor, result]);

  // Draft-only rows: patients with NO finalized version yet, only draft
  // attempts against their still-open V1 (or whichever slot is first).
  // These used to be invisible in this list entirely -- now surfaced in
  // their own section, using the latest attempt's own data (same data
  // already shown on the patient detail page), labeled "U[n]" rather than
  // "v[n]" so it's never mistaken for a real, finalized version number.
  const draftRows = useMemo(() => {
    return patients.filter(p => p.versions.length === 0 && p.uAttempts.length > 0).map(p => {
      const latest = [...p.uAttempts].sort((a, b) => b.attemptNumber - a.attemptNumber)[0];
      return { p, latest };
    }).filter(({ p, latest }) => matchesFilters(p, latest.reviewerId, latest.auditResult));
  }, [patients, q, payor, result]);

  const totalDraftOnlyPatients = patients.filter(p => p.versions.length === 0 && p.uAttempts.length > 0).length;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Treatment Plans"
          description={
            `${rows.length} patient(s) with a finalized version`
            + (totalDraftOnlyPatients > 0 ? ` · ${totalDraftOnlyPatients} more with only a draft in progress (shown below)` : "")
            + "."
          }
        />

        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search patient, reference ID, or reviewer" className="pl-8" />
          </div>
          <Select value={payor} onValueChange={v => setPayor(v as Payor | "all")}>
            <SelectTrigger className="w-40"><SelectValue placeholder="Payor" /></SelectTrigger>
            <SelectContent>{PAYOR_FILTER_OPTIONS.map(p => <SelectItem key={p} value={p}>{p === "all" ? "All payors" : p}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={result} onValueChange={v => setResult(v as "all" | "Pass" | "Fail")}>
            <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All results</SelectItem>
              <SelectItem value="Pass">Pass</SelectItem>
              <SelectItem value="Fail">Fail</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {draftRows.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/40 overflow-hidden">
            <div className="px-4 py-2.5 flex items-center gap-1.5 text-xs font-medium text-amber-900 border-b border-amber-200">
              <FileClock className="h-3.5 w-3.5" />
              In progress — draft uploads not yet finalized ({draftRows.length})
            </div>
            <table className="w-full text-sm">
              <thead className="bg-amber-50/60 text-xs uppercase tracking-wide text-amber-700">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Patient</th>
                  <th className="text-left px-4 py-2 font-medium">Reference ID</th>
                  <th className="text-left px-4 py-2 font-medium">Attempt</th>
                  <th className="text-left px-4 py-2 font-medium">Payor</th>
                  <th className="text-left px-4 py-2 font-medium">Assessment</th>
                  <th className="text-left px-4 py-2 font-medium">Score</th>
                  <th className="text-left px-4 py-2 font-medium">Reviewer</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-left px-4 py-2 font-medium">Latest Result</th>
                  <th className="text-right px-4 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {draftRows.map(({ p, latest }) => {
                  const rev = reviewers.find(r => r.id === latest.reviewerId)!;
                  return (
                    <tr key={p.refId} className="hover:bg-amber-50 cursor-pointer" onClick={() => nav({ to: "/plans/$refId", params: { refId: p.refId } })}>
                      <td className="px-4 py-3 font-medium">{p.name}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-xs">{p.refId}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-md border border-amber-300 bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                          U{latest.attemptNumber}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-600">{p.payor}</td>
                      <td className="px-4 py-3 text-slate-600">{latest.assessmentDate}</td>
                      <td className="px-4 py-3">
                        {latest.status === "processing" ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-blue-700">
                            <Loader2 className="h-3 w-3 animate-spin" />Processing…
                          </span>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="font-medium tabular-nums w-9">{latest.score}%</span>
                            <div className="h-1.5 w-20 rounded-full bg-slate-100 overflow-hidden">
                              <div className={`h-full ${latest.score >= 85 ? "bg-emerald-500" : latest.score >= 70 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${latest.score}%` }} />
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">{rev.name}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center rounded-md border border-amber-200 bg-white px-2 py-0.5 text-xs font-medium text-amber-700">
                          Not finalized
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {latest.status === "processing" ? (
                          <span className="inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700">Processing</span>
                        ) : (
                          <StatusBadge status={latest.auditResult} />
                        )}
                      </td>
                      <td className="px-4 py-3 text-right"><span className="text-xs text-slate-500 hover:text-slate-900">Open →</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">Patient</th>
                <th className="text-left px-4 py-2.5 font-medium">Reference ID</th>
                <th className="text-left px-4 py-2.5 font-medium">Version</th>
                <th className="text-left px-4 py-2.5 font-medium">Payor</th>
                <th className="text-left px-4 py-2.5 font-medium">Assessment</th>
                <th className="text-left px-4 py-2.5 font-medium">Score</th>
                <th className="text-left px-4 py-2.5 font-medium">Reviewed By</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium">Result</th>
                <th className="text-right px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(({ p, latest }) => {
                const rev = reviewers.find(r => r.id === latest.reviewerId)!;
                return (
                  <tr key={p.refId} className="hover:bg-slate-50 cursor-pointer" onClick={() => nav({ to: "/plans/$refId", params: { refId: p.refId } })}>
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 text-slate-600 font-mono text-xs">{p.refId}</td>
                    <td className="px-4 py-3 text-slate-600">v{latest.version}</td>
                    <td className="px-4 py-3 text-slate-600">{p.payor}</td>
                    <td className="px-4 py-3 text-slate-600">{latest.assessmentDate}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium tabular-nums w-9">{latest.score}%</span>
                        <div className="h-1.5 w-20 rounded-full bg-slate-100 overflow-hidden">
                          <div className={`h-full ${latest.score >= 85 ? "bg-emerald-500" : latest.score >= 70 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${latest.score}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{rev.name}</td>
                    <td className="px-4 py-3"><ReviewedBadge reviewed={latest.reviewed} /></td>
                    <td className="px-4 py-3"><StatusBadge status={latest.auditResult} /></td>
                    <td className="px-4 py-3 text-right"><span className="text-xs text-slate-500 hover:text-slate-900">Open →</span></td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr><td colSpan={10} className="px-4 py-10 text-center text-sm text-slate-500">No plans match your filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
