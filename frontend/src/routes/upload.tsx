import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useTP } from "@/lib/tp-context";
import { reviewers, type Payor } from "@/lib/tp-mock";
import { PageHeader } from "@/components/tp/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Upload as UploadIcon, FileCheck2 } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/upload")({ component: UploadPage });

const PAYORS: Payor[] = ["Healthfirst", "Emblem", "Anthem", "Molina", "Aetna", "Cigna"];

function UploadPage() {
  const nav = useNavigate();
  const { patients, addPatient, addVersion } = useTP();
  const [mode, setMode] = useState<"new" | "existing">("new");

  // new
  const [name, setName] = useState("");
  const [refId, setRefId] = useState("");
  const [payor, setPayor] = useState<Payor>("Healthfirst");
  const [reviewerId, setReviewerId] = useState(reviewers[0].id);
  const [file, setFile] = useState<File | null>(null);

  // existing
  const [search, setSearch] = useState("");
  const [selectedRef, setSelectedRef] = useState<string | null>(null);
  const selected = patients.find(p => p.refId === selectedRef);
  const nextVersion = selected ? Math.max(...selected.versions.map(v => v.version)) + 1 : 0;
  const filtered = search
    ? patients.filter(p => p.name.toLowerCase().includes(search.toLowerCase()) || p.refId.toLowerCase().includes(search.toLowerCase())).slice(0, 5)
    : [];

  function handleNew() {
    if (!name || !refId) { toast.error("Patient name and reference ID are required."); return; }
    if (patients.find(p => p.refId === refId)) { toast.error("Reference ID already exists."); return; }
    const template = patients[0];
    addPatient({
      refId, name, payor,
      versions: [{
        ...template.versions[0],
        version: 1,
        uploadedAt: new Date().toISOString().slice(0, 10),
        assessmentDate: new Date().toISOString().slice(0, 10),
        reviewerId, reviewed: false,
      }],
    });
    toast.success(`Version 1 created for ${name}`);
    nav({ to: "/plans/$refId", params: { refId } });
  }

  function handleExisting() {
    if (!selected) return;
    const v = addVersion(selected.refId, payor, reviewerId);
    toast.success(`Version ${v} created for ${selected.name}`);
    nav({ to: "/plans/$refId", params: { refId: selected.refId } });
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto p-8">
        <PageHeader title="Upload New Treatment Plan" description="Submit a plan for automated compliance review." />

        <div className="mt-6 inline-flex rounded-md border border-slate-200 bg-white p-0.5 text-sm">
          {(["new", "existing"] as const).map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
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
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>Search existing patient</Label>
                <Input value={search} onChange={e => { setSearch(e.target.value); setSelectedRef(null); }} placeholder="Name or reference ID" />
                {filtered.length > 0 && !selectedRef && (
                  <div className="mt-1 rounded border border-slate-200 bg-white divide-y">
                    {filtered.map(p => (
                      <button key={p.refId} onClick={() => { setSelectedRef(p.refId); setSearch(`${p.name} — ${p.refId}`); setPayor(p.payor); }}
                        className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50">
                        <div className="font-medium">{p.name}</div>
                        <div className="text-xs text-slate-500 font-mono">{p.refId} · v{Math.max(...p.versions.map(v => v.version))}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              {selected && (
                <div className="rounded bg-slate-50 border border-slate-200 p-3 text-sm flex items-center gap-2">
                  <FileCheck2 className="h-4 w-4 text-slate-600" />
                  <div>Current version: <span className="font-medium">v{nextVersion - 1}</span>. This upload will create <span className="font-medium">Version {nextVersion}</span>.</div>
                </div>
              )}
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
            </>
          )}

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
            {mode === "new"
              ? <Button onClick={handleNew}>Create Version 1</Button>
              : <Button onClick={handleExisting} disabled={!selected}>Create Version {nextVersion || ""}</Button>}
          </div>
        </div>
      </div>
    </div>
  );
}
