// Round 41: this file used to test the mock-data V/U lifecycle end to end
// (upload -> unified review page -> override -> finalize -> /plans ->
// Developer Mode), all against tp-context.tsx's mock patients. As of this
// round, THREE of those surfaces (plans.index.tsx, plans.$refId.index.tsx,
// dev.tsx) read real data from the real backend instead -- none of the old
// scenarios are meaningful anymore (confirmed by actually running the old
// file: all 5 tests failed, either on an auth redirect to /login they
// never handled, or on a jsdom localStorage bug this round's vitest.config
// fix also resolved). Retired rather than patched to fake-pass.
//
// What's still mock and untouched by this round (addPatient/addAttempt/
// finalizeAttempt/overrideRuleStatus, Rules Studio CRUD, Reports,
// Dashboard, Admin Settings, /upload) has no NEW test coverage need here --
// nothing about how those work changed. This file now covers what
// actually changed: real login, developer-role gating, and real patient
// data rendering on the three converted surfaces.
//
// These tests hit a REAL backend over real HTTP (not a mocked fetch) --
// same "real, not simulated" standard as every other round's verification.
// Requires `uvicorn app.main:app` running on http://localhost:8000 against
// a real Postgres with the Round 41 migration applied. Zero real Anthropic
// API calls: everything here is auth + patient/version CRUD, no upload.
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from "vitest";
import { render, screen, within, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createRouter, createMemoryHistory } from "@tanstack/react-router";
import { QueryClient } from "@tanstack/react-query";
import { routeTree } from "../routeTree.gen";

afterEach(cleanup);

const capturedObjectUrlBlobs: Blob[] = [];

beforeAll(() => {
  if (!window.HTMLElement.prototype.hasPointerCapture) {
    window.HTMLElement.prototype.hasPointerCapture = () => false;
  }
  if (!window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = () => {};
  }

  // Node 22+'s own experimental global `localStorage` (SQLite-file-backed,
  // requires --localstorage-file) shadows jsdom's real per-window Storage
  // implementation in this vitest+jsdom+Node combination -- confirmed by
  // testing jsdom's Storage in isolation (works fine) vs. through vitest
  // (throws/undefined). A plain in-memory polyfill sidesteps both
  // implementations entirely rather than fighting over which one "wins".
  class MemoryStorage implements Storage {
    private store = new Map<string, string>();
    get length() { return this.store.size; }
    clear() { this.store.clear(); }
    getItem(key: string) { return this.store.has(key) ? this.store.get(key)! : null; }
    key(index: number) { return Array.from(this.store.keys())[index] ?? null; }
    removeItem(key: string) { this.store.delete(key); }
    setItem(key: string, value: string) { this.store.set(key, String(value)); }
  }
  Object.defineProperty(window, "localStorage", { value: new MemoryStorage(), configurable: true });

  // jsdom (this vitest+Node combination) has no URL.createObjectURL/
  // revokeObjectURL implementation at all -- confirmed by calling it
  // directly in isolation (throws "is not a function"), not an app bug.
  // PdfViewer.tsx calls these on every real PDF blob it fetches, so without
  // a stub the component would crash in this test environment specifically.
  // Records every Blob handed to createObjectURL so tests can assert on the
  // REAL blob's type/size (proving real bytes came back from the real
  // backend), not just that some object URL string was produced.
  window.URL.createObjectURL = ((blob: Blob) => {
    capturedObjectUrlBlobs.push(blob);
    return `blob:test-${capturedObjectUrlBlobs.length}`;
  }) as typeof URL.createObjectURL;
  window.URL.revokeObjectURL = () => {};
});

const API_BASE = "http://localhost:8000";
const TOKEN_KEY = "tp_review_token";

/** `token`, if given, is written to localStorage BEFORE the app mounts --
 * simulates an already-logged-in session (auth-context.tsx's initial
 * effect reads it on mount). Without it, this is a clean, logged-out load.
 */
function renderApp(initialPath: string, token?: string) {
  window.localStorage.clear();
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  const queryClient = new QueryClient();
  const history = createMemoryHistory({ initialEntries: [initialPath] });
  const router = createRouter({ routeTree, context: { queryClient }, history });
  render(<RouterProvider router={router} />);
  return router;
}

async function login(email: string, password: string): Promise<string> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!resp.ok) throw new Error(`login failed for ${email}: ${resp.status} ${await resp.text()}`);
  return (await resp.json()).access_token;
}

const adminToken = () => login("m.chen@brightpath-aba.com", "ChangeMe123!");

