import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { ApiError, fetchUploadFileBlob } from "@/lib/api-client";

// Real PDF pane (Round 42) -- fetches GET /uploads/:id/file as a Blob (needs
// the Authorization header, so a plain <iframe src="..."> / <embed
// src="..."> can't hit the endpoint directly) and renders it via a
// short-lived object URL. Works for both a draft's latest upload and a
// finalized version's final upload -- the caller just passes whichever
// upload id is currently selected.
export function PdfViewer({ uploadId }: { uploadId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setUrl(null);

    fetchUploadFileBlob(uploadId)
      .then(blob => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(err => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : "Failed to load the PDF.");
      })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [uploadId]);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />Loading real PDF…
      </div>
    );
  }
  if (error) {
    return <div className="h-full flex items-center justify-center p-6 text-center text-sm text-red-700">{error}</div>;
  }
  if (!url) return null;

  return <iframe src={url} title="Treatment plan PDF" className="h-full w-full border-0" />;
}
