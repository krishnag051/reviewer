import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { Loader2 } from "lucide-react";
import { ApiError } from "@/lib/api-client";

// Real PDF pane (Round 42) -- fetches GET /uploads/:id/file as a Blob (needs
// the Authorization header, so a plain <iframe src="..."> / <embed
// src="..."> can't hit the endpoint directly) and renders it via a
// short-lived object URL. Works for both a draft's latest upload and a
// finalized version's final upload -- the caller just passes whichever
// upload id is currently selected.
//
// Round 70, Item 2: real page-jump, via the PDF "open parameters" spec
// browsers' own built-in PDF viewers (Chrome/Edge's PDFium, Firefox's
// pdf.js) already honor -- appending "#page=N" to the blob URL navigates
// to page N. Chose this over adding react-pdf/pdfjs-dist as a new
// dependency: no new library, no custom canvas renderer to maintain, and
// it's exactly the toolbar/behavior already visible in the reference
// screenshot (that IS a browser's native PDF viewer chrome, not a custom
// one). `page` here always means the PHYSICAL page number stored in
// final_pages/model_pages -- see app/services/page_labels.py's docstring
// for why no translation step is needed for navigation itself.
//
// Round 72, Item 1 -- REAL BUG FOUND AND FIXED: Round 70's original
// version just re-set the SAME <iframe>'s `src` prop to
// `${baseUrl}${hash}` on every goToPage() call, assuming the browser would
// treat a hash-only change to an already-loaded blob: URL as in-document
// navigation (the way `<a href="#anchor">` works on a normal HTML page).
// Confirmed live (Krishna, this round): it does not -- clicking a page
// link did nothing. The embedded PDF viewer plugin only reads the
// "#page=N" open-parameter at genuine (re)navigation/initial-load time; a
// same-document src reassignment on an already-rendered blob: URL doesn't
// re-trigger that parse in Chrome/Edge's PDFium (or reliably in Firefox's
// pdf.js either). The fix: force a REAL remount of the iframe element on
// every page-jump via a `key` combining the hash AND a monotonic jump
// counter below -- React tears down and recreates the DOM node with the
// full "src" (including "#page=N") present at creation time, which IS the
// reliably-honored case for this spec. The counter matters too: without
// it, clicking the SAME page number twice in a row would produce an
// identical key (no remount, silent no-op) even after the user had
// scrolled elsewhere and wanted to jump back. No new network fetch
// happens on any of this (same in-memory blob: URL, already resolved),
// just a fast PDFium/pdf.js re-parse -- a small, acceptable cost for a
// real, working jump every time, which is what this round asked for.
// Round 72, Item 4: generalized from a hardcoded `uploadId` (which always
// called fetchUploadFileBlob specifically) to a caller-supplied
// `fetchBlob` + `cacheKey` -- this is what actually lets the Session Notes
// page (session-notes.$uploadId.tsx) genuinely REUSE this exact component
// for each attached session-note file (via fetchSessionNoteFileBlob)
// instead of duplicating the blob-fetch/object-URL/iframe technique in a
// second, parallel implementation. `cacheKey` replaces `uploadId` as the
// effect's re-fetch trigger -- callers pass whatever value actually
// identifies "this is a different file now" (an upload id, a session-note
// file id, etc.).
export interface PdfViewerHandle {
  goToPage: (page: number) => void;
}

export const PdfViewer = forwardRef<
  PdfViewerHandle,
  { fetchBlob: () => Promise<Blob>; cacheKey: string; title?: string }
>(function PdfViewer({ fetchBlob, cacheKey, title }, ref) {
  const [baseUrl, setBaseUrl] = useState<string | null>(null);
  const [hash, setHash] = useState("");
  // Incremented on every goToPage() call, even a repeat click on the SAME
  // page number -- included in the iframe's `key` below so re-clicking an
  // already-current page still forces a fresh remount/re-navigation
  // (otherwise an identical hash string would mean an identical key, no
  // remount, and a silent no-op if the user had since scrolled elsewhere
  // in the viewer and wanted to jump back to that same page).
  const [jumpCount, setJumpCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useImperativeHandle(ref, () => ({
    goToPage: (page: number) => {
      setHash(`#page=${page}`);
      setJumpCount(n => n + 1);
    },
  }), []);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setBaseUrl(null);
    setHash("");
    setJumpCount(0);

    fetchBlob()
      .then(blob => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setBaseUrl(objectUrl);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally
    // keyed on cacheKey, not fetchBlob (a fresh closure every render would
    // otherwise re-fetch on every parent re-render).
  }, [cacheKey]);

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
  if (!baseUrl) return null;

  return (
    <iframe
      key={`${hash}-${jumpCount}`}
      src={`${baseUrl}${hash}`}
      title={title ?? "PDF"}
      className="h-full w-full border-0"
    />
  );
});
