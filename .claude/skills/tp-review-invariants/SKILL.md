---
name: tp-review-invariants
description: Consult this whenever writing or editing backend code that touches rule_results, uploads, versions, rules, or audit_log — specifically: overrides, finalize/void, rule edits, scoring, the sync tick, or any endpoint that mutates data. Also consult when writing tests for any of the above. Covers the exact transactional order, guard conditions, and audit-write pattern each of these operations requires — these are easy to get subtly wrong by writing "reasonable-looking" code that skips a guard or writes audit entries outside the transaction.
---

# TP Review — Mutation Conventions

This project is a healthcare-compliance tool. Every mutation below has a
specific, deliberate order — don't reorder steps or drop a guard because the
happy path "looks like it would work" without it. If unsure whether a
shortcut is safe, it isn't — check `docs/TP_Review_Gap_Analysis.md` for the
reasoning behind each guard before assuming it's optional.

## The audit-write pattern (applies to every mutation in this file)

Every operation below writes its audit_log row **inside the same DB
transaction** as the data change, using the one shared helper:

```python
from app.audit import record

record(
    session,               # same session/transaction as the mutation
    user_id=current_user.id,   # None only for scheduled/system jobs
    action="human-readable summary, e.g. 'Overrode R-034 on TP-2026-0500 v1/u2'",
    target_type="rule_result",
    target_id=rule_result.id,
    details={"final_status": {"from": "fail", "to": "pass"}},  # field-level diff, changed fields only
)
```

Never construct an `audit_log` row directly elsewhere. Never write it in a
separate transaction/commit after the fact — if the transaction rolls back,
the audit entry must roll back with it.

## Override (`PATCH /rule_results/:id`)

**2026-07-30, corrected — this is the final answer, reversing two earlier
wrong statements of this same guard (one said finalized-only, the next said
both):** overrides are **draft-only**. The real workflow is: the agent
flags each rule pass/fail/N-A with a finding and page number; a human
reviewer goes through the draft, corrects whatever the agent got wrong
(status, finding text, page numbers), and routes what needs fixing to BCBA
or wherever it belongs — all of this happens only while the upload is still
in progress. Once an upload is finalized, it's the final, locked document —
nothing about it changes again, ever, including via override.

Order matters:
1. **Check whether the parent `upload.is_final == true` FIRST, before the
   optimistic-lock check or anything else.** If true, reject with 409 —
   do not apply anything, do not touch the row lock. This is now the single
   most important guard in this operation (previously it gated a
   score-recompute step that no longer exists — see below).
2. Optimistic lock check: compare the `updated_at` the client sent against
   the current row; mismatch → 409, do not apply anything.
3. Apply only the fields present in the request body
   (`final_status` / `final_finding` / `final_pages` / `reason`), any subset,
   independently. Do not require all three together.
4. Set `is_overridden = true`, `last_edited_by`, `last_edited_at`.
5. Insert a `rule_result_edits` row with only the changed fields as
   `{field: {from, to}}`.
6. Write the audit entry (see pattern above).

**There is no score-recompute step anymore.** A draft upload's parent
version has no `score`/`audit_result` yet (those stay null until finalize
sets them together, once, from whatever `final_status` values exist at
that moment) — so there's nothing to recompute mid-draft, and finalized
uploads can no longer be overridden at all. `app/services/scoring.py::compute_score`
is called from exactly one place now: `finalize.py`.

All of the above happens in one transaction. Any failure after step 1 rolls
back everything, including the audit entries.

## Finalize (`POST /uploads/:id/finalize`)

Guards, checked in this order, each returning a specific 409 on failure:
1. `upload.status == "ready"` (not `processing`, not `error`)
2. `upload.voided == false`
3. No sibling upload in the same version already has `is_final == true`
4. **No `rule_result` on this upload has `final_status == "uncertain"`** —
   return the list of unresolved `rule_code`s in the 409 body so the frontend
   can point the reviewer at exactly what's blocking them.

If all four pass, in one transaction:
- `is_final = true` on this upload
- `purge_after = now() + app_config.retention_days` on every **non-voided**
  sibling upload in the same version
- Compute score/audit_result (via `scoring.py`) → write to `versions.score`,
  `versions.audit_result`, `versions.status = "finalized"`,
  `versions.final_upload_id`
- Audit entry

**There is no un-finalize endpoint. Do not add one**, even if a task
description implies it would be convenient — flag it back to the user instead.
A confirmation dialog on the frontend before this call is the only safety net
this operation gets, by design.

## Void (`POST /uploads/:id/void`)

Only allowed if `is_final == false`. Sets `voided=true`, `voided_by`,
`voided_at`, requires a `reason` in the request body (not optional — this is
what makes the disagreement/mistake data useful later). Voided uploads:
excluded from `/uploads/:id/diff` results, excluded from finalize-sibling
checks, and become purge-eligible immediately
(`purge_after = now()`) rather than waiting for a finalize event elsewhere in
the version.

## Rule edit (`PATCH /rules/:id`) and rule create (`POST /rules`)

**Creation** writes a `rule_version_history` row at `version=1` in the *same*
transaction as the `rules` insert — this is easy to forget because it "looks
done" without it (the rule works fine right up until someone edits it or a
snapshot needs to reference the original wording). Never ship a rule-create
path without this.

**Edit** order: (1) apply the diff to the live `rules` row + increment
`current_version`, (2) write a `rule_version_history` row capturing the
*post-change* state, tagged with the NEW `current_version` — written
immediately as that version becomes current, not deferred to the next edit,
(3) increment `rule_sync_state.pending_change_count`, (4) audit entry (using
the diff captured before step 1's mutation). Never skip step 2 — it's what
makes historical uploads' snapshots resolvable to exact wording later.

Do NOT write history at the *pre-change* state under the *old* version
number — that version was already documented (by creation, for v1, or by
the previous edit, for v2+), so it collides with the existing row on a
rule's first-ever edit (`uq_rule_version_history_rule_version`) and, more
generally, leaves the version a rule is *currently on* undocumented until
some later edit happens to write it. Writing the post-change content under
the new version number the moment it's created avoids both problems.

## Sync tick (scheduled job, not user-triggered)

If `pending_change_count == 0`, do nothing — don't publish an empty
no-op snapshot. If greater than 0, build the candidate snapshot from live
`rules`, compare its `content_hash` against the current snapshot's; if
identical (an edit that reverted to the same state), skip publishing and just
reset the counter. Otherwise: insert the new `rule_snapshots` row, repoint
`rule_sync_state.current_snapshot_id`, reset `last_synced_at` / `next_sync_at`
/ `pending_change_count`. Audit entry with `user_id=None`.

## Writing tests for any of the above

Each guard/step above corresponds to a required test in
`docs/TP_Review_Master_Build_Document.md` §8. When adding a new mutation
endpoint not covered here, ask whether it needs its own guard section in this
file before assuming the general audit pattern is sufficient.
