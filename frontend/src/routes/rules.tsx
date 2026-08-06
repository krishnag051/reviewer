import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { useRules, useCreateRule, useUpdateRule, useSetRuleActive } from "@/lib/real-data";
import { ApiError, apiErrorMessage, type RuleOut, type RuleType, type RulePayor } from "@/lib/api-client";
import { PAYORS } from "@/lib/tp-mock";
import { PageHeader, CategoryTag } from "@/components/tp/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Plus, Pencil, Search, Lock, Loader2, Info, NotebookText } from "lucide-react";
import { toast } from "sonner";
import { Textarea } from "@/components/ui/textarea";

export const Route = createFileRoute("/rules")({ component: RulesStudio });

const RULE_TYPES: RuleType[] = ["structural", "semantic", "cross_reference"];
const ALL_TAB = "__all__";

type EditForm = {
  id: string | null; // null = creating a new rule
  rule_code: string;
  category: string;
  question_set: string;
  question_text: string;
  rule_type: RuleType;
  payor: RulePayor | null;
  active: boolean;
};

// Round 50: real Rules Studio, wired to the real backend `rules` table --
// GET /rules is readable by any authenticated role; every mutation is
// admin-gated on the backend independent of this UI (see api-client.ts's
// own comment). Explicitly dropped from the old mock version: check-type
// ("deterministic"/"judgment"), action lane, and action tag -- those are
// agent-making's own internal concepts and were NEVER backend columns,
// only ever mock fields. Rather than fake them here, they're gone; the
// backend's own `rule_type` (structural/semantic/cross_reference) is a
// different, real classification and is shown as itself, not conflated
// with agent-making's check_type.
function RulesStudio() {
  const { user } = useAuth();
  const readOnly = user?.role !== "admin";

  const rulesQuery = useRules();
  const rules = rulesQuery.data ?? [];
  const createMutation = useCreateRule();
  const updateMutation = useUpdateRule();
  const setActiveMutation = useSetRuleActive();

  const [payorTab, setPayorTab] = useState<string>(ALL_TAB);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState<string>("all");
  const [editing, setEditing] = useState<EditForm | null>(null);
  const [open, setOpen] = useState(false);

  const payorRules = useMemo(
    () => payorTab === ALL_TAB ? rules : rules.filter(r => r.payor === null || r.payor === payorTab),
    [rules, payorTab],
  );
  const categoriesForPayor = useMemo(() => Array.from(new Set(payorRules.map(r => r.category))).sort(), [payorRules]);
  const filtered = useMemo(() => payorRules.filter(r =>
    (cat === "all" || r.category === cat) &&
    (!q || r.question_text.toLowerCase().includes(q.toLowerCase()) || r.rule_code.toLowerCase().includes(q.toLowerCase()))
  ), [payorRules, cat, q]);

  const universalCount = payorRules.filter(r => r.payor === null).length;
  const specificCount = payorRules.length - universalCount;

  function openNew() {
    setEditing({
      id: null, rule_code: "", category: categoriesForPayor[0] ?? "", question_set: "", question_text: "",
      rule_type: "structural", payor: payorTab === ALL_TAB ? null : (payorTab as RulePayor), active: true,
    });
    setOpen(true);
  }
  function openEdit(r: RuleOut) {
    setEditing({
      id: r.id, rule_code: r.rule_code, category: r.category, question_set: r.question_set,
      question_text: r.question_text, rule_type: r.rule_type, payor: r.payor, active: r.active,
    });
    setOpen(true);
  }

  async function handleSave() {
    if (!editing) return;
    try {
      if (editing.id === null) {
        if (!editing.rule_code.trim()) { toast.error("Rule code is required."); return; }
        await createMutation.mutateAsync({
          rule_code: editing.rule_code, category: editing.category, question_set: editing.question_set,
          question_text: editing.question_text, rule_type: editing.rule_type, payor: editing.payor, active: editing.active,
        });
        toast.success(`${editing.rule_code} created.`);
      } else {
        await updateMutation.mutateAsync({
          ruleId: editing.id,
          changes: {
            category: editing.category, question_set: editing.question_set, question_text: editing.question_text,
            rule_type: editing.rule_type, payor: editing.payor,
          },
        });
        toast.success(`${editing.rule_code} saved.`);
      }
      setOpen(false);
    } catch (err) {
      toast.error(err instanceof ApiError ? apiErrorMessage(err) : "Something went wrong.");
    }
  }

  async function handleToggleActive(r: RuleOut) {
    try {
      await setActiveMutation.mutateAsync({ ruleId: r.id, active: !r.active });
      toast.success(`${r.rule_code} ${r.active ? "deactivated" : "activated"}.`);
    } catch (err) {
      toast.error(err instanceof ApiError ? apiErrorMessage(err) : "Something went wrong.");
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Rules Studio"
          description={rulesQuery.isLoading ? "Loading real rules from the backend…" : `${rules.length} rules total · ${rules.filter(r => r.active).length} active`}
          actions={readOnly
            ? <div className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 text-amber-800 px-2.5 py-1 text-xs"><Lock className="h-3 w-3" />Read-only for this role</div>
            : <Button onClick={openNew}><Plus className="h-4 w-4 mr-1.5" />New Rule</Button>}
        />

        <div className="flex items-start gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
          <Info className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <div>
            Editing here changes real, persisted rule <span className="font-medium">metadata only</span> — category, question set/text,
            rule type, payor, and active status. It does <span className="font-medium">not</span> change what the real rule-checking
            agent actually checks: that logic (prompts, deterministic checkers) lives in the agent's own codebase and isn't editable
            from this UI. Rule code is permanent once created.
          </div>
        </div>

        {rulesQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-slate-500 py-10">
            <Loader2 className="h-4 w-4 animate-spin" />Loading real rules…
          </div>
        ) : (
          <Tabs value={payorTab} onValueChange={v => { setPayorTab(v); setCat("all"); }}>
            <TabsList className="flex flex-wrap gap-1 h-auto p-1">
              <TabsTrigger value={ALL_TAB}>All payors</TabsTrigger>
              {PAYORS.map(p => <TabsTrigger key={p} value={p}>{p}</TabsTrigger>)}
            </TabsList>

            <TabsContent value={payorTab} className="mt-6 space-y-4">
              {payorTab !== ALL_TAB && (
                <div className="text-xs text-slate-500">
                  {universalCount} universal rule(s) + {specificCount} {payorTab}-specific rule(s) = {payorRules.length} applicable to this payor.
                </div>
              )}

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
                      <th className="text-left px-4 py-2.5 font-medium w-32">Rule Code</th>
                      <th className="text-left px-4 py-2.5 font-medium w-40">Category</th>
                      <th className="text-left px-4 py-2.5 font-medium">Question</th>
                      <th className="text-left px-4 py-2.5 font-medium w-32">Rule Type</th>
                      <th className="text-left px-4 py-2.5 font-medium w-20">Active</th>
                      <th className="text-right px-4 py-2.5 font-medium w-20"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filtered.map(r => (
                      <tr key={r.id} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-mono text-xs">
                          {r.rule_code}
                          {r.payor !== null && <span className="ml-1 text-[10px] text-amber-700">•{r.payor}</span>}
                        </td>
                        <td className="px-4 py-3"><CategoryTag>{r.category}</CategoryTag></td>
                        <td className="px-4 py-3">
                          {r.question_text}
                          {r.session_notes_only && (
                            <span
                              title={`Data source: session notes only — must never be resolved from the TP alone.${r.tp_section ? ` Anchors to: ${r.tp_section}.` : ""}`}
                              className="ml-2 inline-flex items-center gap-1 rounded bg-violet-50 text-violet-700 border border-violet-200 px-1.5 py-0.5 text-[10px] uppercase tracking-wide align-middle"
                            >
                              <NotebookText className="h-3 w-3" />Session Notes Only
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-600 font-mono text-xs">{r.rule_type}</td>
                        <td className="px-4 py-3">
                          <Switch
                            checked={r.active}
                            disabled={readOnly || setActiveMutation.isPending}
                            onCheckedChange={() => handleToggleActive(r)}
                          />
                        </td>
                        <td className="px-4 py-3 text-right">
                          {!readOnly && (
                            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => openEdit(r)}>
                              <Pencil className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                    {filtered.length === 0 && (
                      <tr><td colSpan={6} className="px-4 py-10 text-center text-slate-500">No rules match this filter.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </TabsContent>
          </Tabs>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{editing?.id === null ? "New rule" : "Edit rule"}</DialogTitle></DialogHeader>
          {editing && (
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label htmlFor="rule-code">Rule Code {editing.id !== null && <span className="text-slate-400">(permanent)</span>}</Label>
                  <Input
                    id="rule-code"
                    value={editing.rule_code}
                    disabled={editing.id !== null}
                    onChange={e => setEditing({ ...editing, rule_code: e.target.value })}
                    placeholder="e.g., QA-GIP-18"
                  />
                </div>
                <div><Label htmlFor="rule-type">Rule Type</Label>
                  <Select value={editing.rule_type} onValueChange={v => setEditing({ ...editing, rule_type: v as RuleType })}>
                    <SelectTrigger id="rule-type"><SelectValue /></SelectTrigger>
                    <SelectContent>{RULE_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div><Label htmlFor="rule-category">Category</Label><Input id="rule-category" value={editing.category} onChange={e => setEditing({ ...editing, category: e.target.value })} /></div>
                <div><Label htmlFor="rule-payor">Payor</Label>
                  <Select value={editing.payor ?? "ALL"} onValueChange={v => setEditing({ ...editing, payor: v === "ALL" ? null : v as RulePayor })}>
                    <SelectTrigger id="rule-payor"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="ALL">ALL (universal)</SelectItem>
                      {PAYORS.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div><Label htmlFor="rule-question-set">Question Set</Label><Input id="rule-question-set" value={editing.question_set} onChange={e => setEditing({ ...editing, question_set: e.target.value })} /></div>
              <div><Label htmlFor="rule-question-text">Question Text</Label><Textarea id="rule-question-text" value={editing.question_text} onChange={e => setEditing({ ...editing, question_text: e.target.value })} rows={3} /></div>
              {editing.id === null && (
                <div className="flex items-center gap-2"><Switch checked={editing.active} onCheckedChange={v => setEditing({ ...editing, active: v })} /><span className="text-sm">Active</span></div>
              )}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={createMutation.isPending || updateMutation.isPending}>
              {(createMutation.isPending || updateMutation.isPending) ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Saving…</> : "Save rule"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
