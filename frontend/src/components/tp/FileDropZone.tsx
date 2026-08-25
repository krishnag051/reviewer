import { useRef, useState, type DragEvent, type ReactNode } from "react";
import { UploadIcon } from "lucide-react";

/** Fix Round, Item 1: real drag-and-drop, sharing the EXACT SAME
 * validation as the click-to-browse path -- this is the one place either
 * path's files get checked, so there's no way for drag-and-drop to be
 * looser than browsing.
 *
 * Investigated first: neither drop zone had ANY real validation before
 * this round -- the "PDF only · max 25 MB" text was decorative only;
 * `onChange={e => setFile(e.target.files?.[0] ?? null)}` accepted
 * whatever the browser handed back with zero checks. The `accept`
 * attribute on the hidden `<input>` only filters the OS file-picker
 * dialog -- it enforces nothing once a file is actually selected, and
 * doesn't apply to a drag at all. Real validation had to be built for
 * BOTH paths together, not just added to drag-and-drop, to satisfy this
 * round's own "don't build a second, looser validation path" instruction
 * -- there was no first, stricter one to match yet.
 */

export type FileDropZoneValidation = {
  /** MIME type(s) or extension(s) to accept, e.g. "application/pdf". `undefined` = any type. */
  accept?: string;
  /** Human-readable accept description for error messages, e.g. "PDF". */
  acceptLabel?: string;
  /** Max size per file, in bytes. `undefined` = no limit. */
  maxSizeBytes?: number;
  multiple: boolean;
};

export type FileDropZoneProps = FileDropZoneValidation & {
  onFiles: (files: File[]) => void;
  /** Rendered inside the zone -- current file name(s)/placeholder text, icon, etc. */
  children: ReactNode;
  className?: string;
};

function isPdfFile(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

/** Validates one already-selected/dropped file list against the SAME
 * rules regardless of path. Returns the accepted files plus a single,
 * clear error message if anything was rejected -- never a silent drop.
 * `multiple: false` accepts only the first valid file and reports how
 * many extras were rejected, rather than silently discarding them with
 * no explanation.
 */
export function validateFiles(files: File[], rules: FileDropZoneValidation): { accepted: File[]; error: string | null } {
  if (files.length === 0) return { accepted: [], error: null };

  const acceptLabel = rules.acceptLabel ?? (rules.accept ? rules.accept : "file");
  const typeOk = (f: File) => !rules.accept || (rules.accept === "application/pdf" ? isPdfFile(f) : f.type === rules.accept);

  const wrongType = files.filter(f => !typeOk(f));
  const tooBig = files.filter(f => typeOk(f) && rules.maxSizeBytes != null && f.size > rules.maxSizeBytes);
  const valid = files.filter(f => typeOk(f) && (rules.maxSizeBytes == null || f.size <= rules.maxSizeBytes));

  const errors: string[] = [];
  if (wrongType.length > 0) {
    errors.push(`${wrongType.length === 1 ? `"${wrongType[0].name}" is not a valid ${acceptLabel} file` : `${wrongType.length} files are not valid ${acceptLabel} files`}.`);
  }
  if (tooBig.length > 0) {
    const maxMb = (rules.maxSizeBytes! / (1024 * 1024)).toFixed(0);
    errors.push(`${tooBig.length === 1 ? `"${tooBig[0].name}" is over the ${maxMb} MB limit` : `${tooBig.length} files are over the ${maxMb} MB limit`}.`);
  }

  if (!rules.multiple && valid.length > 1) {
    errors.push(`Only the first file ("${valid[0].name}") was accepted -- this zone takes one file at a time, the other ${valid.length - 1} were not uploaded.`);
    return { accepted: [valid[0]], error: errors.join(" ") };
  }

  return { accepted: valid, error: errors.length > 0 ? errors.join(" ") : null };
}

/** Real, non-silent detection of a dropped FOLDER (as opposed to a file)
 * -- per this round's own "handle a dragged folder" requirement.
 * `webkitGetAsEntry()` is supported in every real browser this app
 * targets (Chrome/Edge/Firefox/Safari); if it's ever unavailable, this
 * simply can't tell a folder from a file and treats it as a file
 * (falls through to the type/size checks above, which will usually
 * reject it anyway since a folder has no real MIME type).
 */
function hasDirectoryEntry(items: DataTransferItemList): boolean {
  for (let i = 0; i < items.length; i++) {
    const entry = items[i].webkitGetAsEntry?.();
    if (entry && entry.isDirectory) return true;
  }
  return false;
}

export function FileDropZone({ accept, acceptLabel, maxSizeBytes, multiple, onFiles, children, className }: FileDropZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);
  const dragCounter = useRef(0);

  function handleFiles(fileList: FileList | File[]) {
    const files = Array.from(fileList);
    const { accepted, error } = validateFiles(files, { accept, acceptLabel, maxSizeBytes, multiple });
    setDropError(error);
    if (accepted.length > 0) onFiles(accepted);
  }

  // dragenter/dragleave fire on every child element too as the pointer
  // moves across them, not just the zone's own boundary -- a plain
  // enter/leave pair would flicker isDragging off while still hovering
  // over a child. A counter (enter ++, leave --, active while > 0) is the
  // standard fix, and naturally means a drag leaving the REAL outer
  // boundary (counter back to 0) is the only thing that turns the active
  // state off -- exactly "outside the actual drop zone shouldn't trigger
  // anything" from this round's own edge-case list.
  function onDragEnter(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    dragCounter.current += 1;
    setIsDragging(true);
  }
  function onDragLeave(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    dragCounter.current = Math.max(0, dragCounter.current - 1);
    if (dragCounter.current === 0) setIsDragging(false);
  }
  function onDragOver(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault(); // required for onDrop to fire at all
  }
  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault();
    dragCounter.current = 0;
    setIsDragging(false);

    if (e.dataTransfer.items && hasDirectoryEntry(e.dataTransfer.items)) {
      setDropError("Folders can't be uploaded here -- drop a file directly, or click to browse.");
      return;
    }
    handleFiles(e.dataTransfer.files);
  }

  return (
    <label
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDragOver={onDragOver}
      onDrop={onDrop}
      className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed py-10 cursor-pointer transition-colors ${
        dropError
          ? "border-red-300 bg-red-50"
          : isDragging
            ? "border-blue-400 bg-blue-50"
            : "border-slate-200 bg-slate-50 hover:bg-slate-100"
      } ${className ?? ""}`}
    >
      <UploadIcon className={`h-6 w-6 ${dropError ? "text-red-400" : isDragging ? "text-blue-500" : "text-slate-400"}`} />
      {children}
      {dropError && <div className="text-xs text-red-600 font-medium px-4 text-center">{dropError}</div>}
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        className="hidden"
        onChange={e => {
          if (e.target.files) handleFiles(e.target.files);
          e.target.value = ""; // allow re-selecting the same file after a rejection
        }}
      />
    </label>
  );
}
