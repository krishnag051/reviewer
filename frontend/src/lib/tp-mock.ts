// Mock data for TP Review System

export type Payor = "Healthfirst" | "Emblem" | "Anthem" | "Molina" | "Aetna" | "Cigna";
export type RuleStatus = "Pass" | "Fail" | "N/A";
export type RuleCategory =
  | "Patient Info"
  | "Diagnosis"
  | "Assessment"
  | "Goals & Objectives"
  | "Service Delivery"
  | "Signatures"
  | "Behavior Plan"
  | "Authorization";

export type Reviewer = {
  id: string;
  name: string;
  credentials: string;
  email: string;
  role: "Admin" | "Standard User";
};

export const reviewers: Reviewer[] = [
  { id: "u1", name: "M. Chen", credentials: "BCBA-D", email: "m.chen@brightpath-aba.com", role: "Admin" },
  { id: "u2", name: "S. Patel", credentials: "BCBA", email: "s.patel@brightpath-aba.com", role: "Standard User" },
  { id: "u3", name: "J. Rivera", credentials: "BCBA", email: "j.rivera@brightpath-aba.com", role: "Standard User" },
  { id: "u4", name: "A. Thompson", credentials: "BCaBA", email: "a.thompson@brightpath-aba.com", role: "Standard User" },
  { id: "u5", name: "L. Nguyen", credentials: "BCBA", email: "l.nguyen@brightpath-aba.com", role: "Admin" },
];

export type Rule = {
  id: string;
  category: RuleCategory;
  questionSet: "Treatment Plan" | "97151" | "97153" | "97155" | "97156";
  question: string;
  severity: "Normal" | "Critical";
  active: boolean;
};

export const rules: Rule[] = [
  { id: "R-001", category: "Patient Info", questionSet: "Treatment Plan", question: "Is the patient's full legal name present on the cover page?", severity: "Normal", active: true },
  { id: "R-002", category: "Patient Info", questionSet: "Treatment Plan", question: "Is the patient's date of birth documented and consistent throughout?", severity: "Normal", active: true },
  { id: "R-003", category: "Patient Info", questionSet: "Treatment Plan", question: "Is the insurance member ID present on the plan?", severity: "Critical", active: true },
  { id: "R-010", category: "Diagnosis", questionSet: "Treatment Plan", question: "Is a current DSM-5 diagnosis of ASD (F84.0) documented?", severity: "Critical", active: true },
  { id: "R-011", category: "Diagnosis", questionSet: "Treatment Plan", question: "Is the diagnosing provider's name and NPI listed?", severity: "Normal", active: true },
  { id: "R-020", category: "Assessment", questionSet: "97151", question: "Is the FBA dated within the last 90 days?", severity: "Critical", active: true },
  { id: "R-021", category: "Assessment", questionSet: "97151", question: "Are standardized assessment tools (VB-MAPP, ABLLS, Vineland) documented with scores?", severity: "Normal", active: true },
  { id: "R-022", category: "Assessment", questionSet: "97151", question: "Is caregiver/parent input on skill priorities documented?", severity: "Normal", active: true },
  { id: "R-030", category: "Goals & Objectives", questionSet: "Treatment Plan", question: "Are goals written in measurable, observable terms?", severity: "Critical", active: true },
  { id: "R-031", category: "Goals & Objectives", questionSet: "Treatment Plan", question: "Does each goal include mastery criteria?", severity: "Normal", active: true },
  { id: "R-032", category: "Goals & Objectives", questionSet: "Treatment Plan", question: "Does each goal include baseline data?", severity: "Normal", active: true },
  { id: "R-033", category: "Goals & Objectives", questionSet: "Treatment Plan", question: "Are short-term objectives linked to long-term goals?", severity: "Normal", active: true },
  { id: "R-040", category: "Service Delivery", questionSet: "97153", question: "Is the recommended weekly hours of 97153 documented with a specific unit count?", severity: "Critical", active: true },
  { id: "R-041", category: "Service Delivery", questionSet: "97155", question: "Is the recommended weekly hours of 97155 (protocol modification) documented?", severity: "Normal", active: true },
  { id: "R-042", category: "Service Delivery", questionSet: "97156", question: "Is parent training (97156) included with a specific frequency?", severity: "Normal", active: true },
  { id: "R-043", category: "Service Delivery", questionSet: "Treatment Plan", question: "Is the location of services (home, clinic, school) specified?", severity: "Normal", active: true },
  { id: "R-050", category: "Behavior Plan", questionSet: "Treatment Plan", question: "If interfering behaviors are present, is a Behavior Intervention Plan (BIP) included?", severity: "Critical", active: true },
  { id: "R-051", category: "Behavior Plan", questionSet: "Treatment Plan", question: "Are antecedent strategies documented for each target behavior?", severity: "Normal", active: true },
  { id: "R-052", category: "Behavior Plan", questionSet: "Treatment Plan", question: "Are replacement behaviors identified for each target behavior?", severity: "Normal", active: true },
  { id: "R-060", category: "Authorization", questionSet: "Treatment Plan", question: "Is the requested authorization period clearly stated (start and end date)?", severity: "Critical", active: true },
  { id: "R-061", category: "Authorization", questionSet: "Treatment Plan", question: "Does the authorization period not exceed 6 months?", severity: "Normal", active: true },
  { id: "R-070", category: "Signatures", questionSet: "Treatment Plan", question: "Is the BCBA signature present and dated?", severity: "Critical", active: true },
  { id: "R-071", category: "Signatures", questionSet: "Treatment Plan", question: "Is the parent/guardian signature present and dated within 30 days of BCBA signature?", severity: "Normal", active: true },
  { id: "R-072", category: "Signatures", questionSet: "Treatment Plan", question: "Is the BCBA's credential and certification number listed under the signature?", severity: "Normal", active: true },
];

