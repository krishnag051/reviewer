import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { useAuth } from "@/lib/auth-context";
import { usePatients, useAppConfig, useSetSupportingDocMode } from "@/lib/real-data";
import { listPatientVersions, getVersion, getUpload, type PatientListItem, type VersionOut, type SupportingDocMode } from "@/lib/api-client";
import { PageHeader, StatusBadge } from "@/components/tp/ui";
import { Loader2, ShieldOff, Settings2 } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/dev")({ component: DeveloperMode });

// Diagnostics only, not a user-facing feature -- one flat list of every
// draft upload AND finalized version across every REAL patient (Round 41,
// Stage 1 -- real data, not mock). Gated to the developer role both here
// (route-level 403) and in AppShell's nav (link hidden entirely for
// anyone else) -- see the developer-role decision in FRONTEND_STATE.md.
type DevRow = {
  key: string;
  patientName: string;
  refId: string;
  kind: "Draft" | "Finalized";
  label: string; // "U1" / "v2"
  status: "Processing" | "Pass" | "Fail" | "Error";
  score: number | null;
  date: string;
  failingRuleCount: number | null;
};

function DeveloperMode() {
  const { user } = useAuth();

  if (user?.role !== "developer") {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-center max-w-sm">
          <ShieldOff className="h-8 w-8 text-slate-400 mx-auto mb-3" />
          <div className="text-lg font-medium text-slate-900">Developer access only</div>
          <div className="mt-1 text-sm text-slate-500">
            This diagnostics view is restricted to the developer role. You're signed in as {user?.role ?? "unknown"}.
          </div>
        </div>
      </div>
    );
  }
  return <DeveloperModeContent />;
}

