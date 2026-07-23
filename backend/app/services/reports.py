import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Rule, User, Version

WEEKS_IN_VOLUME_CHART = 4


def resolve_date_range(
    range_: str, start: date | None, end: date | None
) -> tuple[datetime | None, datetime | None]:
    """Turns the range selector into an inclusive [from, to] UTC datetime
    pair, or (None, None) for "all time" (no filtering at all).
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    if range_ == "week":
        monday = today - timedelta(days=today.weekday())
        return datetime.combine(monday, datetime.min.time(), tzinfo=timezone.utc), now

    if range_ == "lastweek":
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        return (
            datetime.combine(last_monday, datetime.min.time(), tzinfo=timezone.utc),
            datetime.combine(this_monday, datetime.min.time(), tzinfo=timezone.utc) - timedelta(microseconds=1),
        )

    if range_ == "30d":
        return now - timedelta(days=30), now

    if range_ == "all":
        return None, None

    if range_ == "custom":
        if start is None or end is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "custom_range_requires_start_end",
                    "message": "start and end are required when range=custom",
                },
            )
        return (
            datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
            datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc),
        )

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "invalid_range", "message": f"unknown range {range_!r}"},
    )


def _finalized_versions_in_range(session: Session, from_dt: datetime | None, to_dt: datetime | None) -> list[Version]:
    query = select(Version).where(Version.status == "finalized")
    if from_dt is not None:
        query = query.where(Version.finalized_at >= from_dt)
    if to_dt is not None:
        query = query.where(Version.finalized_at <= to_dt)
    return list(session.execute(query).scalars().all())


def _weekly_volume(session: Session) -> list[dict]:
    """Last 4 calendar weeks (Mon-Sun), always — independent of whatever
    range the summary counts/per-reviewer breakdown are filtered to. Matches
    the reference UI, where this chart is its own fixed "last 4 weeks" view.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    this_monday = today - timedelta(days=today.weekday())

    weeks = []
    for i in range(WEEKS_IN_VOLUME_CHART - 1, -1, -1):
        week_start = this_monday - timedelta(days=7 * i)
        week_end = week_start + timedelta(days=7)
        start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(week_end, datetime.min.time(), tzinfo=timezone.utc)
        versions = session.execute(
            select(Version).where(
                Version.status == "finalized",
                Version.finalized_at >= start_dt,
                Version.finalized_at < end_dt,
            )
        ).scalars().all()
        weeks.append({
            "week_start": week_start.isoformat(),
            "pass_count": sum(1 for v in versions if v.audit_result == "pass"),
            "fail_count": sum(1 for v in versions if v.audit_result == "fail"),
        })
    return weeks


def get_overview(
    session: Session, range_: str, start: date | None, end: date | None
) -> dict:
    """GET /reports/overview. Only FINALIZED versions are counted anywhere
    in this report — a version with no final upload yet has no audit_result
    to count, and must not silently show up as anything (not a pass, not a
    fail, not "processed").
    """
    from_dt, to_dt = resolve_date_range(range_, start, end)
    versions = _finalized_versions_in_range(session, from_dt, to_dt)

    processed = len(versions)
    passed = sum(1 for v in versions if v.audit_result == "pass")
    failed = sum(1 for v in versions if v.audit_result == "fail")

    reviewer_ids = {v.reviewer_id for v in versions if v.reviewer_id is not None}
    users_by_id = {
        u.id: u for u in session.execute(select(User).where(User.id.in_(reviewer_ids))).scalars().all()
    }

    by_reviewer: dict[uuid.UUID | None, list[Version]] = {}
    for v in versions:
        by_reviewer.setdefault(v.reviewer_id, []).append(v)

    per_reviewer = []
    for reviewer_id, vs in by_reviewer.items():
        p = sum(1 for v in vs if v.audit_result == "pass")
        f = sum(1 for v in vs if v.audit_result == "fail")
        total = len(vs)
        per_reviewer.append({
            "reviewer_id": reviewer_id,
            "reviewer_name": users_by_id[reviewer_id].name if reviewer_id in users_by_id else None,
            "processed": total,
            "passed": p,
            "failed": f,
            "pass_rate": round(p / total * 100, 1) if total else 0.0,
        })
    per_reviewer.sort(key=lambda r: r["reviewer_name"] or "")

    return {
        "range": range_,
        "processed": processed,
        "passed": passed,
        "failed": failed,
        "passed_pct": round(passed / processed * 100, 1) if processed else 0.0,
        "failed_pct": round(failed / processed * 100, 1) if processed else 0.0,
        "weekly_volume": _weekly_volume(session),
        "per_reviewer": per_reviewer,
    }


