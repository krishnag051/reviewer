// Mock data for TP Review System

export type Payor =
  | "Aetna" | "Anthem" | "Cigna" | "Emblem" | "Empire"
  | "Healthfirst" | "Molina" | "MVP" | "Straight Medicaid" | "New York Medicaid";

// Matches agent-making's actual payor list: the 9 official payors per the
// locked project scope, plus New York Medicaid as a real bonus payor.
export const PAYORS: Payor[] = [
  "Aetna", "Anthem", "Cigna", "Emblem", "Empire",
  "Healthfirst", "Molina", "MVP", "Straight Medicaid", "New York Medicaid",
];

export type RuleStatus = "Pass" | "Fail" | "N/A";

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

// --- Rules -------------------------------------------------------------
// Real rule content sourced from agent-making/agent/rules/rules.json (read
// only, not modified) so the Rules Studio reads like the real thing before
// it's ever wired up. check_type/action_lane/action_tag are agent-making's
// actual current values for each rule -- "actionTag" is the Director/QA/
// Coordinator/General sub-tag scoped under the Facilitator-assign lane;
// "Coordinator" isn't used by any current rule but stays a valid tag value
// since it's part of the original project scope.

export type RuleCheckType = "deterministic" | "judgment";
export type ActionLane = "BCBA-fix" | "Facilitator-assign";
export type ActionTag = "Director" | "QA" | "Coordinator" | "General" | null;

export type Rule = {
  id: string;
  category: string;
  payor: "ALL" | Payor;
  description: string;
  checkType: RuleCheckType;
  actionLane: ActionLane;
  actionTag: ActionTag;
  active: boolean;
};