export type PdfPage = { page: number; title: string; body: string[] };

export type RuleResult = {
  ruleId: string;
  status: RuleStatus;
  finding: string;
  pages: number[];
  overridden?: boolean;
};

export type PlanVersion = {
  version: number;
  uploadedAt: string;
  assessmentDate: string;
  reviewerId: string;
  pdf: PdfPage[];
  results: RuleResult[];
  score: number;
  auditResult: "Pass" | "Fail";
  reviewed: boolean;
};

export type Patient = {
  refId: string;
  name: string;
  payor: Payor;
  versions: PlanVersion[];
};

// Generate realistic PDF page content
const makePdf = (patient: string, dob: string, memberId: string, opts: {
  fbaDate: string;
  authStart: string;
  authEnd: string;
  hoursNote?: string;
  bipIncluded?: boolean;
  bcbaSigDate?: string;
  parentSigDate?: string;
}): PdfPage[] => [
  {
    page: 1, title: "Cover Page",
    body: [
      `TREATMENT PLAN — Applied Behavior Analysis`,
      `Patient: ${patient}`,
      `Date of Birth: ${dob}`,
      `Insurance Member ID: ${memberId}`,
      `Date of Plan: ${opts.authStart}`,
      `Authorization Period: ${opts.authStart} — ${opts.authEnd}`,
      `Prepared by: BrightPath ABA Services`,
    ],
  },
  {
    page: 2, title: "Diagnosis & Background",
    body: [
      `DSM-5 Diagnosis: Autism Spectrum Disorder (F84.0)`,
      `Diagnosing Provider: Dr. R. Kaplan, MD — NPI 1487293620`,
      `Date of Diagnosis: 2024-02-11`,
      `Medical History: No significant contraindications. Currently receiving speech therapy 2x/week.`,
      `Family caregiver goals: Increase independent self-care and reduce elopement in community settings.`,
    ],
  },
  {
    page: 3, title: "Assessment Summary",
    body: [
      `Functional Behavior Assessment (FBA) Date: ${opts.fbaDate}`,
      `VB-MAPP Milestones Total: 82/170 (Level 2 partial)`,
      `Vineland-3 Adaptive Behavior Composite Standard Score: 68`,
      `ABLLS-R: 328 skills scored; deficits in social interaction and group instruction`,
      `Caregiver interview completed with mother; priorities: communication, toileting, tantrum reduction.`,
    ],
  },
  {
    page: 4, title: "Service Recommendations",
    body: [
      opts.hoursNote ?? `97153 (Direct Therapy): 30 hours/week — 120 units/week`,
      `97155 (Protocol Modification): 4 hours/week — 16 units/week`,
      `97156 (Parent Training): 1 hour/week — 4 units/week`,
      `97151 (Assessment): 8 hours upon reauthorization`,
      `Service Location: Home and Clinic (BrightPath Queens site)`,
    ],
  },
  {
    page: 5, title: "Goals & Objectives",
    body: [
      `Goal 1 — Manding: Independently mand for 20 preferred items across 3 environments with 80% accuracy across 3 consecutive sessions. Baseline: 4/20 items.`,
      `Goal 2 — Tacting: Tact 50 common community items with 90% accuracy. Baseline: 12/50 items.`,
      `Goal 3 — Toileting: Independent toileting with < 1 accident per week across 4 consecutive weeks. Baseline: 5 accidents/week.`,
      `Goal 4 — Social: Initiate peer interactions 3x per 30-min play session across 3 settings. Baseline: 0 initiations.`,
      `Short-term objectives are linked to each long-term goal and reviewed monthly.`,
    ],
  },
  {
    page: 6, title: opts.bipIncluded ? "Behavior Intervention Plan" : "Behavior Notes",
    body: opts.bipIncluded ? [
      `Target Behavior 1 — Aggression (hitting): Antecedent strategies include non-contingent attention every 2 min and offering choices before demands. Replacement: mand for break using PECS card.`,
      `Target Behavior 2 — Elopement: Antecedent strategies include visual boundary markers and pre-teaching stop response. Replacement: request "walk with me" verbally.`,
      `Reinforcement schedule: FR1 initially, thinning to VR3 upon mastery.`,
    ] : [
      `Minor interfering behaviors noted (mild non-compliance). Full Behavior Intervention Plan not developed at this time; will reassess at 3-month checkpoint.`,
    ],
  },
  {
    page: 7, title: "Signatures",
    body: [
      opts.bcbaSigDate ? `BCBA Signature: [signed] — Date: ${opts.bcbaSigDate}` : `BCBA Signature: (missing)`,
      `Credential: BCBA-D, Certification #1-23-45678`,
      opts.parentSigDate ? `Parent/Guardian Signature: [signed] — Date: ${opts.parentSigDate}` : `Parent/Guardian Signature: (missing)`,
    ],
  },
];