def get_trends(session: Session, group_by: str) -> dict:
    """GET /reports/trends. Queries v_override_analytics — does not
    re-derive the rule_results/uploads/versions/rules join or the finalized-
    only filter here; that's exactly what the view already does. This
    function only pivots the view's pre-aggregated (rule_code, direction,
    count, reviewer, payor, month) rows into a reviewer-or-question_set ×
    rule_code pass-rate matrix.

    group_by="provider": rows = reviewer, cell = that reviewer's pass rate
    for that rule (summed across all their finalized audits, all payors/
    months).
    group_by="questionset": rows = question_set (via rules.question_set);
    each cell aggregates across ALL reviewers, populated only for rule_codes
    that belong to that question_set. (This mode's exact semantics are
    genuinely ambiguous in the source material — flagged separately.)

    "Average" per row is a count-weighted average (sum of that row's own
    pass counts / sum of that row's own total counts), not a plain mean of
    the row's percentages.
    """
    rows = session.execute(
        text("SELECT rule_code, direction, count, reviewer, payor, month FROM v_override_analytics")
    ).all()

    pass_counts: dict[tuple, int] = {}
    total_counts: dict[tuple, int] = {}
    for rule_code, direction, count, reviewer, _payor, _month in rows:
        key = (reviewer, rule_code)
        total_counts[key] = total_counts.get(key, 0) + count
        if direction.endswith("_pass"):
            pass_counts[key] = pass_counts.get(key, 0) + count

    if group_by == "provider":
        reviewer_ids = {k[0] for k in total_counts if k[0] is not None}
        users_by_id = {
            u.id: u for u in session.execute(select(User).where(User.id.in_(reviewer_ids))).scalars().all()
        }
        matrix = []
        for reviewer_id in reviewer_ids:
            cells: dict[str, float] = {}
            row_pass = row_total = 0
            for (r, rule_code), total in total_counts.items():
                if r != reviewer_id:
                    continue
                p = pass_counts.get((r, rule_code), 0)
                cells[rule_code] = round(p / total * 100, 1)
                row_pass += p
                row_total += total
            matrix.append({
                "row_key": str(reviewer_id),
                "row_label": users_by_id[reviewer_id].name if reviewer_id in users_by_id else str(reviewer_id),
                "cells": cells,
                "average": round(row_pass / row_total * 100, 1) if row_total else None,
            })
        matrix.sort(key=lambda r: r["row_label"])
        return {"group_by": "provider", "rows": matrix}

    if group_by == "questionset":
        rule_codes = {k[1] for k in total_counts}
        rules_by_code = {
            r.rule_code: r for r in session.execute(select(Rule).where(Rule.rule_code.in_(rule_codes))).scalars().all()
        }

        qs_pass: dict[tuple, int] = {}
        qs_total: dict[tuple, int] = {}
        for (reviewer, rule_code), total in total_counts.items():
            rule = rules_by_code.get(rule_code)
            if rule is None:
                continue
            key = (rule.question_set, rule_code)
            qs_total[key] = qs_total.get(key, 0) + total
            qs_pass[key] = qs_pass.get(key, 0) + pass_counts.get((reviewer, rule_code), 0)

        question_sets = {k[0] for k in qs_total}
        matrix = []
        for qs in question_sets:
            cells = {}
            row_pass = row_total = 0
            for (q, rule_code), total in qs_total.items():
                if q != qs:
                    continue
                p = qs_pass.get((q, rule_code), 0)
                cells[rule_code] = round(p / total * 100, 1)
                row_pass += p
                row_total += total
            matrix.append({
                "row_key": qs,
                "row_label": qs,
                "cells": cells,
                "average": round(row_pass / row_total * 100, 1) if row_total else None,
            })
        matrix.sort(key=lambda r: r["row_label"])
        return {"group_by": "questionset", "rows": matrix}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"error": "invalid_group_by", "message": f"unknown group_by {group_by!r}"},
    )
