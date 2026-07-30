import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, PAYORS, pendingSlotLabel, type Payor } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Upload as UploadIcon, FileCheck2 } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/upload")({ component: UploadPage });

// Fake PDF content generator for a freshly-uploaded attempt -- no real PDF
// parsing happens client-side yet (see INTEGRATION_PLAN.md), so this just
// gives the attempt SOME representative page content to render.
function makeAttemptPdf(name: string, refId: string) {
  return [
    { page: 1, title: "Cover Page", body: [`TREATMENT PLAN — Applied Behavior Analysis`, `Patient: ${name}`, `Reference ID: ${refId}`, `Prepared by: BrightPath ABA Services`] },
    { page: 2, title: "Diagnosis & Background", body: [`DSM-5 Diagnosis: Autism Spectrum Disorder (F84.0)`, `Medical History: No significant contraindications.`] },
    { page: 3, title: "Assessment Summary", body: [`Functional Behavior Assessment (FBA) completed.`, `VB-MAPP and Vineland-3 administered.`] },
    { page: 4, title: "Service Recommendations", body: [`97153 (Direct Therapy): 30 hours/week.`, `97156 (Parent Training): 1 hour/week.`] },
    { page: 5, title: "Goals & Objectives", body: [`Goal 1 — Manding: Independently mand for 20 preferred items across 3 environments.`] },
    { page: 6, title: "Behavior Intervention Plan", body: [`Target Behavior — Elopement: Antecedent strategies and replacement behavior documented.`] },
    { page: 7, title: "Signatures", body: [`BCBA Signature: [signed]`, `Parent/Guardian Signature: [signed]`] },
  ];
}

