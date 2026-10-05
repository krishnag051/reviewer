// Real HTTP client against the real backend (Round 41, Stage 1). This is
// the ONLY module in the frontend that knows the backend's actual route
// shapes -- everything else goes through the typed functions below, not
// raw fetch calls. Types here are hand-mirrored from the backend's
// Pydantic response models (app/routers/*.py) -- kept in sync by reading
// those files directly, not guessed at.
//
// Auth is a Bearer token in the Authorization header (never cookies), read
// from/written to localStorage by auth-context.tsx -- this module never
// touches storage itself, it just accepts a token getter and reports 401s
// upward so the auth layer can react (clear the stale token, redirect to
// login) instead of every caller having to special-case it.

// Deployment round: backend routes now live under /api (every route moved,
// no un-prefixed fallback kept on the backend side) -- this dev-mode
// default was still the pre-/api-prefix value, which would 404 every real
// request against the new backend unless VITE_API_BASE_URL is set
// explicitly. Production is unaffected (its own VITE_API_BASE_URL is
// baked in at build time as https://tp.masterfaster.org/api already).
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

let getToken: () => string | null = () => null;
let onUnauthorized: () => void = () => {};

/** Wired once from auth-context.tsx at app startup -- lets this module read
 * the current token and react to a 401 without importing React/context
 * itself (keeps this a plain, testable fetch layer). */
export function configureApiClient(opts: { getToken: () => string | null; onUnauthorized: () => void }) {
  getToken = opts.getToken;
  onUnauthorized = opts.onUnauthorized;
}

async function request<T>(
  path: string,
  init?: RequestInit & { skipAuth?: boolean },
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!init?.skipAuth) {
    const token = getToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const resp = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });

  if (resp.status === 401 && !init?.skipAuth) {
    onUnauthorized();
  }

  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { /* non-JSON error body, ignore */ }
    const message =
      (body && typeof body === "object" && "detail" in body
        ? typeof (body as { detail: unknown }).detail === "string"
          ? (body as { detail: string }).detail
          : JSON.stringify((body as { detail: unknown }).detail)
        : `${resp.status} ${resp.statusText}`);
    throw new ApiError(resp.status, body, message);
  }

  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

// --- Auth -----------------------------------------------------------

export type Role = "admin" | "user" | "developer";

export type Me = {
  id: string;
  name: string;
  email: string;
  role: Role;
  credential_title: string | null;
  created_at: string;
};

export async function login(email: string, password: string): Promise<{ access_token: string; token_type: string }> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);
  return request("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
    skipAuth: true,
  });
}

export async function getMe(): Promise<Me> {
  return request("/auth/me");
}

// --- Patients ---------------------------------------------------------

export type PatientListItem = {
  id: string;
  reference_id: string;
  name: string;
  payor: string | null;
  latest_version_number: number | null;
  score: number | null;
  audit_result: string | null;
  reviewed: boolean | null;
  active: boolean;
};

// Part 6, Fix Round: "active" (default -- every existing caller's own
// expectation of "the patient list" unchanged) / "archived" (the dedicated
// deactivated view) / "all" (the single-patient review page, which must
// still find and render a deactivated patient's own page).
export type PatientStatusFilter = "active" | "archived" | "all";

export async function listPatients(statusFilter: PatientStatusFilter = "active"): Promise<PatientListItem[]> {
  return request(`/patients?status_filter=${statusFilter}`);
}

// --- Reports (Round 74: Dashboard's real data, not tp-mock.ts) --------

export type WeeklyVolumeEntry = {
  week_start: string;
  pass_count: number;
  fail_count: number;
};

export type PerReviewerEntry = {
  reviewer_id: string | null;
  reviewer_name: string | null;
  processed: number;
  passed: number;
  failed: number;
  pass_rate: number;
};

export type OverviewOut = {
  range: string;
  processed: number;
  passed: number;
  failed: number;
  passed_pct: number;
  failed_pct: number;
  // Fix Round (2026-09-11), item Reports: these two fields were always
  // returned by the real backend endpoint (app/routers/reports.py's own
  // OverviewOut) but never declared here -- confirmed real cause of why
  // reports.tsx never consumed them and fell back to tp-mock.ts instead.
  weekly_volume: WeeklyVolumeEntry[];
  per_reviewer: PerReviewerEntry[];
};

