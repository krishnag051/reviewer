import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTP } from "@/lib/tp-context";
import type { Rule } from "@/lib/tp-mock";
import { PageHeader, CategoryTag } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Pencil, Trash2, Search, Lock } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/textarea";

export const Route = createFileRoute("/rules")({ component: RulesStudio });

const CATS: Rule["category"][] = ["Patient Info", "Diagnosis", "Assessment", "Goals & Objectives", "Service Delivery", "Behavior Plan", "Authorization", "Signatures"];
const QSETS: Rule["questionSet"][] = ["Treatment Plan", "97151", "97153", "97155", "97156"];

function RulesStudio() {
  const { rules, role, upsertRule, deleteRule, toggleRule } = useTP();
  const readOnly = role !== "Admin";
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<Rule["category"] | "all">("all");
  const [editing, setEditing] = useState<Rule | null>(null);
  const [open, setOpen] = useState(false);

  const filtered = useMemo(() => rules.filter(r =>
    (cat === "all" || r.category === cat) &&
    (!q || r.question.toLowerCase().includes(q.toLowerCase()) || r.id.toLowerCase().includes(q.toLowerCase()))
  ), [rules, cat, q]);

  function openNew() {
    setEditing({ id: `R-${String(Math.floor(Math.random() * 900) + 100)}`, category: "Assessment", questionSet: "Treatment Plan", question: "", severity: "Normal", active: true });
    setOpen(true);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Rules Studio"
          description={`${rules.length} rules · ${rules.filter(r => r.active).length} active`}
          actions={readOnly
            ? <div className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 text-amber-800 px-2.5 py-1 text-xs"><Lock className="h-3 w-3" />Read-only for Standard Users</div>
            : <Button onClick={openNew}><Plus className="h-4 w-4 mr-1.5" />New Rule</Button>}
        />

        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search rules" className="pl-8" />
          </div>
          <Select value={cat} onValueChange={v => setCat(v as typeof cat)}>
            <SelectTrigger className="w-52"><SelectValue placeholder="Category" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All categories</SelectItem>
              {CATS.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium w-20">Rule ID</th>
                <th className="text-left px-4 py-2.5 font-medium w-40">Category</th>
                <th className="text-left px-4 py-2.5 font-medium w-36">Question Set</th>
                <th className="text-left px-4 py-2.5 font-medium">Question</th>
                <th className="text-left px-4 py-2.5 font-medium w-24">Severity</th>
                <th className="text-left px-4 py-2.5 font-medium w-20">Active</th>
                <th className="text-right px-4 py-2.5 font-medium w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map(r => (
                <tr key={r.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-mono text-xs">{r.id}</td>
                  <td className="px-4 py-3"><CategoryTag>{r.category}</CategoryTag></td>
                  <td className="px-4 py-3 text-slate-600 font-mono text-xs">{r.questionSet}</td>
                  <td className="px-4 py-3">{r.question}</td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${r.severity === "Critical" ? "text-red-700 bg-red-50 border-red-200" : "text-slate-600 bg-slate-50 border-slate-200"}`}>
                      {r.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Switch checked={r.active} disabled={readOnly} onCheckedChange={() => { toggleRule(r.id); toast.success(`${r.id} ${r.active ? "deactivated" : "activated"}`); }} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!readOnly && (
                      <div className="inline-flex gap-0.5">
                        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => { setEditing(r); setOpen(true); }}><Pencil className="h-3.5 w-3.5" /></Button>
                        <Button variant="ghost" size="icon" className="h-7 w-7 text-red-600 hover:text-red-700" onClick={() => { deleteRule(r.id); toast.success(`${r.id} deleted`); }}><Trash2 className="h-3.5 w-3.5" /></Button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editing && rules.find(r => r.id === editing.id) ? "Edit rule" : "New rule"}</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Rule ID</Label><Input value={editing.id} onChange={e => setEditing({ ...editing, id: e.target.value })} /></div>
                <div><Label>Severity</Label>
                  <Select value={editing.severity} onValueChange={v => setEditing({ ...editing, severity: v as Rule["severity"] })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="Normal">Normal</SelectItem><SelectItem value="Critical">Critical</SelectItem></SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Category</Label>
                  <Select value={editing.category} onValueChange={v => setEditing({ ...editing, category: v as Rule["category"] })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{CATS.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div><Label>Question Set</Label>
                  <Select value={editing.questionSet} onValueChange={v => setEditing({ ...editing, questionSet: v as Rule["questionSet"] })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{QSETS.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div><Label>Question</Label><Textarea value={editing.question} onChange={e => setEditing({ ...editing, question: e.target.value })} rows={3} /></div>
              <div className="flex items-center gap-2"><Switch checked={editing.active} onCheckedChange={v => setEditing({ ...editing, active: v })} /><span className="text-sm">Active</span></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => { if (editing) { upsertRule(editing); toast.success(`${editing.id} saved`); setOpen(false); } }}>Save rule</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