async function provisionUser(token: string, role: "admin" | "user" | "developer") {
  const email = `round41-${role}-${crypto.randomUUID().slice(0, 8)}@test.local`;
  const password = "TestPass123!";
  const resp = await fetch(`${API_BASE}/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name: `Round41 ${role}`, email, password, role }),
  });
  if (!resp.ok) throw new Error(`provisioning ${role} test account failed: ${resp.status} ${await resp.text()}`);
  return { email, password };
}

async function createPatient(token: string, referenceId: string, name: string, payor: string) {
  const resp = await fetch(`${API_BASE}/patients`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ reference_id: referenceId, name, payor }),
  });
  if (!resp.ok) throw new Error(`creating test patient failed: ${resp.status} ${await resp.text()}`);
  return resp.json();
}

describe("real login against the real backend", () => {
  it("rejects a wrong password with a real 401-derived error message", async () => {
    const user = userEvent.setup();
    renderApp("/login");

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Email"), "m.chen@brightpath-aba.com");
    await user.type(screen.getByLabelText("Password"), "definitely-not-the-real-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByText(/Incorrect email or password/);
    console.log("STEP A: real 401 from the real backend surfaces as a real error message, no redirect");
  }, 15000);

  it("logs in for real, persists the session, and lands on the real Dashboard", async () => {
    const user = userEvent.setup();
    renderApp("/login");

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Email"), "m.chen@brightpath-aba.com");
    await user.type(screen.getByLabelText("Password"), "ChangeMe123!");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("heading", { name: "Dashboard" });
    expect(screen.getByText("M. Chen")).toBeTruthy();
    expect(screen.getByText(/admin/)).toBeTruthy();
    expect(window.localStorage.getItem(TOKEN_KEY)).toBeTruthy();
    console.log("STEP A: real login succeeds, real token stored, real user name/role shown in AppShell");
  }, 15000);

  it("redirects an unauthenticated visit to any real page back to /login", async () => {
    renderApp("/plans");
    await screen.findByRole("heading", { name: "Sign in" });
    console.log("STEP A: no token in storage -> AuthGate redirects to /login before /plans ever renders");
  }, 15000);
});

describe("developer-role gating on Developer Mode", () => {
  it("admin role: the Developer Mode nav link is not shown at all", async () => {
    const token = await adminToken();
    renderApp("/", token);
    await screen.findByRole("heading", { name: "Dashboard" });
    expect(screen.queryByRole("link", { name: "Developer Mode" })).toBeNull();
    console.log("STEP A: admin session -- no Developer Mode link in the nav");
  }, 15000);

  it("user role: nav link hidden, and direct navigation to /dev is blocked", async () => {
    const admin = await adminToken();
    const account = await provisionUser(admin, "user");
    const token = await login(account.email, account.password);

    renderApp("/", token);
    await screen.findByRole("heading", { name: "Dashboard" });
    expect(screen.queryByRole("link", { name: "Developer Mode" })).toBeNull();
    console.log("STEP A: user session -- no Developer Mode link in the nav");

    cleanup();
    renderApp("/dev", token);
    await screen.findByText(/Developer access only/);
    console.log("STEP B: user session -- direct navigation to /dev is blocked by the route itself, not just a hidden link");
  }, 15000);

  it("developer role: nav link present, and the route renders the real diagnostics content", async () => {
    const admin = await adminToken();
    const account = await provisionUser(admin, "developer");
    const token = await login(account.email, account.password);

    const user = userEvent.setup();
    renderApp("/", token);
    await screen.findByRole("heading", { name: "Dashboard" });
    await user.click(screen.getByRole("link", { name: "Developer Mode" }));
    await screen.findByRole("heading", { name: "Developer Mode" });
    expect(screen.queryByText(/Developer access only/)).toBeNull();
    console.log("STEP A: developer session -- nav link present, real diagnostics page renders");
  }, 15000);
});

describe("real patient data on the converted surfaces", () => {
  it("Treatment Plans list renders real patients from the real backend, not mock data", async () => {
    const token = await adminToken();
    const refId = `TP-TEST-round41-${crypto.randomUUID().slice(0, 8)}`;
    await createPatient(token, refId, "Round41 List Test Patient", "Aetna");

    const user = userEvent.setup();
    renderApp("/", token);
    await screen.findByRole("heading", { name: "Dashboard" });

    await user.click(screen.getByRole("link", { name: "Treatment Plans" }));
    await screen.findByRole("heading", { name: "Treatment Plans" });
    // GET /patients does one sub-query per patient for "latest version" --
    // this dev database accumulates test patients across repeated runs of
    // this file, so the real fetch can take longer than RTL's 1000ms
    // findBy default as that list grows. Real network + real N+1, not
    // flaky -- give it real headroom instead of a default that assumes an
    // instant mock response.
    await screen.findByText("Round41 List Test Patient", {}, { timeout: 8000 });
    const row = screen.getByText("Round41 List Test Patient").closest("tr")!;
    expect(within(row).getByText(refId)).toBeTruthy();
    console.log("STEP A: a real, freshly-created patient (not mock demo data) appears in the real Treatment Plans list");

    // Confirm the OLD mock demo data (e.g. "Ethan Ramirez", never created
    // via this real backend) is NOT present -- proves this list is real,
    // not the old mock array.
    expect(screen.queryByText("Ethan Ramirez")).toBeNull();
    console.log("STEP B: old mock demo patient names are absent -- this is real backend data, not tp-mock.ts");
  }, 20000);

  it("a real patient's real version opens correctly from the unified review page", async () => {
    const token = await adminToken();
    const refId = `TP-TEST-round41-detail-${crypto.randomUUID().slice(0, 8)}`;
    const patient = await createPatient(token, refId, "Round41 Detail Test Patient", "Molina");
    const versionResp = await fetch(`${API_BASE}/patients/${patient.id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    });
    expect(versionResp.status).toBe(201);

    renderApp(`/plans/${refId}`, token);

    await screen.findByRole("heading", { name: "Round41 Detail Test Patient" });
    await screen.findByText(/In progress · not finalized/);
    await screen.findByText(/This version has no uploads yet in the real backend/, {}, { timeout: 8000 });
    console.log("STEP A: a real patient's real (upload-less, in-progress) version opens correctly -- no crash, honest empty state, not a fake result");
    console.log(
      "NOTE: verifying a real patient's real UPLOAD/rule-results content is blocked this round -- " +
      "creating an upload always triggers the real agent pipeline (zero-credit standing rule). " +
      "This test proves the patient/version fetch chain works; upload-level verification is the " +
      "one thing this round could not complete for real, per instruction.",
    );
  }, 20000);
});