export async function getReportsOverview(
  range: "week" | "lastweek" | "30d" | "all" | "custom" = "all",
  start?: string,
  end?: string,
): Promise<OverviewOut> {
  const params = new URLSearchParams({ range });
  if (range === "custom" && start && end) {
    params.set("start", start);
    params.set("end", end);
  }
  return request(`/reports/overview?${params.toString()}`);
}

export type TrendsRow = {
  row_key: string;
  row_label: string;
  cells: Record<string, number>;
  average: number | null;
};

export type TrendsOut = {
  group_by: string;
  rows: TrendsRow[];
};

export async function getReportsTrends(groupBy: "provider" | "questionset"): Promise<TrendsOut> {
  return request(`/reports/trends?group_by=${groupBy}`);
}

export type RecentActivityItem = {
  upload_id: string;
  patient_name: string;
  reference_id: string;
  version_number: number;
  upload_number: number;
  status: string;
  is_final: boolean;
  reviewer_name: string | null;
  audit_result: string | null;
  score: number | null;
  created_at: string;
};

export async function getRecentActivity(limit = 10): Promise<RecentActivityItem[]> {
  return request(`/reports/recent-activity?limit=${limit}`);
}

export type PatientOut = {
  id: string;
  reference_id: string;
  name: string;
  payor: string | null;
  created_at: string;
  active: boolean;
  deactivated_at: string | null;
};

// Part 6, Fix Round: reversible deactivate/archive -- never a hard delete.
export async function deactivatePatient(patientId: string): Promise<PatientOut> {
  return request(`/patients/${patientId}/deactivate`, { method: "POST" });
}

export async function reactivatePatient(patientId: string): Promise<PatientOut> {
  return request(`/patients/${patientId}/reactivate`, { method: "POST" });
}

