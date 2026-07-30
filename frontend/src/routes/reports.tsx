import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, rules as allRules } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/reports")({ component: Reports });

function Reports() {
  const { patients } = useTP();
  const versions = patients.flatMap(p => p.versions);
  const [range, setRange] = useState("30d");

  const cards = useMemo(() => {
    const processed = versions.length;
    const passed = versions.filter(v => v.auditResult === "Pass").length;
    const failed = versions.filter(v => v.auditResult === "Fail").length;
    return { processed, passed, failed };
  }, [versions]);

  const weekly = useMemo(() => {
    const buckets = [0, 1, 2, 3].map(i => {
      const label = `W-${4 - i}`;
      const from = i * 7, to = (i + 1) * 7;
      const inRange = versions.filter(v => {
        const days = Math.abs((new Date(v.finalizedAt).getTime() - new Date("2026-07-15").getTime()) / 86400000);
        return days >= from && days < to;
      });
      const passed = inRange.filter(v => v.auditResult === "Pass").length;
      const failed = inRange.filter(v => v.auditResult === "Fail").length;
      return { label, passed, failed };
    }).reverse();
    return buckets;
  }, [versions]);

  const maxWeekly = Math.max(1, ...weekly.map(w => w.passed + w.failed));

  const perReviewer = useMemo(() => {
    return reviewers.map(r => {
      const items = versions.filter(v => v.reviewerId === r.id);
      const passed = items.filter(v => v.auditResult === "Pass").length;
      const failed = items.filter(v => v.auditResult === "Fail").length;
      const rate = items.length ? Math.round((passed / items.length) * 100) : 0;
      return { r, processed: items.length, passed, failed, rate };
    });
  }, [versions]);

  const [groupBy, setGroupBy] = useState<"provider" | "questionset">("provider");
  const matrix = useMemo(() => {
    const activeRules = allRules.filter(r => r.active).slice(0, 12);
    const rows = reviewers.map(rev => {
      const revVersions = versions.filter(v => v.reviewerId === rev.id);
      const cells = activeRules.map(rule => {
        const results = revVersions.flatMap(v => v.results.filter(r => r.ruleId === rule.id));
        const nonNa = results.filter(r => r.status !== "N/A");
        if (nonNa.length === 0) return null;
        const passed = nonNa.filter(r => r.status === "Pass").length;
        return Math.round((passed / nonNa.length) * 100);
      });
      const nonNull = cells.filter((c): c is number => c !== null);
      const avg = nonNull.length ? Math.round(nonNull.reduce((a, b) => a + b, 0) / nonNull.length) : 0;
      return { label: `${rev.name}, ${rev.credentials}`, cells, avg };
    });
    return { rules: activeRules, rows };
  }, [versions]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Reports"
          description="Audit performance across the team and rule library."
          actions={
            <Select value={range} onValueChange={setRange}>
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

        <Tabs defaultValue="overview">
          <TabsList>
            <TabsTrigger value="overview">Overview</TabsTrigger>
            <TabsTrigger value="trend">Trend Data</TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="space-y-6 mt-6">
            <div className="grid grid-cols-3 gap-4">
              {[
                { label: "TPs Processed", value: cards.processed, sub: "Across all patients" },
                { label: "Passed", value: cards.passed, sub: cards.processed ? `${Math.round(cards.passed / cards.processed * 100)}% of total` : "—" },
                { label: "Failed", value: cards.failed, sub: cards.processed ? `${Math.round(cards.failed / cards.processed * 100)}% of total` : "—" },
              ].map(c => (
                <div key={c.label} className="rounded-lg border border-slate-200 bg-white p-5">
                  <div className="text-sm text-slate-500">{c.label}</div>
                  <div className="mt-2 text-3xl font-semibold">{c.value}</div>
                  <div className="mt-1 text-xs text-slate-500">{c.sub}</div>
                </div>
              ))}
            </div>

            <div className="rounded-lg border border-slate-200 bg-white p-5">
              <div className="text-sm font-semibold mb-4">Weekly Pass/Fail volume (last 4 weeks)</div>
              <div className="flex items-stretch justify-around gap-6 h-48">
                {weekly.map(w => (
                  <div key={w.label} className="flex-1 h-full flex flex-col items-center gap-2">
                    <div className="flex-1 w-full flex items-end gap-1 min-h-0">
                      <div className="flex-1 bg-emerald-500 rounded-t min-h-[2px]" style={{ height: `${(w.passed / maxWeekly) * 100}%` }} title={`Pass: ${w.passed}`} />
                      <div className="flex-1 bg-red-400 rounded-t min-h-[2px]" style={{ height: `${(w.failed / maxWeekly) * 100}%` }} title={`Fail: ${w.failed}`} />
                    </div>
                    <div className="text-xs text-slate-500">{w.label}</div>
                    <div className="text-xs text-slate-700 tabular-nums">{w.passed}/{w.failed}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-4 text-xs text-slate-500">
                <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-sm bg-emerald-500" /> Pass</div>
                <div className="flex items-center gap-1.5"><div className="h-2 w-2 rounded-sm bg-red-400" /> Fail</div>
              </div>
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
                  {perReviewer.map(row => (
                    <tr key={row.r.id}>
                      <td className="px-4 py-2.5">{row.r.name}, {row.r.credentials}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.processed}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.passed}</td>
                      <td className="px-4 py-2.5 text-slate-600 tabular-nums">{row.failed}</td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 flex-1 rounded-full bg-slate-100 overflow-hidden">
                            <div className={`h-full ${row.rate >= 85 ? "bg-emerald-500" : row.rate >= 70 ? "bg-amber-500" : "bg-red-500"}`} style={{ width: `${row.rate}%` }} />
                          </div>
                          <span className="tabular-nums text-xs w-10 text-right">{row.rate}%</span>
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
                    {matrix.rules.map(r => (
                      <th key={r.id} className="text-center px-2 py-2 font-mono font-medium">{r.id}</th>
                    ))}
                    <th className="text-center px-3 py-2 font-medium bg-slate-100">Avg</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {matrix.rows.map(row => (
                    <tr key={row.label}>
                      <td className="px-3 py-2 font-medium sticky left-0 bg-white z-10 whitespace-nowrap">{row.label}</td>
                      {row.cells.map((c, i) => (
                        <td key={i} className={cn("text-center px-2 py-2 tabular-nums",
                          c === null ? "text-slate-300" : c < 70 ? "bg-red-50 text-red-800" : "text-slate-700")}>
                          {c === null ? "—" : `${c}%`}
                        </td>
                      ))}
                      <td className="text-center px-3 py-2 tabular-nums font-medium bg-slate-50">{row.avg}%</td>
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