const today = new Date("2026-07-15");
const daysAgo = (n: number) => {
  const d = new Date(today); d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

export const initialPatients: Patient[] = [
  {
    refId: "TP-2026-0812", name: "Ethan Ramirez", payor: "Healthfirst",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(120), assessmentDate: daysAgo(125), reviewerId: "u2",
        pdf: makePdf("Ethan Ramirez", "2019-04-12", "HF-8827321", {
          fbaDate: daysAgo(140), authStart: daysAgo(120), authEnd: daysAgo(120 - 180),
          hoursNote: "97153 (Direct Therapy): 30 hours/week (no unit count provided)",
          bipIncluded: false, bcbaSigDate: daysAgo(120), parentSigDate: daysAgo(115),
        }),
        results: [], score: 71, auditResult: "Fail", reviewed: true,
      },
      {
        version: 2, uploadedAt: daysAgo(35), assessmentDate: daysAgo(40), reviewerId: "u2",
        pdf: makePdf("Ethan Ramirez", "2019-04-12", "HF-8827321", {
          fbaDate: daysAgo(118), authStart: daysAgo(35), authEnd: daysAgo(35 - 180),
          hoursNote: "97153 (Direct Therapy): 40 hours/week (no unit count provided)",
          bipIncluded: false, bcbaSigDate: daysAgo(35), parentSigDate: daysAgo(30),
        }),
        results: [], score: 78, auditResult: "Fail", reviewed: false,
      },
    ],
  },
  {
    refId: "TP-2025-0102", name: "Sofia Chen-Alvarez", payor: "Emblem",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(200), assessmentDate: daysAgo(205), reviewerId: "u3",
        pdf: makePdf("Sofia Chen-Alvarez", "2018-11-03", "EM-4491082", {
          fbaDate: daysAgo(215), authStart: daysAgo(200), authEnd: daysAgo(200 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(200), parentSigDate: daysAgo(198),
        }),
        results: [], score: 92, auditResult: "Pass", reviewed: true,
      },
      {
        version: 2, uploadedAt: daysAgo(18), assessmentDate: daysAgo(22), reviewerId: "u3",
        pdf: makePdf("Sofia Chen-Alvarez", "2018-11-03", "EM-4491082", {
          fbaDate: daysAgo(30), authStart: daysAgo(18), authEnd: daysAgo(18 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(18), parentSigDate: daysAgo(15),
        }),
        results: [], score: 96, auditResult: "Pass", reviewed: true,
      },
    ],
  },
  {
    refId: "TP-2026-0155", name: "Marcus Okonkwo", payor: "Anthem",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(10), assessmentDate: daysAgo(14), reviewerId: "u1",
        pdf: makePdf("Marcus Okonkwo", "2020-07-22", "AN-7710948", {
          fbaDate: daysAgo(60), authStart: daysAgo(10), authEnd: daysAgo(10 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(10), parentSigDate: daysAgo(8),
        }),
        results: [], score: 88, auditResult: "Pass", reviewed: false,
      },
    ],
  },
  {
    refId: "TP-2026-0201", name: "Ava Nakamura", payor: "Molina",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(6), assessmentDate: daysAgo(9), reviewerId: "u5",
        pdf: makePdf("Ava Nakamura", "2017-01-30", "MO-3391172", {
          fbaDate: daysAgo(200), authStart: daysAgo(6), authEnd: daysAgo(6 - 240),
          hoursNote: "97153 (Direct Therapy): recommended but hours not specified",
          bipIncluded: false, bcbaSigDate: daysAgo(6),
        }),
        results: [], score: 54, auditResult: "Fail", reviewed: false,
      },
    ],
  },
  {
    refId: "TP-2026-0290", name: "Liam O'Sullivan", payor: "Aetna",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(3), assessmentDate: daysAgo(5), reviewerId: "u2",
        pdf: makePdf("Liam O'Sullivan", "2021-08-14", "AE-2298811", {
          fbaDate: daysAgo(20), authStart: daysAgo(3), authEnd: daysAgo(3 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(3), parentSigDate: daysAgo(2),
        }),
        results: [], score: 95, auditResult: "Pass", reviewed: true,
      },
    ],
  },
  {
    refId: "TP-2026-0304", name: "Aaliyah Washington", payor: "Cigna",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(60), assessmentDate: daysAgo(65), reviewerId: "u4",
        pdf: makePdf("Aaliyah Washington", "2019-12-05", "CG-5528190", {
          fbaDate: daysAgo(75), authStart: daysAgo(60), authEnd: daysAgo(60 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(60), parentSigDate: daysAgo(58),
        }),
        results: [], score: 84, auditResult: "Pass", reviewed: true,
      },
      {
        version: 2, uploadedAt: daysAgo(1), assessmentDate: daysAgo(4), reviewerId: "u4",
        pdf: makePdf("Aaliyah Washington", "2019-12-05", "CG-5528190", {
          fbaDate: daysAgo(15), authStart: daysAgo(1), authEnd: daysAgo(1 - 180),
          bipIncluded: true, bcbaSigDate: daysAgo(1), parentSigDate: daysAgo(1),
        }),
        results: [], score: 91, auditResult: "Pass", reviewed: false,
      },
    ],
  },
  {
    refId: "TP-2026-0322", name: "Noah Blackwell", payor: "Healthfirst",
    versions: [
      {
        version: 1, uploadedAt: daysAgo(45), assessmentDate: daysAgo(50), reviewerId: "u1",
        pdf: makePdf("Noah Blackwell", "2020-03-19", "HF-9987214", {
          fbaDate: daysAgo(60), authStart: daysAgo(45), authEnd: daysAgo(45 - 180),
          bipIncluded: false, bcbaSigDate: daysAgo(45), parentSigDate: daysAgo(43),
        }),
        results: [], score: 82, auditResult: "Pass", reviewed: true,
      },
    ],
  },
];

