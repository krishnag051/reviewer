"""No longer hollow (2026-07-30) — see CLAUDE.md's Boundaries section. This
calls into `agent-making` exclusively through `app.agent_client`
(Round 66) — never imports `pipeline.*` directly, and never will again;
that's the whole point of the new boundary. The boundary this backend must
never cross still holds: no rule-checking LOGIC lives here, only
translation between agent-making's rule_id/status vocabulary and this
backend's `RuleResultDraft` contract — that translation is exactly what
this file still owns, unchanged, now reading from `app.agent_client`'s
typed `ReviewResult`/`RuleResult` objects instead of a raw dict.

Rule identity: agent-making identifies rules by a human-readable code
string (`rule_id` in its own data, e.g. "QA-TEMP-01"). This backend
identifies rules by a UUID primary key (`rules.id`) and keeps the
human-readable code as `rules.rule_code`. The snapshot pinned to this
upload (`snapshot.rule_ids_and_versions`) is the authoritative list of
*backend* {rule.id, version} pairs — exactly like the old hollow stub used
it — so the real implementation below still iterates that list, and for
each entry looks up the matching backend Rule row to get its `rule_code`,
then finds agent-making's finding for that code. A backend UUID rule_id is
never sent to agent-making, and an agent-making rule_id string never
becomes a RuleResultDraft.rule_id directly — the snapshot's backend UUID
always is what's used there, matching upload_pipeline.py's
`uuid.UUID(draft.rule_id)` expectation.

For this mapping to produce anything other than "not_checkable" fallbacks
for every rule, the backend's `rules` table needs to actually contain
agent-making's real rule set (rule_code == agent-making's rule_id) — see
`scripts/seed.py::seed_rules` and `docs/BACKEND_IMPLEMENTATION_SUMMARY.md`'s
note on this reseed.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent_client import ReviewResult, RuleResult, review_intake_answers, review_session_notes, review_treatment_plan
from app.config import settings
from app.db.models import Rule, RuleSnapshot, Upload
from app.rule_engine.contract import RuleResultDraft

# agent-making's real result vocabulary -> this backend's rule_result_status
# enum. "not_applicable" collapses to the pre-existing "na" spelling;
# "not_checkable" is kept as its own value (migration ff6ae00976bd), not
# folded into "na" -- "the rule doesn't apply" (na) and "an answer couldn't
# be determined" (not_checkable -- payor detection failed, a deterministic
# checker found no matching text in this document, or no checker exists
# for this rule at all) are genuinely different findings for a reviewer.
_RESULT_TO_MODEL_STATUS = {
    "pass": "pass",
    "fail": "fail",
    "uncertain": "uncertain",
    "not_applicable": "na",
    "not_checkable": "not_checkable",
}
# Fix Round (2026-08-27): the reverse direction -- needed to hand a
# compound rule's phase-1 draft (already translated to this backend's own
# vocabulary) back to agent-making's combine_compound_rule_result, which
# only knows agent-making's own 4-value result vocabulary.
_MODEL_STATUS_TO_RESULT = {v: k for k, v in _RESULT_TO_MODEL_STATUS.items()}


def _drafts_from_review_result(
    review_result: ReviewResult, snapshot_entries: list[dict], rule_codes_by_id: dict[str, str],
) -> list[RuleResultDraft]:
    # agent-making's `results` list has one row per {page, detail} pair for
    # multi-page evidence (merge.py::_explode_to_rows, already applied by
    # app.agent_client before this ever sees it) -- this contract wants ONE
    # draft per rule, so re-group by rule_id first.
    rows_by_rule_id: dict[str, list[RuleResult]] = {}
    for row in review_result.results:
        rows_by_rule_id.setdefault(row.rule_id, []).append(row)

    drafts = []
    for entry in snapshot_entries:
        backend_rule_id = entry["rule_id"]
        rule_code = rule_codes_by_id.get(backend_rule_id)
        rows = rows_by_rule_id.get(rule_code) if rule_code else None

        if not rows:
            # No matching agent-making finding for this pinned rule -- either
            # the rule_code doesn't exist in agent-making's current rule set
            # (drift between the two rule sets) or the review itself failed
            # upstream of this rule ever being reached. Flag, don't guess.
            drafts.append(RuleResultDraft(
                rule_id=backend_rule_id,
                rule_version_used=entry["version"],
                model_status="not_checkable",
                model_finding=(
                    f"No matching finding from the rule-checking agent for rule_code "
                    f"{rule_code!r} (backend rule {backend_rule_id})."
                ),
                model_pages=[],
                model_source_quote=None,
            ))
            continue

        pages: list[int] = []
        for row in rows:
            pages.extend(row.page)
        details = list(dict.fromkeys(row.evidence for row in rows))  # de-dup, preserve order

        drafts.append(RuleResultDraft(
            rule_id=backend_rule_id,
            rule_version_used=entry["version"],
            model_status=_RESULT_TO_MODEL_STATUS[rows[0].status],
            model_finding="; ".join(details),
            model_pages=sorted(set(pages)),
            model_source_quote=None,
        ))
    return drafts


def _draft_from_session_notes_result(rule_result: RuleResult, backend_rule_id: str, version: int) -> RuleResultDraft:
    return RuleResultDraft(
        rule_id=backend_rule_id,
        rule_version_used=version,
        model_status=_RESULT_TO_MODEL_STATUS[rule_result.status],
        model_finding=rule_result.evidence,
        model_pages=rule_result.page,
        model_source_quote=None,
    )


def run_rule_checks(
    session: Session, upload_id: str, snapshot_id: str, parsed_pages: list[dict]
) -> list[RuleResultDraft]:
    """Real implementation. `parsed_pages` (this backend's own pdf_parser.py
    output) is intentionally unused here -- agent-making's pipeline does its
    own extraction end-to-end from a file path, it doesn't accept
    pre-parsed pages. `session` is used to look up the upload's real
    `file_path` (agent-making needs a real path, not parsed text) and to
    resolve the pinned snapshot's rule_ids against this backend's `rules`
    table for the rule_code translation described in this module's
    docstring.

    Raises on any pipeline failure (a non-"complete" ReviewResult) rather
    than returning something — `upload_pipeline.py`'s existing try/except
    around this call already rolls back and sets upload.status="error" +
    error_detail for any exception; this reuses that path rather than
    inventing a second one.

    Round 67: when this upload has session-note files attached, ALSO calls
    `app.agent_client.review_session_notes` and merges its QA-RPT-03/
    QA-ACF-02/QA-ACF-08 results into this SAME drafts list, overriding
    whatever the main TP-only `review_treatment_plan` call said for those
    exact 3 rule_ids -- that main call has no session-note data at all, so
    its own answer for these specific rules (typically "not_checkable" per
    their own rules.json notes) is never the real one once a session note
    is actually attached. Not a separate hidden result set: this is the
    one and only place these 3 rule_ids' drafts get built, same as every
    other rule.

    Deliberately still the free OpenRouter tier for this real backend call
    site, not real Anthropic -- see `review_session_notes`'s own docstring.
    Whether/when real backend usage should switch to actual billed Haiku
    calls (the original, pre-Round-56 production design) is a separate
    decision this round does NOT make -- flagged, not silently decided.
    """
    upload = session.get(Upload, uuid.UUID(upload_id))
    snapshot = session.get(RuleSnapshot, uuid.UUID(snapshot_id))

    # Fix Round (2026-08-27): the real fix for "is the intake schedule text
    # actually reaching the judgment call, or is it still reasoning blind" --
    # it wasn't. `extra_rule_context` gives QA-SCH-02's own judgment call
    # the real intake answer to read (the final schedule/POS comparison
    # itself stays a judgment call, deliberately -- see
    # pipeline/schedule_hours.py's own docstring for why -- but it's no
    # longer blind while making that call). `extra_fields` gives
    # _check_PPI05 (deterministic) the real intake BCBA NPI/credentials
    # answer as a second ground-truth source, alongside the old
    # document-mode supporting_doc field (dormant since structured_form
    # became the default -- confirmed real gap, see fields.py::
    # _check_PPI05's own updated docstring).
    extra_rule_context: dict[str, str] = {}
    extra_fields: dict[str, str] = {}
    if upload.intake_answers is not None:
        extra_rule_context["QA-SCH-02"] = (
            f"Patient Central Reach Information intake answer -- Schedule and POS: "
            f"{upload.intake_answers.pos_schedule_vs_97153_hours!r}. Hours Requesting: "
            f"{upload.intake_answers.hours_requesting!r}."
        )
        extra_fields["intake_bcba_name_credentials_npi"] = upload.intake_answers.bcba_name_credentials_npi

    result = review_treatment_plan(
        upload.file_path,
        supporting_doc_path=upload.supporting_document_path,
        # Round 86: the TP's real, client-supplied filename -- see
        # app/db/models.py::Upload.original_filename and
        # app/services/uploads.py::create_upload for where this is
        # captured. None for any upload row created before that column
        # existed; agent_client.py's own default keeps that inert/
        # backward-compatible, same as it's always been.
        source_filename=upload.original_filename,
        max_calls=settings.rule_engine_max_calls,
        extra_rule_context=extra_rule_context or None,
        extra_fields=extra_fields or None,
    )
    if result.status != "complete":
        error = result.error
        raise RuntimeError(
            f"rule-checking agent failed ({error.code if error else 'unknown'}): "
            f"{error.message if error else 'no message'}"
        )

    backend_rule_ids = [uuid.UUID(entry["rule_id"]) for entry in snapshot.rule_ids_and_versions]
    rule_codes_by_id = {
        str(r.id): r.rule_code
        for r in session.execute(select(Rule).where(Rule.id.in_(backend_rule_ids))).scalars().all()
    }

    drafts = _drafts_from_review_result(result, snapshot.rule_ids_and_versions, rule_codes_by_id)

    session_note_paths = {note.original_filename: note.file_path for note in upload.session_note_files}
    # Next Round (2026-08-27): QA-OBS-03's own simple, explicit fallback --
    # its notes are unambiguous: "if genuinely absent from the system,
    # treat as fail -> auto QA-tag by design," not left to judgment to
    # guess at from a TP that was never going to mention its own missing
    # session note. This is the minimum real fix: when NO session note was
    # uploaded at all, force this one rule's draft to fail. The harder half
    # (does an ATTACHED note genuinely "back" the TP's own observation/
    # assessment content) is NOT built here -- that's a real cross-
    # document semantic comparison the current extraction (5 narrow
    # structured fields, never the note's full text) can't answer; when a
    # note IS attached, this rule is left exactly as the main judgment call
    # already answered it, same as before this round.
    if not session_note_paths:
        obs03_backend_id = rule_codes_by_id and next(
            (bid for bid, code in rule_codes_by_id.items() if code == "QA-OBS-03"), None
        )
        if obs03_backend_id is not None:
            version_for_obs03 = next(
                (e["version"] for e in snapshot.rule_ids_and_versions if e["rule_id"] == obs03_backend_id), None
            )
            if version_for_obs03 is not None:
                drafts = [
                    RuleResultDraft(
                        rule_id=obs03_backend_id,
                        rule_version_used=version_for_obs03,
                        model_status="fail",
                        model_finding=(
                            "No session note was uploaded with this TP. This rule's own notes require "
                            "treating that as a fail (auto QA-tagged), not a guess based on the TP alone."
                        ),
                        model_pages=[],
                        model_source_quote=None,
                    ) if d.rule_id == obs03_backend_id else d
                    for d in drafts
                ]

    if session_note_paths:
        rule_id_by_code = {code: backend_id for backend_id, code in rule_codes_by_id.items()}
        draft_by_rule_id_pre = {d.rule_id: d for d in drafts}
        # Fix Round (2026-08-27): QA-COC-01's phase-1 draft (whatever the
        # main TP-only judgment call already decided, blind to session-note
        # data), translated back to agent-making's own vocabulary -- see
        # app/agent_client.py::review_session_notes and
        # pipeline/session_note_comparison.py::combine_compound_rule_result
        # for why this needs to be COMBINED, not overwritten.
        phase1_results: dict[str, RuleResult] = {}
        for compound_code in ("QA-COC-01",):
            backend_id = rule_id_by_code.get(compound_code)
            draft = draft_by_rule_id_pre.get(backend_id) if backend_id else None
            if draft is not None:
                phase1_results[compound_code] = RuleResult(
                    rule_id=compound_code,
                    # category is unused by the combine step below --
                    # never sent back out as a real RuleResult itself.
                    category="Unknown",
                    status=_MODEL_STATUS_TO_RESULT[draft.model_status],
                    page=draft.model_pages,
                    evidence=draft.model_finding,
                    confidence=None,
                )
        session_note_results = review_session_notes(
            upload.file_path,
            session_note_paths,
            model_override="openrouter",
            max_calls=settings.session_notes_max_calls,
            phase1_results=phase1_results,
        )
        version_by_backend_id = {entry["rule_id"]: entry["version"] for entry in snapshot.rule_ids_and_versions}
        draft_by_rule_id = dict(draft_by_rule_id_pre)
        for rr in session_note_results:
            backend_rule_id = rule_id_by_code.get(rr.rule_id)
            if backend_rule_id is None or backend_rule_id not in version_by_backend_id:
                continue  # this rule_code isn't part of the pinned snapshot -- nothing to override
            draft_by_rule_id[backend_rule_id] = _draft_from_session_notes_result(
                rr, backend_rule_id, version_by_backend_id[backend_rule_id],
            )
        drafts = list(draft_by_rule_id.values())  # dict overwrite preserves original insertion order

    # Fix Round (2026-08-26): same override mechanism as session notes above,
    # for the confirmed QA-SCH-02 gap -- review_treatment_plan never sees the
    # upload's Patient Central Reach Information intake answers at all, so
    # its own answer for QA-SCH-02 (not_checkable, per that rule's own notes)
    # is never the real one once real intake answers exist. `intake_answers`
    # is None for a document-mode upload (no structured Q&A collected at
    # all) -- nothing to override in that case.
    if upload.intake_answers is not None:
        rule_id_by_code = {code: backend_id for backend_id, code in rule_codes_by_id.items()}
        draft_by_rule_id_pre_intake = {d.rule_id: d for d in drafts}
        # Fix Round (2026-08-27): QA-SCH-02's own phase-1 draft, translated
        # back to agent-making's vocabulary -- same combine reasoning as
        # QA-COC-01 above (the judgment call is no longer blind now that
        # extra_rule_context carries the real intake answer, so its own
        # attempt deserves a chance to combine with, not be erased by, the
        # deterministic hours-only check below).
        sch02_phase1_results: dict[str, RuleResult] = {}
        backend_id = rule_id_by_code.get("QA-SCH-02")
        draft = draft_by_rule_id_pre_intake.get(backend_id) if backend_id else None
        if draft is not None:
            sch02_phase1_results["QA-SCH-02"] = RuleResult(
                rule_id="QA-SCH-02",
                category="Unknown",
                status=_MODEL_STATUS_TO_RESULT[draft.model_status],
                page=draft.model_pages,
                evidence=draft.model_finding,
                confidence=None,
            )
        intake_results = review_intake_answers(
            upload.file_path,
            pos_schedule_vs_97153_hours=upload.intake_answers.pos_schedule_vs_97153_hours,
            hours_requesting=upload.intake_answers.hours_requesting,
            phase1_results=sch02_phase1_results,
        )
        version_by_backend_id = {entry["rule_id"]: entry["version"] for entry in snapshot.rule_ids_and_versions}
        draft_by_rule_id = dict(draft_by_rule_id_pre_intake)
        for rr in intake_results:
            backend_rule_id = rule_id_by_code.get(rr.rule_id)
            if backend_rule_id is None or backend_rule_id not in version_by_backend_id:
                continue  # this rule_code isn't part of the pinned snapshot -- nothing to override
            # Reused as-is: this helper only ever builds a RuleResultDraft
            # from a RuleResult + backend_rule_id + version, nothing
            # session-notes-specific in its body.
            draft_by_rule_id[backend_rule_id] = _draft_from_session_notes_result(
                rr, backend_rule_id, version_by_backend_id[backend_rule_id],
            )
        drafts = list(draft_by_rule_id.values())

    return drafts
