import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useSessionNotes } from "@/lib/real-data";
import { fetchSessionNoteFileBlob, apiErrorMessage } from "@/lib/api-client";
import { PageHeader } from "@/components/tp/ui";
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
      <div className="max-w-3xl mx-auto p-8 space-y-6">
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
              note's own content, which is deliberately deferred agent-side work (not part of this round). Below
              is raw file metadata only — filename and upload date — with no verified date-range judgment
              attached. Don't infer a match/mismatch from the order or grouping shown here; there isn't one yet.
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
          <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="text-left px-4 py-2.5 font-medium">Filename</th>
                  <th className="text-left px-4 py-2.5 font-medium w-48">Uploaded</th>
                  <th className="text-right px-4 py-2.5 font-medium w-24"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {files.map(note => (
                  <tr key={note.id}>
                    <td className="px-4 py-3 font-medium">{note.original_filename}</td>
                    <td className="px-4 py-3 text-slate-600">{new Date(note.created_at).toLocaleString()}</td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        variant="ghost" size="sm"
                        disabled={downloadingId === note.id}
                        onClick={() => handleDownload(note.id, note.original_filename)}
                      >
                        {downloadingId === note.id
                          ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          : <Download className="h-3.5 w-3.5" />}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