// /upload ONLY ever creates draft attempts (addAttempt). It never shows a
// Finalize action -- that lives exclusively on the patient's own detail
// page (plans.$refId.index.tsx), where every draft attempt for the
// currently-open V-slot gets its own full detail (score, fail list, lane
// tags) plus the "Finalize as V[n]" button. On submit this page immediately
// navigates to that patient's page -- it doesn't show a confirmation of its
// own, since the patient page's "processing" state (see DraftAttemptCard)
// IS the confirmation that the upload was received.
function UploadPage() {
  const { patients, addPatient, addAttempt } = useTP();
  const nav = useNavigate();
  const [mode, setMode] = useState<"new" | "existing">("new");

  // new
  const [name, setName] = useState("");
  const [refId, setRefId] = useState("");
  const [payor, setPayor] = useState<Payor>(PAYORS[0]);
  const [reviewerId, setReviewerId] = useState(reviewers[0].id);
  const [file, setFile] = useState<File | null>(null);

  // existing
  const [search, setSearch] = useState("");
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const selectedExisting = patients.find(p => p.refId === selectedRef) ?? null;

  const filtered = search
    ? patients.filter(p => p.name.toLowerCase().includes(search.toLowerCase()) || p.refId.toLowerCase().includes(search.toLowerCase())).slice(0, 5)
    : [];

  function handleNew() {
    if (!name || !refId) { toast.error("Patient name and reference ID are required."); return; }
    if (patients.find(p => p.refId === refId)) { toast.error("Reference ID already exists — use Existing Patient to add another attempt."); return; }
    // addPatient's state update is queued, not applied to this render's
    // `patients` yet -- addAttempt no longer relies on that (see its own
    // comment in tp-context.tsx), so calling it right after addPatient in
    // the same handler is safe. Attempt number for a brand-new patient's
    // first attempt is always 1, known without waiting on anything.
    addPatient({ refId, name, payor });
    addAttempt(refId, reviewerId, makeAttemptPdf(name, refId), new Date().toISOString().slice(0, 10));
    toast.success(`Attempt U1 created for ${name} — the agent is now reviewing it.`);
    nav({ to: "/plans/$refId", params: { refId } });
  }

  function handleUploadToExisting(p: (typeof patients)[number]) {
    // `p` is a snapshot already rendered from committed state (this isn't
    // chained after a same-tick addPatient), so this is accurate for the
    // toast without needing addAttempt's return value.
    const attemptNumber = p.uAttempts.length + 1;
    addAttempt(p.refId, reviewerId, makeAttemptPdf(p.name, p.refId), new Date().toISOString().slice(0, 10));
    toast.success(`Attempt U${attemptNumber} created for ${p.name} — the agent is now reviewing it.`);
    nav({ to: "/plans/$refId", params: { refId: p.refId } });
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-8">
        <PageHeader title="Upload Treatment Plan" description="Upload a draft attempt. Review and finalization happen on the patient's own page." />

        <div className="mt-6 inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-sm">
          {(["new", "existing"] as const).map(m => (
            <button
              key={m}
              onClick={() => { setMode(m); setSelectedRef(null); setSearch(""); }}
              className={`px-4 py-1.5 rounded ${mode === m ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}
            >
              {m === "new" ? "New Patient" : "Existing Patient"}
            </button>
          ))}
        </div>

        <div className="mt-6 rounded-lg border border-slate-200 bg-white p-6 space-y-5">
          {mode === "new" ? (
            <>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5"><Label>Patient Name</Label><Input value={name} onChange={e => setName(e.target.value)} placeholder="e.g., Jordan Nakamura" /></div>
                <div className="space-y-1.5"><Label>Reference ID (permanent)</Label><Input value={refId} onChange={e => setRefId(e.target.value)} placeholder="e.g., TP-2026-0500" /></div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5"><Label>Payor</Label>
                  <Select value={payor} onValueChange={v => setPayor(v as Payor)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{PAYORS.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5"><Label>Reviewer / BCBA</Label>
                  <Select value={reviewerId} onValueChange={setReviewerId}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>{reviewers.map(r => <SelectItem key={r.id} value={r.id}>{r.name}, {r.credentials}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-1.5">
                <Label>Treatment Plan PDF</Label>
                <label className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 py-10 cursor-pointer hover:bg-slate-100 transition-colors">
                  <UploadIcon className="h-6 w-6 text-slate-400" />
                  <div className="text-sm text-slate-700">{file ? file.name : "Drop your PDF here, or click to browse"}</div>
                  <div className="text-xs text-slate-500">PDF only · max 25 MB</div>
                  <input type="file" accept="application/pdf" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} />
                </label>
              </div>
              <div className="flex justify-end">
                <Button onClick={handleNew}>Create Attempt U1 (against {pendingSlotLabel(0)})</Button>
              </div>
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Search existing patient</Label>
                <Input value={search} onChange={e => { setSearch(e.target.value); setSelectedRef(null); }} placeholder="Name or reference ID" />
                {filtered.length > 0 && !selectedRef && (
                  <div className="mt-1 rounded border border-slate-200 bg-white divide-y">
                    {filtered.map(p => {
                      const nextV = pendingSlotLabel(p.versions.length);
                      return (
                        <button key={p.refId} onClick={() => { setSelectedRef(p.refId); setSearch(`${p.name} — ${p.refId}`); }}
                          className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 flex items-center justify-between gap-2">
                          <div>
                            <div className="font-medium">{p.name}</div>
                            <div className="text-xs text-slate-500 font-mono">{p.refId} · {p.versions.length} finalized version(s)</div>
                          </div>
                          {p.uAttempts.length > 0 && (
                            <span className="text-[10px] uppercase tracking-wide rounded bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 shrink-0">
                              {p.uAttempts.length} draft{p.uAttempts.length > 1 ? "s" : ""} in progress for {nextV}
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>

              {selectedExisting && (
                <>
                  <div className="rounded bg-slate-50 border border-slate-200 p-3 text-sm flex items-center gap-2">
                    <FileCheck2 className="h-4 w-4 text-slate-600" />
                    <div>
                      <span className="font-medium">{selectedExisting.name}</span> ({selectedExisting.refId}) — {selectedExisting.versions.length} finalized version(s).
                      This upload will create attempt <span className="font-medium">U{selectedExisting.uAttempts.length + 1}</span> against the <span className="font-medium">{pendingSlotLabel(selectedExisting.versions.length)}</span> slot.
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Reviewer / BCBA</Label>
                    <Select value={reviewerId} onValueChange={setReviewerId}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>{reviewers.map(r => <SelectItem key={r.id} value={r.id}>{r.name}, {r.credentials}</SelectItem>)}</SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label>Treatment Plan PDF</Label>
                    <label className="flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-slate-200 bg-slate-50 py-10 cursor-pointer hover:bg-slate-100 transition-colors">
                      <UploadIcon className="h-6 w-6 text-slate-400" />
                      <div className="text-sm text-slate-700">{file ? file.name : "Drop your PDF here, or click to browse"}</div>
                      <div className="text-xs text-slate-500">PDF only · max 25 MB</div>
                      <input type="file" accept="application/pdf" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} />
                    </label>
                  </div>
                  <div className="flex justify-end">
                    <Button onClick={() => handleUploadToExisting(selectedExisting)}>Create Attempt U{selectedExisting.uAttempts.length + 1} (against {pendingSlotLabel(selectedExisting.versions.length)})</Button>
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