function DeveloperModeContent() {
  const nav = useNavigate();
  const patientsQuery = usePatients();
  const patients: PatientListItem[] = patientsQuery.data ?? [];

  // Stage 1: real data, N+1 fetches (patients -> each patient's versions ->
  // each version's uploads) -- acceptable for a diagnostics-only page read
  // occasionally, not something this app does on every render elsewhere.
  const versionsQueries = useQueries({
    queries: patients.map(p => ({
      queryKey: ["patient-versions", p.id],
      queryFn: () => listPatientVersions(p.id),
      enabled: patientsQuery.isSuccess,
    })),
  });
  const versionsLoaded = patients.length === 0 || versionsQueries.every(q => q.isSuccess);
  const versionsByPatient = new Map<string, VersionOut[]>(patients.map((p, i) => [p.id, versionsQueries[i]?.data ?? []]));

  const allVersions = patients.flatMap(p => (versionsByPatient.get(p.id) ?? []).map(v => ({ patient: p, version: v })));
  const versionDetailQueries = useQueries({
    queries: allVersions.map(({ version }) => ({
      queryKey: ["version", version.id],
      queryFn: () => getVersion(version.id),
      enabled: versionsLoaded,
    })),
  });
  const detailsLoaded = allVersions.length === 0 || versionDetailQueries.every(q => q.isSuccess);

  const allUploads = allVersions.flatMap(({ patient, version }, i) => {
    const detail = versionDetailQueries[i]?.data;
    return (detail?.uploads ?? []).map(upload => ({ patient, version, upload }));
  });
  const uploadDetailQueries = useQueries({
    queries: allUploads.map(({ upload }) => ({
      queryKey: ["upload", upload.id],
      queryFn: () => getUpload(upload.id),
      enabled: detailsLoaded,
    })),
  });

  const loading = patientsQuery.isLoading || !versionsLoaded || !detailsLoaded || (allUploads.length > 0 && uploadDetailQueries.some(q => q.isLoading));

  const rows = useMemo<DevRow[]>(() => {
    const out: DevRow[] = [];
    for (const { patient, version } of allVersions) {
      if (version.status === "finalized") {
        out.push({
          key: version.id,
          patientName: patient.name,
          refId: patient.reference_id,
          kind: "Finalized",
          label: `v${version.version_number}`,
          status: version.audit_result === "pass" ? "Pass" : "Fail",
          score: version.score,
          date: version.finalized_at ?? version.created_at,
          failingRuleCount: null,
        });
      }
    }
    allUploads.forEach(({ patient, version, upload }, i) => {
      if (version.status !== "in_progress") return; // finalized version's uploads are covered by the version row above
      const detail = uploadDetailQueries[i]?.data;
      const failing = detail?.rule_results.filter(r => r.final_status === "fail").length ?? null;
      const status: DevRow["status"] =
        upload.status === "processing" ? "Processing" :
        upload.status === "error" ? "Error" :
        failing && failing > 0 ? "Fail" : "Pass";
      out.push({
        key: upload.id,
        patientName: patient.name,
        refId: patient.reference_id,
        kind: "Draft",
        label: `U${upload.upload_number}`,
        status,
        score: null,
        date: upload.created_at,
        failingRuleCount: failing,
      });
    });
    return out.sort((a, b) => b.date.localeCompare(a.date));
  }, [allVersions, allUploads, uploadDetailQueries]);

  const counts = useMemo(() => ({
    processing: rows.filter(r => r.status === "Processing").length,
    pass: rows.filter(r => r.status === "Pass").length,
    fail: rows.filter(r => r.status === "Fail" || r.status === "Error").length,
  }), [rows]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto p-8 space-y-6">
        <PageHeader
          title="Developer Mode"
          description={`Diagnostics only, real backend data — every draft upload and finalized version across all ${patients.length} real patient(s). Not part of the normal review workflow.`}
        />

        {loading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />Loading real data from the backend…
          </div>
        )}

        <SupportingDocModeSwitch />

        <div className="grid grid-cols-3 gap-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">Processing</div>
            <div className="mt-1 text-2xl font-semibold text-blue-700">{counts.processing}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">Pass</div>
            <div className="mt-1 text-2xl font-semibold text-emerald-700">{counts.pass}</div>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="text-xs text-slate-500">Fail / Error</div>
            <div className="mt-1 text-2xl font-semibold text-red-700">{counts.fail}</div>
          </div>
        </div>

        <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium">Patient</th>
                <th className="text-left px-4 py-2.5 font-medium">Reference ID</th>
                <th className="text-left px-4 py-2.5 font-medium">Kind</th>
                <th className="text-left px-4 py-2.5 font-medium">Attempt/Version</th>
                <th className="text-left px-4 py-2.5 font-medium">Status</th>
                <th className="text-left px-4 py-2.5 font-medium">Score</th>
                <th className="text-left px-4 py-2.5 font-medium">Date</th>
                <th className="text-left px-4 py-2.5 font-medium">Failing rules</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map(r => (
                <tr
                  key={r.key}
                  className="hover:bg-slate-50 cursor-pointer"
                  onClick={() => nav({ to: "/plans/$refId", params: { refId: r.refId } })}
                >
                  <td className="px-4 py-3 font-medium">{r.patientName}</td>
                  <td className="px-4 py-3 text-slate-600 font-mono text-xs">{r.refId}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${r.kind === "Draft" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-slate-100 text-slate-600 border-slate-200"}`}>
                      {r.kind}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{r.label}</td>
                  <td className="px-4 py-3">
                    {r.status === "Processing" ? (
                      <span className="inline-flex items-center gap-1.5 text-xs text-blue-700">
                        <Loader2 className="h-3 w-3 animate-spin" />Processing
                      </span>
                    ) : r.status === "Error" ? (
                      <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700">Error</span>
                    ) : (
                      <StatusBadge status={r.status} />
                    )}
                  </td>
                  <td className="px-4 py-3 tabular-nums">{r.score === null ? "—" : `${r.score}%`}</td>
                  <td className="px-4 py-3 text-slate-600">{r.date.slice(0, 10)}</td>
                  <td className="px-4 py-3 text-slate-600">{r.failingRuleCount === null ? "—" : r.failingRuleCount}</td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={8} className="px-4 py-10 text-center text-sm text-slate-500">No attempts or versions exist yet in the real backend.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// Round 56, Item 1: live-switchable feature flag, real backend state (GET/
// PATCH /admin/app-config) -- not a mock toggle. Switching this changes
// which upload path new uploads take from this point forward; it never
// touches any upload that already exists either way (see backend's
// app/services/app_config.py).
function SupportingDocModeSwitch() {
  const configQuery = useAppConfig();
  const setModeMutation = useSetSupportingDocMode();

  async function handleChange(mode: SupportingDocMode) {
    try {
      await setModeMutation.mutateAsync(mode);
      toast.success(`supporting_doc_mode set to "${mode}" — new uploads will use this path from now on.`);
    } catch {
      toast.error("Failed to update supporting_doc_mode.");
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
        <Settings2 className="h-4 w-4" />Upload path (supporting_doc_mode)
      </div>
      <div className="mt-1 text-xs text-slate-500">
        Controls which second-file path a new upload takes. Switching here affects only uploads created after
        the switch — no existing upload's data changes either way.
      </div>
      {configQuery.isLoading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading…</div>
      ) : (
        <div className="mt-3 inline-flex rounded-md border border-slate-200 bg-slate-50 p-0.5 text-sm">
          {(["structured_form", "document"] as const).map(m => (
            <button
              key={m}
              disabled={setModeMutation.isPending}
              onClick={() => handleChange(m)}
              className={`px-3 py-1.5 rounded ${configQuery.data?.supporting_doc_mode === m ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {m === "structured_form" ? "Structured Q&A + Session Notes" : "Free-form Document + AI Extraction"}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