// Generate rule results for each version based on plan data
function generateResults(patient: Patient, version: PlanVersion): RuleResult[] {
  const p = patient;
  const v = version;
  const findingsFor: Record<string, () => RuleResult> = {
    "R-001": () => ({ ruleId: "R-001", status: "Pass", pages: [1], finding: `Patient name "${p.name}" is present on the cover page.` }),
    "R-002": () => ({ ruleId: "R-002", status: "Pass", pages: [1, 2], finding: `DOB matches on cover page and diagnosis section.` }),
    "R-003": () => ({ ruleId: "R-003", status: "Pass", pages: [1], finding: `Insurance member ID documented on cover page.` }),
    "R-010": () => ({ ruleId: "R-010", status: "Pass", pages: [2], finding: `DSM-5 diagnosis of Autism Spectrum Disorder (F84.0) is documented.` }),
    "R-011": () => ({ ruleId: "R-011", status: "Pass", pages: [2], finding: `Diagnosing provider Dr. R. Kaplan, MD (NPI 1487293620) is listed.` }),
    "R-020": () => {
      const fbaAge = Math.round((new Date(v.uploadedAt).getTime() - new Date(v.pdf[2].body[0].match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? v.uploadedAt).getTime()) / 86400000);
      const pass = fbaAge <= 90;
      return { ruleId: "R-020", status: pass ? "Pass" : "Fail", pages: [3], finding: pass
        ? `FBA is dated ${fbaAge} days prior to plan upload — within the 90-day requirement.`
        : `FBA dated ${fbaAge} days prior to plan upload, exceeds the 90-day requirement.` };
    },
    "R-021": () => ({ ruleId: "R-021", status: "Pass", pages: [3], finding: `VB-MAPP (82/170), Vineland-3 (SS 68), and ABLLS-R scores are documented.` }),
    "R-022": () => ({ ruleId: "R-022", status: "Pass", pages: [3], finding: `Caregiver interview with priorities documented.` }),
    "R-030": () => ({ ruleId: "R-030", status: "Pass", pages: [5], finding: `Goals are written in measurable terms (frequency, accuracy percentages).` }),
    "R-031": () => ({ ruleId: "R-031", status: "Pass", pages: [5], finding: `Mastery criteria present for all 4 goals (e.g., "80% accuracy across 3 consecutive sessions").` }),
    "R-032": () => ({ ruleId: "R-032", status: "Pass", pages: [5], finding: `Baseline data documented for each goal.` }),
    "R-033": () => ({ ruleId: "R-033", status: "Pass", pages: [5], finding: `Short-term objectives noted as linked to long-term goals.` }),
    "R-040": () => {
      const hoursLine = v.pdf[3].body[0];
      const hasUnits = /unit/i.test(hoursLine) && !/no unit/i.test(hoursLine);
      const specified = !/not specified/i.test(hoursLine);
      const pass = hasUnits && specified;
      return { ruleId: "R-040", status: pass ? "Pass" : "Fail", pages: [4], finding: pass
        ? `97153 hours and unit count documented on Page 4.`
        : specified
          ? `97153 hours documented on Page 4, but no corresponding unit count is included anywhere in the plan.`
          : `97153 recommended on Page 4 but weekly hours not specified.` };
    },
    "R-041": () => ({ ruleId: "R-041", status: "Pass", pages: [4], finding: `97155 documented at 4 hours/week (16 units).` }),
    "R-042": () => ({ ruleId: "R-042", status: "Pass", pages: [4], finding: `97156 parent training documented at 1 hour/week.` }),
    "R-043": () => ({ ruleId: "R-043", status: "Pass", pages: [4], finding: `Service location specified: Home and Clinic.` }),
    "R-050": () => {
      const bip = /Behavior Intervention Plan/i.test(v.pdf[5].title);
      return { ruleId: "R-050", status: bip ? "Pass" : "Fail", pages: [6], finding: bip
        ? `Behavior Intervention Plan is included with target behaviors and strategies.`
        : `Interfering behaviors are noted on Page 6, but no full Behavior Intervention Plan is documented.` };
    },
    "R-051": () => {
      const bip = /Behavior Intervention Plan/i.test(v.pdf[5].title);
      return { ruleId: "R-051", status: bip ? "Pass" : "N/A", pages: [6], finding: bip
        ? `Antecedent strategies documented for aggression and elopement.`
        : `No BIP required per note on Page 6.` };
    },
    "R-052": () => {
      const bip = /Behavior Intervention Plan/i.test(v.pdf[5].title);
      return { ruleId: "R-052", status: bip ? "Pass" : "N/A", pages: [6], finding: bip
        ? `Replacement behaviors identified (PECS mand for break; verbal "walk with me").`
        : `Not applicable — no formal BIP present.` };
    },
    "R-060": () => ({ ruleId: "R-060", status: "Pass", pages: [1], finding: `Authorization period clearly stated on Page 1.` }),
    "R-061": () => {
      const line = v.pdf[0].body[5];
      const m = line.match(/(\d{4}-\d{2}-\d{2}).+?(\d{4}-\d{2}-\d{2})/);
      if (!m) return { ruleId: "R-061", status: "N/A", pages: [1], finding: "Unable to parse authorization dates." };
      const days = Math.abs((new Date(m[2]).getTime() - new Date(m[1]).getTime()) / 86400000);
      const pass = days <= 186;
      return { ruleId: "R-061", status: pass ? "Pass" : "Fail", pages: [1], finding: pass
        ? `Authorization period spans ${Math.round(days)} days (within 6 months).`
        : `Authorization period spans ${Math.round(days)} days, exceeds the 6-month maximum.` };
    },
    "R-070": () => {
      const line = v.pdf[6].body[0];
      const pass = !/missing/i.test(line);
      return { ruleId: "R-070", status: pass ? "Pass" : "Fail", pages: [7], finding: pass
        ? `BCBA signature present and dated on Page 7.`
        : `BCBA signature is missing on Page 7.` };
    },
    "R-071": () => {
      const line = v.pdf[6].body[2];
      const pass = !/missing/i.test(line);
      return { ruleId: "R-071", status: pass ? "Pass" : "Fail", pages: [7], finding: pass
        ? `Parent/guardian signature present and dated within 30 days of BCBA signature.`
        : `Parent/guardian signature is missing on Page 7.` };
    },
    "R-072": () => ({ ruleId: "R-072", status: "Pass", pages: [7], finding: `Credential (BCBA-D) and certification #1-23-45678 listed.` }),
  };

  return rules.filter(r => r.active).map(r => findingsFor[r.id]?.() ?? {
    ruleId: r.id, status: "Pass" as RuleStatus, pages: [1], finding: `Reviewed and passed.`
  });
}

