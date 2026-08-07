// Real-data react-query hooks. Every hook here hits the real backend via
// api-client.ts; nothing in this file is mock. Used by plans.index.tsx,
// plans.$refId.index.tsx, dev.tsx (Round 41, Stage 1 -- read-only), /upload
// (Round 42, Stage 2 -- real patient/version/upload creation + status
// polling), plans.$refId.index.tsx's override/finalize actions (Round 43,
// Stage 3), and now rules.tsx / Rules Studio (Round 50 -- real rule
// metadata CRUD; see api-client.ts's own comment on what editing here
// does and doesn't affect). Everything else in the app (Reports, Dashboard,
// Admin Settings, correction email, mark-reviewed) stays on
// tp-context.tsx's mock data -- see FRONTEND_STATE.md §0.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createPatient, createRule, createSimulatedUpload, createUpload, createVersion, finalizeUpload, getAppConfig,
  getLatestIntakeAnswers, getUpload, getVersion, listPatientVersions, listPatients, listRules, listSessionNotes,
  overrideRuleResult, setRuleActive, setSupportingDocMode, updateRule,
  type IntakeAnswers, type RulePayor, type RuleType, type SupportingDocMode,
} from "./api-client";

export function usePatients() {
  return useQuery({ queryKey: ["patients"], queryFn: listPatients });
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
    }) => createUpload(args.versionId, args.file, args.payload),
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
