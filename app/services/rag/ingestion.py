"""Session ingestion — build text documents from session data and store in PageIndex."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.db.session import Session, SessionStatus
from app.models.db.zone_analytics import ZoneAnalytics
from app.services.rag.page_index import page_index


def build_session_document(session: Session, grid: list[list[float]]) -> dict:
    """Build a structured document from a completed session and its zone grid.

    The document contains:
    - metadata: session_id, store_id, camera_id, timestamps, customer_count
    - text: human-readable summary suitable for LLM context
    """
    # Identify hot and cold zones
    zones: list[tuple[int, int, float]] = []
    for r in range(len(grid)):
        for c in range(len(grid[r])):
            zones.append((r, c, grid[r][c]))

    zones_sorted = sorted(zones, key=lambda z: z[2], reverse=True)
    hot_zones = zones_sorted[:5]
    cold_zones = [z for z in zones_sorted if z[2] > 0][-5:] if any(z[2] > 0 for z in zones_sorted) else zones_sorted[-5:]

    # Build grid text representation
    grid_text_lines: list[str] = []
    for r, row in enumerate(grid):
        row_str = " ".join(f"{v:5.1f}" for v in row)
        grid_text_lines.append(f"  Row {r}: {row_str}")
    grid_text = "\n".join(grid_text_lines)

    # Build the text summary
    text_parts: list[str] = [
        f"Session ID: {session.id}",
        f"Store: {session.store_id or 'N/A'}",
        f"Camera: {session.camera_id or 'N/A'}",
        f"Video: {session.video_filename or 'N/A'}",
        f"Total Customers Detected: {session.customer_count or 0}",
        f"Completed At: {session.completed_at or 'N/A'}",
        f"Notes: {session.notes or 'None'}",
        "",
        "Heatmap Grid (10x10, values 0-100):",
        grid_text,
        "",
        "Top 5 Hottest Zones (most foot traffic):",
    ]

    for r, c, val in hot_zones:
        text_parts.append(f"  Zone ({r},{c}): {val:.1f}")

    text_parts.append("")
    text_parts.append("Top 5 Coldest Zones (least foot traffic):")
    for r, c, val in cold_zones:
        text_parts.append(f"  Zone ({r},{c}): {val:.1f}")

    return {
        "metadata": {
            "session_id": str(session.id),
            "store_id": session.store_id,
            "camera_id": session.camera_id,
            "customer_count": session.customer_count,
            "video_filename": session.video_filename,
            "completed_at": str(session.completed_at) if session.completed_at else None,
            "created_at": str(session.created_at) if session.created_at else None,
        },
        "grid": grid,
        "hot_zones": [(r, c, val) for r, c, val in hot_zones],
        "cold_zones": [(r, c, val) for r, c, val in cold_zones],
        "text": "\n".join(text_parts),
    }


def _reconstruct_grid(zone_rows: list[ZoneAnalytics]) -> list[list[float]]:
    """Reconstruct 10x10 grid from zone_analytics ORM rows."""
    grid: list[list[float]] = [[0.0] * 10 for _ in range(10)]
    for zone in zone_rows:
        grid[zone.row][zone.col] = round(float(zone.heat_value), 2)
    return grid


async def ingest(session_id: str, db: AsyncSession) -> None:
    """Ingest a completed session into the PageIndex.

    1. Load session + zone_analytics from DB
    2. Reconstruct the 10x10 grid
    3. Build a text document
    4. Store in PageIndex
    """
    sid = uuid.UUID(session_id)

    result = await db.execute(
        select(Session)
        .where(Session.id == sid)
        .options(selectinload(Session.zone_analytics))
    )
    session = result.scalar_one_or_none()

    if not session:
        raise ValueError(f"Session {session_id} not found")

    if session.status != SessionStatus.COMPLETED:
        raise ValueError(f"Session {session_id} is not completed (status={session.status})")

    grid = _reconstruct_grid(session.zone_analytics)
    document = build_session_document(session, grid)
    page_index.store(sid, document)
