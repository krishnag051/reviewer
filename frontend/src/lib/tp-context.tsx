import { createContext, useContext, useState, type ReactNode } from "react";
import {
  initialPatients, runMockReview, scoreResults, randomProcessingDelayMs,
  type Patient, type PdfPage, type RuleStatus, type UAttempt, type Payor,
} from "./tp-mock";

// Round 41: the mock role/current-user concept that used to live here
// (`role`/`setRole`/`currentUserId`/`useCurrentUser`) is gone -- replaced
// by real login (see auth-context.tsx's useAuth()). Every consumer that
// used to read role/current-user from useTP() now reads useAuth() instead
// (AppShell, rules.tsx, admin.tsx). This context is now scoped to what's
// still mock-only: draft/version CRUD (see FRONTEND_STATE.md's "mock data
// path" note). The rules library (`rules`/`upsertRule`/`deleteRule`/
// `toggleRule`) that used to live here is gone as of Round 50 -- Rules
// Studio now reads/writes the real backend via real-data.ts/api-client.ts
// instead. reports.tsx's own rule-derived stats still import `rules`
// directly from tp-mock.ts (unrelated to this context, untouched).
type Ctx = {
  patients: Patient[];
  addPatient: (p: { refId: string; name: string; payor: Payor }) => void;
  // Fire-and-forget by design (see addAttempt's own comment below for why
  // it can't reliably return the created attempt synchronously) --
  // callers must compute any attempt-number-dependent UI text from state
  // they already have, not from this call's return value.
  addAttempt: (refId: string, reviewerId: string, pdf: PdfPage[], assessmentDate: string) => void;
  finalizeAttempt: (refId: string, attemptId: string) => number | null;
  markReviewed: (refId: string, version: number) => void;
  // Draft-only (2026-07-30, corrected -- this is the final answer,
  // reversing two earlier wrong statements of this same decision: one
  // round said finalized-only, the next said both). The real workflow is
  // the agent flags each rule with a finding + page number, a human
  // reviewer corrects whatever's wrong WHILE the attempt is still a draft,
  // and finalizing locks the document -- no further overrides after that.
  overrideRuleStatus: (refId: string, attemptId: string, ruleId: string, status: RuleStatus, finding?: string) => void;
};

const TPContext = createContext<Ctx | null>(null);