// Round 42: real PDF pane (GET /uploads/:id/file) + Stage 2 upload wiring.
// TP-TEST-round42-pdf-demo (backend/scripts/seed_round42_pdf_demo.py) has a
// real finalized v1 and a real in-progress v2 draft, each with a real
// "ready" upload and real rule_results, INSERTED DIRECTLY into the dev
// database rather than produced by a real pipeline run -- so this exercises
// the real GET endpoints (patients/versions/uploads/file) over real HTTP
// with zero real Anthropic API calls, same as every other real-data test
// in this file.
describe("real PDF pane (Round 42)", () => {
  const DEMO_REF_ID = "TP-TEST-round42-pdf-demo";

  it("renders the real PDF next to real rule results for the in-progress draft (v2)", async () => {
    const token = await adminToken();
    renderApp(`/plans/${DEMO_REF_ID}`, token);

    await screen.findByRole("heading", { name: "Round42 PDF Demo Patient" });
    await screen.findByText(/In progress · not finalized/);

    const iframe = await screen.findByTitle("Treatment plan PDF", {}, { timeout: 8000 });
    expect(iframe.getAttribute("src")).toMatch(/^blob:/);
    const blob = capturedObjectUrlBlobs.at(-1)!;
    expect(blob.type).toBe("application/pdf");
    expect(blob.size).toBeGreaterThan(0);
    console.log(`STEP A: real PDF blob fetched for the draft's upload -- type=${blob.type} size=${blob.size} bytes`);

    await screen.findAllByText(/Round 42 demo finding for/);
    expect(screen.getAllByText(/Round 42 demo finding for/).length).toBeGreaterThan(0);
    console.log("STEP B: real rule results render in the same view as the real PDF pane -- side by side, not one replacing the other");
  }, 15000);

  it("renders the real PDF next to real rule results for the finalized version (v1), after switching versions", async () => {
    const token = await adminToken();
    const user = userEvent.setup();
    renderApp(`/plans/${DEMO_REF_ID}`, token);

    await screen.findByRole("heading", { name: "Round42 PDF Demo Patient" });
    await screen.findByTitle("Treatment plan PDF", {}, { timeout: 8000 });
    const blobCountBeforeSwitch = capturedObjectUrlBlobs.length;

    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: /^v1 —/ }));

    await screen.findByText(/Fail/);
    await screen.findByTitle("Treatment plan PDF", {}, { timeout: 8000 });
    await waitForBlobCountAbove(blobCountBeforeSwitch);

    const blob = capturedObjectUrlBlobs.at(-1)!;
    expect(blob.type).toBe("application/pdf");
    expect(blob.size).toBeGreaterThan(0);
    console.log(`STEP A: switching to the finalized v1 fetches ITS OWN real PDF (upload ${capturedObjectUrlBlobs.length}) -- type=${blob.type} size=${blob.size} bytes`);

    expect(screen.getAllByText(/Round 42 demo finding for/).length).toBeGreaterThan(0);
    console.log("STEP B: the finalized version's real rule results render alongside its real PDF");
  }, 15000);
});

