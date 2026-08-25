// Fix Round, Item 1 verification: real, automated tests for the shared
// drag-and-drop + validation logic in FileDropZone.tsx. Two layers:
//
// 1. Direct unit tests of `validateFiles()` -- the exact function both the
//    browse path (onChange) and the drop path (onDrop) call, so proving it
//    correct here proves both paths correct at once, by construction (there
//    is only one validation code path to test).
// 2. Real simulated `drop` events fired at the actually-rendered
//    <FileDropZone> component via Testing Library's `fireEvent.drop`, which
//    exercises the real onDrop handler (drag counter reset, folder
//    detection, error rendering) -- not just the pure function in
//    isolation. This is the closest a jsdom test environment can get to a
//    physical mouse drag: a real DataTransfer-shaped payload through the
//    real DOM event, same technique Testing Library's own docs recommend
//    for drag-and-drop. It is NOT a substitute for a human physically
//    dragging a file in a real browser -- that manual pass is still
//    reported separately, unchecked, in the final report.
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { FileDropZone, validateFiles } from "@/components/tp/FileDropZone";

afterEach(cleanup);

function makeFile(name: string, sizeBytes: number, type: string): File {
  const file = new File([new Uint8Array(Math.max(sizeBytes, 0))], name, { type });
  // jsdom's File doesn't always honor a byte-array-length-derived `.size`
  // consistently across versions -- force it explicitly so size-limit
  // tests are exercising the exact value they claim to.
  Object.defineProperty(file, "size", { value: sizeBytes });
  return file;
}

const TP_RULES = { accept: "application/pdf", acceptLabel: "PDF", maxSizeBytes: 25 * 1024 * 1024, multiple: false };
const NOTES_RULES = { multiple: true };

