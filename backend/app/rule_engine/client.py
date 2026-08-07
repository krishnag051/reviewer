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

from app.agent_client import ReviewResult, RuleResult, review_session_notes, review_treatment_plan
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

    result = review_treatment_plan(
        upload.file_path,
        supporting_doc_path=upload.supporting_document_path,
        max_calls=settings.rule_engine_max_calls,
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
    if session_note_paths:
        session_note_results = review_session_notes(
            upload.file_path,
            session_note_paths,
            model_override="openrouter",
            max_calls=settings.session_notes_max_calls,
        )
        rule_id_by_code = {code: backend_id for backend_id, code in rule_codes_by_id.items()}
        version_by_backend_id = {entry["rule_id"]: entry["version"] for entry in snapshot.rule_ids_and_versions}
        draft_by_rule_id = {d.rule_id: d for d in drafts}
        for rr in session_note_results:
            backend_rule_id = rule_id_by_code.get(rr.rule_id)
            if backend_rule_id is None or backend_rule_id not in version_by_backend_id:
                continue  # this rule_code isn't part of the pinned snapshot -- nothing to override
            draft_by_rule_id[backend_rule_id] = _draft_from_session_notes_result(
                rr, backend_rule_id, version_by_backend_id[backend_rule_id],
            )
        drafts = list(draft_by_rule_id.values())  # dict overwrite preserves original insertion order

    return drafts