export function TPProvider({ children }: { children: ReactNode }) {
  const [patients, setPatients] = useState<Patient[]>(initialPatients);

  // New patient: creates the patient shell only -- versions:[] and
  // uAttempts:[]. V1 gets created the exact same way every later version
  // does, via addAttempt -> finalizeAttempt, no shortcut to an instant V1.
  const addPatient: Ctx["addPatient"] = (p) => {
    setPatients(prev => [{ refId: p.refId, name: p.name, payor: p.payor, versions: [], uAttempts: [] }, ...prev]);
  };

  // Appends a new draft UAttempt against the patient's current open
  // V-slot. attemptNumber is always uAttempts.length + 1 -- scoped to
  // whatever's currently in progress, not a global counter, so it
  // naturally restarts at 1 once a slot is finalized and uAttempts clears.
  // No cap on how many attempts can pile up before finalizing -- U1, U2,
  // U3... as many revise-and-reupload cycles as needed is the whole point.
  //
  // BUG FIX (found live): this used to read `patients` -- the outer
  // closure captured at THIS render -- to find the patient, before ever
  // calling setPatients. That's fine when addAttempt is the only state
  // change in the handler, but upload.tsx's "New Patient" flow calls
  // addPatient() immediately followed by addAttempt() in the very same
  // synchronous handler. addPatient's setPatients call is queued, not
  // applied to `patients` mid-render -- so the outer `patients` addAttempt
  // read was still the PRE-creation snapshot, the lookup always failed,
  // and the attempt was silently never created (only the console.warn
  // below fired). Fixed by doing the lookup INSIDE the setPatients
  // updater instead of before it -- React processes queued functional
  // updaters for the same state in order within one batch, so this one
  // correctly sees the patient shell addPatient's updater just added, even
  // though `patients` (this render's snapshot) still doesn't. This is one
  // shared `patients` state in TPProvider, read via the same useTP() by
  // every consumer -- there was never a second, separate list to drift
  // from; the appearance of disagreement was a timing issue, not two
  // sources of truth.
  //
  // Because of this, the created attempt can no longer be handed back
  // synchronously (the updater may not run before this function returns)
  // -- callers must not depend on the return value; both call sites in
  // upload.tsx were updated to compute the attempt number from state they
  // already have instead of from this return value.
  // `attemptId` is generated up front, independent of any patient lookup --
  // it doesn't need `attemptNumber` (only the mock-review computation
  // inside the updater does), so it can be created before setPatients
  // without reintroducing the stale-closure bug above. That lets the
  // simulated-processing setTimeout below target this exact attempt by ID
  // once it fires, without ever reading a snapshot of `patients` itself --
  // its own updater re-looks-up the patient/attempt fresh at fire time, so
  // it's correct no matter what else has happened to that patient meanwhile
  // (including another addAttempt or a finalize).
  const addAttempt: Ctx["addAttempt"] = (refId, reviewerId, pdf, assessmentDate) => {
    const attemptId = `${refId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setPatients(prev => {
      const patient = prev.find(p => p.refId === refId);
      if (!patient) {
        console.warn(`addAttempt: no patient with refId ${refId}`);
        return prev;
      }
      const attemptNumber = patient.uAttempts.length + 1;
      const results = runMockReview(patient.payor, attemptNumber);
      const { score, auditResult } = scoreResults(results);
      const attempt: UAttempt = {
        id: attemptId,
        attemptNumber,
        uploadedAt: new Date().toISOString().slice(0, 10),
        assessmentDate,
        reviewerId,
        pdf,
        status: "processing",
        results,
        score,
        auditResult,
      };
      return prev.map(p => p.refId !== refId ? p : { ...p, uAttempts: [...p.uAttempts, attempt] });
    });

    // Simulated "agent is running" delay -- stands in for the real
    // rule-checking agent's run time. TPProvider is mounted once at the
    // app root, so this timer survives navigating away from /upload (which
    // now happens immediately after this call returns).
    setTimeout(() => {
      setPatients(prev => prev.map(p => p.refId !== refId ? p : {
        ...p,
        uAttempts: p.uAttempts.map(a => a.id === attemptId ? { ...a, status: "complete" } : a),
      }));
    }, randomProcessingDelayMs());
  };

  // The "UF" action. Promotes one attempt into the next official
  // PlanVersion and clears every draft for that patient -- including
  // OTHER sibling attempts that didn't get chosen, regardless of which
  // attempt was selected. In this mock-data pass siblings are simply
  // dropped (per the confirmed decision); when this connects to a real
  // database later, they should likely be soft-retained for audit history
  // instead of destroyed, consistent with how this project archives
  // rather than deletes elsewhere -- not assumed away here, just not built
  // yet since there's nowhere durable to keep them in mock state.
  const finalizeAttempt: Ctx["finalizeAttempt"] = (refId, attemptId) => {
    const patient = patients.find(p => p.refId === refId);
    const attempt = patient?.uAttempts.find(a => a.id === attemptId);
    if (!patient || !attempt) {
      console.warn(`finalizeAttempt: no matching attempt ${attemptId} for patient ${refId} (already finalized, or navigated away from stale data?)`);
      return null;
    }
    const newVersionNumber = patient.versions.length + 1;
    setPatients(prev => prev.map(p => {
      if (p.refId !== refId) return p;
      // Re-check inside the updater against the latest state, not the
      // `patient`/`attempt` closed over above -- guards against a second
      // finalize racing in in the same tick and clearing uAttempts first.
      const liveAttempt = p.uAttempts.find(a => a.id === attemptId);
      if (!liveAttempt) return p;
      const newVersion = {
        version: p.versions.length + 1,
        finalizedAt: new Date().toISOString().slice(0, 10),
        assessmentDate: liveAttempt.assessmentDate,
        reviewerId: liveAttempt.reviewerId,
        pdf: liveAttempt.pdf,
        results: liveAttempt.results,
        score: liveAttempt.score,
        auditResult: liveAttempt.auditResult,
        reviewed: false,
        finalizedFromAttemptId: liveAttempt.id,
      };
      return { ...p, versions: [...p.versions, newVersion], uAttempts: [] };
    }));
    return newVersionNumber;
  };

  const markReviewed: Ctx["markReviewed"] = (refId, version) => {
    setPatients(prev => prev.map(p => p.refId !== refId ? p : {
      ...p, versions: p.versions.map(v => v.version === version ? { ...v, reviewed: true } : v),
    }));
  };

  // Draft-only (2026-07-30, corrected -- final answer, reversing two
  // earlier statements of this same decision). The real workflow: the
  // agent flags each rule pass/fail/N-A with a finding and page number; a
  // human reviewer corrects whatever's wrong while the attempt is still a
  // draft, and whatever needs fixing gets routed to BCBA or wherever it
  // belongs -- all before finalizing. Once finalized, the version is
  // locked: no override affordance exists on a PlanVersion anywhere in the
  // UI (see plans.$refId.index.tsx -- the override dropdown only renders
  // for a selected draft attempt now, never a selected finalized version).
  const overrideRuleStatus: Ctx["overrideRuleStatus"] = (refId, attemptId, ruleId, status, finding) => {
    setPatients(prev => prev.map(p => p.refId !== refId ? p : {
      ...p, uAttempts: p.uAttempts.map(a => {
        if (a.id !== attemptId) return a;
        const results = a.results.map(r => r.ruleId === ruleId ? { ...r, status, finding: finding ?? r.finding, overridden: true } : r);
        const { score, auditResult } = scoreResults(results);
        return { ...a, results, score, auditResult };
      }),
    }));
  };

  return (
    <TPContext.Provider value={{
      patients,
      addPatient, addAttempt, finalizeAttempt, markReviewed, overrideRuleStatus,
    }}>
      {children}
    </TPContext.Provider>
  );
}

export function useTP() {
  const ctx = useContext(TPContext);
  if (!ctx) throw new Error("TPProvider missing");
  return ctx;
}
