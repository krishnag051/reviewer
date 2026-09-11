// Real-data react-query hooks. Every hook here hits the real backend via
// api-client.ts; nothing in this file is mock. Used by plans.index.tsx,
// plans.$refId.index.tsx, dev.tsx (Round 41, Stage 1 -- read-only), /upload
// (Round 42, Stage 2 -- real patient/version/upload creation + status
// polling), plans.$refId.index.tsx's override/finalize actions (Round 43,
// Stage 3), rules.tsx / Rules Studio (Round 50 -- real rule metadata CRUD;
// see api-client.ts's own comment on what editing here does and doesn't
// affect), and now index.tsx / Dashboard (Round 74 -- real
// GET /reports/overview + GET /reports/recent-activity, replacing
// tp-mock.ts's fabricated counts/activity feed entirely), and now Admin
// Settings' Notifications tab too (deployment round -- real
// notif_from_name/notif_from_address/notif_default_cc/auto_send, replacing
// that tab's own hardcoded defaultValue mockup), and now the Reports page
// itself (Fix Round, 2026-09-11 -- real GET /reports/overview [now with
// its weekly_volume/per_reviewer fields actually declared and consumed,
// not just the 3 top-line numbers Dashboard used] + GET /reports/trends,
// replacing reports.tsx's own tp-mock.ts-backed cards/chart/table/matrix
// entirely). Everything ELSE in the app (Admin Settings' OTHER tabs --
// Organization/Company Info specifically has no real backing endpoint at
// all, flagged not built rather than invented -- correction email,
// mark-reviewed) still stays on tp-context.tsx's mock data -- see
// FRONTEND_STATE.md §0.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createPatient, createRule, createSimulatedUpload, createUpload, createVersion, deactivatePatient, finalizeUpload, getAppConfig,
  getLatestIntakeAnswers, getRecentActivity, getReportsOverview, getReportsTrends, getSessionNoteExtraction, getUpload, getVersion,
  listPatientVersions, listPatients, listRules, listSessionNotes, overrideRuleResult, reactivatePatient, setRuleActive,
  setNotificationSettings, setSupportingDocMode, updateRule,
  type IntakeAnswers, type NotificationSettingsUpdate, type PatientStatusFilter, type RulePayor, type RuleType, type SupportingDocMode,
} from "./api-client";

// Part 6, Fix Round: defaults to "active", matching every existing caller's
// own expectation of "the patient list" unchanged. Pass "archived" for the
// dedicated deactivated view, or "all" for a page that must find a patient
// regardless of active state (the single-patient review page -- it has to
// be able to render a deactivated patient's own page to show the
// reactivate control at all).
export function usePatients(statusFilter: PatientStatusFilter = "active") {
  return useQuery({ queryKey: ["patients", statusFilter], queryFn: () => listPatients(statusFilter) });
}

export function useDeactivatePatient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patientId: string) => deactivatePatient(patientId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["patients"] }); },
  });
}

export function useReactivatePatient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patientId: string) => reactivatePatient(patientId),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["patients"] }); },
  });
}

export function useReportsOverview(range: "week" | "lastweek" | "30d" | "all" | "custom" = "all", start?: string, end?: string) {
  return useQuery({
    queryKey: ["reports-overview", range, start, end],
    queryFn: () => getReportsOverview(range, start, end),
  });
}

// Fix Round (2026-09-11): real backing for reports.tsx's "Trend Data" tab
// (provider/question-set × rule matrix) -- the backend endpoint
// (app/services/reports.py::get_trends, querying v_override_analytics)
// already existed; nothing in the frontend ever called it before this.
export function useReportsTrends(groupBy: "provider" | "questionset") {
  return useQuery({ queryKey: ["reports-trends", groupBy], queryFn: () => getReportsTrends(groupBy) });
}

export function useRecentActivity(limit = 8) {
  return useQuery({ queryKey: ["recent-activity", limit], queryFn: () => getRecentActivity(limit) });
}

export function usePatientVersions(patientId: string | undefined) {
  return useQuery({
    queryKey: ["patient-versions", patientId],
    queryFn: () => listPatientVersions(patientId!),
    enabled: !!patientId,
  });
}

export function useVersionDetail(versionId: string | undefined) {
  return useQuery({
    queryKey: ["version", versionId],
    queryFn: () => getVersion(versionId!),
    enabled: !!versionId,
  });
}

export function useUploadDetail(uploadId: string | undefined) {
  return useQuery({
    queryKey: ["upload", uploadId],
    queryFn: () => getUpload(uploadId!),
    enabled: !!uploadId,
    // Real status polling (Round 42) -- an upload sits at "processing"
    // until the background pipeline task flips it to "ready"/"error"; poll
    // while it's still in flight so the UI reflects that transition without
    // a manual refresh, and stop once it lands on a terminal status.
    refetchInterval: query => (query.state.data?.status === "processing" ? 3000 : false),
  });
}

export function useCreatePatient() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { reference_id: string; name: string; payor?: string | null }) => createPatient(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["patients"] }),
  });
}

export function useCreateVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { patientId: string; payor?: string | null }) =>
      createVersion(args.patientId, { payor: args.payor }),
    onSuccess: (_data, args) => {
      queryClient.invalidateQueries({ queryKey: ["patients"] });
      queryClient.invalidateQueries({ queryKey: ["patient-versions", args.patientId] });
    },
  });
}

