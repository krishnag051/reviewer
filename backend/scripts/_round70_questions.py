"""Round 70, Item 1 — real, hand-authored plain-English question text for
every one of the 120 rules in agent-making/agent/rules/rules.json.

Why a separate module instead of editing rules.json by hand: 120 entries,
each needing its own real sentence, is much safer to get right (and to
diff/review) as one explicit Python dict than as manual JSON surgery.

IMPORTANT: this adds a NEW "question" field to each rule -- it does NOT
touch "description". agent-making's own judge.py/fields.py prompts and
deterministic checkers read "description" (and "notes") today; rewriting
that field would risk changing real judgment behavior, which is out of
scope for a frontend-display round. "question" is purely additive.

Run via: python scripts/apply_round70_questions.py (see that file).
"""

QUESTIONS = {
    # --- Template ---
    "QA-TEMP-01": "If the provider is a Limited Permit holder, is the correct template used, with credentials stated correctly and consistently throughout?",
    "QA-TEMP-02": "Does the treatment plan include a header and page numbers on every page?",
    "QA-TEMP-03": "Has all highlighted text been removed from the document?",
    "QA-TEMP-04": "Has all correspondence with the BCBA (reviewer comments, emails, embedded questions) been removed from the document?",
    "QA-TEMP-05": "Has every instance of \"RBT\" been changed to \"RBT/BT\" or \"BT\"?",
    # --- Report Information ---
    "QA-RPT-01": "Are all fields in the Report Information section completed?",
    "QA-RPT-02": "Is the date of the initial assessment carried onto this treatment plan?",
    "QA-RPT-03": "Do the dates of the current report match the 97151 assessment session notes?",
    "QA-RPT-04": "Are the requested authorization dates within 2 days of submission?",
    "QA-RPT-05": "Are the requested authorization dates accurate (a 6-month default based on the previous authorization's end date or the new insurance's start date)?",
    "QA-RPT-06": "Does the current report's end date fall before the start of the requested authorization dates?",
    # --- Patient/Provider Info ---
    "QA-PPI-01": "Does the patient information match what's on file in Central Reach?",
    "QA-PPI-02": "Is the patient's age correct and consistent everywhere it appears in the treatment plan?",
    "QA-PPI-03": "Is the patient's legal name spelled correctly and consistently throughout the document?",
    "QA-PPI-04": "Are the patient's payor and insurance ID correct?",
    "QA-PPI-05": "Are the provider's credentials, NPI, and license number correct and consistent?",
    # --- Hours Requesting ---
    "QA-HRS-01": "Do the requested 97153 hours match the coordinator's approval email?",
    "QA-HRS-02": "If more than 20 hours of 97153 are requested, is a note included on the review email to Eliana?",
    "QA-HRS-03": "Do supervision hours stay within the required ratio to direct hours, with clinical director approval documented if that ratio is exceeded?",
    "QA-HRS-04": "When group hours are requested, are there also more direct hours with a rationale tailored to this client's clinical needs?",
    "QA-HRS-05": "If fewer than 10 hours of 97153 are requested, is approval confirmed?",
    "QA-HRS-06": "If requested hours increased from the previous authorization, is a rationale for the increase in place?",
    "QA-HRS-07": "If hours increased, does the rationale compare against the client's previous mastery criteria?",
    "QA-HRS-08": "Do the requested CPT codes and hours match the insurance's billing codes guide?",
    "QA-HRS-09": "If services overlap with home health aide, speech, or OT, are the ABA goals clearly differentiated from those other services?",
    # --- School & ABA Schedule ---
    "QA-SCH-01": "Does the ABA schedule match the hours requested?",
    "QA-SCH-02": "Has the schedule been confirmed as accurate with the service coordinator?",
    "QA-SCH-03": "Does the ABA schedule avoid overlapping with the school schedule, unless the payor allows in-school services?",
    "QA-SCH-04": "If ABA services occur during the school day, have school hours been adjusted accordingly?",
    "QA-SCH-05": "Do the school hours in the schedule match the total stated under Educational History?",
    "QA-SCH-06": "If the schedule overlaps with a related therapy, has that therapy's schedule been added to the treatment plan?",
    "QA-SCH-07": "If more than 3 hours per day of 97153 are scheduled, has the clinical director approved it?",
    "QA-SCH-08": "Is the place of service correct (only home, office, school, or community)?",
    # --- Biopsychosocial ---
    "QA-BIO-01": "Is the Biopsychosocial section fully completed and consistent with the diagnostic report?",
    "QA-BIO-02": "Is the date of the most recent diagnosis carried onto the treatment plan?",
    "QA-BIO-03": "Does the treatment plan include any other applicable diagnosis (e.g., a secondary diagnosis)?",
    "QA-BIO-05": "Do the developmental history and the stated diagnosis avoid contradicting each other?",
    "QA-BIO-06": "If a medication is listed, is a reason stated for it, and, if it treats ADHD, is ADHD listed as a secondary diagnosis?",
    "QA-BIO-07": "Is the educational history presented in chronological order and consistent with the coordinator's information?",
    "QA-BIO-08": "For patients under 5 with community daytime hours, has the word \"school\" been replaced with \"community,\" \"daycare,\" or \"preschool\" as appropriate?",
    "QA-BIO-09": "For patients age 5 or older in Special Education, does the treatment plan indicate an active IEP?",
    "QA-BIO-10": "Do the educational history and Coordination of Care sections avoid contradicting each other?",
    "QA-BIO-11": "Does the treatment plan list any other services the child is currently receiving?",
    "QA-BIO-12": "Does the treatment plan include all Early Intervention (EI) services the child has received?",
    "QA-BIO-13": "Is the first day of ABA services with Master Faster carried onto the treatment plan?",
    "QA-BIO-14": "Is the client's history of ABA therapy with other providers fully documented?",
    "QA-BIO-15": "Does the treatment plan include the school's name?",
    "QA-BIO-16": "Does the school name match what's on file in Central Reach?",
    # --- Problem Areas ---
    "QA-PROB-01": "Are there at least 2 documented, evidenced problem areas each for Social, Communication, and Behavior, written in narrative format?",
    "QA-PROB-02": "Does each \"As evidenced by\" statement genuinely support and align with the goals listed?",
    "QA-PROB-03": "For patients under 5, do the described behaviors reflect a genuine ASD-related deficit, distinguishable from typical age-appropriate behavior?",
    # --- Observations ---
    "QA-OBS-01": "Was a patient observation completed?",
    "QA-OBS-02": "Are the observation location and date fully completed?",
    "QA-OBS-03": "Does a session note back up the observation (and if not, was it forwarded to QA)?",
    "QA-OBS-04": "Does the observation date fall within the report dates and before the testing tool's administration date?",
    # --- Assessment of Current Functioning ---
    "QA-ACF-01": "Are the assessment's date, location, and patient location all completed?",
    "QA-ACF-02": "Does the session note backing the assessment match its stated date and location?",
    "QA-ACF-03": "Is the assessment grid present with a legend showing colors, dates, and assessor?",
    "QA-ACF-04": "If the current assessment score is lower than the previous assessment, has this been flagged for Director review?",
    "QA-ACF-05": "Is the Assessment Summary Statement documented (not left blank)?",
    "QA-ACF-06": "Does the testing tool section name the assessor who administered it?",
    "QA-ACF-07": "Does the treatment plan include both an old and a new testing tool result (or two dated administrations of the same tool)?",
    "QA-ACF-08": "Does a session note back up the testing tool used (and if not, was it forwarded to QA)?",
    # --- Clinical Interpretation ---
    "QA-CI-01": "Is the Clinical Interpretation completed with a clear, client-specific, and detailed rationale?",
    # --- Barriers to Treatment ---
    "QA-BAR-01": "Does the treatment plan include at least one documented barrier to treatment?",
    # --- BIP ---
    "QA-BIP-01": "Is at least one severity rating moderate or higher (i.e., not all four ratings mild)?",
    "QA-BIP-02": "If any punishment procedures are used, is supporting data attached and clinical director approval documented?",
    "QA-BIP-03": "For a medically-related BIP, have all medical causes been ruled out and documented?",
    "QA-BIP-04": "Does every tantrum-reduction goal include a duration qualifier (e.g., sustained over a number of consecutive sessions)?",
    "QA-BIP-05": "Are the mastery criteria for behavior targets age-appropriate given the client's developmental and safety profile?",
    "QA-BIP-06": "Is the current level always indicated for each behavior target?",
    "QA-BIP-07": "Does the plan include a goal for the client to appropriately express disagreement or non-compliance?",
    # --- Results of Preference Assessment ---
    "QA-PREF-01": "Is the result of the preference assessment documented?",
    # --- Mastered Goals ---
    "QA-MAST-01": "Do the mastered goals fall within the previous authorization's dates?",
    "QA-MAST-02": "Do the mastered goals avoid duplicating goals already listed as mastered in the previous treatment plan?",
    # --- Goals in Progress ---
    "QA-GIP-01": "Does the treatment plan avoid mentioning school goals, ADLs, or group activities unless 97154 is being requested?",
    "QA-GIP-02": "Does the 3-month/6-month graph data match the length of the authorization?",
    "QA-GIP-03": "Is at least one severity rating moderate or higher (not all mild)?",
    "QA-GIP-04": "Does every goal have a valid Anticipated Mastery Date (none blank or showing \"Invalid Date\")?",
    "QA-GIP-05": "Is goal progress free of contradiction or duplication with the mastered goals list?",
    "QA-GIP-06": "Are the general goals fully completed and each supported by a rationale?",
    "QA-GIP-07": "For goals open more than 6 months, has the rationale been flagged for Director review?",
    "QA-GIP-08": "Do all goals match the authorized place of service?",
    "QA-GIP-09": "When community is an authorized place of service, do the goals indicate which ones are worked on in the community?",
    "QA-GIP-10": "Is the sampling method consistent across the baseline, current level, sampling, and mastery criteria fields for each goal?",
    "QA-GIP-11": "Is each goal written in full behavioral context (antecedent/SD, setting, and expected response)?",
    "QA-GIP-12": "Does each communication goal name a specific verbal operant or behavioral term (e.g., mand, tact)?",
    "QA-GIP-13": "Is there at least one goal per requested hour, excluding Parent Training?",
    "QA-GIP-14": "If a goal's data is trending downward, is an explanation provided?",
    "QA-GIP-15": "Is all information requested by the previous authorization period included, per the clinical spreadsheet?",
    "QA-GIP-16": "Are mastery criteria age/ASD-appropriate, avoiding a 0% or zero-occurrence endpoint in favor of \"fewer than one instance\" phrasing?",
    "QA-GIP-17": "Is each goal observable and measurable, stating the antecedent/SD, the deficit being addressed, and the expected response?",
    # --- Parent/Caregiver Involvement ---
    "QA-PAR-01": "Are there at least 3 parent-training goals for this authorization period, using \"parent\" rather than \"caregiver\" wording (or a documented rationale where \"caregiver\" is used)?",
    # --- Coordination of Care ---
    "QA-COC-01": "Does the Coordination of Care entry include the provider's name, title, and date, with a detailed session note?",
    "QA-COC-02": "Is Coordination of Care completed for all related providers (PCP, school, other therapists)?",
    "QA-COC-03": "Does the treatment plan state that Coordination of Care will occur once the patient starts services?",
    "QA-COC-04": "Was the treatment plan faxed to the doctor within the last 6 months?",
    "QA-COC-05": "Does the Coordination of Care date fall on or before the end date of the current report?",
    "QA-COC-06": "Does the date faxed to the doctor include the full month, day, and year?",
    # --- Transition Plan ---
    "QA-TRANS-01": "Is the Transition Plan patient-specific and realistic given the goals in this document?",
    "QA-TRANS-02": "Have any extra or duplicate bullet points/numbering been removed from the Transition Plan?",
    # --- Discharge Criteria ---
    "QA-DISC-01": "Are the Discharge Criteria patient-specific and realistic given the goals in this document?",
    "QA-DISC-02": "Have any extra or duplicate bullet points/numbering been removed from the Discharge Criteria?",
    # --- Signatures ---
    "QA-SIG-01": "Does the signature include the date it was signed?",
    "QA-SIG-02": "Does the signature include the correct credentials?",
    "QA-SIG-03": "Does the signature date fall before the start of the requested authorization dates?",
    "QA-SIG-04": "Is the signature date no more than 2 days after the end date of the current report?",
    "QA-SIG-05": "Did a BCBA sign the report?",
    "QA-SIG-06": "If the writing BCBA differs from the case BCBA, did both sign, with that clearly indicated?",
    # --- Data Sheets ---
    "QA-DS-01": "Did the BCBA create data sheets for this patient?",
    # --- Payor-specific ---
    "HF-01": "For Healthfirst, if the patient is over 13, is the authorization date range 3 months (instead of the usual 6)?",
    "HF-02": "For Healthfirst, are no more than 5 hours of 97151 (assessment) requested?",
    "HF-03": "For Healthfirst community hours, does the treatment plan state how many hours, where, and which goals are being worked on?",
    "SM-01": "For Straight Medicaid, does the authorization start the day after the current authorization expires, and end no more than 6 months after the current report's end date?",
    "SM-02": "For Straight Medicaid, are all hours requested per week (not per day)?",
    "EMP-01": "For Empire, is the date of the current report within 30 days of the authorization start date?",
    "EMP-02": "For Empire, are goal dates within 30 days of the authorization start date?",
    "EMP-03": "For Empire, is the signature date within 30 days of the authorization start date?",
    "EMB-01": "For Emblem, are no more than 3 hours of 97151 (assessment) requested?",
    "AET-01": "For Aetna, is the testing tool one of Vineland, VB-MAPP, or ABLLS (and not AFLS, which isn't allowed)?",
}
