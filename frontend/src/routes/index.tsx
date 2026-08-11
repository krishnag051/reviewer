import { createFileRoute, Link } from "@tanstack/react-router";
import { useReportsOverview, useRecentActivity } from "@/lib/real-data";
import { StatusBadge, PageHeader } from "@/components/tp/ui";
import { Upload, FileText, BookOpen, BarChart3, ArrowUpRight, Loader2 } from "lucide-react";

export const Route = createFileRoute("/")({ component: Dashboard });

// Round 74, Item 3: real GET /reports/overview + GET /reports/recent-activity
// (both new this round -- app/routers/reports.py -- built specifically to
// replace this page's entire previous data source, frontend/src/lib/
// tp-mock.ts's fabricated patients/versions, e.g. "Aaliyah Washington,"
// "Liam O'Sullivan" -- none of which exist anywhere in the real database).
//
// Round 88: the three cards below used to only count FINALIZED versions --
// correct reasoning at the time (nothing had been finalized yet, so 0 was
// the honest answer), but this system's real use pattern since then is
// repeated real pipeline runs with finalize never actually used, so the
// cards stayed frozen at 0 forever while real activity (visible right
// below, in Recent activity) kept happening. app/services/reports.py's
// get_overview now counts real, completed pipeline runs (any upload with
// status "ready", pass/fail computed live from its own rule_results) --
// see that function's own docstring for the full decision, including why
// the per-reviewer/weekly-volume metrics deliberately stayed finalized-only
// (a genuinely separate, more formal "what did this reviewer sign off on"
// question -- neither of those is rendered on this page anyway).
function Dashboard() {
  const overviewQuery = useReportsOverview();
  const activityQuery = useRecentActivity(8);

  const cards = [
    { label: "TPs Reviewed", value: overviewQuery.data?.processed, hint: "Real pipeline runs completed" },
    { label: "Passed TPs", value: overviewQuery.data?.passed, hint: "Completed with a passing score" },
    { label: "Failed TPs", value: overviewQuery.data?.failed, hint: "Completed with a failing score" },
  ];
  const quick = [
    { to: "/upload", label: "Upload New", icon: Upload, desc: "Submit a new treatment plan for audit" },
    { to: "/plans", label: "Treatment Plans", icon: FileText, desc: "Review all patient audit results" },
    { to: "/rules", label: "Rules Studio", icon: BookOpen, desc: "Manage the compliance ruleset" },
    { to: "/reports", label: "Reports", icon: BarChart3, desc: "Team and rule-level trends" },
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-8">
        <PageHeader title="Dashboard" description="Real compliance audit overview — live from the database, updated as uploads and finalizations happen." />

        <div className="grid grid-cols-3 gap-4">
          {cards.map(c => (
            <div key={c.label} className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="text-sm text-slate-500">{c.label}</div>
              <div className="mt-2 text-3xl font-semibold">
                {overviewQuery.isLoading ? <Loader2 className="h-6 w-6 animate-spin text-slate-300" /> : c.value ?? 0}
              </div>
              <div className="mt-1 text-xs text-slate-500">{c.hint}</div>
            </div>
          ))}
        </div>

        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Quick actions</h2>
          <div className="grid grid-cols-4 gap-3">
            {quick.map(q => (
              <Link key={q.to} to={q.to} className="group rounded-xl border border-slate-200 bg-white p-4 shadow-sm hover:border-slate-900 hover:shadow transition-all">
                <div className="flex items-center justify-between">
                  <q.icon className="h-5 w-5 text-slate-700" />
                  <ArrowUpRight className="h-4 w-4 text-slate-400 group-hover:text-slate-900" />
                </div>
                <div className="mt-3 text-sm font-medium">{q.label}</div>
                <div className="mt-0.5 text-xs text-slate-500">{q.desc}</div>
              </Link>
            ))}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-700">Recent activity</h2>
            <Link to="/plans" className="text-xs text-slate-600 hover:text-slate-900">View all →</Link>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
            {activityQuery.isLoading && (
              <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
                <Loader2 className="h-4 w-4 animate-spin" />Loading…
              </div>
            )}
            {activityQuery.data && activityQuery.data.length === 0 && (
              <div className="p-6 text-center text-sm text-slate-500">
                No uploads yet — nothing has been submitted to this system for real review.
              </div>
            )}
            {activityQuery.data && activityQuery.data.length > 0 && (
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium">Patient</th>
                    <th className="text-left px-4 py-2.5 font-medium">Reference ID</th>
                    <th className="text-left px-4 py-2.5 font-medium">Version</th>
                    <th className="text-left px-4 py-2.5 font-medium">Reviewer</th>
                    <th className="text-left px-4 py-2.5 font-medium">Date</th>
                    <th className="text-left px-4 py-2.5 font-medium">Result</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {activityQuery.data.map(a => (
                    <tr
                      key={a.upload_id}
                      className="hover:bg-slate-50 cursor-pointer"
                      onClick={() => (window.location.href = `/plans/${a.reference_id}`)}
                    >
                      <td className="px-4 py-3 font-medium">{a.patient_name}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-xs">{a.reference_id}</td>
                      <td className="px-4 py-3 text-slate-600">v{a.version_number}</td>
                      <td className="px-4 py-3 text-slate-600">{a.reviewer_name ?? "—"}</td>
                      <td className="px-4 py-3 text-slate-600">{new Date(a.created_at).toLocaleDateString()}</td>
                      <td className="px-4 py-3">
                        {a.audit_result === "pass" || a.audit_result === "fail" ? (
                          <StatusBadge status={a.audit_result === "pass" ? "Pass" : "Fail"} />
                        ) : (
                          <span className="inline-flex items-center rounded-md border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700">
                            Not finalized
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
