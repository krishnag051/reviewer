import { createContext, useContext, useState, type ReactNode } from "react";
import { initialPatients, reviewers, rules as initialRules, type Patient, type Rule, type RuleStatus } from "./tp-mock";

type Role = "Admin" | "Standard User";

type Ctx = {
  role: Role;
  setRole: (r: Role) => void;
  currentUserId: string;
  patients: Patient[];
  rules: Rule[];
  addPatient: (p: Patient) => void;
  addVersion: (refId: string, payor: Patient["payor"], reviewerId: string) => number;
  markReviewed: (refId: string, version: number) => void;
  overrideRuleStatus: (refId: string, version: number, ruleId: string, status: RuleStatus, finding?: string) => void;
  upsertRule: (r: Rule) => void;
  deleteRule: (id: string) => void;
  toggleRule: (id: string) => void;
};

const TPContext = createContext<Ctx | null>(null);

export function TPProvider({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>("Admin");
  const [patients, setPatients] = useState<Patient[]>(initialPatients);
  const [rules, setRules] = useState<Rule[]>(initialRules);
  const currentUserId = "u1";

  const addPatient = (p: Patient) => setPatients(prev => [p, ...prev]);

  const addVersion: Ctx["addVersion"] = (refId, payor, reviewerId) => {
    let newVersion = 1;
    setPatients(prev => prev.map(p => {
      if (p.refId !== refId) return p;
      newVersion = Math.max(...p.versions.map(v => v.version)) + 1;
      const template = p.versions[p.versions.length - 1];
      const clone = {
        ...template, version: newVersion,
        uploadedAt: new Date().toISOString().slice(0, 10),
        assessmentDate: new Date().toISOString().slice(0, 10),
        reviewerId, reviewed: false,
      };
      return { ...p, payor, versions: [...p.versions, clone] };
    }));
    return newVersion;
  };

  const markReviewed: Ctx["markReviewed"] = (refId, version) => {
    setPatients(prev => prev.map(p => p.refId !== refId ? p : {
      ...p, versions: p.versions.map(v => v.version === version ? { ...v, reviewed: true } : v),
    }));
  };

  const overrideRuleStatus: Ctx["overrideRuleStatus"] = (refId, version, ruleId, status, finding) => {
    setPatients(prev => prev.map(p => p.refId !== refId ? p : {
      ...p, versions: p.versions.map(v => {
        if (v.version !== version) return v;
        const results = v.results.map(r => r.ruleId === ruleId ? { ...r, status, finding: finding ?? r.finding, overridden: true } : r);
        const nonNa = results.filter(r => r.status !== "N/A");
        const passed = nonNa.filter(r => r.status === "Pass").length;
        const score = Math.round((passed / nonNa.length) * 100);
        return { ...v, results, score, auditResult: score >= 85 ? "Pass" : "Fail" };
      }),
    }));
  };

  const upsertRule: Ctx["upsertRule"] = (r) => {
    setRules(prev => {
      const exists = prev.find(x => x.id === r.id);
      return exists ? prev.map(x => x.id === r.id ? r : x) : [...prev, r];
    });
  };
  const deleteRule = (id: string) => setRules(prev => prev.filter(r => r.id !== id));
  const toggleRule = (id: string) => setRules(prev => prev.map(r => r.id === id ? { ...r, active: !r.active } : r));

  return (
    <TPContext.Provider value={{ role, setRole, currentUserId, patients, rules, addPatient, addVersion, markReviewed, overrideRuleStatus, upsertRule, deleteRule, toggleRule }}>
      {children}
    </TPContext.Provider>
  );
}

export function useTP() {
  const ctx = useContext(TPContext);
  if (!ctx) throw new Error("TPProvider missing");
  return ctx;
}

export function useCurrentUser() {
  const { currentUserId } = useTP();
  return reviewers.find(r => r.id === currentUserId)!;
}