// Populate results
initialPatients.forEach(p => {
  p.versions.forEach(v => {
    v.results = generateResults(p, v);
    // Recompute score
    const nonNa = v.results.filter(r => r.status !== "N/A");
    const passed = nonNa.filter(r => r.status === "Pass").length;
    v.score = Math.round((passed / nonNa.length) * 100);
    v.auditResult = v.score >= 85 ? "Pass" : "Fail";
  });
});

export const auditLog = [
  { at: "2026-07-14 14:32", user: "M. Chen", action: "Edited rule R-020 (updated question wording)", refId: "" },
  { at: "2026-07-14 11:18", user: "S. Patel", action: "Marked TP-2026-0812 v2 as Reviewed", refId: "TP-2026-0812" },
  { at: "2026-07-13 16:47", user: "J. Rivera", action: "Overrode answer for R-033 (Pass → N/A)", refId: "TP-2025-0102" },
  { at: "2026-07-13 09:22", user: "A. Thompson", action: "Uploaded new version (v1)", refId: "TP-2026-0155" },
  { at: "2026-07-12 15:03", user: "L. Nguyen", action: "Created new rule R-072", refId: "" },
  { at: "2026-07-12 10:41", user: "M. Chen", action: "Deactivated rule R-999 (deprecated)", refId: "" },
  { at: "2026-07-11 13:29", user: "S. Patel", action: "Sent correction email to reviewer", refId: "TP-2026-0201" },
  { at: "2026-07-10 17:12", user: "J. Rivera", action: "Marked TP-2026-0304 v1 as Reviewed", refId: "TP-2026-0304" },
  { at: "2026-07-10 08:55", user: "A. Thompson", action: "Uploaded new version (v2)", refId: "TP-2026-0812" },
  { at: "2026-07-09 14:07", user: "M. Chen", action: "Edited notification default CC list", refId: "" },
];

export const invoices = [
  { date: "2026-07-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
  { date: "2026-06-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
  { date: "2026-05-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
];
