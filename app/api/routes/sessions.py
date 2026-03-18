"""Session routes — CRUD, file upload, heatmap/grid image proxy."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user
from app.database import get_db
from app.models.db.session import Session, SessionStatus
from app.models.db.user import User
from app.models.db.zone_analytics import ZoneAnalytics
from app.models.schemas.session import SessionCreate, SessionListResponse, SessionResponse
from app.services.cv_client import CVEngineError, cv_client

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_session_response(session: Session, grid_data: list[list[float]] | None = None) -> SessionResponse:
    """Convert an ORM Session to a SessionResponse, optionally including grid data."""
    return SessionResponse(
        id=session.id,
        cv_job_id=session.cv_job_id,
        status=session.status.value,
        video_filename=session.video_filename,
        customer_count=session.customer_count,
        grid_data=grid_data,
        heatmap_image_url=f"/api/v1/sessions/{session.id}/heatmap" if session.cv_job_id else None,
        initial_grid_url=f"/api/v1/sessions/{session.id}/initial-grid" if session.cv_job_id else None,
        store_id=session.store_id,
        camera_id=session.camera_id,
        notes=session.notes,
        created_at=session.created_at,
        completed_at=session.completed_at,
    )


def _reconstruct_grid(zone_rows: list[ZoneAnalytics]) -> list[list[float]]:
    """Reconstruct 10x10 grid from zone_analytics rows."""
    grid: list[list[float]] = [[0.0] * 10 for _ in range(10)]
    for zone in zone_rows:
        grid[zone.row][zone.col] = round(float(zone.heat_value), 2)
    return grid


async def _get_user_session(
    db: AsyncSession,
    session_id: uuid.UUID,
    user: User,
    *,
    load_zones: bool = False,
) -> Session:
    """Load a session by ID, verifying ownership. Optionally eager-load zone_analytics."""
    query = select(Session).where(Session.id == session_id)
    if load_zones:
        query = query.options(selectinload(Session.zone_analytics))

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session or session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session


# ---------------------------------------------------------------------------
# Task 8.1 — Create Session
# ---------------------------------------------------------------------------

@router.post("", response_model=SessionResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_session(
    body: SessionCreate = Depends(),
    file: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new analysis session.

    Accepts either a multipart file upload or a video_path string.
    Dispatches a Celery process_video task and returns 202.
    """
    video_filename: str | None = None
    video_path: str | None = body.video_path

    if file:
        # Save uploaded file to a temporary location
        import os
        import aiofiles

        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        file_id = uuid.uuid4().hex
        safe_name = file.filename or "video.mp4"
        dest = os.path.join(upload_dir, f"{file_id}_{safe_name}")

        async with aiofiles.open(dest, "wb") as f:
            content = await file.read()
            await f.write(content)

        video_filename = safe_name
        video_path = dest

    if not video_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either a file upload or video_path must be provided",
        )

    session = Session(
        user_id=current_user.id,
        status=SessionStatus.QUEUED,
        video_filename=video_filename or video_path.rsplit("/", 1)[-1],
        video_path=video_path,
        store_id=body.store_id,
        camera_id=body.camera_id,
        notes=body.notes,
    )
    db.add(session)
    await db.flush()

    # Dispatch Celery task (imported lazily to avoid circular imports
    # and allow the module to load even when Celery isn't configured yet)
    try:
        from app.workers.tasks import process_video

        process_video.delay(str(session.id))
    except Exception:
        # If Celery isn't running, the session stays queued and can be
        # picked up later or retried manually.
        pass

    return _build_session_response(session)


# ---------------------------------------------------------------------------
# Task 8.2 — List Sessions
# ---------------------------------------------------------------------------

@router.get("", response_model=SessionListResponse)
async def list_sessions(
    status_filter: SessionStatus | None = Query(default=None, alias="status"),
    store_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List sessions belonging to the current user with optional filters."""
    base_query = select(Session).where(Session.user_id == current_user.id)

    if status_filter:
        base_query = base_query.where(Session.status == status_filter)
    if store_id:
        base_query = base_query.where(Session.store_id == store_id)

    # Total count
    count_query = select(func.count()).select_from(base_query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginated results
    items_query = (
        base_query
        .order_by(Session.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(items_query)
    sessions = result.scalars().all()

    return SessionListResponse(
        total=total,
        items=[_build_session_response(s) for s in sessions],
    )


# ---------------------------------------------------------------------------
# Task 8.3 — Get Session Detail
# ---------------------------------------------------------------------------

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get session details with reconstructed 10x10 grid data."""
    session = await _get_user_session(db, session_id, current_user, load_zones=True)
    grid_data = _reconstruct_grid(session.zone_analytics) if session.zone_analytics else None
    return _build_session_response(session, grid_data=grid_data)


# ---------------------------------------------------------------------------
# Task 8.4 — Proxy Heatmap Image
# ---------------------------------------------------------------------------

@router.get("/{session_id}/heatmap")
async def get_heatmap(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Proxy the heatmap image from the CV Engine."""
    session = await _get_user_session(db, session_id, current_user)

    if not session.cv_job_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No CV job associated with this session",
        )

    try:
        image_bytes = await cv_client.get_heatmap_image(session.cv_job_id)
    except CVEngineError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc

    return Response(content=image_bytes, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Task 8.5 — Proxy Initial Grid Image
# ---------------------------------------------------------------------------

@router.get("/{session_id}/initial-grid")
async def get_initial_grid(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Proxy the initial grid image from the CV Engine."""
    session = await _get_user_session(db, session_id, current_user)

    if not session.cv_job_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No CV job associated with this session",
        )

    try:
        image_bytes = await cv_client.get_initial_grid_image(session.cv_job_id)
    except CVEngineError as exc:
        raise HTTPException(
            status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
            detail=exc.message,
        ) from exc

    return Response(content=image_bytes, media_type="image/jpeg")


# ---------------------------------------------------------------------------
# Task 8.6 — Delete Session (soft delete)
# ---------------------------------------------------------------------------

@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a session by setting status to failed and clearing data references."""
    session = await _get_user_session(db, session_id, current_user)

    # Soft delete: mark as failed and nullify paths
    session.status = SessionStatus.FAILED
    session.video_path = None
    session.result_dir = None
    session.notes = f"[DELETED] {session.notes or ''}"
    await db.flush()

    return None
