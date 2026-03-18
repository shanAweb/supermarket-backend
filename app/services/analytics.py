"""Analytics service — query and aggregate zone heatmap and customer count data."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db.customer_count import CustomerCount
from app.models.db.session import Session
from app.models.db.zone_analytics import ZoneAnalytics


def _build_zone_query_filters(
    query: Any,
    *,
    user_id: uuid.UUID,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> Any:
    """Apply common filters (ownership, session_ids, store_id, date range) to a zone query."""
    query = query.join(Session, ZoneAnalytics.session_id == Session.id)
    query = query.where(Session.user_id == user_id)

    if session_ids:
        query = query.where(Session.id.in_(session_ids))
    if store_id:
        query = query.where(Session.store_id == store_id)
    if from_date:
        query = query.where(Session.created_at >= from_date)
    if to_date:
        query = query.where(Session.created_at <= to_date)

    return query


async def get_zone_averages(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[list[float]]:
    """Return a 10x10 grid of average heat values across matching sessions."""
    query = select(
        ZoneAnalytics.row,
        ZoneAnalytics.col,
        func.avg(ZoneAnalytics.heat_value).label("avg_heat"),
    ).group_by(ZoneAnalytics.row, ZoneAnalytics.col)

    query = _build_zone_query_filters(
        query,
        user_id=user_id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )

    result = await db.execute(query)
    rows = result.all()

    # Initialize 10x10 grid with zeros
    grid: list[list[float]] = [[0.0] * 10 for _ in range(10)]
    for row_idx, col_idx, avg_heat in rows:
        grid[row_idx][col_idx] = round(float(avg_heat), 2)

    return grid


async def get_zone_rankings(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return all zones ranked by average heat (descending)."""
    query = select(
        ZoneAnalytics.row,
        ZoneAnalytics.col,
        func.avg(ZoneAnalytics.heat_value).label("avg_heat"),
    ).group_by(ZoneAnalytics.row, ZoneAnalytics.col)

    query = _build_zone_query_filters(
        query,
        user_id=user_id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    query = query.order_by(func.avg(ZoneAnalytics.heat_value).desc())

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "row": r,
            "col": c,
            "avg_heat": round(float(avg), 2),
            "label": f"Zone ({r}, {c})",
        }
        for r, c, avg in rows
    ]


async def get_customer_counts(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return customer count time-series data across sessions."""
    query = (
        select(
            Session.id.label("session_id"),
            Session.created_at,
            Session.customer_count,
        )
        .where(Session.user_id == user_id)
        .where(Session.customer_count.is_not(None))
    )

    if session_ids:
        query = query.where(Session.id.in_(session_ids))
    if store_id:
        query = query.where(Session.store_id == store_id)
    if from_date:
        query = query.where(Session.created_at >= from_date)
    if to_date:
        query = query.where(Session.created_at <= to_date)

    query = query.order_by(Session.created_at.asc())

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "session_id": row.session_id,
            "created_at": row.created_at,
            "customer_count": row.customer_count,
        }
        for row in rows
    ]


async def get_peak_zones(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    top_n: int = 5,
    session_ids: list[uuid.UUID] | None = None,
    store_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the top N hottest zones by average heat."""
    query = select(
        ZoneAnalytics.row,
        ZoneAnalytics.col,
        func.avg(ZoneAnalytics.heat_value).label("avg_heat"),
    ).group_by(ZoneAnalytics.row, ZoneAnalytics.col)

    query = _build_zone_query_filters(
        query,
        user_id=user_id,
        session_ids=session_ids,
        store_id=store_id,
        from_date=from_date,
        to_date=to_date,
    )
    query = query.order_by(func.avg(ZoneAnalytics.heat_value).desc()).limit(top_n)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "row": r,
            "col": c,
            "avg_heat": round(float(avg), 2),
            "label": f"Zone ({r}, {c})",
        }
        for r, c, avg in rows
    ]


async def get_session_comparison(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_a_id: uuid.UUID,
    session_b_id: uuid.UUID,
) -> dict[str, Any]:
    """Compare two sessions by computing per-zone heat deltas.

    Returns grids for both sessions and a delta grid (A - B).
    """

    async def _load_grid(session_id: uuid.UUID) -> list[list[float]]:
        query = (
            select(ZoneAnalytics.row, ZoneAnalytics.col, ZoneAnalytics.heat_value)
            .join(Session, ZoneAnalytics.session_id == Session.id)
            .where(ZoneAnalytics.session_id == session_id)
            .where(Session.user_id == user_id)
        )
        result = await db.execute(query)
        rows = result.all()

        grid: list[list[float]] = [[0.0] * 10 for _ in range(10)]
        for r, c, val in rows:
            grid[r][c] = round(float(val), 2)
        return grid

    grid_a = await _load_grid(session_a_id)
    grid_b = await _load_grid(session_b_id)

    # Compute delta: A - B
    delta: list[list[float]] = [
        [round(grid_a[r][c] - grid_b[r][c], 2) for c in range(10)]
        for r in range(10)
    ]

    return {
        "session_a": {"id": session_a_id, "grid": grid_a},
        "session_b": {"id": session_b_id, "grid": grid_b},
        "delta": delta,
    }