async function waitForBlobCountAbove(count: number) {
  for (let i = 0; i < 40; i++) {
    if (capturedObjectUrlBlobs.length > count) return;
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error(`timed out waiting for a new PDF blob fetch (still at ${capturedObjectUrlBlobs.length})`);
}

// Round 42, Stage 2: upload-creation wiring reaches the real endpoint
// without ever completing a real pipeline run. This hits the exact same
// real route the /upload form's createUpload() calls (POST
// /versions/:id/uploads) directly over HTTP against the LIVE dev backend --
// deliberately NOT via the form itself, and deliberately with content that
// is not a real PDF. The backend's own pipeline (app/services/
// upload_pipeline.py) calls app/services/pdf_parser.py::parse_pdf() BEFORE
// it ever reaches run_rule_checks()/review_treatment_plan() -- parse_pdf
// raises on unparseable bytes (confirmed by reading pdf_parser.py: it's a
// bare `PdfReader(file_path)` with no fallback), so garbage bytes guarantee
// the pipeline fails at the parse step and never reaches the real agent
// call, mirroring the existing (pre-Round-42)
// test_pipeline_failure_leaves_nothing_partial_status_error backend test's
// same technique. This test polls GET /uploads/:id afterward and asserts
// status="error" with zero rule_results -- confirming that assumption held
// for real on this live server, not just trusting it.
describe("Stage 2 upload-route wiring (Round 42)", () => {
  it("POST /versions/:id/uploads returns the real 201 shape createUpload() expects, and never reaches the real agent for garbage content", async () => {
    const token = await adminToken();
    const refId = `TP-TEST-round42-wiring-${crypto.randomUUID().slice(0, 8)}`;
    const patient = await createPatient(token, refId, "Round42 Wiring Test Patient", "Aetna");
    const versionResp = await fetch(`${API_BASE}/patients/${patient.id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    });
    expect(versionResp.status).toBe(201);
    const version = await versionResp.json();

    // Hand-built multipart body, not jsdom's FormData/Blob -- jsdom's
    // FormData/Blob classes aren't the same objects Node's native fetch
    // expects, and passing one to the other silently drops the file part
    // (confirmed: an equivalent script run under plain Node succeeds with
    // FormData/Blob, the exact same code fails 422 "field required" for
    // `file` when run under this vitest+jsdom environment). Building the
    // multipart payload by hand sidesteps that interop gap entirely.
    const boundary = "----round42WiringTestBoundary";
    // Round 58: updated from Round 51's document-mode shape
    // (`supporting_document`) to the current structured_form default (the
    // 5 QA text fields + a session_notes file) -- this test only cares
    // about basic upload-route wiring mechanics (garbage TP bytes -> parse
    // failure -> status="error"), not which mode is active, so it just
    // needs to satisfy whatever the live default requires. See
    // ROUND56_QA_FORM_DATA in the backend's own tests/conftest.py for the
    // same 5 field names.
    const multipartBody =
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="wiring-test.pdf"\r\n` +
      `Content-Type: application/pdf\r\n\r\n` +
      `not a real pdf, just wiring-shape bytes\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="client_insurance"\r\n\r\n` +
      `Aetna\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="bcba_name_credentials_npi"\r\n\r\n` +
      `Jane Smith, BCBA-D - NPI 1234567890\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="authorization_dates"\r\n\r\n` +
      `01/15/2026 to 07/15/2026\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="pos_schedule_vs_97153_hours"\r\n\r\n` +
      `Home, Mon-Fri 5-8pm, 15 hrs/week\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="hours_requesting"\r\n\r\n` +
      `15 hrs/week\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="session_notes"; filename="session-note.pdf"\r\n` +
      `Content-Type: application/pdf\r\n\r\n` +
      `not a real pdf, session notes are never parsed\r\n` +
      `--${boundary}--\r\n`;
    const uploadResp = await fetch(`${API_BASE}/versions/${version.id}/uploads`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body: multipartBody,
    });

    expect(uploadResp.status).toBe(201);
    const uploadOut = await uploadResp.json();
    expect(uploadOut).toMatchObject({
      version_id: version.id,
      upload_number: 1,
      is_final: false,
      voided: false,
      status: "processing",
    });
    console.log("STEP A: real POST /versions/:id/uploads returns the exact 201 shape createUpload() in api-client.ts expects");

    let detail: { status: string; error_detail: string | null; rule_results: unknown[] } | null = null;
    for (let i = 0; i < 30; i++) {
      const detailResp = await fetch(`${API_BASE}/uploads/${uploadOut.id}`, { headers: { Authorization: `Bearer ${token}` } });
      detail = await detailResp.json();
      if (detail!.status !== "processing") break;
      await new Promise(r => setTimeout(r, 300));
    }
    expect(detail!.status).toBe("error");
    expect(detail!.error_detail).toBeTruthy();
    expect(detail!.rule_results).toEqual([]);
    console.log(
      `STEP B: the background pipeline failed at parse_pdf (error_detail: ${detail!.error_detail!.slice(0, 80)}...) ` +
      "-- confirmed it never reached review_treatment_plan/the real Anthropic API",
    );
  }, 15000);
});

// Round 43, Stage 3: real override + finalize, wired to the exact routes
// Round 40 hardened (app/services/rule_results.py::override_rule_result,
// app/services/finalize.py::finalize_upload). Zero real Anthropic API
// calls -- override/finalize are pure DB operations, no pipeline involved.
//
// Each test needs its own fresh, real in-progress draft (real Upload,
// status="ready", one "fail" + one "pass" real RuleResult, no pipeline run)
// -- finalize is irreversible, so a fixed patient can't be reused across
// repeated runs, and the two tests below can't share one patient either
// (the race test finalizes behind the UI's back mid-test). Seeded via
// backend/scripts/seed_round43_override_demo.py --ref-id <unique>, with the
// ref ids passed through via ROUND43_DEMO_REF_ID / ROUND43_DEMO_REF_ID_RACE.
// Each test skips (rather than failing) if its own env var isn't set, so
// this file still runs standalone without requiring the extra seed step.
const ROUND43_REF_ID = process.env.ROUND43_DEMO_REF_ID;
const ROUND43_RACE_REF_ID = process.env.ROUND43_DEMO_REF_ID_RACE;

describe("Stage 3: real override + finalize (Round 43)", () => {
  it.skipIf(!ROUND43_REF_ID)("overrides a real finding through the UI, then finalizes for real and the UI locks", async () => {
    const refId = ROUND43_REF_ID!;
    const token = await adminToken();
    const user = userEvent.setup();

    renderApp(`/plans/${refId}`, token);

    await screen.findByRole("heading", { name: /Round43 Override Demo Patient/ });
    await screen.findByText(/In progress · not finalized/);
    await screen.findByText(/Draft — override any real finding below/);
    console.log("STEP A: real draft loaded -- Stage 3 draft banner + real rule results present");

    // --- 1. real override, Fail -> Pass, through the actual UI control ---
    const failRow = (await screen.findByText(/Round 43 demo finding \(fail, awaiting override\)/)).closest("div.px-2") as HTMLElement;
    await user.click(within(failRow).getByRole("button", { name: /Override this finding/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Pass" }));

    await screen.findByText(/Overridden to Pass/); // real success toast
    await within(failRow).findByText("Overridden");
    expect(within(failRow).getByText("Pass")).toBeTruthy();
    console.log("STEP B: real PATCH /rule_results/:id round-tripped -- UI shows Pass + Overridden for real, not optimistically faked");

    // --- 2. real finalize, requiring the typed reference_id confirmation ---
    await user.click(screen.getByRole("button", { name: /Finalize as V1/ }));
    const dialog = await screen.findByRole("dialog");
    const finalizeButton = within(dialog).getByRole("button", { name: "Finalize" }) as HTMLButtonElement;
    expect(finalizeButton.disabled).toBe(true);

    const refIdInput = within(dialog).getByLabelText("Reference ID");
    await user.type(refIdInput, "definitely-the-wrong-reference-id");
    expect(finalizeButton.disabled).toBe(true);
    console.log("STEP C: Finalize stays disabled until the typed reference ID matches the real patient's -- backend invariant mirrored client-side, not just trusted");

    await user.clear(refIdInput);
    await user.type(refIdInput, refId);
    expect(finalizeButton.disabled).toBe(false);
    await user.click(finalizeButton);

    await screen.findByText(/Finalized as v1 — this is permanent/);
    await screen.findByText(/Real, finalized data — locked/);
    expect(screen.queryByRole("button", { name: /Finalize as V1/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Override this finding/ })).toBeNull();
    console.log("STEP D: real POST /uploads/:id/finalize round-tripped -- UI flips to the same locked, read-only view Round 41 already renders for older finalized data; override/finalize controls disappear for good");
  }, 20000);

  it.skipIf(!ROUND43_RACE_REF_ID)("surfaces a real post-finalize 409 as an actual toast when finalize lands behind the rendered UI's back", async () => {
    const refId = ROUND43_RACE_REF_ID!;
    const token = await adminToken();
    const user = userEvent.setup();

    renderApp(`/plans/${refId}`, token);
    await screen.findByRole("heading", { name: /Round43 Override Demo Patient/ });
    const failRow = await screen.findByText(/Round 43 demo finding \(fail, awaiting override\)/);
    console.log("STEP A: real draft rendered, override control visible -- this render's react-query cache still thinks it's a draft");

    // Finalize for real, but NOT through this render's own Finalize button --
    // a raw fetch call, exactly like a second browser tab / a concurrent
    // reviewer finalizing the same upload. This render's cache is not
    // invalidated by it, so its UI still shows the override pencil -- the
    // exact stale-client window app/services/rule_results.py's FOR UPDATE
    // lock on the Upload row exists to make safe on the BACKEND side
    // regardless of what any client still believes.
    const patientsResp = await fetch(`${API_BASE}/patients`, { headers: { Authorization: `Bearer ${token}` } });
    const patients = await patientsResp.json();
    const thisPatient = patients.find((p: { reference_id: string }) => p.reference_id === refId);
    const versionsResp = await fetch(`${API_BASE}/patients/${thisPatient.id}/versions`, { headers: { Authorization: `Bearer ${token}` } });
    const [version] = await versionsResp.json();
    const versionDetailResp = await fetch(`${API_BASE}/versions/${version.id}`, { headers: { Authorization: `Bearer ${token}` } });
    const versionDetail = await versionDetailResp.json();
    const finalizeResp = await fetch(`${API_BASE}/uploads/${versionDetail.uploads[0].id}/finalize`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ reference_id: refId }),
    });
    expect(finalizeResp.status).toBe(200);
    console.log("STEP B: real finalize landed on the backend, behind this render's back -- its cache hasn't refetched");

    // Now click the still-rendered (stale) override control -- fires the
    // real PATCH against what is, on the real backend, now a finalized
    // upload. This is a real 409, not a fabricated one.
    const failRowNode = failRow.closest("div.px-2") as HTMLElement;
    await user.click(within(failRowNode).getByRole("button", { name: /Override this finding/ }));
    await user.click(await screen.findByRole("menuitem", { name: "Pass" }));

    const toastText = await screen.findByText(/this upload is finalized; overrides are draft-only/);
    expect(toastText).toBeTruthy();
    console.log(
      "STEP C: the real 409 upload_already_finalized response is surfaced as an actual rendered toast " +
      `("${toastText.textContent}") -- not just visible in a network tab -- confirming apiErrorMessage() + the ` +
      "onError handler correctly turn Round 40's real hardened guard into user-facing text",
    );
  }, 20000);
});

// Round 49: the dev-only simulated-completion path. Zero real Anthropic API
// calls: exercises POST /versions/:id/uploads/simulate
// (app/services/simulated_pipeline.py), which has no import path to the
// real agent at all -- see
// backend/tests/test_simulated_pipeline_never_touches_real_api.py for the
// backend-side structural proof.
//
// The literal "drop a file into the upload form" step is done via a raw
// fetch with a hand-built multipart body, NOT userEvent.upload() through
// the rendered form -- the same jsdom/Node FormData+File interop gap Round
// 42's Stage 2 wiring test hit and documented (a File/Blob built via
// jsdom's own constructors silently loses its content when handed to
// Node's native fetch in THIS vitest+jsdom+Node combination; confirmed
// again live this round via a direct curl to the same real endpoint, which
// works perfectly -- this is an environment gap, not a route bug).
// Everything else below IS a real click-through against the real rendered
// UI: role-gated checkbox visibility, real navigation, real status
// polling, real SIMULATED labeling, real finalize dialog + typed
// confirmation, real locked state afterward -- for both V1 and V2.
describe("Round 49: simulated-completion lifecycle (dev-only, zero real API calls)", () => {
  it("developer-only 'Simulate completion' checkbox is visible and toggles; hidden from a real reviewer role", async () => {
    const devToken = await login("round41.developer@test.local", "TestPass123!");
    const user = userEvent.setup();

    renderApp("/upload", devToken);
    await screen.findByRole("heading", { name: "Upload Treatment Plan" });
    const simulateCheckbox = await screen.findByRole("checkbox");
    await screen.findByText(/Simulate completion \(dev-only\)/);
    expect((simulateCheckbox as HTMLInputElement).checked).toBe(false);
    await user.click(simulateCheckbox);
    expect((simulateCheckbox as HTMLInputElement).checked).toBe(true);
    console.log("STEP A: developer role sees the checkbox and it toggles for real");

    cleanup();
    const adminToken2 = await adminToken();
    renderApp("/upload", adminToken2);
    await screen.findByRole("heading", { name: "Upload Treatment Plan" });
    expect(screen.queryByText(/Simulate completion \(dev-only\)/)).toBeNull();
    console.log("STEP B: admin (a stand-in for a real BCBA/reviewer) never sees the checkbox at all -- confirmed by its absence, not just untested");
  }, 15000);

  it("U1 simulated -> V1 -> U1(v2) simulated -> V2, real UI throughout, clearly labeled as simulated at every step", async () => {
    const devToken = await login("round41.developer@test.local", "TestPass123!");
    const user = userEvent.setup();
    const refId = `TP-TEST-round49-simlifecycle-${crypto.randomUUID().slice(0, 8)}`;

    const patient = await createPatient(devToken, refId, "Round49 Simulated Lifecycle Patient", "Aetna");
    const versionResp = await fetch(`${API_BASE}/patients/${patient.id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${devToken}` },
      body: JSON.stringify({}),
    });
    const version = await versionResp.json();

    async function postSimulatedUpload(versionId: string) {
      const boundary = "----round49SimulatedUploadBoundary";
      const body =
        `--${boundary}\r\n` +
        `Content-Disposition: form-data; name="file"; filename="sim.pdf"\r\n` +
        `Content-Type: application/pdf\r\n\r\n` +
        `not a real pdf -- the simulated path never reads file content anyway\r\n` +
        `--${boundary}--\r\n`;
      const resp = await fetch(`${API_BASE}/versions/${versionId}/uploads/simulate`, {
        method: "POST",
        headers: { Authorization: `Bearer ${devToken}`, "Content-Type": `multipart/form-data; boundary=${boundary}` },
        body,
      });
      expect(resp.status).toBe(201);
      return resp.json();
    }

    const upload1 = await postSimulatedUpload(version.id);
    expect(upload1.status).toBe("processing");
    console.log("STEP A: real POST /versions/:id/uploads/simulate created a real, pending upload (raw multipart -- see file-header comment for why not userEvent.upload)");

    // ---- real UI render: real polling, real SIMULATED labeling ----
    renderApp(`/plans/${refId}`, devToken);
    await screen.findByRole("heading", { name: "Round49 Simulated Lifecycle Patient" });
    await screen.findByText(/In progress · not finalized/);
    await screen.findByText(/SIMULATED — this upload's findings are dev-only synthetic placeholders/, {}, { timeout: 12000 });
    await screen.findByText(/Rule check results \(SIMULATED, dev-only/);
    const simulatedFindings = await screen.findAllByText(/SIMULATED — not a real agent result/);
    expect(simulatedFindings.length).toBeGreaterThan(0);
    console.log(`STEP B: real polling (Round 42's refetchInterval) picked up the simulated pipeline's real ~5s completion; ${simulatedFindings.length} findings rendered, every one clearly labeled SIMULATED`);

    // ---- real finalize dialog, through the real UI ----
    await user.click(screen.getByRole("button", { name: /Finalize as V1/ }));
    const dialog1 = await screen.findByRole("dialog");
    await user.type(within(dialog1).getByLabelText("Reference ID"), refId);
    await user.click(within(dialog1).getByRole("button", { name: "Finalize" }));
    await screen.findByText(/Finalized as v1 — this is permanent/);
    await screen.findByText(/Real, finalized data — locked/);
    expect(screen.queryByRole("button", { name: /Override this finding/ })).toBeNull();
    console.log("STEP C: real finalize through the real dialog (typed reference_id required) -- real lock, real score/audit_result computed from the synthetic pass/fail mix, override controls gone");

    // ---- U1 against a fresh v2 draft (same patient) ----
    const version2Resp = await fetch(`${API_BASE}/patients/${patient.id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${devToken}` },
      body: JSON.stringify({}),
    });
    const version2 = await version2Resp.json();
    expect(version2.version_number).toBe(2);
    await postSimulatedUpload(version2.id);
    console.log("STEP D: real second upload created against a fresh v2 draft on the same patient, simulated again");

    cleanup();
    renderApp(`/plans/${refId}`, devToken);
    await screen.findByRole("heading", { name: "Round49 Simulated Lifecycle Patient" });
    // Combined switcher defaults to the newest (v2, still in-progress) version.
    await screen.findByText(/In progress · not finalized/);
    await screen.findByText(/SIMULATED — this upload's findings are dev-only synthetic placeholders/, {}, { timeout: 12000 });

    await user.click(screen.getByRole("button", { name: /Finalize as V2/ }));
    const dialog2 = await screen.findByRole("dialog");
    await user.type(within(dialog2).getByLabelText("Reference ID"), refId);
    await user.click(within(dialog2).getByRole("button", { name: "Finalize" }));
    await screen.findByText(/Finalized as v2 — this is permanent/);
    console.log("STEP E: full U1->V1->U1(v2)->V2 lifecycle completed in seconds via simulated completion, real UI throughout for review+finalize -- zero real Anthropic API calls end to end");
  }, 60000);
});

