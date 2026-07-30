import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { PAYORS, type Payor, type Rule, type ActionLane, type ActionTag, type RuleCheckType } from "@/lib/tp-mock";
import { PageHeader, CategoryTag, LaneTag } from "@/components/tp/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
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

const LANES: ActionLane[] = ["BCBA-fix", "Facilitator-assign"];
const TAGS: NonNullable<ActionTag>[] = ["Director", "QA", "Coordinator", "General"];
const CHECK_TYPES: RuleCheckType[] = ["deterministic", "judgment"];

function RulesStudio() {
  const { rules, role, upsertRule, deleteRule, toggleRule } = useTP();
  const readOnly = role !== "Admin";
  const [payor, setPayor] = useState<Payor>(PAYORS[0]);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [editing, setEditing] = useState<Rule | null>(null);
  const [open, setOpen] = useState(false);

  // This payor's applicable rules: universal ("ALL") + this payor's own
  // specific rules -- the same scoping agent-making's own pipeline applies
  // internally (see AGENT_STATE.md/INTEGRATION_PLAN.md), just surfaced here
  // as an explicit tab instead of detected from a document.
  const payorRules = useMemo(() => rules.filter(r => r.payor === "ALL" || r.payor === payor), [rules, payor]);
  const categoriesForPayor = useMemo(() => Array.from(new Set(payorRules.map(r => r.category))).sort(), [payorRules]);

  const filtered = useMemo(() => payorRules.filter(r =>
    (cat === "all" || r.category === cat) &&
    (!q || r.description.toLowerCase().includes(q.toLowerCase()) || r.id.toLowerCase().includes(q.toLowerCase()))
  ), [payorRules, cat, q]);

  const universalCount = payorRules.filter(r => r.payor === "ALL").length;
  const specificCount = payorRules.length - universalCount;

  function openNew() {
    setEditing({
      id: "", category: categoriesForPayor[0] ?? "Template", payor,
      description: "", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true,
    });
    setOpen(true);
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Rules Studio"
          description={`${rules.length} rules total · ${rules.filter(r => r.active).length} active`}
          actions={readOnly
            ? <div className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 text-amber-800 px-2.5 py-1 text-xs"><Lock className="h-3 w-3" />Read-only for Standard Users</div>
            : <Button onClick={openNew}><Plus className="h-4 w-4 mr-1.5" />New Rule</Button>}
        />

        <Tabs value={payor} onValueChange={v => { setPayor(v as Payor); setCat("all"); }}>
          <TabsList className="flex flex-wrap gap-1 h-auto p-1">
            {PAYORS.map(p => <TabsTrigger key={p} value={p}>{p}</TabsTrigger>)}
          </TabsList>

          <TabsContent value={payor} className="mt-6 space-y-4">
            <div className="text-xs text-slate-500">
              {universalCount} universal rule(s) + {specificCount} {payor}-specific rule(s) = {payorRules.length} applicable to this payor.
            </div>

            <div className="flex items-center gap-3">
              <div className="relative flex-1 max-w-md">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <Input value={q} onChange={e => setQ(e.target.value)} placeholder="Search rules" className="pl-8" />
              </div>
              <Select value={cat} onValueChange={setCat}>
                <SelectTrigger className="w-64"><SelectValue placeholder="Category" /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All categories</SelectItem>
                  {categoriesForPayor.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>

            <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium w-28">Rule ID</th>
                    <th className="text-left px-4 py-2.5 font-medium w-48">Category</th>
                    <th className="text-left px-4 py-2.5 font-medium">Description</th>
                    <th className="text-left px-4 py-2.5 font-medium w-28">Check Type</th>
                    <th className="text-left px-4 py-2.5 font-medium w-48">Lane / Tag</th>
                    <th className="text-left px-4 py-2.5 font-medium w-20">Active</th>
                    <th className="text-right px-4 py-2.5 font-medium w-24"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {filtered.map(r => (
                    <tr key={r.id} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-mono text-xs">
                        {r.id}
                        {r.payor !== "ALL" && <span className="ml-1 text-[10px] text-amber-700">•{r.payor}</span>}
                      </td>
                      <td className="px-4 py-3"><CategoryTag>{r.category}</CategoryTag></td>
                      <td className="px-4 py-3">{r.description}</td>
                      <td className="px-4 py-3 text-slate-600 font-mono text-xs">{r.checkType}</td>
                      <td className="px-4 py-3"><LaneTag lane={r.actionLane} tag={r.actionTag} /></td>
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
                  {filtered.length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-10 text-center text-slate-500">No rules match this filter.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </TabsContent>
        </Tabs>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editing && rules.find(r => r.id === editing.id) ? "Edit rule" : "New rule"}</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Rule ID</Label><Input value={editing.id} onChange={e => setEditing({ ...editing, id: e.target.value })} placeholder="e.g., QA-GIP-18" /></div>
                <div><Label>Check Type</Label>
                  <Select value={editing.checkType} onValueChange={v => setEditing({ ...editing, checkType: v as RuleCheckType })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{CHECK_TYPES.map(c => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Category</Label><Input value={editing.category} onChange={e => setEditing({ ...editing, category: e.target.value })} /></div>
                <div><Label>Payor</Label>
                  <Select value={editing.payor} onValueChange={v => setEditing({ ...editing, payor: v as Rule["payor"] })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">ALL (universal)</SelectItem>
                      {PAYORS.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div><Label>Description</Label><Textarea value={editing.description} onChange={e => setEditing({ ...editing, description: e.target.value })} rows={3} /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label>Action Lane</Label>
                  <Select value={editing.actionLane} onValueChange={v => setEditing({ ...editing, actionLane: v as ActionLane, actionTag: v === "BCBA-fix" ? null : editing.actionTag })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{LANES.map(l => <SelectItem key={l} value={l}>{l}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div><Label>Action Tag {editing.actionLane === "BCBA-fix" && <span className="text-slate-400">(Facilitator-assign only)</span>}</Label>
                  <Select value={editing.actionTag ?? "none"} disabled={editing.actionLane === "BCBA-fix"} onValueChange={v => setEditing({ ...editing, actionTag: v === "none" ? null : v as ActionTag })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">None</SelectItem>
                      {TAGS.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="flex items-center gap-2"><Switch checked={editing.active} onCheckedChange={v => setEditing({ ...editing, active: v })} /><span className="text-sm">Active</span></div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={() => {
              if (!editing) return;
              if (!editing.id.trim()) { toast.error("Rule ID is required."); return; }
              upsertRule(editing);
              toast.success(`${editing.id} saved`);
              setOpen(false);
            }}>Save rule</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
