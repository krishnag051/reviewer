import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useSessionNotes } from "@/lib/real-data";
import { fetchSessionNoteFileBlob, apiErrorMessage } from "@/lib/api-client";
import { PageHeader } from "@/components/tp/ui";
import { PdfViewer } from "@/components/tp/PdfViewer";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Download, Loader2, NotebookText } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/session-notes/$uploadId")({ component: SessionNotesPage });

// Round 56, Item 4: same "opens in a new tab, never rendered inline" UX
// pattern as the "Helping Document" button (plans.$refId.index.tsx), but
// this is a real routed page (not a raw blob) since it lists potentially
// many files, not one. Deliberately a raw-metadata placeholder: real date
// extraction from session notes -- the only thing that could actually
// compute the "falls within the TP's report date range" vs. "falls
// outside it" split this page is EVENTUALLY meant to show -- is agent-side
// work explicitly deferred to a future round (see CLAUDE.md's Round 56
// scope). Showing a fake-looking split off data that was never verified
// would be worse than showing nothing, so this says so plainly instead.
//
// Round 72, Item 4: each file is now genuinely viewable inline, not just
// downloadable -- an embedded, scrollable PdfViewer per file, reusing the
// EXACT SAME component the main review page uses for the TP itself
// (PdfViewer.tsx, generalized in this round to accept any blob-fetcher,
// not just fetchUploadFileBlob) rather than a second, parallel PDF-
// rendering technique. Additive: the download button stays.
function SessionNotesPage() {
  const { uploadId } = Route.useParams();
  const notesQuery = useSessionNotes(uploadId);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const files = notesQuery.data?.files ?? [];

  async function handleDownload(fileId: string, filename: string) {
    setDownloadingId(fileId);
    try {
      const blob = await fetchSessionNoteFileBlob(uploadId, fileId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (err) {
      toast.error(apiErrorMessage(err));
    } finally {
      setDownloadingId(null);
    }
  }

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
              report date range, and ones that fall outside it. That requires real date extraction from each
              note's own content, which is deliberately deferred agent-side work (not part of this round). Files
              below are shown as-is, in upload order, with no verified date-range judgment attached. Don't infer a
              match/mismatch from the order shown here; there isn't one yet.
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
              <div key={note.id} className="rounded-lg border border-slate-200 bg-white overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-200 bg-slate-50">
                  <div>
                    <div className="font-medium text-sm">{note.original_filename}</div>
                    <div className="text-xs text-slate-500">Uploaded {new Date(note.created_at).toLocaleString()}</div>
                  </div>
                  <Button
                    variant="ghost" size="sm"
                    disabled={downloadingId === note.id}
                    onClick={() => handleDownload(note.id, note.original_filename)}
                  >
                    {downloadingId === note.id
                      ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                      : <Download className="h-3.5 w-3.5 mr-1.5" />}
                    Download
                  </Button>
                </div>
                {/* Embedded, scrollable inline view -- the same real PdfViewer
                    component the main review page uses, just pointed at this
                    session-note file's own blob instead of the TP's. */}
                <div className="h-[70vh] bg-slate-100">
                  <PdfViewer
                    cacheKey={`${uploadId}-${note.id}`}
                    fetchBlob={() => fetchSessionNoteFileBlob(uploadId, note.id)}
                    title={note.original_filename}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