export async function createPatient(body: { reference_id: string; name: string; payor?: string | null }): Promise<PatientOut> {
  return request("/patients", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Versions -----------------------------------------------------------

export type VersionOut = {
  id: string;
  patient_id: string;
  version_number: number;
  payor: string | null;
  reviewer_id: string | null;
  assessment_date: string | null;
  status: "in_progress" | "finalized";
  final_upload_id: string | null;
  score: number | null;
  audit_result: string | null;
  finalized_at: string | null;
  reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
};

export type UploadOut = {
  id: string;
  version_id: string;
  upload_number: number;
  is_final: boolean;
  voided: boolean;
  status: "processing" | "ready" | "error";
  error_detail: string | null;
  rules_snapshot_id: string | null;
  created_at: string;
};

export type VersionDetailOut = VersionOut & { uploads: UploadOut[] };

export async function listPatientVersions(patientId: string): Promise<VersionOut[]> {
  return request(`/patients/${patientId}/versions`);
}

export async function getVersion(versionId: string): Promise<VersionDetailOut> {
  return request(`/versions/${versionId}`);
}

export async function createVersion(
  patientId: string,
  body: { payor?: string | null; assessment_date?: string | null } = {},
): Promise<VersionOut> {
  return request(`/patients/${patientId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// Fix Round (Full Rule-by-Rule Fix List), Item 17: real production
// incident -- a version's payor set wrong at creation had no way to be
// corrected short of archiving the whole upload. Blocked with a 409 by
// the backend once the version is finalized (see
// backend/app/routers/versions.py::update_version).
export async function updateVersion(
  versionId: string,
  body: { reviewer_id?: string | null; assessment_date?: string | null; payor?: string | null },
): Promise<VersionOut> {
  return request(`/versions/${versionId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Uploads / rule_results ----------------------------------------------

export type RuleResultOut = {
  id: string;
  rule_id: string;
  rule_version_used: number;
  final_status: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
  final_finding: string;
  final_pages: number[];
  is_overridden: boolean;
  updated_at: string;
  // Round 70: real, human-readable content for the results panel --
  // question_text/category/rule_code, version-pinned to rule_version_used
  // (see backend app/db/models.py::RuleResult's own docstring). Never a
  // bare rule_id UUID shown to a user again.
  question_text: string;
  category: string;
  rule_code: string;
  // The model layer's own original answer -- shown alongside final_* so a
  // reviewer can see what the AI actually said, distinct from any human
  // override. Never itself writable from this API.
  model_status: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
  model_finding: string;
  model_pages: number[];
  // Next Round, Part 2: the pre-humanize "raw" text, alongside
  // model_finding (now the humanized text shown everywhere else). Only
  // populated for a rule_result created after the humanize pass was wired
  // in -- null for anything older. Display-only, same as model_finding.
  model_finding_raw: string | null;
};

export type UploadDetailOut = UploadOut & {
  rule_results: RuleResultOut[];
  // Round 57: reuses the same 5-field shape as IntakeAnswers (api-client.ts
  // above) -- null for a "document"-mode upload (past or present), which
  // is exactly the per-upload signal the review page uses to decide
  // "Intake Q&A" vs. "Helping Document" button behavior.
  intake_answers: IntakeAnswers | null;
  // Round 70, Item 2: {"physical_page_number": "printed_label"} for pages
  // where the document's OWN printed label was found -- see backend
  // app/services/page_labels.py. Display/cross-check only; page-jump
  // navigation itself always targets the physical page number.
  page_label_map: Record<string, string>;
  // Next Round (2026-08-27), Part 2 item 2: whether THIS upload has a
  // prior-TP file attached -- optional on every upload (unlike
  // supporting_document, always present under "document" mode), so the
  // frontend needs a real presence flag to decide whether to show the
  // "Previous TP" button at all.
  has_previous_tp: boolean;
};

export async function getUpload(uploadId: string): Promise<UploadDetailOut> {
  return request(`/uploads/${uploadId}`);
}

/** Extracts a human-readable message from an ApiError -- the backend's 409s
 * (stale_update, upload_already_finalized, not_ready, sibling_already_final,
 * uncertain_results_remain, reference_id_mismatch, already_finalized,
 * voided) all send `detail: {error, message}`, not a plain string, so the
 * generic ApiError.message (JSON.stringify of that object) isn't fit to
 * show a user directly -- this pulls the real `message` field out instead. */
export function apiErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = err.body && typeof err.body === "object" ? (err.body as { detail?: unknown }).detail : undefined;
    if (detail && typeof detail === "object" && "message" in detail && typeof (detail as { message: unknown }).message === "string") {
      return (detail as { message: string }).message;
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong.";
}

// --- Rule result overrides (Stage 3) -------------------------------------

export type RuleResultPatchOut = {
  id: string;
  upload_id: string;
  rule_id: string;
  rule_version_used: number;
  final_status: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
  final_finding: string;
  final_pages: number[];
  is_overridden: boolean;
  last_edited_by: string | null;
  last_edited_at: string | null;
  updated_at: string;
  question_text: string;
  category: string;
  rule_code: string;
  model_status: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
  model_finding: string;
  model_pages: number[];
  model_finding_raw: string | null;
};

export async function overrideRuleResult(
  ruleResultId: string,
  body: {
    updated_at: string;
    final_status?: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
    final_finding?: string;
    final_pages?: number[];
    reason?: string;
  },
): Promise<RuleResultPatchOut> {
  return request(`/rule_results/${ruleResultId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Escalation / correction email (Round 70, Item 5; real send Fix Round item 3) ---

/** POST /versions/:id/correction-email -- generates AND PERSISTS a real
 * GeneratedEmail row (subject/body built from this upload's CURRENT
 * rule_results at the moment this is called, filtered/ordered by
 * `statuses`). Does not send anything by itself -- see sendGeneratedEmail
 * below. Calling this again immediately before sending (rather than
 * reusing an earlier-generated row) is what makes the eventual send
 * reflect any override made up to that exact moment. */
export type RuleResultStatus = "pass" | "fail" | "uncertain" | "na" | "not_checkable";

export type GeneratedEmailOut = {
  id: string;
  version_id: string;
  upload_id: string;
  generated_by: string | null;
  to_addr: string | null;
  cc: string | null;
  bcc: string | null;
  subject: string;
  body: string;
  routed_to: "bcba" | "qa" | "clinical_director" | "coordinator";
  routed_by: string | null;
  routed_at: string;
  created_at: string;
  statuses: RuleResultStatus[];
  sent_at: string | null;
  send_error: string | null;
};

export async function generateCorrectionEmail(
  versionId: string,
  body: {
    upload_id?: string;
    routed_to: "bcba" | "qa" | "clinical_director" | "coordinator";
    statuses: RuleResultStatus[];
    to_addr?: string | null;
    cc?: string | null;
    bcc?: string | null;
  },
): Promise<GeneratedEmailOut> {
  return request(`/versions/${versionId}/correction-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** POST /versions/:id/correction-email/:email_id/send -- real SMTP send
 * (see backend/app/services/mailer.py) of the exact draft `email_id`
 * refers to, with the treatment plan (and, if present on this upload,
 * the supporting document / session notes / intake Q&A) auto-attached.
 * Throws (via ApiError) on any real send failure -- callers must not
 * treat a resolved promise from generateCorrectionEmail as "sent"; only
 * a resolved promise from THIS function means it actually went out. */
export async function sendGeneratedEmail(versionId: string, emailId: string): Promise<GeneratedEmailOut> {
  return request(`/versions/${versionId}/correction-email/${emailId}/send`, { method: "POST" });
}

// --- Finalize (Stage 3) --------------------------------------------------

export async function finalizeUpload(uploadId: string, referenceId: string): Promise<UploadDetailOut> {
  return request(`/uploads/${uploadId}/finalize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reference_id: referenceId }),
  });
}

/** Fetches the upload's real stored PDF as a Blob from GET /uploads/:id/file
 * -- can't use `request()` above (that always assumes a JSON body / parses
 * `detail` out of error responses) since this is a raw binary response, and
 * can't be loaded via a plain `<iframe src="...">`/`<embed src="...">` either
 * since neither sends the Authorization header — callers turn this into an
 * object URL (see PdfViewer.tsx) instead. */
export async function fetchUploadFileBlob(uploadId: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE_URL}/uploads/${uploadId}/file`, { headers });

  if (resp.status === 401) onUnauthorized();

  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { /* non-JSON error body, ignore */ }
    const message =
      body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(resp.status, body, message);
  }

  return resp.blob();
}

/** Round 51 -- mirrors fetchUploadFileBlob above exactly, for the mandatory
 * second ("supporting document") file. Same auth-header-via-fetch reason:
 * a plain `<a href>`/`window.open(url)` can't send the Bearer token, so
 * callers (see upload-detail UI's "Helping Document" button) fetch this
 * blob first and open an object URL in a new tab instead. */
export async function fetchUploadSupportingFileBlob(uploadId: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE_URL}/uploads/${uploadId}/supporting-file`, { headers });

  if (resp.status === 401) onUnauthorized();

  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { /* non-JSON error body, ignore */ }
    const message =
      body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(resp.status, body, message);
  }

  return resp.blob();
}

/** Next Round (2026-08-27), Part 2 item 2 -- mirrors
 * fetchUploadSupportingFileBlob above exactly, for the new OPTIONAL prior-TP
 * slot. */
export async function fetchUploadPreviousTpFileBlob(uploadId: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE_URL}/uploads/${uploadId}/previous-tp-file`, { headers });

  if (resp.status === 401) onUnauthorized();

  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { /* non-JSON error body, ignore */ }
    const message =
      body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(resp.status, body, message);
  }

  return resp.blob();
}

/** Round 56: the 5 structured Q&A answers -- see backend's
 * UploadIntakeAnswers. Kept as exactly these 5 named fields, matching the
 * backend Form fields 1:1 -- no generic dict, so a typo/rename 422s
 * clearly instead of silently vanishing. */
export type IntakeAnswers = {
  client_insurance: string;
  bcba_name_credentials_npi: string;
  authorization_dates: string;
  pos_schedule_vs_97153_hours: string;
  hours_requesting: string;
};

/** Round 56: `document` (Rounds 51-55's free-form supporting document + AI
 * extraction) vs. `structured_form` (the 5-question form + session notes
 * this round adds) -- exactly one of createUpload's two payload shapes
 * below is required, based on which mode is currently active. */
export async function createUpload(
  versionId: string,
  file: File,
  payload: { supportingDocument: File } | { intakeAnswers: IntakeAnswers; sessionNotes: File[] },
  // Next Round (2026-08-27), Part 2 item 2: the new, OPTIONAL "prior
  // Treatment Plan" file -- independent of which payload shape above is
  // active (document vs. structured_form), so it's its own separate
  // param rather than a third payload variant. Omit entirely (undefined)
  // for the common case of no prior TP to attach.
  previousTp?: File,
): Promise<UploadOut> {
  const formData = new FormData();
  formData.append("file", file);
  if ("supportingDocument" in payload) {
    formData.append("supporting_document", payload.supportingDocument);
  } else {
    for (const [key, value] of Object.entries(payload.intakeAnswers)) formData.append(key, value);
    for (const note of payload.sessionNotes) formData.append("session_notes", note);
  }
  if (previousTp) formData.append("previous_tp", previousTp);
  return request(`/versions/${versionId}/uploads`, { method: "POST", body: formData });
}

/** Round 56, Item 2's "editable across versions" prefill source -- null
 * when this patient has no prior structured-mode upload yet. */
export async function getLatestIntakeAnswers(patientId: string): Promise<IntakeAnswers | null> {
  return request(`/patients/${patientId}/latest-intake-answers`);
}

// --- Session notes (Round 56, Item 3/4) -----------------------------------

export type SessionNoteFileOut = {
  id: string;
  original_filename: string;
  created_at: string;
};

// Round 57, Item 2: wraps the file list with which patient this upload
// actually belongs to -- previously the page had no way to show this
// except unreliably inferring it from filename text.
export type SessionNotesPageOut = {
  patient_name: string;
  patient_reference_id: string;
  files: SessionNoteFileOut[];
};

export async function listSessionNotes(uploadId: string): Promise<SessionNotesPageOut> {
  return request(`/uploads/${uploadId}/session-notes`);
}

/** Mirrors fetchUploadSupportingFileBlob's auth-header-via-fetch reason --
 * a plain `<a href>` can't send the Bearer token. */
export async function fetchSessionNoteFileBlob(uploadId: string, fileId: string): Promise<Blob> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE_URL}/uploads/${uploadId}/session-notes/${fileId}`, { headers });
  if (resp.status === 401) onUnauthorized();
  if (!resp.ok) {
    let body: unknown = null;
    try { body = await resp.json(); } catch { /* non-JSON error body, ignore */ }
    const message =
      body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
        ? (body as { detail: string }).detail
        : `${resp.status} ${resp.statusText}`;
    throw new ApiError(resp.status, body, message);
  }
  return resp.blob();
}

// Round 79, Item 2: real extracted fields for a session-note file --
// straight from agent-making's own Round 59 extraction step
// (app.agent_client.extract_session_note), not re-derived here.
export type SessionNoteExtractionField = {
  value: string | null;
  confidence: "none" | "low" | "medium" | "high";
  source_quote: string | null;
};

export type SessionNoteExtractionOut = {
  session_date: SessionNoteExtractionField;
  session_location: SessionNoteExtractionField;
  clinician_telehealth_location: SessionNoteExtractionField;
  patient_telehealth_location: SessionNoteExtractionField;
  assessment_activity: SessionNoteExtractionField;
};

export async function getSessionNoteExtraction(uploadId: string, fileId: string): Promise<SessionNoteExtractionOut> {
  return request(`/uploads/${uploadId}/session-notes/${fileId}/extraction`);
}

// --- App config (Round 56, Item 1's feature flag) --------------------------

export type SupportingDocMode = "document" | "structured_form";

export type AppConfigOut = {
  id: string;
  supporting_doc_mode: SupportingDocMode;
  retention_days: number;
  // Deployment round: real outbound-email defaults -- see
  // backend/app/routers/admin.py's own AppConfigOut for the exact same
  // shape. null for the 3 string fields means genuinely unset in the DB
  // (never defaulted client-side to some placeholder string).
  notif_from_name: string | null;
  notif_from_address: string | null;
  notif_default_cc: string | null;
  // Real column, but nothing else in the backend reads it yet to gate
  // actual auto-send behavior -- see set_notification_settings' own
  // docstring. Persisting/loading it here is still real (survives a
  // reload), just doesn't yet drive any send behavior on its own.
  auto_send: boolean;
};

export async function getAppConfig(): Promise<AppConfigOut> {
  return request("/admin/app-config");
}

export async function setSupportingDocMode(mode: SupportingDocMode): Promise<AppConfigOut> {
  return request("/admin/app-config", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ supporting_doc_mode: mode }),
  });
}

export type NotificationSettingsUpdate = {
  notif_from_name?: string | null;
  notif_from_address?: string | null;
  notif_default_cc?: string | null;
  auto_send?: boolean | null;
};

export async function setNotificationSettings(body: NotificationSettingsUpdate): Promise<AppConfigOut> {
  return request("/admin/app-config/notifications", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Dev-only (Round 49) -- POST /versions/:id/uploads/simulate. Never calls
 * the real agent; requires the developer role AND the backend's
 * ALLOW_SIMULATED_COMPLETION flag (404s otherwise). See upload.tsx's own
 * comment for why this can't be reached from the normal review workflow. */
export async function createSimulatedUpload(versionId: string, file: File): Promise<UploadOut> {
  const formData = new FormData();
  formData.append("file", file);
  return request(`/versions/${versionId}/uploads/simulate`, { method: "POST", body: formData });
}

// --- Admin (user provisioning) -------------------------------------------

export async function createUser(body: {
  name: string; email: string; password: string; role: Role; credential_title?: string | null;
}): Promise<Me> {
  return request("/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Rules Studio (Round 50) -----------------------------------------------
//
// GET /rules is readable by any authenticated role; every mutating route
// (POST/PATCH/deactivate/reactivate) is admin-gated on the backend
// independent of anything this client does -- a non-admin's mutation
// attempt gets a real 403, this is not just a UI-side restriction.
//
// IMPORTANT, and surfaced in the Rules Studio UI itself: every field below
// is real, persisted metadata (category, question_set, question_text,
// rule_type, payor, active) -- but none of it feeds the real rule-checking
// agent. agent-making loads its own rules.json directly off disk; the
// backend's rule_code is used only as a lookup key to match agent-making's
// findings back onto these rows AFTER the real review already ran. Editing
// a rule here never changes what the agent actually checks.

export type RuleType = "structural" | "semantic" | "cross_reference";

// Fix Round 15 (2026-10-05): "New York Medicaid" removed -- consolidated
// into "Straight Medicaid" (not a distinct payor). See tp-mock.ts's PAYORS.
export type RulePayor =
  | "Aetna" | "Anthem" | "Cigna" | "Emblem" | "Empire" | "Healthfirst" | "Molina"
  | "MVP" | "Straight Medicaid";

export type RuleOut = {
  id: string;
  rule_code: string;
  category: string;
  question_set: string;
  question_text: string;
  rule_type: RuleType;
  payor: RulePayor | null;
  active: boolean;
  current_version: number;
  // Round 56: metadata only -- see backend's Rule.session_notes_only/
  // tp_section docstring. Never fed into any comparison logic anywhere.
  session_notes_only: boolean;
  tp_section: string | null;
};

export async function listRules(): Promise<RuleOut[]> {
  return request("/rules");
}

export async function createRule(body: {
  rule_code: string;
  category: string;
  question_set: string;
  question_text: string;
  rule_type: RuleType;
  payor?: RulePayor | null;
  active?: boolean;
}): Promise<RuleOut> {
  return request("/rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateRule(
  ruleId: string,
  body: Partial<{
    category: string; question_set: string; question_text: string; rule_type: RuleType; payor: RulePayor | null;
    session_notes_only: boolean; tp_section: string | null;
  }>,
): Promise<RuleOut> {
  return request(`/rules/${ruleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function setRuleActive(ruleId: string, active: boolean): Promise<RuleOut> {
  return request(`/rules/${ruleId}/${active ? "reactivate" : "deactivate"}`, { method: "POST" });
}
