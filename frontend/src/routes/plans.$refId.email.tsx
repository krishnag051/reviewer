import { createFileRoute, useNavigate, notFound } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, rules as allRules } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Bold, Italic, Underline, List, Link2, Send, Copy, ChevronLeft } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/plans/$refId/email")({ component: EmailPage });

function EmailPage() {
  const { refId } = Route.useParams();
  const nav = useNavigate();
  const { patients } = useTP();
  const patient = patients.find(p => p.refId === refId);
  if (!patient) throw notFound();
  const version = [...patient.versions].sort((a, b) => b.version - a.version)[0];
  const reviewer = reviewers.find(r => r.id === version.reviewerId)!;

  const [to, setTo] = useState(reviewer.email);
  const [showCc, setShowCc] = useState(false);
  const [showBcc, setShowBcc] = useState(false);
  const [cc, setCc] = useState("");
  const [bcc, setBcc] = useState("");
  const [subject, setSubject] = useState(`Treatment Plan Correction Needed — ${patient.name} — ${patient.refId}`);
  const [groupBy, setGroupBy] = useState<"section" | "page">("section");

  const failed = version.results.filter(r => r.status === "Fail");

  const body = useMemo(() => {
    const opening = `Hi ${reviewer.name.split(" ")[0]},\n\nOur automated compliance review flagged ${failed.length} item(s) on Version ${version.version} of the treatment plan for ${patient.name} (${patient.refId}). Please review and revise the items below at your earliest convenience.\n\n`;
    let grouped = "";
    if (groupBy === "section") {
      const bySection: Record<string, typeof failed> = {};
      failed.forEach(f => {
        const rule = allRules.find(r => r.id === f.ruleId)!;
        (bySection[rule.category] ??= []).push(f);
      });
      grouped = Object.entries(bySection).map(([cat, items]) => {
        const lines = items.map(f => {
          const rule = allRules.find(r => r.id === f.ruleId)!;
          return `  • [${rule.id}] ${rule.question}\n    Finding: ${f.finding}\n    Reference: p.${f.pages.join(", p.")}`;
        }).join("\n\n");
        return `${cat}\n${lines}`;
      }).join("\n\n");
    } else {
      const byPage: Record<number, typeof failed> = {};
      failed.forEach(f => f.pages.forEach(p => { (byPage[p] ??= []).push(f); }));
      grouped = Object.entries(byPage).sort((a, b) => Number(a[0]) - Number(b[0])).map(([p, items]) => {
        const lines = items.map(f => {
          const rule = allRules.find(r => r.id === f.ruleId)!;
          return `  • [${rule.id}] ${rule.question}\n    Finding: ${f.finding}`;
        }).join("\n\n");
        return `Page ${p}\n${lines}`;
      }).join("\n\n");
    }
    const closing = `\n\nOnce revised, please re-upload the plan and it will be automatically re-audited. Reply to this email if any finding needs clarification.\n\nThanks,\nM. Chen, BCBA-D\nClinical Director, BrightPath ABA`;
    return opening + grouped + closing;
  }, [failed, groupBy, patient, version, reviewer]);

  const [editedBody, setEditedBody] = useState(body);
  // Reset body when groupBy changes
  useMemo(() => setEditedBody(body), [body]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-8">
        <button onClick={() => nav({ to: "/plans/$refId", params: { refId } })} className="text-sm text-slate-500 hover:text-slate-900 mb-4 inline-flex items-center gap-1"><ChevronLeft className="h-4 w-4" />Back to plan</button>
        <PageHeader
          title="Correction Email"
          description={`${failed.length} failed item${failed.length === 1 ? "" : "s"} · ${patient.name} · v${version.version}`}
          actions={
            <div className="inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-xs">
              {(["section", "page"] as const).map(g => (
                <button key={g} onClick={() => setGroupBy(g)}
                  className={`px-3 py-1.5 rounded ${groupBy === g ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
                  Group by {g === "section" ? "Section" : "Page"}
                </button>
              ))}
            </div>
          }
        />

        <div className="mt-6 rounded-lg border border-slate-200 bg-white overflow-hidden">
          <div className="divide-y divide-slate-100">
            <div className="flex items-center gap-3 px-4 py-2">
              <Label className="w-14 text-xs text-slate-500">To</Label>
              <Input value={to} onChange={e => setTo(e.target.value)} className="border-0 shadow-none focus-visible:ring-0 px-0 h-8" />
              <div className="flex gap-2 text-xs text-slate-500">
                {!showCc && <button onClick={() => setShowCc(true)} className="hover:text-slate-900">Cc</button>}
                {!showBcc && <button onClick={() => setShowBcc(true)} className="hover:text-slate-900">Bcc</button>}
              </div>
            </div>
            {showCc && (
              <div className="flex items-center gap-3 px-4 py-2">
                <Label className="w-14 text-xs text-slate-500">Cc</Label>
                <Input value={cc} onChange={e => setCc(e.target.value)} placeholder="Add recipients (comma-separated)" className="border-0 shadow-none focus-visible:ring-0 px-0 h-8" />
              </div>
            )}
            {showBcc && (
              <div className="flex items-center gap-3 px-4 py-2">
                <Label className="w-14 text-xs text-slate-500">Bcc</Label>
                <Input value={bcc} onChange={e => setBcc(e.target.value)} placeholder="Add recipients (comma-separated)" className="border-0 shadow-none focus-visible:ring-0 px-0 h-8" />
              </div>
            )}
            <div className="flex items-center gap-3 px-4 py-2">
              <Label className="w-14 text-xs text-slate-500">Subject</Label>
              <Input value={subject} onChange={e => setSubject(e.target.value)} className="border-0 shadow-none focus-visible:ring-0 px-0 h-8 font-medium" />
            </div>
          </div>

          <div className="border-t border-slate-200 bg-slate-50 px-3 py-1.5 flex items-center gap-1">
            {[Bold, Italic, Underline, List, Link2].map((Icon, i) => (
              <Button key={i} variant="ghost" size="icon" className="h-7 w-7 text-slate-500 hover:text-slate-900"><Icon className="h-3.5 w-3.5" /></Button>
            ))}
          </div>

          <Textarea
            value={editedBody}
            onChange={e => setEditedBody(e.target.value)}
            className="min-h-[420px] border-0 shadow-none focus-visible:ring-0 font-mono text-[13px] leading-relaxed resize-y"
          />

          <div className="border-t border-slate-200 px-4 py-3 flex items-center justify-between bg-slate-50">
            <div className="text-xs text-slate-500">This preview will send from notify@brightpath-aba.com</div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => { navigator.clipboard.writeText(editedBody); toast.success("Email body copied"); }}>
                <Copy className="h-3.5 w-3.5 mr-1.5" />Copy
              </Button>
              <Button size="sm" onClick={() => toast.success(`Correction email sent to ${to}`)}>
                <Send className="h-3.5 w-3.5 mr-1.5" />Send Now
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
