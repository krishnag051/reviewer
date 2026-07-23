import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.deps import get_current_user
from app.services.reports import get_overview, get_trends

router = APIRouter(prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user)])


class WeeklyVolumeEntry(BaseModel):
    week_start: str
    pass_count: int
    fail_count: int


class PerReviewerEntry(BaseModel):
    reviewer_id: uuid.UUID | None
    reviewer_name: str | None
    processed: int
    passed: int
    failed: int
    pass_rate: float


class OverviewOut(BaseModel):
    range: str
    processed: int
    passed: int
    failed: int
    passed_pct: float
    failed_pct: float
    weekly_volume: list[WeeklyVolumeEntry]
    per_reviewer: list[PerReviewerEntry]


class TrendsRow(BaseModel):
    row_key: str
    row_label: str
    cells: dict[str, float]
    average: float | None


class TrendsOut(BaseModel):
    group_by: str
    rows: list[TrendsRow]


@router.get("/overview", response_model=OverviewOut)
def reports_overview(
    range: Literal["week", "lastweek", "30d", "all", "custom"] = "30d",
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    return get_overview(db, range, start, end)


@router.get("/trends", response_model=TrendsOut)
def reports_trends(
    group_by: Literal["provider", "questionset"] = "provider",
    db: Session = Depends(get_db),
) -> dict:
    return get_trends(db, group_by)
