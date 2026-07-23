import { createFileRoute, Link } from "@tanstack/react-router";
import { useTP } from "@/lib/tp-context";
import { reviewers } from "@/lib/tp-mock";
import { StatusBadge, PageHeader } from "@/components/tp/ui";
import { Upload, FileText, BookOpen, BarChart3, ArrowUpRight } from "lucide-react";

export const Route = createFileRoute("/")({ component: Dashboard });

function Dashboard() {
  const { patients } = useTP();
  const versions = patients.flatMap(p => p.versions.map(v => ({ p, v })));
  const passed = versions.filter(x => x.v.auditResult === "Pass").length;
  const failed = versions.filter(x => x.v.auditResult === "Fail").length;
  const reviewed = passed + failed;

  const recent = [...versions]
    .sort((a, b) => b.v.uploadedAt.localeCompare(a.v.uploadedAt))
    .slice(0, 8);

  const cards = [
    { label: "TPs Reviewed", value: reviewed, hint: "Automated audit complete" },
    { label: "Passed TPs", value: passed, hint: "Automated audit ≥ 85%" },
    { label: "Failed TPs", value: failed, hint: "Automated audit < 85%" },
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
        <PageHeader title="Dashboard" description="Compliance audit overview for BrightPath ABA — as of July 15, 2026." />

        <div className="grid grid-cols-3 gap-4">
          {cards.map(c => (
            <div key={c.label} className="rounded-lg border border-slate-200 bg-white p-5">
              <div className="text-sm text-slate-500">{c.label}</div>
              <div className="mt-2 text-3xl font-semibold">{c.value}</div>
              <div className="mt-1 text-xs text-slate-500">{c.hint}</div>
            </div>
          ))}
        </div>

        <div>
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Quick actions</h2>
          <div className="grid grid-cols-4 gap-3">
            {quick.map(q => (
              <Link key={q.to} to={q.to} className="group rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-900 transition-colors">
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
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
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
                {recent.map(({ p, v }) => {
                  const rev = reviewers.find(r => r.id === v.reviewerId)!;
                  return (
                    <tr key={p.refId + v.version} className="hover:bg-slate-50 cursor-pointer" onClick={() => (window.location.href = `/plans/${p.refId}`)}>
                      <td className="px-4 py-3 font-medium">{p.name}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-xs">{p.refId}</td>
                      <td className="px-4 py-3 text-slate-600">v{v.version}</td>
                      <td className="px-4 py-3 text-slate-600">{rev.name}, {rev.credentials}</td>
                      <td className="px-4 py-3 text-slate-600">{v.uploadedAt}</td>
                      <td className="px-4 py-3"><StatusBadge status={v.auditResult} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
