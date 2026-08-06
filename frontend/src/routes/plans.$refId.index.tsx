import { createFileRoute, useNavigate, notFound } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import {
  usePatients, usePatientVersions, useVersionDetail, useUploadDetail,
  useOverrideRuleResult, useFinalizeUpload,
} from "@/lib/real-data";
import { apiErrorMessage, fetchUploadSupportingFileBlob, type RuleResultOut } from "@/lib/api-client";
import { StatusBadge, ReviewedBadge } from "@/components/tp/ui";
import { PdfViewer } from "@/components/tp/PdfViewer";
import { Select, SelectContent, SelectGroup, SelectLabel, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel } from "@/components/ui/dropdown-menu";
import { Loader2, Pencil, Megaphone, FlaskConical, FileText, NotebookText } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/plans/$refId/")({ component: PlanDetail });

const STATUS_LABELS: Record<RuleResultOut["final_status"], string> = {
  pass: "Pass", fail: "Fail", na: "N/A", uncertain: "Uncertain", not_checkable: "Not checkable",
};

// Round 41, Stage 1: real data, read-only. Round 42 adds the real PDF pane
// (GET /uploads/:id/file, via PdfViewer.tsx) alongside the real rule
// results -- for both a draft's latest upload and a finalized version's
// final upload, same `finalUpload` lookup below either way. Round 43,
// Stage 3 adds the last two real write actions: per-rule override (PATCH
// /rule_results/:id) and Finalize (POST /uploads/:id/finalize) -- both only
// ever shown/enabled for a non-final upload, matching the backend's
// draft-only invariant (CLAUDE.md). "Escalate to BCBA" stays a mock/toast
// placeholder -- lane routing has no backend counterpart built yet, and
// mark-reviewed/correction-email (finalized-only actions) are still out of
// scope -- a just-finalized version simply becomes the same read-only view
// Round 41 already renders for older finalized data.
function PlanDetail() {
  const { refId } = Route.useParams();
  const nav = useNavigate();

  const patientsQuery = usePatients();
  const patient = patientsQuery.data?.find(p => p.reference_id === refId);

  if (patientsQuery.isSuccess && !patient) throw notFound();

  const versionsQuery = usePatientVersions(patient?.id);
  const sortedVersions = useMemo(
    () => [...(versionsQuery.data ?? [])].sort((a, b) => b.version_number - a.version_number),
    [versionsQuery.data],
  );

  // Selection: "v-{versionId}" -- the combined switcher below lists every
  // real version (finalized or still in_progress). Falls back to the
  // newest version once the list loads.
  const [selectedValue, setSelectedValue] = useState<string | null>(null);
  const effectiveVersionId = selectedValue?.replace(/^v-/, "") ?? sortedVersions[0]?.id;
  const selectedVersionSummary = sortedVersions.find(v => v.id === effectiveVersionId);

  const versionDetailQuery = useVersionDetail(effectiveVersionId);
  const uploads = versionDetailQuery.data?.uploads ?? [];
  const finalUpload = uploads.find(u => u.id === versionDetailQuery.data?.final_upload_id) ?? uploads[uploads.length - 1];
  const uploadDetailQuery = useUploadDetail(finalUpload?.id);

  const [filter, setFilter] = useState<"all" | "pass" | "fail" | "na" | "uncertain" | "not_checkable">("all");

  const results = uploadDetailQuery.data?.rule_results ?? [];
  const counts = useMemo(() => ({
    all: results.length,
    pass: results.filter(r => r.final_status === "pass").length,
    fail: results.filter(r => r.final_status === "fail").length,
    na: results.filter(r => r.final_status === "na").length,
    uncertain: results.filter(r => r.final_status === "uncertain").length,
    not_checkable: results.filter(r => r.final_status === "not_checkable").length,
  }), [results]);
  const filteredResults = filter === "all" ? results : results.filter(r => r.final_status === filter);
  // Round 49: a dev-only simulated-completion upload's findings all carry
  // this literal prefix (app/services/simulated_pipeline.py) -- surfacing
  // it here means it's impossible to view this page without the banner
  // below appearing, not just relying on the finding text itself.
  const isSimulated = results.length > 0 && results.every(r => r.final_finding.startsWith("SIMULATED"));

  // Draft-only, per CLAUDE.md's override invariant -- `finalUpload.is_final`
  // is the same field the backend's own guard checks (a plain boolean read
  // here, not re-deriving the rule; the backend is the source of truth and
  // will 409 regardless if this client-side gate is ever wrong/stale).
  const isDraft = !!finalUpload && !finalUpload.is_final;
  const hasUncertain = results.some(r => r.final_status === "uncertain");

  const overrideMutation = useOverrideRuleResult();
  const finalizeMutation = useFinalizeUpload();
  const [finalizeOpen, setFinalizeOpen] = useState(false);
  const [confirmRefId, setConfirmRefId] = useState("");

  function handleOverride(res: RuleResultOut, newStatus: RuleResultOut["final_status"]) {
    if (!finalUpload) return;
    overrideMutation.mutate(
      { ruleResultId: res.id, uploadId: finalUpload.id, updated_at: res.updated_at, final_status: newStatus },
      {
        onSuccess: () => toast.success(`Overridden to ${STATUS_LABELS[newStatus]}.`),
        onError: err => toast.error(apiErrorMessage(err)),
      },
    );
  }

  // Round 57, Item 1: whether THIS specific upload was created under
  // structured_form or document mode -- read straight off the upload's own
  // data (intake_answers present or not), not the live global
  // supporting_doc_mode flag. That's deliberate: an older "document"-mode
  // upload must keep showing "Helping Document" even after the flag has
  // since been switched to structured_form, and vice versa -- this button
  // reflects what THIS upload actually has, not today's default.
  const intakeAnswers = uploadDetailQuery.data?.intake_answers ?? null;
  const [qaModalOpen, setQaModalOpen] = useState(false);

  const [openingSupportingDoc, setOpeningSupportingDoc] = useState(false);

  // Round 51: opens the real supporting document (GET /uploads/:id/
  // supporting-file) in a NEW browser tab -- never rendered inline, the
  // main PDF/rule-results area stays exactly as it is. A plain <a href>/
  // window.open(url) can't carry the Bearer token, so this fetches the
  // real blob first and opens an object URL instead (same technique
  // PdfViewer.tsx already uses for the TP's own file, just not inlined).
  async function handleOpenSupportingDocument() {
    if (!finalUpload) return;
    setOpeningSupportingDoc(true);
    try {
      const blob = await fetchUploadSupportingFileBlob(finalUpload.id);
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setOpeningSupportingDoc(false);
    }
  }

  function handleFinalize() {
    if (!finalUpload || !effectiveVersionId) return;
    finalizeMutation.mutate(
      { uploadId: finalUpload.id, referenceId: confirmRefId, versionId: effectiveVersionId },
      {
        onSuccess: () => {
          toast.success(`Finalized as v${selectedVersionSummary?.version_number} — this is permanent.`);
          setFinalizeOpen(false);
          setConfirmRefId("");
        },
        onError: err => toast.error(apiErrorMessage(err)),
      },
    );
  }

  if (patientsQuery.isLoading || versionsQuery.isLoading) {
    return (
      <div className="h-full flex items-center justify-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />Loading real data from the backend…
      </div>
    );
  }
  if (!patient) return null; // notFound() above is about to take over

  return (
    <div className="h-full flex flex-col">
      <div className="shrink-0 border-b border-slate-200 bg-white">
        <div className="px-6 py-4">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
                <button onClick={() => nav({ to: "/plans" })} className="hover:text-slate-900">Treatment Plans</button>
                <span>/</span>
                <span className="font-mono">{patient.reference_id}</span>
              </div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-xl font-semibold">{patient.name}</h1>
                {selectedVersionSummary && (
                  selectedVersionSummary.status === "finalized" ? (
                    <>
                      <StatusBadge status={selectedVersionSummary.audit_result === "pass" ? "Pass" : "Fail"} />
                      <ReviewedBadge reviewed={selectedVersionSummary.reviewed} />
                    </>
                  ) : (
                    <span className="text-[10px] uppercase tracking-wide rounded bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5">
                      In progress · not finalized
                    </span>
                  )
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs text-slate-600">
                <div><span className="text-slate-400">Payor:</span> {patient.payor ?? "—"}</div>
                {selectedVersionSummary?.status === "finalized" && (
                  <div><span className="text-slate-400">Score:</span> <span className="font-medium">{selectedVersionSummary.score}%</span></div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Select
                value={effectiveVersionId ? `v-${effectiveVersionId}` : undefined}
                onValueChange={setSelectedValue}
              >
                <SelectTrigger className="w-56 h-9"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    <SelectLabel>Versions (real data)</SelectLabel>
                    {sortedVersions.map((v, i) => (
                      <SelectItem key={v.id} value={`v-${v.id}`}>
                        v{v.version_number} — {v.status === "finalized" ? "finalized" : "in progress"}{i === 0 ? " (latest)" : ""}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
              {finalUpload && (
                intakeAnswers ? (
                  // Round 57, Item 1: structured_form-mode uploads have no
                  // document to show -- the old "Helping Document" button
                  // (a new-tab file viewer) makes no sense here. Opens a
                  // modal instead, using data already fetched by
                  // uploadDetailQuery above -- no separate request.
                  <Button variant="outline" onClick={() => setQaModalOpen(true)}>
                    <FileText className="h-4 w-4 mr-1.5" />Intake Q&A
                  </Button>
                ) : (
                  <Button variant="outline" onClick={handleOpenSupportingDocument} disabled={openingSupportingDoc}>
                    {openingSupportingDoc
                      ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Opening…</>
                      : <><FileText className="h-4 w-4 mr-1.5" />Helping Document</>}
                  </Button>
                )
              )}
              {finalUpload && (
                // Round 56, Item 4 -- same UX pattern as Helping Document
                // above (new tab, never rendered inline), but this opens a
                // real app route (not a raw blob) since it lists multiple
                // files, not just one. The new tab reads the same
                // localStorage auth token, so it's authenticated on load
                // with no extra plumbing.
                <Button variant="outline" onClick={() => window.open(`/session-notes/${finalUpload.id}`, "_blank")}>
                  <NotebookText className="h-4 w-4 mr-1.5" />Session Notes
                </Button>
              )}
              {isDraft && uploadDetailQuery.data?.status === "ready" && (
                <>
                  <Button
                    variant="outline"
                    onClick={() => toast("Escalated to BCBA (mock — no real routing yet).")}
                  >
                    <Megaphone className="h-4 w-4 mr-1.5" />Escalate to BCBA
                  </Button>
                  <Button
                    onClick={() => setFinalizeOpen(true)}
                    disabled={hasUncertain}
                    title={hasUncertain ? "Resolve every Uncertain result before finalizing" : undefined}
                  >
                    Finalize as V{selectedVersionSummary?.version_number}
                  </Button>
                </>
              )}
            </div>
          </div>
          <div className="mt-3 rounded-md bg-slate-50 border border-slate-200 px-3 py-2 text-xs text-slate-500">
            {isDraft
              ? "Draft — override any real finding below, or finalize this real upload once ready. Finalizing is permanent: there is no un-finalize."
              : "Real, finalized data — locked. No further overrides; mark-reviewed and correction email arrive in a later stage."}
          </div>
        </div>
      </div>

      <Dialog open={finalizeOpen} onOpenChange={open => { setFinalizeOpen(open); if (!open) setConfirmRefId(""); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Finalize as V{selectedVersionSummary?.version_number}?</DialogTitle>
            <DialogDescription>
              This is permanent — there is no way to un-finalize once this completes. Type the patient's
              reference ID (<span className="font-mono">{patient.reference_id}</span>) to confirm.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-ref-id">Reference ID</Label>
            <Input
              id="confirm-ref-id"
              value={confirmRefId}
              onChange={e => setConfirmRefId(e.target.value)}
              placeholder={patient.reference_id}
              autoComplete="off"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFinalizeOpen(false)}>Cancel</Button>
            <Button
              onClick={handleFinalize}
              disabled={confirmRefId !== patient.reference_id || finalizeMutation.isPending}
            >
              {finalizeMutation.isPending ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Finalizing…</> : "Finalize"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={qaModalOpen} onOpenChange={setQaModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Intake Q&A</DialogTitle>
            <DialogDescription>
              The 5 structured answers submitted with this specific upload (U{finalUpload?.upload_number}) — not
              necessarily the patient's most recent answers if this is an older draft or finalized version.
            </DialogDescription>
          </DialogHeader>
          {intakeAnswers && (
            <div className="space-y-3 text-sm">
              {([
                ["Client Insurance", intakeAnswers.client_insurance],
                ["BCBA Name, Credentials & NPI", intakeAnswers.bcba_name_credentials_npi],
                ["Authorization Dates", intakeAnswers.authorization_dates],
                ["POS/Schedule vs. 97153 Hours Requesting", intakeAnswers.pos_schedule_vs_97153_hours],
                ["Hours Requesting", intakeAnswers.hours_requesting],
              ] as const).map(([label, value]) => (
                <div key={label}>
                  <div className="text-xs font-medium text-slate-500">{label}</div>
                  <div className="mt-0.5 text-slate-900">{value}</div>
                </div>
              ))}
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setQaModalOpen(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {sortedVersions.length === 0 ? (
          <div className="flex-1 flex items-center justify-center p-8 text-center">
            <div>
              <div className="text-lg font-medium text-slate-900">No versions yet</div>
              <div className="mt-1 text-sm text-slate-500">This patient has no versions in the real backend.</div>
            </div>
          </div>
        ) : versionDetailQuery.isLoading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-slate-500 p-8">
            <Loader2 className="h-4 w-4 animate-spin" />Loading this version's uploads…
          </div>
        ) : !finalUpload ? (
          <div className="p-8 text-center text-sm text-slate-500">
            This version has no uploads yet in the real backend.
          </div>
        ) : (
          <div className="h-full flex">
            <div className="w-1/2 h-full border-r border-slate-200 bg-slate-100">
              <PdfViewer uploadId={finalUpload.id} />
            </div>
            <div className="w-1/2 h-full overflow-y-auto">
              {uploadDetailQuery.isLoading ? (
                <div className="flex items-center justify-center gap-2 text-sm text-slate-500 p-8">
                  <Loader2 className="h-4 w-4 animate-spin" />Loading real rule results…
                </div>
              ) : uploadDetailQuery.data?.status === "processing" ? (
                <div className="flex items-center justify-center gap-2 text-sm text-blue-700 p-8">
                  <Loader2 className="h-4 w-4 animate-spin" />The real agent is still reviewing this upload.
                </div>
              ) : uploadDetailQuery.data?.status === "error" ? (
                <div className="p-8 text-center text-sm text-red-700">
                  This upload's real pipeline run failed: {uploadDetailQuery.data.error_detail}
                </div>
              ) : (
                <div className="p-6">
                  {isSimulated && (
                    <div className="mb-3 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900">
                      <FlaskConical className="h-3.5 w-3.5" />
                      SIMULATED — this upload's findings are dev-only synthetic placeholders, not a real agent review.
                    </div>
                  )}
                  <div className="shrink-0 border-b border-slate-200 px-1 py-3 mb-2">
                    <div className="text-xs text-slate-500 mb-2">
                      {isSimulated ? "Rule check results (SIMULATED, dev-only" : "Rule check results (real, upload"} {finalUpload.upload_number})
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      {([
                        { key: "all", label: "All", count: counts.all },
                        { key: "pass", label: "Pass", count: counts.pass },
                        { key: "fail", label: "Fail", count: counts.fail },
                        { key: "uncertain", label: "Uncertain", count: counts.uncertain },
                        { key: "na", label: "N/A", count: counts.na },
                        { key: "not_checkable", label: "Not checkable", count: counts.not_checkable },
                      ] as const).map(f => (
                        <button
                          key={f.key}
                          onClick={() => setFilter(f.key)}
                          className={`flex-1 rounded-md border px-2 py-2 text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${filter === f.key ? "border-slate-400 bg-slate-100" : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"}`}
                        >
                          <span>{f.label}</span>
                          <span className="rounded bg-slate-900/10 px-1.5 py-0.5 tabular-nums">{f.count}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="divide-y divide-slate-100">
                    {filteredResults.map(res => (
                      <div key={res.id} className="px-2 py-4 hover:bg-slate-50">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2 mb-1.5">
                              <span className="text-[10px] font-mono text-slate-400">rule_id: {res.rule_id.slice(0, 8)}…</span>
                              {res.is_overridden && <span className="text-[10px] font-medium uppercase tracking-wide text-blue-700">Overridden</span>}
                            </div>
                            <div className="mt-1.5 text-sm text-slate-600">{res.final_finding}</div>
                            {res.final_pages.length > 0 && (
                              <div className="mt-2 flex items-center gap-1.5">
                                {res.final_pages.map(p => (
                                  <span key={p} className="text-[11px] font-mono rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5">p.{p}</span>
                                ))}
                              </div>
                            )}
                          </div>
                          <div className="shrink-0 flex items-center gap-1.5">
                            <StatusBadge status={res.final_status === "pass" ? "Pass" : res.final_status === "fail" ? "Fail" : "N/A"} />
                            {isDraft && (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <button
                                    className="rounded p-1 text-slate-400 hover:text-slate-700 hover:bg-slate-100 disabled:opacity-40"
                                    disabled={overrideMutation.isPending}
                                    title="Override this finding"
                                    aria-label={`Override this finding (rule_id ${res.rule_id.slice(0, 8)})`}
                                  >
                                    <Pencil className="h-3.5 w-3.5" />
                                  </button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="end">
                                  <DropdownMenuLabel>Override to</DropdownMenuLabel>
                                  {(["pass", "fail", "na", "uncertain", "not_checkable"] as const)
                                    .filter(s => s !== res.final_status)
                                    .map(s => (
                                      <DropdownMenuItem key={s} onClick={() => handleOverride(res, s)}>
                                        {STATUS_LABELS[s]}
                                      </DropdownMenuItem>
                                    ))}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                    {filteredResults.length === 0 && (
                      <div className="p-10 text-center text-sm text-slate-500">No rules match this filter.</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