export function useCreateUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    // Round 56: exactly one of the two payload shapes is required,
    // depending on the live supporting_doc_mode -- see api-client.ts's
    // createUpload for the exact FormData shape each one produces.
    mutationFn: (args: {
      versionId: string;
      file: File;
      payload: { supportingDocument: File } | { intakeAnswers: IntakeAnswers; sessionNotes: File[] };
      // Next Round (2026-08-27), Part 2 item 2: the new, OPTIONAL prior-TP
      // file -- independent of the payload shape above.
      previousTp?: File;
    }) => createUpload(args.versionId, args.file, args.payload, args.previousTp),
    onSuccess: (_data, args) => {
      queryClient.invalidateQueries({ queryKey: ["version", args.versionId] });
      queryClient.invalidateQueries({ queryKey: ["patients"] });
    },
  });
}

/** Dev-only (Round 49) -- see api-client.ts::createSimulatedUpload. Same
 * cache-invalidation shape as useCreateUpload; the only difference is which
 * backend route gets called. */
export function useCreateSimulatedUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { versionId: string; file: File }) => createSimulatedUpload(args.versionId, args.file),
    onSuccess: (_data, args) => {
      queryClient.invalidateQueries({ queryKey: ["version", args.versionId] });
      queryClient.invalidateQueries({ queryKey: ["patients"] });
    },
  });
}

// --- Stage 3: real override + finalize -----------------------------------

export function useOverrideRuleResult() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      ruleResultId: string;
      uploadId: string;
      updated_at: string;
      final_status?: "pass" | "fail" | "na" | "uncertain" | "not_checkable";
      // Round 70, Item 3: the backend PATCH contract already accepted
      // final_finding/final_pages (app/routers/rule_results.py's
      // RuleResultPatch) -- this hook just never forwarded them. Extends
      // the SAME mechanism, not a second one: still one PATCH call, one
      // optimistic-lock token, one override_rule_result() service call.
      final_finding?: string;
      final_pages?: number[];
      reason?: string;
    }) => overrideRuleResult(args.ruleResultId, {
      updated_at: args.updated_at,
      final_status: args.final_status,
      final_finding: args.final_finding,
      final_pages: args.final_pages,
      reason: args.reason,
    }),
    onSuccess: (_data, args) => {
      queryClient.invalidateQueries({ queryKey: ["upload", args.uploadId] });
    },
  });
}

export function useFinalizeUpload() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { uploadId: string; referenceId: string; versionId: string }) =>
      finalizeUpload(args.uploadId, args.referenceId),
    onSuccess: (_data, args) => {
      queryClient.invalidateQueries({ queryKey: ["upload", args.uploadId] });
      queryClient.invalidateQueries({ queryKey: ["version", args.versionId] });
      queryClient.invalidateQueries({ queryKey: ["patient-versions"] });
      queryClient.invalidateQueries({ queryKey: ["patients"] });
    },
  });
}

// --- Rules Studio (Round 50) -----------------------------------------------

export function useRules() {
  return useQuery({ queryKey: ["rules"], queryFn: listRules });
}

export function useCreateRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      rule_code: string; category: string; question_set: string; question_text: string;
      rule_type: RuleType; payor?: RulePayor | null; active?: boolean;
    }) => createRule(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useUpdateRule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: {
      ruleId: string;
      changes: Partial<{ category: string; question_set: string; question_text: string; rule_type: RuleType; payor: RulePayor | null }>;
    }) => updateRule(args.ruleId, args.changes),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useSetRuleActive() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: { ruleId: string; active: boolean }) => setRuleActive(args.ruleId, args.active),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["rules"] }),
  });
}

// --- Round 56: app-config feature flag, structured intake, session notes --

export function useAppConfig() {
  return useQuery({ queryKey: ["app-config"], queryFn: getAppConfig });
}

export function useSetSupportingDocMode() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (mode: SupportingDocMode) => setSupportingDocMode(mode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-config"] }),
  });
}

// Deployment round: real notification defaults (Admin Settings ->
// Notifications tab) -- was fully hardcoded mock UI with no query/mutation
// at all before this round; see admin.tsx's own comment on the same tab.
export function useSetNotificationSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: NotificationSettingsUpdate) => setNotificationSettings(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["app-config"] }),
  });
}

/** Item 2's "editable across versions" prefill -- null when this patient
 * has no prior structured-mode upload yet (an ordinary first-submission
 * case, not an error). */
export function useLatestIntakeAnswers(patientId: string | undefined) {
  return useQuery({
    queryKey: ["latest-intake-answers", patientId],
    queryFn: () => getLatestIntakeAnswers(patientId!),
    enabled: !!patientId,
  });
}

export function useSessionNotes(uploadId: string | undefined) {
  return useQuery({
    queryKey: ["session-notes", uploadId],
    queryFn: () => listSessionNotes(uploadId!),
    enabled: !!uploadId,
  });
}

// Round 79, Item 2: real extracted fields per session-note file, from
// agent-making's own Round 59 extraction step. Cached client-side by
// react-query the same way every other real hook here is; the backend's
// own content-hash cache (agent-making-side) means re-fetching an
// already-extracted file costs no real model call either.
export function useSessionNoteExtraction(uploadId: string | undefined, fileId: string | undefined) {
  return useQuery({
    queryKey: ["session-note-extraction", uploadId, fileId],
    queryFn: () => getSessionNoteExtraction(uploadId!, fileId!),
    enabled: !!uploadId && !!fileId,
    staleTime: Infinity, // this file's extraction never changes once computed
  });
}
