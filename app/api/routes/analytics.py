"""Analytics routes — zone averages, rankings, customer counts, peak zones, comparison."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.db.user import User
from app.models.schemas.analytics import (
    ComparisonResponse,
    CustomerCountsResponse,
    PeakZonesResponse,
    ZoneGridResponse,
    ZoneRankingsResponse,
)
from app.services import analytics as analytics_service

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Task 10.1 — Zone Averages
# ---------------------------------------------------------------------------

@router.get("/zones", response_model=ZoneGridResponse)
async def get_zone_averages(
    store_id: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    session_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a 10x10 grid of average heat values across matching sessions."""
    grid = await analytics_service.get_zone_averages(
        db,
        current_user.id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    return ZoneGridResponse(grid=grid)


# ---------------------------------------------------------------------------
# Task 10.2 — Zone Rankings
# ---------------------------------------------------------------------------

@router.get("/zone-rankings", response_model=ZoneRankingsResponse)
async def get_zone_rankings(
    store_id: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    session_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all zones ranked by average heat, highest first."""
    rankings = await analytics_service.get_zone_rankings(
        db,
        current_user.id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    return ZoneRankingsResponse(rankings=rankings)


# ---------------------------------------------------------------------------
# Task 10.3 — Customer Counts
# ---------------------------------------------------------------------------

@router.get("/customer-counts", response_model=CustomerCountsResponse)
async def get_customer_counts(
    store_id: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    session_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return customer count time-series data across sessions."""
    data = await analytics_service.get_customer_counts(
        db,
        current_user.id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    return CustomerCountsResponse(data=data)


# ---------------------------------------------------------------------------
# Task 10.4 — Peak Zones
# ---------------------------------------------------------------------------

@router.get("/peak-zones", response_model=PeakZonesResponse)
async def get_peak_zones(
    top_n: int = Query(default=5, ge=1, le=100),
    store_id: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    session_ids: list[uuid.UUID] | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the top N hottest zones by average heat."""
    rankings = await analytics_service.get_peak_zones(
        db,
        current_user.id,
        top_n=top_n,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    return PeakZonesResponse(rankings=rankings)


# ---------------------------------------------------------------------------
# Task 10.5 — Session Comparison
# ---------------------------------------------------------------------------

@router.get("/comparison", response_model=ComparisonResponse)
async def get_session_comparison(
    session_a: uuid.UUID = Query(...),
    session_b: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compare two sessions — returns both grids and a computed delta grid."""
    result = await analytics_service.get_session_comparison(
        db,
        current_user.id,
        session_a,
        session_b,
    )
    return result
