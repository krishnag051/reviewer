import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useReportsOverview, useReportsTrends } from "@/lib/real-data";
import { PageHeader } from "@/components/tp/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/reports")({ component: Reports });

// Fix Round (2026-09-11): this page used to compute everything from
// tp-mock.ts's fabricated patients/versions/reviewers via useTP() --
// confirmed real cause of the round-number placeholder look ("10
// processed, 10 passed, 0 failed"). Now reads the real backend the exact
// same way index.tsx's own Dashboard already did (Round 74's
// GET /reports/overview) plus GET /reports/trends for the matrix tab,
// which existed on the backend the whole time but nothing in the
// frontend ever called.
function Reports() {
  const [range, setRange] = useState<"week" | "lastweek" | "30d" | "all" | "custom">("30d");
  // "custom" needs a real start/end date-picker UI that doesn't exist yet
  // (the old mock version never actually branched on `range` either -- its
  // weekly bucket was hardcoded to "last 4 weeks" regardless of selection).
  // Falls back to "all" under the hood rather than sending an incomplete
  // custom range the backend would 400 on -- flagged here, not silently
  // pretended to work.
  const effectiveRange = range === "custom" ? "all" : range;
  const overviewQuery = useReportsOverview(effectiveRange);
  const overview = overviewQuery.data;

  const [groupBy, setGroupBy] = useState<"provider" | "questionset">("provider");
  const trendsQuery = useReportsTrends(groupBy);
  const trends = trendsQuery.data;

  const cards = {
    processed: overview?.processed ?? 0,
    passed: overview?.passed ?? 0,
    failed: overview?.failed ?? 0,
  };

  const weekly = overview?.weekly_volume ?? [];
  const maxWeekly = Math.max(1, ...weekly.map(w => w.pass_count + w.fail_count));

  const perReviewer = overview?.per_reviewer ?? [];

  // Matrix columns: the union of every rule_code any row's cells actually
  // has, sorted -- the trends endpoint returns cells as a {rule_code:
  // pass_rate} map per row (only populated for rule_codes that row has
  // real data for), not a fixed pre-declared column list.
  const matrixRuleCodes = Array.from(new Set((trends?.rows ?? []).flatMap(r => Object.keys(r.cells)))).sort();

  const isLoading = overviewQuery.isLoading || trendsQuery.isLoading;
  const isError = overviewQuery.isError || trendsQuery.isError;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Reports"
          description="Audit performance across the team and rule library."
          actions={
            <Select value={range} onValueChange={v => setRange(v as typeof range)}>
              <SelectTrigger className="w-40 h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="week">This week</SelectItem>
                <SelectItem value="lastweek">Last week</SelectItem>
                <SelectItem value="30d">Last 30 days</SelectItem>
                <SelectItem value="all">All time</SelectItem>
                <SelectItem value="custom">Custom</SelectItem>
              </SelectContent>
            </Select>
          }
        />

        {isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            Couldn't load real report data from the server.
          </div>
        )}

        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="trend">Trend Data</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6 mt-6">
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "TPs Processed", value: cards.processed, sub: "Across all patients" },
                { label: "Passed", value: cards.passed, sub: overview ? `${overview.passed_pct}% of total` : "—" },
                { label: "Failed", value: cards.failed, sub: overview ? `${overview.failed_pct}% of total` : "—" },
              ].map(c => (
                <div key={c.label} className="rounded-lg border border-slate-200 bg-white p-5">
                  <div className="text-sm text-slate-500">{c.label}</div>
                  <div className="mt-2 text-3xl font-semibold">{isLoading ? "—" : c.value}</div>
                  <div className="mt-1 text-xs text-slate-500">{c.sub}</div>
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-5">
              <div className="text-sm font-semibold mb-4">Weekly Pass/Fail volume</div>
              {weekly.length === 0 ? (
                <div className="text-sm text-slate-400 py-8 text-center">No finalized uploads in this range yet.</div>
              ) : (
                <>
                  <div className="flex items-stretch justify-around gap-6 h-48">
                    {weekly.map(w => (
                      <div key={w.week_start} className="flex-1 h-full flex flex-col items-center gap-2">
                        <div className="flex-1 w-full flex items-end gap-1 min-h-0">
                          <div className="flex-1 bg-emerald-500 rounded-t min-h-[2px]" style={{ height: `${(w.pass_count / maxWeekly) * 100}%` }} title={`Pass: ${w.pass_count}`} />
                          <div className="flex-1 bg-red-400 rounded-t min-h-[2px]" style={{ height: `${(w.fail_count / maxWeekly) * 100}%` }} title={`Fail: ${w.fail_count}`} />
                        </div>
                        <div className="text-xs text-slate-500">{w.week_start}</div>
                        <div className="text-xs text-slate-700 tabular-nums">{w.pass_count}/{w.fail_count}</div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
                    <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-sm bg-emerald-500" /> Pass</div>
                    <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-sm bg-red-400" /> Fail</div>
                  </div>
                </>
              )}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-200 text-sm font-semibold">Per-reviewer breakdown</div>
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">Reviewer</th>
                    <th className="text-left px-4 py-2 font-medium">Processed</th>
                    <th className="text-left px-4 py-2 font-medium">Passed</th>
                    <th className="text-left px-4 py-2 font-medium">Failed</th>
                    <th className="text-left px-4 py-2 font-medium w-56">Pass rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {perReviewer.length === 0 && (
                    <tr><td colSpan={5} className="px-4 py-6 text-center text-slate-400">No finalized uploads in this range yet.</td></tr>
                  )}
                  {perReviewer.map(row => (
                    <tr key={row.reviewer_id ?? row.reviewer_name ?? "unknown"}>
                      <td className="px-4 py-2.5">{row.reviewer_name ?? "Unassigned"}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.processed}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.passed}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.failed}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 flex-1 rounded-full bg-slate-100 overflow-hidden">
                            <div className={`h-full ${row.pass_rate >= 85 ? "bg-emerald-500" : row.pass_rate >= 70 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${row.pass_rate}%` }} />
                          </div>
                          <span className="tabular-nums text-xs w-10 text-right">{row.pass_rate}%</span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="trend" className="space-y-4 mt-6">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-600">Cells below 70% are highlighted for review.</div>
              <div className="inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-xs">
                {(["provider", "questionset"] as const).map(g => (
                  <button key={g} onClick={() => setGroupBy(g)}
                    className={`px-3 py-1.5 rounded ${groupBy === g ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                    Group by {g === "provider" ? "Provider" : "Question Set"}
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50 uppercase tracking-wide text-slate-500 sticky top-0">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium sticky left-0 bg-slate-50 z-10">{groupBy === "provider" ? "Reviewer" : "Question Set"}</th>
                    {matrixRuleCodes.map(code => (
                      <th key={code} className="text-center px-2 py-2 font-mono font-medium">{code}</th>
                    ))}
                    <th className="text-center px-3 py-2 font-medium bg-slate-100">Avg</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {(!trends || trends.rows.length === 0) && (
                    <tr><td colSpan={matrixRuleCodes.length + 2} className="px-4 py-6 text-center text-slate-400">No finalized, overridden audits yet.</td></tr>
                  )}
                  {trends?.rows.map(row => (
                    <tr key={row.row_key}>
                      <td className="px-3 py-2 font-medium sticky left-0 bg-white z-10 whitespace-nowrap">{row.row_label}</td>
                      {matrixRuleCodes.map(code => {
                        const c = row.cells[code] ?? null;
                        return (
                          <td key={code} className={cn("text-center px-2 py-2 tabular-nums",
                            c === null ? "text-slate-300" : c < 70 ? "bg-red-50 text-red-800" : "text-slate-700")}>
                            {c === null ? "—" : `${c}%`}
                          </td>
                        );
                      })}
                      <td className="text-center px-3 py-2 tabular-nums font-medium bg-slate-50">{row.average ?? "—"}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
