import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useSessionNotes, useSessionNoteExtraction } from "@/lib/real-data";
import {
  fetchSessionNoteFileBlob, apiErrorMessage,
  type SessionNoteExtractionField, type SessionNoteExtractionOut, type SessionNoteFileOut,
} from "@/lib/api-client";
import { PageHeader } from "@/components/tp/ui";
import { PdfViewer } from "@/components/tp/PdfViewer";
import { Button } from "@/components/ui/button";
import { AlertTriangle, ChevronDown, ChevronRight, Download, Loader2, NotebookText } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/session-notes/$uploadId")({ component: SessionNotesPage });

const CONFIDENCE_STYLE: Record<SessionNoteExtractionField["confidence"], string> = {
  high: "bg-emerald-50 text-emerald-700 border-emerald-200",
  medium: "bg-amber-50 text-amber-700 border-amber-200",
  low: "bg-orange-50 text-orange-700 border-orange-200",
  none: "bg-slate-100 text-slate-500 border-slate-200",
};

const EXTRACTION_FIELDS: { key: keyof SessionNoteExtractionOut; label: string }[] = [
  { key: "session_date", label: "Session Date" },
  { key: "session_location", label: "Session Location" },
  { key: "clinician_telehealth_location", label: "Clinician Telehealth Location" },
  { key: "patient_telehealth_location", label: "Patient Telehealth Location" },
  { key: "assessment_activity", label: "Assessment Activity" },
];

/** Round 79, Item 2: the real, per-field extraction output (Round 59's
 * agent-making step), displayed plainly -- value, a confidence badge, and
 * the exact source quote it was pulled from, so someone can visually
 * check the extraction against the source note without digging through
 * logs or a separate export. */
function ExtractedFieldRow({ label, field }: { label: string; field: SessionNoteExtractionField }) {
  return (
    <div className="py-2 border-b border-slate-100 last:border-0">
      <div className="flex items-center justify-between gap-2">
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <span className={cn("inline-flex items-center rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide", CONFIDENCE_STYLE[field.confidence])}>
          {field.confidence}
        </span>
      </div>
      <div className="mt-0.5 text-sm text-slate-900">
        {field.value ?? <span className="text-slate-400 italic">Not found in this note</span>}
      </div>
      {field.source_quote && (
        <div className="mt-0.5 text-xs text-slate-500 italic">"{field.source_quote}"</div>
      )}
    </div>
  );
}

function SessionNoteCard({ uploadId, note }: { uploadId: string; note: SessionNoteFileOut }) {
  // Round 79, Item 2: collapsed by default -- the raw PDF preview is no
  // longer the first, large thing shown; the real extracted fields are.
  // Expandable on demand for anyone who wants the full source document.
  const [expanded, setExpanded] = useState(false);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const extractionQuery = useSessionNoteExtraction(uploadId, note.id);

  async function handleDownload() {
    setDownloadingId(note.id);
    try {
      const blob = await fetchSessionNoteFileBlob(uploadId, note.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = note.original_filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-slate-50">
        <div>
          <div className="font-medium text-sm">{note.original_filename}</div>
          <div className="text-xs text-slate-500">Uploaded {new Date(note.created_at).toLocaleString()}</div>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" disabled={downloadingId === note.id} onClick={handleDownload}>
            {downloadingId === note.id
              ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
              : <Download className="h-3.5 w-3.5 mr-1.5" />}
            Download
          </Button>
          <Button variant="outline" size="sm" onClick={() => setExpanded(e => !e)}>
            {expanded ? <ChevronDown className="h-3.5 w-3.5 mr-1.5" /> : <ChevronRight className="h-3.5 w-3.5 mr-1.5" />}
            {expanded ? "Hide document" : "View document"}
          </Button>
        </div>
      </div>

      {/* Real extracted fields -- always visible, not behind the collapse. */}
      <div className="px-4 py-1">
        {extractionQuery.isLoading && (
          <div className="flex items-center gap-2 py-3 text-sm text-slate-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />Extracting real fields from this note…
          </div>
        )}
        {extractionQuery.isError && (
          <div className="py-3 text-sm text-red-600">{apiErrorMessage(extractionQuery.error)}</div>
        )}
        {extractionQuery.data && (
          <div className="divide-y-0">
            {EXTRACTION_FIELDS.map(f => (
              <ExtractedFieldRow key={f.key} label={f.label} field={extractionQuery.data![f.key]} />
            ))}
          </div>
        )}
      </div>

      {/* Collapsed by default -- the full raw document, expandable on demand. */}
      {expanded && (
        <div className="h-[70vh] bg-slate-100 border-t border-slate-200">
          <PdfViewer
            cacheKey={`${uploadId}-${note.id}`}
            fetchBlob={() => fetchSessionNoteFileBlob(uploadId, note.id)}
            title={note.original_filename}
          />
        </div>
      )}
    </div>
  );
}

// Round 56, Item 4: same "opens in a new tab, never rendered inline" UX
// pattern as the "Helping Document" button (plans.$refId.index.tsx), but
// this is a real routed page (not a raw blob) since it lists potentially
// many files, not one.
//
// Round 72, Item 4: each file became genuinely viewable inline via the
// same real PdfViewer component the main review page uses.
//
// Round 79, Item 2: restructured again -- the raw PDF preview is now
// collapsed by default (SessionNoteCard above), and the real extracted
// fields (Round 59's agent-making extraction step, wired through a new
// GET .../extraction endpoint this round) are shown plainly instead,
// exactly the data this page's own placeholder previously said wasn't
// available yet.
function SessionNotesPage() {
  const { uploadId } = Route.useParams();
  const notesQuery = useSessionNotes(uploadId);
  const files = notesQuery.data?.files ?? [];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-4xl mx-auto p-8 space-y-6">
        <PageHeader
          title={notesQuery.data ? `Session Notes — ${notesQuery.data.patient_name}` : "Session Notes"}
          description={
            notesQuery.data
              ? `${notesQuery.data.patient_reference_id} — every session-note file uploaded alongside this TP submission.`
              : "Every session-note file uploaded alongside this TP submission."
          }
        />

        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 flex items-start gap-2.5 text-sm text-amber-900">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div className="font-medium">Inside/outside report-date-range split not built yet</div>
            <div className="mt-0.5 text-amber-800">
              This is intended to eventually split into two groups — session notes that fall within the TP's
              report date range, and ones that fall outside it. That's a separate comparison (already used for the
              QA-RPT-03/QA-ACF-02/QA-ACF-08 rule checks) from the real per-field extraction shown below, which this
              round wires through directly. Files are shown as-is, in upload order.
            </div>
          </div>
        </div>

        {notesQuery.isLoading && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" />Loading…
          </div>
        )}

        {notesQuery.isError && (
          <div className="text-sm text-red-600">{apiErrorMessage(notesQuery.error)}</div>
        )}

        {notesQuery.data && files.length === 0 && (
          <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
            <NotebookText className="h-6 w-6 mx-auto mb-2 text-slate-300" />
            No session-note files were uploaded for this upload — either an older "supporting document" mode
            upload, or this upload predates session notes entirely.
          </div>
        )}

        {notesQuery.data && files.length > 0 && (
          <div className="space-y-6">
            {files.map(note => (
              <SessionNoteCard key={note.id} uploadId={uploadId} note={note} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