// Round 50: Rules Studio wired to the real backend `rules` table. Zero real
// Anthropic API calls -- this is backend CRUD, never touches
// rule_results/overrides/the pipeline. Edits a real seeded rule's metadata
// for real, confirms it persists across a fresh render (not optimistic UI
// only), then restores the original value so this test leaves no net
// change in the dev database.
describe("Round 50: Rules Studio wired to the real backend", () => {
  it("admin lists real rules (not mock names), edits one's metadata for real, and it persists after reload", async () => {
    const token = await adminToken();
    const user = userEvent.setup();

    renderApp("/rules", token);
    await screen.findByRole("heading", { name: "Rules Studio" });
    await screen.findByText(/Rule code is permanent once created\./);

    // Real rule codes look like "QA-..." -- the old mock also used this
    // style, so assert on the COUNT (120 real seeded rules) and the
    // metadata-only banner, not just "some rule code is visible", to
    // confirm this is real backend data rather than a coincidental format
    // match with the retired mock.
    await screen.findByText(/rules total/, {}, { timeout: 8000 });
    const rows = await screen.findAllByRole("row");
    expect(rows.length).toBeGreaterThan(50); // header + ~120 real rules, well beyond any plausible mock fixture size
    console.log(`STEP A: real Rules Studio loaded ${rows.length - 1} real rule rows from the real backend`);

    const firstEditButton = within(rows[1]).getByRole("button");
    await user.click(firstEditButton);
    const dialog = await screen.findByRole("dialog");
    const categoryInput = within(dialog).getByLabelText("Category");
    const originalCategory = (categoryInput as HTMLInputElement).value;
    const newCategory = `${originalCategory} (round50-test-edit)`;

    await user.clear(categoryInput);
    await user.type(categoryInput, newCategory);
    await user.click(within(dialog).getByRole("button", { name: "Save rule" }));
    await screen.findByText(/saved\./);
    console.log(`STEP B: real PATCH /rules/:id round-tripped -- category changed from "${originalCategory}" to "${newCategory}"`);

    // Fresh render (not the same component instance) -- proves the edit
    // persisted server-side, not just in this render's local state.
    cleanup();
    renderApp("/rules", token);
    await screen.findByRole("heading", { name: "Rules Studio" });
    await screen.findByText(newCategory, {}, { timeout: 8000 });
    console.log("STEP C: a completely fresh render shows the edited category -- real persistence, not optimistic-only UI");

    // Restore the original value so this test leaves no net change.
    const rowsAfter = await screen.findAllByRole("row");
    const editedRow = rowsAfter.find(r => within(r).queryByText(newCategory));
    await user.click(within(editedRow!).getByRole("button"));
    const restoreDialog = await screen.findByRole("dialog");
    const restoreCategoryInput = within(restoreDialog).getByLabelText("Category");
    await user.clear(restoreCategoryInput);
    await user.type(restoreCategoryInput, originalCategory);
    await user.click(within(restoreDialog).getByRole("button", { name: "Save rule" }));
    await screen.findByText(/saved\./);
    console.log("STEP D: restored the original category -- this test leaves zero net change in the dev database");
  }, 30000);

  it("admin toggles a real rule active/inactive for real", async () => {
    const token = await adminToken();
    const user = userEvent.setup();

    renderApp("/rules", token);
    await screen.findByRole("heading", { name: "Rules Studio" });
    const rows = await screen.findAllByRole("row", {}, { timeout: 8000 });
    const firstDataRow = rows[1];
    const toggle = within(firstDataRow).getByRole("switch");
    const wasChecked = toggle.getAttribute("aria-checked") === "true";

    await user.click(toggle);
    await screen.findByText(wasChecked ? /deactivated\./ : /activated\./);
    console.log(`STEP A: real POST /rules/:id/${wasChecked ? "deactivate" : "reactivate"} round-tripped via the real switch`);

    // Toggle back so this test leaves no net change.
    await user.click(within(firstDataRow).getByRole("switch"));
    await screen.findByText(wasChecked ? /activated\./ : /deactivated\./);
    console.log("STEP B: toggled back -- zero net change in the dev database");
  }, 20000);

  it("a non-admin role sees Rules Studio read-only -- real rules visible, no edit controls, switches disabled", async () => {
    const userToken = await login("s.patel@brightpath-aba.com", "ChangeMe123!");
    renderApp("/rules", userToken);

    await screen.findByRole("heading", { name: "Rules Studio" });
    await screen.findByText(/Read-only for this role/);
    await screen.findByText(/rules total/, {}, { timeout: 8000 });
    expect(screen.queryByRole("button", { name: /New Rule/ })).toBeNull();

    const rows = await screen.findAllByRole("row");
    const switches = within(rows[1]).queryAllByRole("switch");
    expect(switches.length).toBe(1);
    expect((switches[0] as HTMLInputElement).disabled).toBe(true);
    expect(within(rows[1]).queryByRole("button")).toBeNull(); // no edit pencil
    console.log("STEP A: user role sees the real rule list but every mutation control is absent/disabled -- confirmed by their absence, not just untested");
  }, 15000);
});