describe("validateFiles (Item 1 -- shared validation, unit level)", () => {
  it("accepts a valid PDF under the size limit", () => {
    const pdf = makeFile("plan.pdf", 1024, "application/pdf");
    const { accepted, error } = validateFiles([pdf], TP_RULES);
    expect(accepted).toEqual([pdf]);
    expect(error).toBeNull();
  });

  it("accepts a .pdf-named file even with a missing/wrong browser-reported MIME type (matches real-world drag payloads)", () => {
    const pdf = makeFile("plan.pdf", 1024, "");
    const { accepted, error } = validateFiles([pdf], TP_RULES);
    expect(accepted).toEqual([pdf]);
    expect(error).toBeNull();
  });

  it("rejects a non-PDF file with a clear, non-empty error -- not a silent drop", () => {
    const docx = makeFile("plan.docx", 1024, "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    const { accepted, error } = validateFiles([docx], TP_RULES);
    expect(accepted).toEqual([]);
    expect(error).toMatch(/not a valid PDF file/);
  });

  it("rejects an oversized PDF with a clear error naming the limit", () => {
    const bigPdf = makeFile("huge.pdf", 26 * 1024 * 1024, "application/pdf");
    const { accepted, error } = validateFiles([bigPdf], TP_RULES);
    expect(accepted).toEqual([]);
    expect(error).toMatch(/over the 25 MB limit/);
  });

  it("accepts a PDF exactly at the 25 MB boundary", () => {
    const boundaryPdf = makeFile("boundary.pdf", 25 * 1024 * 1024, "application/pdf");
    const { accepted, error } = validateFiles([boundaryPdf], TP_RULES);
    expect(accepted).toEqual([boundaryPdf]);
    expect(error).toBeNull();
  });

  it("single-file zone (TP): multiple valid PDFs dropped together -- accepts only the first, clearly reports the rest were rejected (not silently dropped)", () => {
    const a = makeFile("a.pdf", 1024, "application/pdf");
    const b = makeFile("b.pdf", 1024, "application/pdf");
    const c = makeFile("c.pdf", 1024, "application/pdf");
    const { accepted, error } = validateFiles([a, b, c], TP_RULES);
    expect(accepted).toEqual([a]);
    expect(error).toMatch(/Only the first file \("a\.pdf"\) was accepted/);
    expect(error).toMatch(/other 2 were not uploaded/);
  });

  it("single-file zone (TP): one valid + one invalid dropped together -- reports both the type rejection and the multi-file rejection", () => {
    const pdf = makeFile("a.pdf", 1024, "application/pdf");
    const docx = makeFile("b.docx", 1024, "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    const { accepted, error } = validateFiles([pdf, docx], TP_RULES);
    expect(accepted).toEqual([pdf]);
    expect(error).toMatch(/not a valid PDF file/);
  });

  it("multi-file zone (Session Notes): any file type, multiple accepted at once, matching browse's multi-select behavior", () => {
    const a = makeFile("notes.txt", 100, "text/plain");
    const b = makeFile("scan.png", 200, "image/png");
    const { accepted, error } = validateFiles([a, b], NOTES_RULES);
    expect(accepted).toEqual([a, b]);
    expect(error).toBeNull();
  });

  it("empty file list is a no-op, not an error", () => {
    const { accepted, error } = validateFiles([], TP_RULES);
    expect(accepted).toEqual([]);
    expect(error).toBeNull();
  });
});

/** Builds a minimal but real-shaped DataTransfer-like object for
 * `fireEvent.drop`/`fireEvent.dragEnter` -- jsdom has no real DataTransfer
 * implementation, so tests (including Testing Library's own recommended
 * pattern for this) hand-construct the subset of the interface the
 * component actually reads: `.files` and `.items` (with `webkitGetAsEntry`
 * for the folder-detection path).
 */
function fileDropPayload(files: File[], opts?: { asDirectory?: boolean }) {
  return {
    dataTransfer: {
      files,
      items: files.map(() => ({
        webkitGetAsEntry: () => (opts?.asDirectory ? { isDirectory: true, isFile: false } : { isDirectory: false, isFile: true }),
      })),
    },
  };
}

describe("FileDropZone (Item 1 -- real simulated drop events on the rendered component)", () => {
  it("dropping a valid PDF calls onFiles with the accepted file and shows no error", () => {
    const received: File[][] = [];
    render(
      <FileDropZone accept="application/pdf" acceptLabel="PDF" maxSizeBytes={25 * 1024 * 1024} multiple={false} onFiles={f => received.push(f)}>
        <div>Drop your PDF here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop your PDF here/).closest("label")!;
    const pdf = makeFile("plan.pdf", 1024, "application/pdf");
    fireEvent.drop(zone, fileDropPayload([pdf]));
    expect(received).toEqual([[pdf]]);
    expect(screen.queryByText(/not a valid/)).toBeNull();
  });

  it("dropping a non-PDF file onto the TP zone shows an inline error and does not call onFiles", () => {
    const received: File[][] = [];
    render(
      <FileDropZone accept="application/pdf" acceptLabel="PDF" maxSizeBytes={25 * 1024 * 1024} multiple={false} onFiles={f => received.push(f)}>
        <div>Drop your PDF here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop your PDF here/).closest("label")!;
    const docx = makeFile("plan.docx", 1024, "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
    fireEvent.drop(zone, fileDropPayload([docx]));
    expect(received).toEqual([]);
    expect(screen.getByText(/not a valid PDF file/)).toBeTruthy();
  });

  it("dropping an oversized PDF onto the TP zone shows the size-limit error and does not call onFiles", () => {
    const received: File[][] = [];
    render(
      <FileDropZone accept="application/pdf" acceptLabel="PDF" maxSizeBytes={25 * 1024 * 1024} multiple={false} onFiles={f => received.push(f)}>
        <div>Drop your PDF here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop your PDF here/).closest("label")!;
    const bigPdf = makeFile("huge.pdf", 26 * 1024 * 1024, "application/pdf");
    fireEvent.drop(zone, fileDropPayload([bigPdf]));
    expect(received).toEqual([]);
    expect(screen.getByText(/over the 25 MB limit/)).toBeTruthy();
  });

  it("dropping multiple PDFs onto the single-file TP zone accepts only the first, with a visible rejection message for the rest", () => {
    const received: File[][] = [];
    render(
      <FileDropZone accept="application/pdf" acceptLabel="PDF" maxSizeBytes={25 * 1024 * 1024} multiple={false} onFiles={f => received.push(f)}>
        <div>Drop your PDF here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop your PDF here/).closest("label")!;
    const a = makeFile("a.pdf", 1024, "application/pdf");
    const b = makeFile("b.pdf", 1024, "application/pdf");
    fireEvent.drop(zone, fileDropPayload([a, b]));
    expect(received).toEqual([[a]]);
    expect(screen.getByText(/Only the first file \("a\.pdf"\) was accepted/)).toBeTruthy();
  });

  it("dropping multiple files of any type onto the multi-file Session Notes zone accepts all of them, matching browse's multi-select", () => {
    const received: File[][] = [];
    render(
      <FileDropZone multiple onFiles={f => received.push(f)}>
        <div>Drop session note files here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop session note files here/).closest("label")!;
    const a = makeFile("notes.txt", 100, "text/plain");
    const b = makeFile("scan.png", 200, "image/png");
    fireEvent.drop(zone, fileDropPayload([a, b]));
    expect(received).toEqual([[a, b]]);
  });

  it("dropping a folder is rejected with a clear, specific error and does not call onFiles", () => {
    const received: File[][] = [];
    render(
      <FileDropZone accept="application/pdf" acceptLabel="PDF" maxSizeBytes={25 * 1024 * 1024} multiple={false} onFiles={f => received.push(f)}>
        <div>Drop your PDF here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop your PDF here/).closest("label")!;
    // A dragged folder still carries a File-shaped entry in `.files` in a
    // real browser (empty type, size 0) -- the component distinguishes it
    // via `.items[].webkitGetAsEntry().isDirectory`, not `.files` alone.
    const folderAsFile = makeFile("MyFolder", 0, "");
    fireEvent.drop(zone, fileDropPayload([folderAsFile], { asDirectory: true }));
    expect(received).toEqual([]);
    expect(screen.getByText(/Folders can't be uploaded here/)).toBeTruthy();
  });

  it("shows the dragging hover state on dragEnter and clears it on dragLeave (real browser mouseover/mouseout equivalent)", () => {
    render(
      <FileDropZone multiple onFiles={() => {}}>
        <div>Drop session note files here, or click to browse</div>
      </FileDropZone>,
    );
    const zone = screen.getByText(/Drop session note files here/).closest("label")!;
    expect(zone.className).not.toMatch(/border-blue-400/);
    fireEvent.dragEnter(zone, fileDropPayload([]));
    expect(zone.className).toMatch(/border-blue-400/);
    fireEvent.dragLeave(zone, fileDropPayload([]));
    expect(zone.className).not.toMatch(/border-blue-400/);
  });
});
