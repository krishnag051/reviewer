import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { usePatients } from "@/lib/real-data";
import { StatusBadge, ReviewedBadge, PageHeader } from "@/components/tp/ui";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Search, FileClock, Loader2 } from "lucide-react";

export const Route = createFileRoute("/plans/")({ component: PlansList });

// Round 41, Stage 1: real data from the backend's GET /patients, not mock.
// One simplification vs. the old mock-data page, stated plainly rather
// than silently: GET /patients returns each patient's LATEST version's
// score/audit_result/reviewed only -- it doesn't expose per-attempt detail
// (upload number, live processing status) without an extra fetch per
// patient. Rather than N+1-fetching every patient just to populate this
// list, the "in progress" section below shows real patients whose latest
// version isn't finalized yet (score/audit_result null), but without the
// old per-draft "U[n]"/processing detail -- open the patient to see that
// (plans.$refId.index.tsx does fetch that detail, real, for the one
// patient being viewed).
function PlansList() {
  const { data: patients = [], isLoading } = usePatients();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [result, setResult] = useState<"all" | "pass" | "fail">("all");

  function matchesFilters(name: string, refId: string, auditResult: string | null) {
    const matchQ = !q || name.toLowerCase().includes(q.toLowerCase()) || refId.toLowerCase().includes(q.toLowerCase());
    const matchR = result === "all" || auditResult === result;
    return matchQ && matchR;
  }

  const rows = useMemo(
    () => patients.filter(p => p.audit_result !== null).filter(p => matchesFilters(p.name, p.reference_id, p.audit_result)),
    [patients, q, result],
  );
  const draftRows = useMemo(
    () => patients.filter(p => p.audit_result === null).filter(p => matchesFilters(p.name, p.reference_id, null)),
    [patients, q, result],
  );

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Treatment Plans"
          description={
            (isLoading ? "Loading real data from the backend…" : `${rows.length} patient(s) with a finalized version`)
            + (!isLoading && draftRows.length > 0 ? ` · ${draftRows.length} more with only a draft in progress (shown below)` : "")
            + (isLoading ? "" : ".")
          }
        />

        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search patient or reference ID" className="pl-8" />
          </div>
          <Select value={result} onValueChange={v => setResult(v as "all" | "pass" | "fail")}>
            <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All results</SelectItem>
              <SelectItem value="pass">Pass</SelectItem>
              <SelectItem value="fail">Fail</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500 py-6">
            <Loader2 className="h-4 w-4 animate-spin" />Loading real patients from the backend…
          </div>
        )}

        {!isLoading && draftRows.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50/40 overflow-hidden">
            <div className="px-4 py-2.5 flex items-center gap-1.5 text-xs font-medium text-amber-900 border-b border-amber-200">
              <FileClock className="h-3.5 w-3.5" />
              In progress — not yet finalized ({draftRows.length})
            </div>
            <table className="w-full text-sm">
              <thead className="bg-amber-50/60 text-xs uppercase tracking-wide text-amber-700">
                <tr>
                  <th className="text-left px-4 py-2 font-medium">Patient</th>
                  <th className="text-left px-4 py-2 font-medium">Reference ID</th>
                  <th className="text-left px-4 py-2 font-medium">Payor</th>
                  <th className="text-left px-4 py-2 font-medium">Latest slot</th>
                  <th className="text-left px-4 py-2 font-medium">Status</th>
                  <th className="text-right px-4 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-100">
                {draftRows.map(p => (
                  <tr key={p.id} className="hover:bg-amber-50 cursor-pointer" onClick={() => nav({ to: "/plans/$refId", params: { refId: p.reference_id } })}>
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 text-slate-600 font-mono text-xs">{p.reference_id}</td>
                    <td className="px-4 py-3 text-slate-600">{p.payor ?? "—"}</td>
                    <td className="px-4 py-3 text-slate-600">{p.latest_version_number ? `V${p.latest_version_number}` : "No version yet"}</td>
                    <td className="px-4 py-3">
                      <span className="inline-flex items-center rounded-md border border-amber-200 bg-white px-2 py-0.5 text-xs font-medium text-amber-700">
                        Not finalized
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right"><span className="text-xs text-slate-500 hover:text-slate-900">Open →</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!isLoading && (
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">Patient</th>
                  <th className="text-left px-4 py-2.5 font-medium">Reference ID</th>
                  <th className="text-left px-4 py-2.5 font-medium">Version</th>
                  <th className="text-left px-4 py-2.5 font-medium">Payor</th>
                  <th className="text-left px-4 py-2.5 font-medium">Score</th>
                  <th className="text-left px-4 py-2.5 font-medium">Status</th>
                  <th className="text-left px-4 py-2.5 font-medium">Result</th>
                  <th className="text-right px-4 py-2.5 font-medium"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map(p => (
                  <tr key={p.id} className="hover:bg-slate-50 cursor-pointer" onClick={() => nav({ to: "/plans/$refId", params: { refId: p.reference_id } })}>
                    <td className="px-4 py-3 font-medium">{p.name}</td>
                    <td className="px-4 py-3 text-slate-600 font-mono text-xs">{p.reference_id}</td>
                    <td className="px-4 py-3 text-slate-600">v{p.latest_version_number}</td>
                    <td className="px-4 py-3 text-slate-600">{p.payor ?? "—"}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium tabular-nums w-9">{p.score}%</span>
                        <div className="h-1.5 w-20 rounded-full bg-slate-100 overflow-hidden">
                          <div className={`h-full ${p.score! >= 85 ? "bg-emerald-500" : p.score! >= 70 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${p.score}%` }} />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3"><ReviewedBadge reviewed={!!p.reviewed} /></td>
                    <td className="px-4 py-3"><StatusBadge status={p.audit_result === "pass" ? "Pass" : "Fail"} /></td>
                    <td className="px-4 py-3 text-right"><span className="text-xs text-slate-500 hover:text-slate-900">Open →</span></td>
                  </tr>
                ))}
                {rows.length === 0 && (
                  <tr><td colSpan={8} className="px-4 py-10 text-center text-sm text-slate-500">No plans match your filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
