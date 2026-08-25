import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import {
  usePatients, usePatientVersions, useCreatePatient, useCreateVersion, useCreateUpload, useCreateSimulatedUpload,
  useAppConfig, useLatestIntakeAnswers,
} from "@/lib/real-data";
import { ApiError, type IntakeAnswers } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { PAYORS, pendingSlotLabel, type Payor } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { FileDropZone } from "@/components/tp/FileDropZone";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Upload as UploadIcon, FileCheck2, Loader2, FlaskConical, X } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/upload")({ component: UploadPage });

// Fix Round, Item 1: the real, enforced limit -- matches the "max 25 MB"
// text already shown in the UI, which was decorative only until now.
const TP_MAX_SIZE_BYTES = 25 * 1024 * 1024;

// Round 42, Stage 2: real upload creation, wired to the real backend --
// POST /patients (new-patient mode only) -> POST /patients/:id/versions
// (new-patient mode, or existing-patient mode when the patient's latest
// version is already finalized -- a finalized version never accepts a new
// upload) -> POST /versions/:id/uploads (the real pipeline trigger, both
// modes). This is the one surface Round 42 converts off tp-context's mock
// addPatient/addAttempt -- everything else still mock (Rules Studio,
// Reports, Dashboard, Admin Settings) is untouched, see FRONTEND_STATE.md.
//
// Round 49: developer-role users additionally see a "Simulate completion
// (dev-only)" checkbox -- routes to POST /versions/:id/uploads/simulate,
// never the real agent. See app/services/simulated_pipeline.py.
//
// Round 51-55: a mandatory second file, the free-form "supporting
// document" + AI extraction. Round 56 replaced this as the DEFAULT path
// with a structured 5-question form + multi-file session notes upload,
// behind the live `supporting_doc_mode` feature flag (switchable from
// Developer Mode) -- the old document path stays fully intact and
// reachable, just dormant by default. `SupportingInfoSection` below
// renders whichever shape the live mode calls for; submit is disabled
// until that mode's own required fields are filled, exactly like the old
// single-file gate used to work.
const EMPTY_ANSWERS: IntakeAnswers = {
  client_insurance: "", bcba_name_credentials_npi: "", authorization_dates: "",
  pos_schedule_vs_97153_hours: "", hours_requesting: "",
};

// Fix Round: client_insurance dropped from this list entirely -- Payor is
// asked once, via the dedicated dropdown below, not typed in twice. The
// dropdown's own selected value is written into client_insurance
// automatically at submit time (see buildAnswersWithPayor below) -- the
// backend's own Form field still expects this exact key non-empty
// (api-client.ts's IntakeAnswers type comment: "matching the backend Form
// fields 1:1... a typo/rename 422s clearly"), so the key itself is NOT
// removed from the type/payload, only the separate user-facing input for it.
const QA_FIELDS: { key: keyof IntakeAnswers; label: string; placeholder: string }[] = [
  { key: "bcba_name_credentials_npi", label: "BCBA Name, Credentials & NPI", placeholder: "e.g., Jane Smith, BCBA-D — NPI 1234567890" },
  { key: "authorization_dates", label: "Authorization Dates", placeholder: "e.g., 01/15/2026 – 07/15/2026" },
  { key: "pos_schedule_vs_97153_hours", label: "Schedule and POS", placeholder: "e.g., Home, Mon–Fri 5–8pm, 15 hrs/week requested" },
  { key: "hours_requesting", label: "Hours Requesting", placeholder: "e.g., 15 hrs/week" },
];

type StructuredPayload = { intakeAnswers: IntakeAnswers; sessionNotes: File[] };

// Round 76, Item 3: split what used to be ONE `SupportingInfoSection`
// (Q&A fields + session-notes uploader stacked together) into two
// independent pieces, so the page can put them in separate columns --
// "Intake Q&A" fields on one side, the file/upload side (including the
// session-notes uploader) on the other. Same fields, same state, same
// validation as before -- purely a layout split, no behavior change.