export const rules: Rule[] = [
  { id: "QA-TEMP-01", category: "Template", payor: "ALL", description: "Limited permit holder -> correct template used, credentials correct throughout", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TEMP-02", category: "Template", payor: "ALL", description: "TP includes header and page numbers on all pages", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TEMP-03", category: "Template", payor: "ALL", description: "All highlights removed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TEMP-04", category: "Template", payor: "ALL", description: "All correspondence with BCBA removed", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TEMP-05", category: "Template", payor: "ALL", description: "'RBT' changed to 'RBT/BT' or 'BT'", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-RPT-01", category: "Report Information", payor: "ALL", description: "All fields completed", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-RPT-02", category: "Report Information", payor: "ALL", description: "Date of initial assessment pulled onto TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-RPT-03", category: "Report Information", payor: "ALL", description: "Dates of current report match 97151 session notes", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-RPT-04", category: "Report Information", payor: "ALL", description: "Auth dates requested within 2 days of submission", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-RPT-05", category: "Report Information", payor: "ALL", description: "Auth dates accurate (6-month default, based on previous auth end or new insurance start)", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-RPT-06", category: "Report Information", payor: "ALL", description: "End date of current report before start of auth dates requested", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PPI-01", category: "Patient/Provider Info", payor: "ALL", description: "Patient info matches Central Reach", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-PPI-02", category: "Patient/Provider Info", payor: "ALL", description: "Patient age correct and consistent throughout TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PPI-03", category: "Patient/Provider Info", payor: "ALL", description: "Patient legal name spelled correctly throughout", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PPI-04", category: "Patient/Provider Info", payor: "ALL", description: "Patient Payor and Insurance ID correct", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PPI-05", category: "Patient/Provider Info", payor: "ALL", description: "Provider Credentials/NPI/License correct", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-HRS-01", category: "Hours Requesting", payor: "ALL", description: "97153 hours match email from coordinator", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-HRS-02", category: "Hours Requesting", payor: "ALL", description: ">20hrs of 97153 -> note on review email to Eliana", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-HRS-03", category: "Hours Requesting", payor: "ALL", description: "Supervision hours must not exceed 1.5/10 ratio; if exceeded, needs clinical director approval", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-HRS-04", category: "Hours Requesting", payor: "ALL", description: "Group hours -> more direct hours + tailored rationale", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-HRS-05", category: "Hours Requesting", payor: "ALL", description: "<10 hrs of 97153 -> confirm approved", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-HRS-06", category: "Hours Requesting", payor: "ALL", description: "Increase in hours -> rationale in place", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-HRS-07", category: "Hours Requesting", payor: "ALL", description: "Increase in hours -> compared against previous mastery criteria", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-HRS-08", category: "Hours Requesting", payor: "ALL", description: "Codes/hours match insurance billing codes guide", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-HRS-09", category: "Hours Requesting", payor: "ALL", description: "Overlap with home health aide/speech/OT -> goals differentiated", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-01", category: "School & ABA Schedule", payor: "ALL", description: "ABA schedule matches hours requested", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-02", category: "School & ABA Schedule", payor: "ALL", description: "Confirmed with service coordinator schedule is accurate", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-SCH-03", category: "School & ABA Schedule", payor: "ALL", description: "ABA schedule doesn't overlap school schedule (unless payor allows in-school)", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-04", category: "School & ABA Schedule", payor: "ALL", description: "If ABA during day, school hours adjusted accordingly", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-05", category: "School & ABA Schedule", payor: "ALL", description: "School hours match total under educational history", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-06", category: "School & ABA Schedule", payor: "ALL", description: "If overlaps related therapy, that schedule is added to TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SCH-07", category: "School & ABA Schedule", payor: "ALL", description: ">3 hrs/day of 97153 -> approved by clinical director", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-SCH-08", category: "School & ABA Schedule", payor: "ALL", description: "POS correct (home/office/school/community only)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-01", category: "Biopsychosocial", payor: "ALL", description: "All info completed, matches diagnostic report", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-BIO-02", category: "Biopsychosocial", payor: "ALL", description: "Date of most recent diagnosis pulled onto TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-03", category: "Biopsychosocial", payor: "ALL", description: "Includes any other diagnosis if applicable", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-BIO-05", category: "Biopsychosocial", payor: "ALL", description: "Developmental history and diagnosis do not contradict", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-06", category: "Biopsychosocial", payor: "ALL", description: "Medication listed -> reason stated; ADHD med = secondary diagnosis", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-07", category: "Biopsychosocial", payor: "ALL", description: "Educational history chronological, matches coordinator info", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-BIO-08", category: "Biopsychosocial", payor: "ALL", description: "Patients <5, community daytime hours -> 'school' replaced with community/daycare/preschool", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-09", category: "Biopsychosocial", payor: "ALL", description: "Patients 5+ in Special Ed -> TP indicates IEP", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-10", category: "Biopsychosocial", payor: "ALL", description: "Educational history and COC do not contradict", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-11", category: "Biopsychosocial", payor: "ALL", description: "Includes any other service child is receiving", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-12", category: "Biopsychosocial", payor: "ALL", description: "Includes all EI services received", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-13", category: "Biopsychosocial", payor: "ALL", description: "First day of ABA with MF pulled onto TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-14", category: "Biopsychosocial", payor: "ALL", description: "History of ABA therapy with other providers completed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-15", category: "Biopsychosocial", payor: "ALL", description: "Includes school name", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIO-16", category: "Biopsychosocial", payor: "ALL", description: "School name matches Central Reach", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-PROB-01", category: "Problem Areas", payor: "ALL", description: "At least 2 each of social/communication/behavior, narrative format", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PROB-02", category: "Problem Areas", payor: "ALL", description: "'As evidenced by' section matches goals listed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PROB-03", category: "Problem Areas", payor: "ALL", description: "Under 5: behaviors describe real ASD deficit, distinguishable from normal behavior", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-OBS-01", category: "Observations", payor: "ALL", description: "Patient observation completed", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-OBS-02", category: "Observations", payor: "ALL", description: "Observation location and dates fully completed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-OBS-03", category: "Observations", payor: "ALL", description: "Session note backs the observation (else forward to QA)", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "QA", active: true },
  { id: "QA-OBS-04", category: "Observations", payor: "ALL", description: "Observation date within report dates, before testing tool date", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-01", category: "Assessment of Current Functioning", payor: "ALL", description: "Date/location/patient location completed", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-02", category: "Assessment of Current Functioning", payor: "ALL", description: "Note backing assessment matches date/location", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "QA", active: true },
  { id: "QA-ACF-03", category: "Assessment of Current Functioning", payor: "ALL", description: "Grid with legend (colors/dates/assessor) present", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-04", category: "Assessment of Current Functioning", payor: "ALL", description: "Score lower than previous assessment -> Director tag", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-ACF-05", category: "Assessment of Current Functioning", payor: "ALL", description: "Assessment Summary Statement is documented (not blank)", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-06", category: "Assessment of Current Functioning", payor: "ALL", description: "Testing tool includes assessor's name", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-07", category: "Assessment of Current Functioning", payor: "ALL", description: "TP includes both old and new testing tool", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-ACF-08", category: "Assessment of Current Functioning", payor: "ALL", description: "Session note backs testing tool used (else forward to QA)", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "QA", active: true },
  { id: "QA-CI-01", category: "Clinical Interpretation", payor: "ALL", description: "Completed with clear and detailed rationale", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BAR-01", category: "Barriers to Treatment", payor: "ALL", description: "Includes at least one barrier to treatment", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIP-01", category: "BIP", payor: "ALL", description: "At least one severity rating >= moderate (not all 4 mild)", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-BIP-02", category: "BIP", payor: "ALL", description: "No punishment procedures unless data attached + director approved", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-BIP-03", category: "BIP", payor: "ALL", description: "Medical BIP -> all medical causes ruled out", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIP-04", category: "BIP", payor: "ALL", description: "All tantrum goals have a duration", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIP-05", category: "BIP", payor: "ALL", description: "Age-appropriate mastery criteria for behavior targets", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIP-06", category: "BIP", payor: "ALL", description: "Current level always indicated", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-BIP-07", category: "BIP", payor: "ALL", description: "Plan for client to disagree appropriately (non-compliance goals)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PREF-01", category: "Results of Preference Assessment", payor: "ALL", description: "Result of preference assessment completed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-MAST-01", category: "Mastered Goals", payor: "ALL", description: "Mastered goals within previous authorization dates", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-MAST-02", category: "Mastered Goals", payor: "ALL", description: "Mastered goals don't appear twice vs. previous TP", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-01", category: "Goals in Progress", payor: "ALL", description: "No school goals/ADL/group mentions unless requesting 97154", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-02", category: "Goals in Progress", payor: "ALL", description: "3mo/6mo graph data matches auth length", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-03", category: "Goals in Progress", payor: "ALL", description: "Severity rating check (moderate min, not all mild)", checkType: "deterministic", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-GIP-04", category: "Goals in Progress", payor: "ALL", description: "No mastery date shows 'invalid date'", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-05", category: "Goals in Progress", payor: "ALL", description: "Goal progress matches mastered goals (no contradiction/duplication)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-06", category: "Goals in Progress", payor: "ALL", description: "General goals fully completed and include a rationale", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-07", category: "Goals in Progress", payor: "ALL", description: "Goals open >6mo have rationale reviewed by Eliana", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "Director", active: true },
  { id: "QA-GIP-08", category: "Goals in Progress", payor: "ALL", description: "All goals match the POS", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-09", category: "Goals in Progress", payor: "ALL", description: "Goals indicate which are worked on in community", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-10", category: "Goals in Progress", payor: "ALL", description: "Sampling method consistent across baseline/current/sampling/mastery", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-11", category: "Goals in Progress", payor: "ALL", description: "Goals in behavioral context (SD, setting, expected response)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-12", category: "Goals in Progress", payor: "ALL", description: "Goals include verbal operant/behavioral term", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-13", category: "Goals in Progress", payor: "ALL", description: "At least 1 goal per hour (excl. Parent Training)", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-14", category: "Goals in Progress", payor: "ALL", description: "If data trending down, explanation provided", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-15", category: "Goals in Progress", payor: "ALL", description: "Info requested by last auth period included (per spreadsheet)", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "QA-GIP-16", category: "Goals in Progress", payor: "ALL", description: "Mastery criteria age/ASD-appropriate; no 0%, use 'fewer than one instance'", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-GIP-17", category: "Goals in Progress", payor: "ALL", description: "Goals observable/measurable with SD, deficit, expectation", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-PAR-01", category: "Parent/Caregiver Involvement", payor: "ALL", description: "3+ parent training goals/auth period, no 'caregiver' wording (or rationale if used)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-01", category: "Coordination of Care", payor: "ALL", description: "COC includes provider name/title/date; session note detailed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-02", category: "Coordination of Care", payor: "ALL", description: "COC completed with all related providers indicated (PCP, school, therapist)", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-03", category: "Coordination of Care", payor: "ALL", description: "TP indicates COC will be done once patient starts services", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-04", category: "Coordination of Care", payor: "ALL", description: "TP faxed to doctor within last 6 months", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-05", category: "Coordination of Care", payor: "ALL", description: "Date of COC not past end date of current report", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-COC-06", category: "Coordination of Care", payor: "ALL", description: "Date faxed to doctor includes month/day/year", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TRANS-01", category: "Transition Plan", payor: "ALL", description: "Patient-specific and realistic based on goals", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-TRANS-02", category: "Transition Plan", payor: "ALL", description: "Remove extra bullets/numbers", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-DISC-01", category: "Discharge Criteria", payor: "ALL", description: "Patient-specific and realistic based on goals", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-DISC-02", category: "Discharge Criteria", payor: "ALL", description: "Remove extra bullets/numbers", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-01", category: "Signatures", payor: "ALL", description: "Signature includes date signed", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-02", category: "Signatures", payor: "ALL", description: "Signature includes correct credentials", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-03", category: "Signatures", payor: "ALL", description: "Signature date before start of auth dates requested", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-04", category: "Signatures", payor: "ALL", description: "Signature date not >2 days after end date of current report", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-05", category: "Signatures", payor: "ALL", description: "BCBA signed the report", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-SIG-06", category: "Signatures", payor: "ALL", description: "If writing BCBA != case BCBA, both signed, clearly indicated", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "QA-DS-01", category: "Data Sheets", payor: "ALL", description: "BCBA created data sheets for the patient", checkType: "judgment", actionLane: "Facilitator-assign", actionTag: "General", active: true },
  { id: "HF-01", category: "Healthfirst-Specific", payor: "Healthfirst", description: "Patients >13: auth dates = 3-month range instead of 6", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "HF-02", category: "Healthfirst-Specific", payor: "Healthfirst", description: "No more than 5 hrs of 97151 (assessment) requested", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "HF-03", category: "Healthfirst-Specific", payor: "Healthfirst", description: "Community hours: TP states how many hours, where, and what goals", checkType: "judgment", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "SM-01", category: "Straight Medicaid-Specific", payor: "Straight Medicaid", description: "Auth start = day after current auth expires; auth end <= 6 months after current report end", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "SM-02", category: "Straight Medicaid-Specific", payor: "Straight Medicaid", description: "All hours are requested per week (not per day)", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "EMP-01", category: "Empire-Specific", payor: "Empire", description: "Date of current report within 30 days of authorization start date", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "EMP-02", category: "Empire-Specific", payor: "Empire", description: "Goal dates within 30 days of authorization start date", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "EMP-03", category: "Empire-Specific", payor: "Empire", description: "Signature date within 30 days of authorization start date", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "EMB-01", category: "Emblem-Specific", payor: "Emblem", description: "No more than 3 hrs of 97151 (assessment) requested", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
  { id: "AET-01", category: "Aetna-Specific", payor: "Aetna", description: "Testing tool restricted to Vineland/VB-MAPP/ABLLS; AFLS not allowed", checkType: "deterministic", actionLane: "BCBA-fix", actionTag: null, active: true },
];

// Which fake PDF page (see makePdf below) a given rule category's evidence
// would plausibly live on -- just for the "jump to page" links to point
// somewhere sensible, not a real mapping.
const CATEGORY_PAGE: Record<string, number> = {
  "Template": 1, "Report Information": 1, "Patient/Provider Info": 1,
  "Hours Requesting": 4, "School & ABA Schedule": 4,
  "Biopsychosocial": 2, "Problem Areas": 2, "Barriers to Treatment": 2, "Coordination of Care": 2,
  "Observations": 3, "Assessment of Current Functioning": 3, "Clinical Interpretation": 3, "Results of Preference Assessment": 3,
  "BIP": 6, "Transition Plan": 6, "Discharge Criteria": 6,
  "Mastered Goals": 5, "Goals in Progress": 5, "Parent/Caregiver Involvement": 5,
  "Signatures": 7, "Data Sheets": 7,
  "Healthfirst-Specific": 4, "Straight Medicaid-Specific": 4, "Empire-Specific": 4, "Emblem-Specific": 4, "Aetna-Specific": 4,
};

export type PdfPage = { page: number; title: string; body: string[] };

export type RuleResult = {
  ruleId: string;
  status: RuleStatus;
  finding: string;
  pages: number[];
  overridden?: boolean;
};

// --- V (finalized, permanent) vs. U (draft, disposable) --------------
//
// A PlanVersion (V) is the official, sequential TP record: V1 = Initial,
// V2 = the next Reassessment, and so on -- permanent once created, never
// renumbered, never deleted. A UAttempt (U) is a draft working upload made
// while preparing a single V-slot -- as many as needed (U1, U2, U3...),
// none of them permanent on their own. "Finalize as V[n]" is the only
// action that promotes one attempt into the next official version.

export type UAttempt = {
  id: string;
  attemptNumber: number;      // 1, 2, 3... scoped to the CURRENT open V-slot only;
                               // resets to 1 once that slot is finalized and a new one opens
  uploadedAt: string;
  assessmentDate: string;
  reviewerId: string;
  pdf: PdfPage[];
  // "processing" until the simulated agent-review delay elapses, then
  // "complete". `results`/`score`/`auditResult` are computed up front at
  // creation either way (the mock scripted-findings logic is deterministic,
  // not time-based) -- `status` only gates whether the UI is allowed to
  // show them yet, standing in for a real backend job that hasn't finished.
  status: "processing" | "complete";
  results: RuleResult[];
  score: number;
  auditResult: "Pass" | "Fail";
  // deliberately no `reviewed` field here -- "mark reviewed" is a
  // post-finalize, V-only action (see PlanVersion below).
};

// Simulated "agent is running" delay between attempt creation and results
// becoming visible -- stands in for the real rule-checking agent's actual
// run time (see AGENT_INTEGRATION_CONTRACT.md), which doesn't exist yet in
// this mock pass. 5-10s per spec.
export const PROCESSING_DELAY_MS_MIN = 5000;
export const PROCESSING_DELAY_MS_MAX = 10000;
export function randomProcessingDelayMs(): number {
  return PROCESSING_DELAY_MS_MIN + Math.random() * (PROCESSING_DELAY_MS_MAX - PROCESSING_DELAY_MS_MIN);
}

// Label for the not-yet-finalized slot a draft is currently pending against.
// A brand-new patient's first slot has no real version number yet -- calling
// it "V1" before anything is finalized implies a V1 already exists, which it
// doesn't. So the CURRENT, not-yet-finalized state is labeled "V0" for that
// one case only; every later slot (versionsCount >= 1) already has a real
// predecessor and keeps its normal "V[versionsCount + 1]" label unchanged.
// The "Finalize as V[n]" action itself never uses this -- it always names
// the real target being created, which for the first slot IS "V1".
export function pendingSlotLabel(versionsCount: number): string {
  return versionsCount === 0 ? "V0" : `V${versionsCount + 1}`;
}

export type PlanVersion = {
  version: number;
  finalizedAt: string;              // when "Finalize as V[n]" was clicked
  assessmentDate: string;
  reviewerId: string;
  pdf: PdfPage[];
  results: RuleResult[];
  score: number;
  auditResult: "Pass" | "Fail";
  reviewed: boolean;
  finalizedFromAttemptId?: string;  // traceability back to which U-attempt became this V
};

export type Patient = {
  refId: string;
  name: string;
  payor: Payor;
  versions: PlanVersion[];   // finalized, permanent -- the ONLY thing the version picker reads
  uAttempts: UAttempt[];     // drafts against the not-yet-finalized next V-slot; [] when nothing is in progress
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

// --- Mock rule-checking flow --------------------------------------------
// A small set of rules get a scripted, realistic finding that starts as a
// Fail and resolves to a Pass once the attempt number reaches
// `resolvesAtAttempt` -- this is what makes revise-and-reupload (U1 -> U2
// -> U3) demonstrate something real: the same rule's finding actually
// changes across attempts, same as a BCBA fixing an issue and reuploading
// would expect to see. Rules not listed here default to a generic Pass.
// A couple are scripted to N/A to demonstrate that lane too.
const SCRIPTED_FINDINGS: Record<string, {
  status: RuleStatus;
  finding: string;
  resolvesAtAttempt?: number;
  resolvedFinding?: string;
}> = {
  "QA-TEMP-04": {
    status: "Fail",
    finding: `Embedded reviewer comment still present in the document text ("Why are hours remaining the same?") -- all correspondence with the BCBA must be removed before finalizing.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `No embedded reviewer comments or correspondence found in the document text.`,
  },
  "QA-HRS-06": {
    status: "Fail",
    finding: `97153 hours increased from 25 to 30/week with no accompanying rationale narrative for the increase.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `97153 hours increased from 25 to 30/week; rationale narrative present on Page 4.`,
  },
  "QA-GIP-16": {
    status: "Fail",
    finding: `Goal 3 (Toileting) Mastery Criteria reads "0 accidents per week" -- a zero-value endpoint must instead read "fewer than one instance."`,
    resolvesAtAttempt: 2,
    resolvedFinding: `All goals' Mastery Criteria use "fewer than one instance" phrasing instead of a zero-value endpoint.`,
  },
  "QA-CI-01": {
    status: "Fail",
    finding: `Clinical Interpretation reads only "Client requires ABA services to address her needs and improve her skills" -- generic boilerplate, doesn't name specific findings or interventions.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `Clinical Interpretation names specific assessment findings and ties them to the chosen interventions.`,
  },
  "QA-ACF-07": {
    status: "Fail",
    finding: `Only one testing tool (VB-MAPP) found with a dated administration -- a second, previously-used tool with its own date is required to establish old vs. new.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `Both VB-MAPP and Vineland-3 are documented with distinct administration dates.`,
  },
  "QA-BIP-01": {
    status: "Fail",
    finding: `All 4 severity ratings are documented as Mild -- at least one must be Moderate or higher, or this needs Director review.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `At least one severity rating (Aggression: Moderate) is documented above Mild.`,
  },
  "QA-GIP-07": {
    status: "Fail",
    finding: `Goal 2 (Tacting) has been open for 8 months with no rationale for continuation reviewed by Eliana on file.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `Continuation rationale for all goals open >6mo is documented and flagged for Eliana's review.`,
  },
  "QA-OBS-03": {
    status: "Fail",
    finding: `No session note on file backing the observation described on Page 3 -- forwarded to QA.`,
    resolvesAtAttempt: 2,
    resolvedFinding: `Session note backing the observation is now on file.`,
  },
  "QA-PAR-01": {
    status: "Fail",
    finding: `Only 1 current parent-training goal found for this authorization period; at least 3 are required.`,
    resolvesAtAttempt: 3,
    resolvedFinding: `3 current parent-training goals documented for this authorization period.`,
  },
  "QA-DS-01": { status: "N/A", finding: `Data sheets are a separate artifact (Central Reach) -- not part of the TP document itself.` },
  "QA-BIO-16": { status: "N/A", finding: `No live Central Reach integration -- cannot verify school name against Central Reach from this document alone.` },
  "QA-PPI-01": { status: "N/A", finding: `No live Central Reach integration -- cannot verify patient info against Central Reach from this document alone.` },
};

function findingForRule(rule: Rule, attemptNumber: number): RuleResult {
  const page = CATEGORY_PAGE[rule.category] ?? 1;
  const scripted = SCRIPTED_FINDINGS[rule.id];
  if (scripted) {
    const resolved = scripted.resolvesAtAttempt !== undefined && attemptNumber >= scripted.resolvesAtAttempt;
    return {
      ruleId: rule.id,
      status: resolved ? "Pass" : scripted.status,
      finding: resolved ? (scripted.resolvedFinding ?? scripted.finding) : scripted.finding,
      pages: [page],
    };
  }
  return { ruleId: rule.id, status: "Pass", finding: "Reviewed against document text — no issues found.", pages: [page] };
}

/** The mock rule-checking flow: every active rule that applies to this
 * patient's payor (universal + payor-specific), run against a given
 * attempt number so scripted findings can resolve across revisions. */
export function runMockReview(payor: Payor, attemptNumber: number): RuleResult[] {
  return rules
    .filter(r => r.active && (r.payor === "ALL" || r.payor === payor))
    .map(r => findingForRule(r, attemptNumber));
}

export function scoreResults(results: RuleResult[]): { score: number; auditResult: "Pass" | "Fail" } {
  const nonNa = results.filter(r => r.status !== "N/A");
  const passed = nonNa.filter(r => r.status === "Pass").length;
  const score = nonNa.length ? Math.round((passed / nonNa.length) * 100) : 100;
  return { score, auditResult: score >= 85 ? "Pass" : "Fail" };
}

function buildVersion(
  version: number, patient: string, dob: string, memberId: string, payor: Payor,
  finalizedAt: string, assessmentDate: string, reviewerId: string,
  pdfOpts: Parameters<typeof makePdf>[3], reviewed: boolean, maturity: number,
): PlanVersion {
  const pdf = makePdf(patient, dob, memberId, pdfOpts);
  const results = runMockReview(payor, maturity);
  const { score, auditResult } = scoreResults(results);
  return { version, finalizedAt, assessmentDate, reviewerId, pdf, results, score, auditResult, reviewed };
}

export const initialPatients: Patient[] = [
  {
    refId: "TP-2026-0812", name: "Ethan Ramirez", payor: "Healthfirst",
    versions: [
      buildVersion(1, "Ethan Ramirez", "2019-04-12", "HF-8827321", "Healthfirst",
        daysAgo(120), daysAgo(125), "u2",
        { fbaDate: daysAgo(140), authStart: daysAgo(120), authEnd: daysAgo(120 - 180), bipIncluded: false, bcbaSigDate: daysAgo(120), parentSigDate: daysAgo(115) },
        true, 1),
      buildVersion(2, "Ethan Ramirez", "2019-04-12", "HF-8827321", "Healthfirst",
        daysAgo(35), daysAgo(40), "u2",
        { fbaDate: daysAgo(118), authStart: daysAgo(35), authEnd: daysAgo(35 - 180), bipIncluded: false, bcbaSigDate: daysAgo(35), parentSigDate: daysAgo(30) },
        false, 2),
    ],
    // Demo patient: 2 draft attempts already in progress against the not-yet-finalized V3 slot.
    uAttempts: [
      {
        id: "TP-2026-0812-u1", attemptNumber: 1, uploadedAt: daysAgo(5), assessmentDate: daysAgo(8), reviewerId: "u2", status: "complete",
        pdf: makePdf("Ethan Ramirez", "2019-04-12", "HF-8827321", { fbaDate: daysAgo(20), authStart: daysAgo(5), authEnd: daysAgo(5 - 180), bipIncluded: false, bcbaSigDate: daysAgo(5), parentSigDate: daysAgo(3) }),
        ...(() => { const results = runMockReview("Healthfirst", 1); return { results, ...scoreResults(results) }; })(),
      },
      {
        id: "TP-2026-0812-u2", attemptNumber: 2, uploadedAt: daysAgo(1), assessmentDate: daysAgo(8), reviewerId: "u2", status: "complete",
        pdf: makePdf("Ethan Ramirez", "2019-04-12", "HF-8827321", { fbaDate: daysAgo(20), authStart: daysAgo(1), authEnd: daysAgo(1 - 180), bipIncluded: false, bcbaSigDate: daysAgo(1), parentSigDate: daysAgo(1) }),
        ...(() => { const results = runMockReview("Healthfirst", 2); return { results, ...scoreResults(results) }; })(),
      },
    ],
  },
  {
    refId: "TP-2025-0102", name: "Sofia Chen-Alvarez", payor: "Emblem",
    versions: [
      buildVersion(1, "Sofia Chen-Alvarez", "2018-11-03", "EM-4491082", "Emblem",
        daysAgo(200), daysAgo(205), "u3",
        { fbaDate: daysAgo(215), authStart: daysAgo(200), authEnd: daysAgo(200 - 180), bipIncluded: true, bcbaSigDate: daysAgo(200), parentSigDate: daysAgo(198) },
        true, 1),
      buildVersion(2, "Sofia Chen-Alvarez", "2018-11-03", "EM-4491082", "Emblem",
        daysAgo(18), daysAgo(22), "u3",
        { fbaDate: daysAgo(30), authStart: daysAgo(18), authEnd: daysAgo(18 - 180), bipIncluded: true, bcbaSigDate: daysAgo(18), parentSigDate: daysAgo(15) },
        true, 3),
    ],
    uAttempts: [],
  },
  {
    refId: "TP-2026-0155", name: "Marcus Okonkwo", payor: "Anthem",
    versions: [
      buildVersion(1, "Marcus Okonkwo", "2020-07-22", "AN-7710948", "Anthem",
        daysAgo(10), daysAgo(14), "u1",
        { fbaDate: daysAgo(60), authStart: daysAgo(10), authEnd: daysAgo(10 - 180), bipIncluded: true, bcbaSigDate: daysAgo(10), parentSigDate: daysAgo(8) },
        false, 2),
    ],
    uAttempts: [],
  },
  {
    refId: "TP-2026-0201", name: "Ava Nakamura", payor: "Molina",
    versions: [
      buildVersion(1, "Ava Nakamura", "2017-01-30", "MO-3391172", "Molina",
        daysAgo(6), daysAgo(9), "u5",
        { fbaDate: daysAgo(200), authStart: daysAgo(6), authEnd: daysAgo(6 - 240), hoursNote: "97153 (Direct Therapy): recommended but hours not specified", bipIncluded: false, bcbaSigDate: daysAgo(6) },
        false, 1),
    ],
    uAttempts: [],
  },
  {
    refId: "TP-2026-0290", name: "Liam O'Sullivan", payor: "Aetna",
    versions: [
      buildVersion(1, "Liam O'Sullivan", "2021-08-14", "AE-2298811", "Aetna",
        daysAgo(3), daysAgo(5), "u2",
        { fbaDate: daysAgo(20), authStart: daysAgo(3), authEnd: daysAgo(3 - 180), bipIncluded: true, bcbaSigDate: daysAgo(3), parentSigDate: daysAgo(2) },
        true, 3),
    ],
    uAttempts: [],
  },
  {
    refId: "TP-2026-0304", name: "Aaliyah Washington", payor: "Cigna",
    versions: [
      buildVersion(1, "Aaliyah Washington", "2019-12-05", "CG-5528190", "Cigna",
        daysAgo(60), daysAgo(65), "u4",
        { fbaDate: daysAgo(75), authStart: daysAgo(60), authEnd: daysAgo(60 - 180), bipIncluded: true, bcbaSigDate: daysAgo(60), parentSigDate: daysAgo(58) },
        true, 2),
      buildVersion(2, "Aaliyah Washington", "2019-12-05", "CG-5528190", "Cigna",
        daysAgo(1), daysAgo(4), "u4",
        { fbaDate: daysAgo(15), authStart: daysAgo(1), authEnd: daysAgo(1 - 180), bipIncluded: true, bcbaSigDate: daysAgo(1), parentSigDate: daysAgo(1) },
        false, 3),
    ],
    uAttempts: [],
  },
  {
    refId: "TP-2026-0322", name: "Noah Blackwell", payor: "Healthfirst",
    versions: [
      buildVersion(1, "Noah Blackwell", "2020-03-19", "HF-9987214", "Healthfirst",
        daysAgo(45), daysAgo(50), "u1",
        { fbaDate: daysAgo(60), authStart: daysAgo(45), authEnd: daysAgo(45 - 180), bipIncluded: false, bcbaSigDate: daysAgo(45), parentSigDate: daysAgo(43) },
        true, 3),
    ],
    uAttempts: [],
  },
];

export const auditLog = [
  { at: "2026-07-14 14:32", user: "M. Chen", action: "Edited rule QA-GIP-16 (updated notes)", refId: "" },
  { at: "2026-07-14 11:18", user: "S. Patel", action: "Marked TP-2026-0812 v2 as Reviewed", refId: "TP-2026-0812" },
  { at: "2026-07-13 16:47", user: "J. Rivera", action: "Overrode answer for QA-GIP-06 (Pass → N/A)", refId: "TP-2025-0102" },
  { at: "2026-07-13 09:22", user: "A. Thompson", action: "Uploaded new draft attempt (U1)", refId: "TP-2026-0155" },
  { at: "2026-07-12 15:03", user: "L. Nguyen", action: "Created new rule QA-SIG-06", refId: "" },
  { at: "2026-07-12 10:41", user: "M. Chen", action: "Deactivated rule QA-GIP-15 (blocked, out of scope for V1)", refId: "" },
  { at: "2026-07-11 13:29", user: "S. Patel", action: "Sent correction email to reviewer", refId: "TP-2026-0201" },
  { at: "2026-07-10 17:12", user: "J. Rivera", action: "Marked TP-2026-0304 v1 as Reviewed", refId: "TP-2026-0304" },
  { at: "2026-07-10 08:55", user: "A. Thompson", action: "Finalized draft attempt as v2", refId: "TP-2026-0812" },
  { at: "2026-07-09 14:07", user: "M. Chen", action: "Edited notification default CC list", refId: "" },
];

export const invoices = [
  { date: "2026-07-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
  { date: "2026-06-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
  { date: "2026-05-01", amount: "$2,400.00", desc: "Monthly subscription — Pro tier" },
];
