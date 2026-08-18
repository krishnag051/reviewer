import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { useTP } from "@/lib/tp-context";
import { useAuth } from "@/lib/auth-context";
import { useAppConfig, useSetNotificationSettings } from "@/lib/real-data";
import { reviewers as initialReviewers, auditLog, invoices, rules as mockRuleLibrary } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Loader2, Trash2, Pencil, Plus, Lock } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/admin")({ component: AdminSettings });

function AdminSettings() {
  const { patients } = useTP();
  const { user } = useAuth();
  const readOnly = user?.role !== "admin";

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Admin Settings"
          description="Organization, users, and workspace configuration."
          actions={readOnly
            ? <div className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 border border-amber-200 text-amber-800 px-2.5 py-1 text-xs"><Lock className="h-3 w-3" />Read-only for Standard Users</div>
            : null}
        />

        <Tabs defaultValue="org">
          <TabsList className="flex flex-wrap gap-1 h-auto p-1">
            <TabsTrigger value="org">Organization</TabsTrigger>
            <TabsTrigger value="users">Users & Roles</TabsTrigger>
            <TabsTrigger value="notif">Notifications</TabsTrigger>
            <TabsTrigger value="integ">Integrations</TabsTrigger>
            <TabsTrigger value="audit">Audit Log</TabsTrigger>
            <TabsTrigger value="billing">Billing</TabsTrigger>
          </TabsList>

          <TabsContent value="org" className="mt-6">
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Company Name", value: "BrightPath ABA Services" },
                { label: "Region", value: "New York, USA" },
                { label: "Rule Library", value: `${mockRuleLibrary.length} rules` },
                { label: "Seeded Patients", value: `${patients.length} patients` },
              ].map(c => (
                <div key={c.label} className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="text-xs text-slate-500">{c.label}</div>
                  <div className="mt-1 text-lg font-medium">{c.value}</div>
                </div>
              ))}
            </div>
            {/* Deployment round: confirmed no real backend endpoint exists
                for company name/region/working hours (searched the whole
                backend -- no matching model field anywhere), so per
                explicit instruction this tab is NOT wired to anything real
                this round -- flagged back rather than inventing an
                endpoint. Still fully mock/placeholder, unchanged. */}
            <div className="mt-6 rounded-lg border border-slate-200 bg-white p-6 space-y-4 max-w-xl">
              <div><Label>Company name</Label><Input defaultValue="BrightPath ABA Services" disabled={readOnly} /></div>
              <div><Label>Primary region</Label>
                <Select defaultValue="ny" disabled={readOnly}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="ny">New York, USA</SelectItem>
                    <SelectItem value="ca">California, USA</SelectItem>
                    <SelectItem value="tx">Texas, USA</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div><Label>Default working hours</Label><Input defaultValue="Mon–Fri, 9:00–17:00 ET" disabled={readOnly} /></div>
              <div><Button disabled={readOnly} onClick={() => toast.info("Not wired to a real endpoint yet — no backend field exists for Company Info (flagged, not built).")}>Save changes</Button></div>
            </div>
          </TabsContent>

          <TabsContent value="users" className="mt-6">
            <UsersTable readOnly={readOnly} />
          </TabsContent>

          <TabsContent value="notif" className="mt-6">
            <NotificationsTab readOnly={readOnly} />
          </TabsContent>

          <TabsContent value="integ" className="mt-6">
            <div className="grid grid-cols-2 gap-4 max-w-3xl">
              {[
                { name: "CentralReach", desc: "Sync patients, authorizations, and BCBAs." },
                { name: "SharePoint / Document Storage", desc: "Auto-pull uploaded treatment plans." },
                { name: "Availity", desc: "Pull payor benefit and auth data." },
                { name: "Google Workspace SSO", desc: "Single sign-on for team members." },
              ].map(i => (
                <div key={i.name} className="rounded-lg border border-slate-200 bg-white p-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="text-sm font-medium">{i.name}</div>
                      <div className="mt-1 text-xs text-slate-500">{i.desc}</div>
                    </div>
                    <span className="text-[10px] uppercase tracking-wide rounded bg-slate-100 text-slate-600 px-1.5 py-0.5">Not connected</span>
                  </div>
                  <Button variant="outline" size="sm" className="mt-4" disabled={readOnly} onClick={() => toast.info(`${i.name} setup would open here`)}>Connect</Button>
                </div>
              ))}
            </div>
          </TabsContent>

          <TabsContent value="audit" className="mt-6">
            <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-medium w-44">Timestamp</th>
                    <th className="text-left px-4 py-2.5 font-medium w-32">User</th>
                    <th className="text-left px-4 py-2.5 font-medium">Action</th>
                    <th className="text-left px-4 py-2.5 font-medium w-40">Reference ID</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {auditLog.map((row, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{row.at}</td>
                      <td className="px-4 py-2.5">{row.user}</td>
                      <td className="px-4 py-2.5 text-slate-700">{row.action}</td>
                      <td className="px-4 py-2.5 text-slate-600 font-mono text-xs">{row.refId || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </TabsContent>

          <TabsContent value="billing" className="mt-6">
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="text-xs text-slate-500">Current tier</div>
                <div className="mt-1 text-lg font-semibold">Pro</div>
                <div className="mt-1 text-xs text-slate-500">$2,400 / month · billed monthly</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="text-xs text-slate-500">Seats used</div>
                <div className="mt-1 text-lg font-semibold">{initialReviewers.length} of 10</div>
                <div className="mt-1 text-xs text-slate-500">5 seats available</div>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white p-5">
                <div className="text-xs text-slate-500">Next invoice</div>
                <div className="mt-1 text-lg font-semibold">Aug 1, 2026</div>
                <div className="mt-1 text-xs text-slate-500">$2,400.00</div>
              </div>
            </div>
            <div className="mt-6 rounded-lg border border-slate-200 bg-white overflow-hidden">
              <div className="px-5 py-3 border-b border-slate-200 text-sm font-semibold">Past invoices</div>
              <table className="w-full text-sm">
                <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="text-left px-4 py-2 font-medium">Date</th>
                    <th className="text-left px-4 py-2 font-medium">Description</th>
                    <th className="text-right px-4 py-2 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {invoices.map(i => (
                    <tr key={i.date}>
                      <td className="px-4 py-2.5 text-slate-600">{i.date}</td>
                      <td className="px-4 py-2.5">{i.desc}</td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{i.amount}</td>
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

/** Deployment round: real GET/PATCH wiring for what was, until this
 * round, a fully hardcoded mockup (static defaultValue strings, a "Save"
 * button with no onClick, a Switch with no onCheckedChange -- see
 * lib/real-data.ts's own module comment). Reads notif_from_name/
 * notif_from_address/notif_default_cc/auto_send from the real AppConfig
 * row on load, writes them back via PATCH /admin/app-config/notifications
 * on Save, with a real success/error toast either way. `auto_send` is a
 * real, persisted column (survives a reload) but has no other reader in
 * this codebase yet -- see set_notification_settings' own backend
 * docstring -- flipping it doesn't yet change any actual send behavior,
 * only what's stored.
 */
function NotificationsTab({ readOnly }: { readOnly: boolean }) {
  const configQuery = useAppConfig();
  const saveMutation = useSetNotificationSettings();

  const [fromName, setFromName] = useState("");
  const [fromAddress, setFromAddress] = useState("");
  const [defaultCc, setDefaultCc] = useState("");
  const [requireManualReview, setRequireManualReview] = useState(true);
  // Only prefill from the real query ONCE it actually has data -- a plain
  // `value={configQuery.data?.notif_from_name ?? ""}` would silently
  // revert every keystroke back to the query's own (possibly stale,
  // pre-invalidation) value on every re-render; this mirrors the
  // "keyed widget, write to local state once, then it's yours" pattern
  // this project already uses elsewhere for exactly this reason.
  const [hasPrefilled, setHasPrefilled] = useState(false);
  useEffect(() => {
    if (configQuery.data && !hasPrefilled) {
      setFromName(configQuery.data.notif_from_name ?? "");
      setFromAddress(configQuery.data.notif_from_address ?? "");
      setDefaultCc(configQuery.data.notif_default_cc ?? "");
      setRequireManualReview(!configQuery.data.auto_send);
      setHasPrefilled(true);
    }
  }, [configQuery.data, hasPrefilled]);

  function handleSave() {
    saveMutation.mutate(
      {
        notif_from_name: fromName,
        notif_from_address: fromAddress,
        notif_default_cc: defaultCc,
        auto_send: !requireManualReview,
      },
      {
        onSuccess: () => toast.success("Notification defaults saved."),
        onError: (err) => toast.error(`Failed to save notification defaults: ${err instanceof Error ? err.message : String(err)}`),
      },
    );
  }

  if (configQuery.isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 text-sm text-slate-500 py-10">
        <Loader2 className="h-4 w-4 animate-spin" />Loading real notification defaults…
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 space-y-4 max-w-xl">
      <div>
        <Label htmlFor="notif-from-name">Default "From" name</Label>
        <Input id="notif-from-name" value={fromName} onChange={e => setFromName(e.target.value)} disabled={readOnly} />
      </div>
      <div>
        <Label htmlFor="notif-from-address">Default "From" address</Label>
        <Input id="notif-from-address" value={fromAddress} onChange={e => setFromAddress(e.target.value)} disabled={readOnly} />
      </div>
      <div>
        <Label htmlFor="notif-default-cc">Default CC list</Label>
        <Input id="notif-default-cc" value={defaultCc} onChange={e => setDefaultCc(e.target.value)} disabled={readOnly} />
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <div>
          <div className="text-sm font-medium">Require manual review before sending</div>
          <div className="text-xs text-slate-500">
            When off, correction emails auto-send after audit fails. (Persisted for real — not yet read by any
            send path in this backend, so toggling this does not yet change actual send behavior.)
          </div>
        </div>
        <Switch checked={requireManualReview} onCheckedChange={setRequireManualReview} disabled={readOnly} />
      </div>
      <div>
        <Button disabled={readOnly || saveMutation.isPending} onClick={handleSave}>
          {saveMutation.isPending ? <Loader2 className="h-4 w-4 mr-1.5 animate-spin" /> : null}
          Save notification defaults
        </Button>
      </div>
    </div>
  );
}

function UsersTable({ readOnly }: { readOnly: boolean }) {
  const [users, setUsers] = useState(initialReviewers);

  return (
    <div>
      <div className="flex justify-end mb-3">
        <Button size="sm" disabled={readOnly} onClick={() => toast.info("Invite dialog would open here")}><Plus className="h-4 w-4 mr-1.5" />Invite user</Button>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="text-left px-4 py-2.5 font-medium">Name</th>
              <th className="text-left px-4 py-2.5 font-medium">Email</th>
              <th className="text-left px-4 py-2.5 font-medium w-44">Role</th>
              <th className="text-right px-4 py-2.5 font-medium w-24"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {users.map(u => (
              <tr key={u.id}>
                <td className="px-4 py-3">{u.name}, {u.credentials}</td>
                <td className="px-4 py-3 text-slate-600">{u.email}</td>
                <td className="px-4 py-3">
                  <Select value={u.role} disabled={readOnly} onValueChange={v => setUsers(prev => prev.map(x => x.id === u.id ? { ...x, role: v as typeof u.role } : x))}>
                    <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="Admin">Admin</SelectItem>
                      <SelectItem value="Standard User">Standard User</SelectItem>
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-4 py-3 text-right">
                  {!readOnly && (
                    <div className="inline-flex gap-0.5">
                      <Button variant="ghost" size="icon" className="h-7 w-7"><Pencil className="h-3.5 w-3.5" /></Button>
                      <Button variant="ghost" size="icon" className="h-7 w-7 text-red-600 hover:text-red-700" onClick={() => setUsers(prev => prev.filter(x => x.id !== u.id))}><Trash2 className="h-3.5 w-3.5" /></Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