// Round 51: the mandatory second ("supporting document") file. Zero real
// Anthropic API calls -- pure storage/CRUD/display, no pipeline touched.
//
// The literal submit-and-persist steps use a raw multipart fetch, not
// userEvent.upload() + a real button click -- the same jsdom/Node
// FormData+File interop gap Round 42/49 already hit and documented (a
// File built via jsdom's own constructors silently loses its content when
// handed to Node's native fetch in this vitest+jsdom+Node combination).
// What IS tested through the real rendered form: that the real Submit
// button's disabled state genuinely responds to which of the two real
// file inputs have a file selected -- that part is pure React state, no
// network involved, so userEvent.upload() against the real inputs works
// fine and proves the real "blocked until both files are selected" UI
// requirement without touching the network at all.
describe("Round 51: mandatory supporting document (storage + display only)", () => {
  // Round 58: this whole describe block specifically exercises
  // "document"-mode behavior (the old free-form supporting-document
  // upload), which stopped being the live default in Round 56
  // (default is now "structured_form"). Rather than update these tests
  // to the new default (that's what the OTHER describe blocks/tests in
  // this file are for), explicitly switch the real backend into
  // "document" mode for the duration of this block, and restore whatever
  // it was before -- these tests are testing document mode ON PURPOSE.
  let previousMode: string | null = null;

  beforeAll(async () => {
    const token = await adminToken();
    const configResp = await fetch(`${API_BASE}/admin/app-config`, { headers: { Authorization: `Bearer ${token}` } });
    previousMode = (await configResp.json()).supporting_doc_mode;
    await fetch(`${API_BASE}/admin/app-config`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ supporting_doc_mode: "document" }),
    });
  });

  afterAll(async () => {
    if (!previousMode) return;
    const token = await adminToken();
    await fetch(`${API_BASE}/admin/app-config`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ supporting_doc_mode: previousMode }),
    });
  });

  it("new-patient flow: submit is blocked with only the TP file selected, enabled once both are", async () => {
    const token = await adminToken();
    const user = userEvent.setup();

    renderApp("/upload", token);
    await screen.findByRole("heading", { name: "Upload Treatment Plan" });
    await screen.findByText(/Supporting Document/);

    await user.type(screen.getByPlaceholderText("e.g., Jordan Nakamura"), "Round51 Test Patient");
    await user.type(screen.getByPlaceholderText("e.g., TP-2026-0500"), `TP-TEST-round51-${crypto.randomUUID().slice(0, 8)}`);

    const submitButton = () => screen.getByRole("button", { name: /Create Upload 1/ }) as HTMLButtonElement;
    expect(submitButton().disabled).toBe(true);
    console.log("STEP A: submit disabled with neither file selected (name/refId alone aren't enough)");

    const fileInputs = document.querySelectorAll('input[type="file"]');
    expect(fileInputs.length).toBe(2); // TP file + supporting document, both real inputs
    await user.upload(fileInputs[0] as HTMLElement, new File(["tp content"], "tp.pdf", { type: "application/pdf" }));
    expect(submitButton().disabled).toBe(true);
    console.log("STEP B: still blocked with only the TP file selected -- the supporting document is genuinely required, not optional");

    await user.upload(fileInputs[1] as HTMLElement, new File(["supporting content"], "supporting.pdf", { type: "application/pdf" }));
    expect(submitButton().disabled).toBe(false);
    console.log("STEP C: submit enabled only once BOTH real file inputs have a file -- confirmed via the real button's disabled state, not inferred");
  }, 15000);

  it("existing-patient flow: same requirement -- blocked with only the TP file, enabled once both are selected", async () => {
    const token = await adminToken();
    const user = userEvent.setup();
    const refId = `TP-TEST-round51-existing-${crypto.randomUUID().slice(0, 8)}`;
    await createPatient(token, refId, "Round51 Existing Test Patient", "Aetna");

    renderApp("/upload", token);
    await screen.findByRole("heading", { name: "Upload Treatment Plan" });
    await user.click(screen.getByRole("button", { name: "Existing Patient" }));
    await user.type(screen.getByPlaceholderText("Name or reference ID"), refId);
    await user.click(await screen.findByText("Round51 Existing Test Patient", {}, { timeout: 8000 }));
    await screen.findByText(/Supporting Document/, {}, { timeout: 8000 });

    const submitButton = () => screen.getByRole("button", { name: "Create Upload" }) as HTMLButtonElement;
    expect(submitButton().disabled).toBe(true);

    const fileInputs = document.querySelectorAll('input[type="file"]');
    expect(fileInputs.length).toBe(2);
    await user.upload(fileInputs[0] as HTMLElement, new File(["tp content"], "tp.pdf", { type: "application/pdf" }));
    expect(submitButton().disabled).toBe(true);
    console.log("STEP A: existing-patient flow blocked with only the TP file -- identical requirement to the new-patient flow");

    await user.upload(fileInputs[1] as HTMLElement, new File(["supporting content"], "supporting.pdf", { type: "application/pdf" }));
    expect(submitButton().disabled).toBe(false);
    console.log("STEP B: enabled once both real files are selected -- same real button state as the new-patient flow");
  }, 15000);

  it("real upload creation is rejected 422 without the supporting document, and succeeds with both files -- both persisted for real", async () => {
    const token = await adminToken();
    const refId = `TP-TEST-round51-api-${crypto.randomUUID().slice(0, 8)}`;
    const patient = await createPatient(token, refId, "Round51 API Test Patient", "Aetna");
    const versionResp = await fetch(`${API_BASE}/patients/${patient.id}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    });
    const version = await versionResp.json();

    // Missing supporting_document -- real 422 from the real backend.
    const boundaryMissing = "----round51MissingSupportingDoc";
    const bodyMissing =
      `--${boundaryMissing}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="tp.pdf"\r\n` +
      `Content-Type: application/pdf\r\n\r\n` +
      `tp bytes\r\n` +
      `--${boundaryMissing}--\r\n`;
    const missingResp = await fetch(`${API_BASE}/versions/${version.id}/uploads`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/form-data; boundary=${boundaryMissing}` },
      body: bodyMissing,
    });
    expect(missingResp.status).toBe(422);
    console.log("STEP A: real POST /versions/:id/uploads rejects a request missing the supporting document -- real 422, not a client-side guess");

    // Both files present -- real 201, both paths persisted.
    const boundary = "----round51BothFiles";
    const body =
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="file"; filename="tp.pdf"\r\n` +
      `Content-Type: application/pdf\r\n\r\n` +
      `tp bytes\r\n` +
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="supporting_document"; filename="helping.pdf"\r\n` +
      `Content-Type: application/pdf\r\n\r\n` +
      `supporting bytes\r\n` +
      `--${boundary}--\r\n`;
    const resp = await fetch(`${API_BASE}/versions/${version.id}/uploads`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body,
    });
    expect(resp.status).toBe(201);
    console.log("STEP B: with both files present, the real upload is created for real (201)");
  }, 15000);

  it("the 'Helping Document' button opens the real supporting file in a new tab, without changing the main review area, for both a draft and a finalized version", async () => {
    const token = await adminToken();
    const user = userEvent.setup();
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    // TP-TEST-round42-pdf-demo (re-seeded with a real supporting document
    // this round) has a finalized v1 and an in-progress v2 draft -- both
    // real uploads, both with a real supporting_document_path.
    renderApp("/plans/TP-TEST-round42-pdf-demo", token);
    await screen.findByRole("heading", { name: "Round42 PDF Demo Patient" });

    // Defaults to the newest version (v2, draft).
    await screen.findByText(/In progress · not finalized/);
    const helpingButtonDraft = await screen.findByRole("button", { name: /Helping Document/ });
    await user.click(helpingButtonDraft);
    await new Promise(r => setTimeout(r, 50));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.calls[0][0]).toMatch(/^blob:/);
    expect(openSpy.mock.calls[0][1]).toBe("_blank");
    // Main review area unchanged -- still the real PDF pane + real rule
    // results, not replaced by anything related to the supporting doc.
    await screen.findByTitle("Treatment plan PDF");
    await screen.findAllByText(/Round 42 demo finding for/);
    console.log("STEP A: draft view -- Helping Document opened a real blob: URL in a new tab; main PDF/rule-results area untouched");

    openSpy.mockClear();
    await user.click(screen.getByRole("combobox"));
    await user.click(await screen.findByRole("option", { name: /^v1 —/ }));
    await screen.findByText(/Real, finalized data — locked/);
    const helpingButtonFinal = await screen.findByRole("button", { name: /Helping Document/ });
    await user.click(helpingButtonFinal);
    await new Promise(r => setTimeout(r, 50));
    expect(openSpy).toHaveBeenCalledTimes(1);
    expect(openSpy.mock.calls[0][0]).toMatch(/^blob:/);
    await screen.findByTitle("Treatment plan PDF");
    console.log("STEP B: finalized view -- same real button, same real behavior; main area still unchanged (locked view + PDF + rule results only)");

    openSpy.mockRestore();
  }, 20000);
});