function IntakeQAFields({
  mode, qaAnswers, setQaAnswers,
}: {
  mode: "document" | "structured_form" | undefined;
  qaAnswers: IntakeAnswers;
  setQaAnswers: (a: IntakeAnswers) => void;
}) {
  if (mode !== "structured_form") return null;
  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50/60 p-4 h-full">
      <div>
        <div className="text-sm font-medium text-slate-900">Patient Central Reach Information <span className="text-slate-400 font-normal">(required, 4 fields)</span></div>
        <div className="text-xs text-slate-500 mt-0.5">Plain text — no document upload needed for these.</div>
      </div>
      <div className="grid grid-cols-1 gap-3">
        {QA_FIELDS.map(f => (
          <div key={f.key} className="space-y-1">
            <Label className="text-xs">{f.label}</Label>
            <Input
              value={qaAnswers[f.key]}
              placeholder={f.placeholder}
              onChange={e => setQaAnswers({ ...qaAnswers, [f.key]: e.target.value })}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function SupportingUploads({
  mode, supportingDocument, setSupportingDocument, sessionNotes, setSessionNotes,
}: {
  mode: "document" | "structured_form" | undefined;
  supportingDocument: File | null;
  setSupportingDocument: (f: File | null) => void;
  sessionNotes: File[];
  setSessionNotes: (fs: File[]) => void;
}) {
  if (!mode) return null;

  if (mode === "document") {
    return (
      <div className="space-y-1.5">
        <Label>Supporting Document <span className="text-slate-400">(required)</span></Label>
        <label className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 py-10 cursor-pointer hover:bg-slate-100 transition-colors">
          <UploadIcon className="h-6 w-6 text-slate-400" />
          <div className="text-sm text-slate-700">{supportingDocument ? supportingDocument.name : "Drop the supporting document here, or click to browse"}</div>
          <div className="text-xs text-slate-500">PDF only · required alongside the TP</div>
          <input type="file" accept="application/pdf" className="hidden" onChange={e => setSupportingDocument(e.target.files?.[0] ?? null)} />
        </label>
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <Label>Session Notes <span className="text-slate-400">(required, one or more files)</span></Label>
      {/* Fix Round, Item 1: real drag-and-drop -- multiple files dropped at
          once are appended to the existing list, matching exactly how
          selecting multiple via browse already worked. Any file type, no
          size limit, per this round's own spec for this zone. */}
      <FileDropZone
        multiple
        onFiles={newFiles => setSessionNotes([...sessionNotes, ...newFiles])}
        className="py-8 bg-white hover:bg-slate-50"
      >
        <div className="text-sm text-slate-700">Drop session note files here, or click to browse</div>
        <div className="text-xs text-slate-500">Any file type · select multiple at once</div>
      </FileDropZone>
      {sessionNotes.length > 0 && (
        <ul className="divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {sessionNotes.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center justify-between px-3 py-1.5 text-sm">
              <span className="truncate">{f.name}</span>
              <button type="button" onClick={() => setSessionNotes(sessionNotes.filter((_, j) => j !== i))} className="text-slate-400 hover:text-red-600 shrink-0 ml-2">
                <X className="h-3.5 w-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadPage() {
  const nav = useNavigate();
  const { user } = useAuth();
  const isDeveloper = user?.role === "developer";
  const [mode, setMode] = useState<"new" | "existing">("new");
  const [submitting, setSubmitting] = useState(false);
  const [useSimulated, setUseSimulated] = useState(false);
  const requiresSupportingInfo = !(isDeveloper && useSimulated);

  const appConfigQuery = useAppConfig();
  const supportingDocMode = appConfigQuery.data?.supporting_doc_mode;

  const patientsQuery = usePatients();
  const patients = patientsQuery.data ?? [];

  // new
  const [name, setName] = useState("");
  const [refId, setRefId] = useState("");
  // Fix Round: Reference ID auto-fills from the typed Patient Name as
  // "{name} {month}-{year}" (ma'am's exact example: "Aaron Gross 8-2026")
  // -- real current date, computed fresh each time, never hardcoded.
  // `refIdTouched` tracks whether the USER has directly edited the
  // Reference ID field themselves; once true, typing in Patient Name never
  // overwrites it again. Goes back to false (auto-fill resumes) only if
  // the user clears Reference ID back to empty -- "reset only if the
  // Reference ID field is still empty/untouched" per the round's own spec.
  const [refIdTouched, setRefIdTouched] = useState(false);
  const [payor, setPayor] = useState<Payor>(PAYORS[0]);
  const [file, setFile] = useState<File | null>(null);
  const [supportingDocument, setSupportingDocument] = useState<File | null>(null);
  const [qaAnswers, setQaAnswers] = useState<IntakeAnswers>(EMPTY_ANSWERS);
  const [sessionNotes, setSessionNotes] = useState<File[]>([]);

  // existing
  const [search, setSearch] = useState("");
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const selectedExisting = patients.find(p => p.reference_id === selectedRef) ?? null;
  const existingVersionsQuery = usePatientVersions(selectedExisting?.id);
  const existingSortedVersions = useMemo(
    () => [...(existingVersionsQuery.data ?? [])].sort((a, b) => b.version_number - a.version_number),
    [existingVersionsQuery.data],
  );
  const existingLatestVersion = existingSortedVersions[0];
  const existingLatestIsDraft = existingLatestVersion?.status === "in_progress";

  // Item 2: "editable across versions" -- prefill from whatever this
  // patient's most recent structured-mode upload answered, still fully
  // editable (not locked). Only relevant to the existing-patient flow --
  // a brand-new patient has no prior upload to prefill from.
  const [existingQaAnswers, setExistingQaAnswers] = useState<IntakeAnswers>(EMPTY_ANSWERS);
  const [existingSessionNotes, setExistingSessionNotes] = useState<File[]>([]);
  const [existingSupportingDocument, setExistingSupportingDocument] = useState<File | null>(null);
  const latestAnswersQuery = useLatestIntakeAnswers(selectedExisting?.id);
  useEffect(() => {
    if (latestAnswersQuery.data) setExistingQaAnswers(latestAnswersQuery.data);
  }, [latestAnswersQuery.data]);

  const filtered = search
    ? patients.filter(p => p.name.toLowerCase().includes(search.toLowerCase()) || p.reference_id.toLowerCase().includes(search.toLowerCase())).slice(0, 5)
    : [];

  const createPatientMutation = useCreatePatient();
  const createVersionMutation = useCreateVersion();
  const createUploadMutation = useCreateUpload();
  const createSimulatedUploadMutation = useCreateSimulatedUpload();

  function errorMessage(err: unknown): string {
    return err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Something went wrong.";
  }

  // Fix Round: real current date at the moment of typing -- never a
  // hardcoded/stale value. Matches ma'am's exact example format: no
  // leading zero on the month, no dashes inside the name, a plain space
  // before "{month}-{year}" (e.g. "Aaron Gross 8-2026").
  function handleNameChange(value: string) {
    setName(value);
    if (!refIdTouched) {
      const now = new Date();
      setRefId(value ? `${value} ${now.getMonth() + 1}-${now.getFullYear()}` : "");
    }
  }

  function handleRefIdChange(value: string) {
    setRefId(value);
    setRefIdTouched(value !== "");
  }

  function buildPayload(
    doc: File | null, qa: IntakeAnswers, notes: File[],
  ): { supportingDocument: File } | StructuredPayload {
    if (supportingDocMode === "document") return { supportingDocument: doc! };
    return { intakeAnswers: qa, sessionNotes: notes };
  }

  function structuredInfoMissing(qa: IntakeAnswers, notes: File[]): boolean {
    return QA_FIELDS.some(f => !qa[f.key].trim()) || notes.length === 0;
  }

  // Fix Round: client_insurance no longer has its own user-facing input --
  // the Payor dropdown (or, for an existing patient, that patient's
  // already-stored payor) is the single source of truth, fed in here at
  // the one point every submit path already goes through. `payorValue`
  // is whatever the caller's own real payor value is; `?? ""` only
  // covers the genuine edge case of an existing patient with no payor
  // ever recorded (not something this round invents a UI for).
  async function submitUpload(
    versionId: string, file: File, doc: File | null, qa: IntakeAnswers, notes: File[], payorValue: string | null,
  ) {
    const qaWithPayor: IntakeAnswers = { ...qa, client_insurance: payorValue ?? "" };
    if (isDeveloper && useSimulated) {
      await createSimulatedUploadMutation.mutateAsync({ versionId, file });
    } else {
      await createUploadMutation.mutateAsync({ versionId, file, payload: buildPayload(doc, qaWithPayor, notes) });
    }
  }

  async function handleNew() {
    if (!name || !refId) { toast.error("Patient name and reference ID are required."); return; }
    if (!file) { toast.error("A treatment plan PDF is required."); return; }
    if (requiresSupportingInfo && supportingDocMode === "document" && !supportingDocument) {
      toast.error("A supporting document is required."); return;
    }
    if (requiresSupportingInfo && supportingDocMode === "structured_form" && structuredInfoMissing(qaAnswers, sessionNotes)) {
      toast.error("All 4 Patient Central Reach Information fields and at least one session note file are required."); return;
    }
    setSubmitting(true);
    try {
      const patient = await createPatientMutation.mutateAsync({ reference_id: refId, name, payor });
      const version = await createVersionMutation.mutateAsync({ patientId: patient.id, payor });
      await submitUpload(version.id, file, supportingDocument, qaAnswers, sessionNotes, payor);
      toast.success(
        isDeveloper && useSimulated
          ? `Upload 1 created for ${name} — SIMULATED completion in ~5s (dev-only, not the real agent).`
          : `Upload 1 created for ${name} — the real backend is now processing it.`,
      );
      nav({ to: "/plans/$refId", params: { refId } });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleUploadToExisting() {
    if (!selectedExisting || !file) { toast.error("A treatment plan PDF is required."); return; }
    if (requiresSupportingInfo && supportingDocMode === "document" && !existingSupportingDocument) {
      toast.error("A supporting document is required."); return;
    }
    if (requiresSupportingInfo && supportingDocMode === "structured_form" && structuredInfoMissing(existingQaAnswers, existingSessionNotes)) {
      toast.error("All 4 Patient Central Reach Information fields and at least one session note file are required."); return;
    }
    setSubmitting(true);
    try {
      const versionId = existingLatestIsDraft
        ? existingLatestVersion!.id
        : (await createVersionMutation.mutateAsync({ patientId: selectedExisting.id })).id;
      await submitUpload(versionId, file, existingSupportingDocument, existingQaAnswers, existingSessionNotes, selectedExisting.payor);
      toast.success(
        isDeveloper && useSimulated
          ? `Upload created for ${selectedExisting.name} — SIMULATED completion in ~5s (dev-only, not the real agent).`
          : `Upload created for ${selectedExisting.name} — the real backend is now processing it.`,
      );
      nav({ to: "/plans/$refId", params: { refId: selectedExisting.reference_id } });
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  const newStructuredMissing = supportingDocMode === "structured_form" && requiresSupportingInfo && structuredInfoMissing(qaAnswers, sessionNotes);
  const newDocMissing = supportingDocMode === "document" && requiresSupportingInfo && !supportingDocument;
  const newModeSubmitDisabled = submitting || !file || newStructuredMissing || newDocMissing || appConfigQuery.isLoading;

  const existingStructuredMissing = supportingDocMode === "structured_form" && requiresSupportingInfo && structuredInfoMissing(existingQaAnswers, existingSessionNotes);
  const existingDocMissing = supportingDocMode === "document" && requiresSupportingInfo && !existingSupportingDocument;
  const existingModeSubmitDisabled = submitting || existingVersionsQuery.isLoading || !file || existingStructuredMissing || existingDocMissing || appConfigQuery.isLoading;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto p-8">
        <PageHeader title="Upload Treatment Plan" description="Upload a draft against the real backend. Review and finalization happen on the patient's own page." />

        <div className="mt-6 inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-sm">
          {(["new", "existing"] as const).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setSelectedRef(null); setSearch(""); }}
              className={`px-4 py-1.5 rounded ${mode === m ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {/* Copy-only rename: mode key itself ("new"/"existing") is
                  untouched, only the button label changed -- "new" mode is
                  still a brand-new patient's first-ever upload, "existing"
                  is still a later upload against an already-existing
                  patient. */}
              {m === "new" ? "Initial Upload" : "Re-upload"}
            </button>
          ))}
        </div>

        {isDeveloper && (
          <label className="mt-4 flex items-center gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 cursor-pointer">
            <input type="checkbox" checked={useSimulated} onChange={e => setUseSimulated(e.target.checked)} />
            <FlaskConical className="h-4 w-4" />
            <span>
              <span className="font-medium">Simulate completion (dev-only)</span> — skips the real agent entirely, marks the upload ready in ~5s with clearly-labeled synthetic findings. Never a real Anthropic API call.
            </span>
          </label>
        )}

        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-6 space-y-5">
          {mode === "new" ? (
            <>
              {/* Round 76, Item 3: real two-column layout -- Intake Q&A on
                  one side, patient data + file uploads (TP PDF, session
                  notes) on the other, so meaningfully more of the form is
                  visible at once instead of one long vertical scroll.
                  Collapses back to a single stacked column below the `lg`
                  breakpoint (narrow viewports) via grid-cols-1 lg:grid-cols-2. */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="space-y-5">
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-1.5"><Label>Patient Name</Label><Input value={name} onChange={e => handleNameChange(e.target.value)} placeholder="e.g., Jordan Nakamura" /></div>
                    <div className="space-y-1.5"><Label>Reference ID (permanent)</Label><Input value={refId} onChange={e => handleRefIdChange(e.target.value)} placeholder="e.g., Jordan Nakamura 8-2026" /></div>
                  </div>
                  <div className="space-y-1.5"><Label>Payor</Label>
                    <Select value={payor} onValueChange={v => setPayor(v as Payor)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>{PAYORS.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Treatment Plan</Label>
                    {/* Fix Round, Item 1: real drag-and-drop, same
                        validation as browse (PDF only, 25 MB max, single
                        file -- extras dropped together are rejected with
                        a clear message, not silently discarded). */}
                    <FileDropZone
                      accept="application/pdf"
                      acceptLabel="PDF"
                      maxSizeBytes={TP_MAX_SIZE_BYTES}
                      multiple={false}
                      onFiles={files => setFile(files[0] ?? null)}
                      className="py-10 bg-slate-50 hover:bg-slate-100"
                    >
                      <div className="text-sm text-slate-700">{file ? file.name : "Drop your PDF here, or click to browse"}</div>
                      <div className="text-xs text-slate-500">PDF only · max 25 MB</div>
                    </FileDropZone>
                  </div>
                  {requiresSupportingInfo && (
                    <SupportingUploads
                      mode={supportingDocMode}
                      supportingDocument={supportingDocument} setSupportingDocument={setSupportingDocument}
                      sessionNotes={sessionNotes} setSessionNotes={setSessionNotes}
                    />
                  )}
                </div>
                <div>
                  {requiresSupportingInfo && (
                    <IntakeQAFields mode={supportingDocMode} qaAnswers={qaAnswers} setQaAnswers={setQaAnswers} />
                  )}
                </div>
              </div>
              <div className="flex justify-end">
                <Button onClick={handleNew} disabled={newModeSubmitDisabled}>
                  {submitting ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Submitting…</> : `Create Upload 1 (against ${pendingSlotLabel(0)})`}
                </Button>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Search existing patient</Label>
                <Input value={search} onChange={e => { setSearch(e.target.value); setSelectedRef(null); }} placeholder="Name or reference ID" />
                {filtered.length > 0 && !selectedRef && (
                  <div className="mt-1 rounded border border-slate-200 bg-white divide-y">
                    {filtered.map(p => (
                      <button key={p.reference_id} onClick={() => { setSelectedRef(p.reference_id); setSearch(`${p.name} — ${p.reference_id}`); }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between gap-2">
                        <div>
                          <div className="font-medium">{p.name}</div>
                          <div className="text-xs text-slate-500 font-mono">{p.reference_id} · latest v{p.latest_version_number ?? "—"}</div>
                        </div>
                        {p.audit_result === null && p.latest_version_number !== null && (
                          <span className="text-[10px] uppercase tracking-wide rounded bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 shrink-0">
                            draft in progress
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {selectedExisting && (
                <>
                  <div className="rounded bg-slate-50 border border-slate-200 p-3 text-sm flex items-center gap-2">
                    <FileCheck2 className="h-4 w-4 text-slate-600" />
                    {existingVersionsQuery.isLoading ? (
                      <span className="text-slate-500 flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" />Loading real version history…</span>
                    ) : (
                      <div>
                        <span className="font-medium">{selectedExisting.name}</span> ({selectedExisting.reference_id}).{" "}
                        {existingLatestIsDraft
                          ? <>This upload adds another attempt to the existing <span className="font-medium">v{existingLatestVersion!.version_number}</span> draft.</>
                          : <>This upload will start a new <span className="font-medium">{pendingSlotLabel(existingSortedVersions.length)}</span> draft version.</>}
                      </div>
                    )}
                  </div>
                  {/* Round 76, Item 3: same two-column convention as the
                      New Patient form above -- Intake Q&A on one side,
                      file uploads on the other. Both flows follow the
                      identical layout, not two diverging designs. */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-5">
                      <div className="space-y-1.5">
                        <Label>Treatment Plan</Label>
                        <label className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 py-10 cursor-pointer hover:bg-slate-100 transition-colors">
                          <UploadIcon className="h-6 w-6 text-slate-400" />
                          <div className="text-sm text-slate-700">{file ? file.name : "Drop your PDF here, or click to browse"}</div>
                          <div className="text-xs text-slate-500">PDF only · max 25 MB</div>
                          <input type="file" accept="application/pdf" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} />
                        </label>
                      </div>
                      {requiresSupportingInfo && (
                        <SupportingUploads
                          mode={supportingDocMode}
                          supportingDocument={existingSupportingDocument} setSupportingDocument={setExistingSupportingDocument}
                          sessionNotes={existingSessionNotes} setSessionNotes={setExistingSessionNotes}
                        />
                      )}
                    </div>
                    <div>
                      {requiresSupportingInfo && supportingDocMode === "structured_form" && latestAnswersQuery.data && (
                        <div className="text-xs text-slate-500 mb-1.5">Prefilled from this patient's most recent submission — edit any field as needed.</div>
                      )}
                      {requiresSupportingInfo && (
                        <IntakeQAFields mode={supportingDocMode} qaAnswers={existingQaAnswers} setQaAnswers={setExistingQaAnswers} />
                      )}
                    </div>
                  </div>
                  <div className="flex justify-end">
                    <Button onClick={handleUploadToExisting} disabled={existingModeSubmitDisabled}>
                      {submitting ? <><Loader2 className="h-4 w-4 animate-spin mr-1.5" />Submitting…</> : "Create Upload"}
                    </Button>
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
