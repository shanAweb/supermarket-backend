"""Insights routes — RAG query (streaming), auto-insights, manual ingestion."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.db.session import Session, SessionStatus
from app.models.db.user import User
from app.models.schemas.insights import AutoInsightResponse, InsightQueryRequest
from app.services.rag import pipeline as rag_pipeline
from app.services.rag.ingestion import ingest

router = APIRouter(prefix="/api/v1/insights", tags=["insights"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_session_ownership(
    db: AsyncSession,
    session_id: uuid.UUID,
    user: User,
) -> Session:
    """Verify a session exists and belongs to the current user."""
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()

    if not session or session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return session


# ---------------------------------------------------------------------------
# Task 13.1 — RAG Query Endpoint (Streaming)
# ---------------------------------------------------------------------------

@router.post("/query")
async def query_insights(
    body: InsightQueryRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question about session data. Returns streamed Claude response via SSE."""
    # Verify ownership of requested sessions
    if body.session_ids:
        for sid in body.session_ids:
            await _verify_session_ownership(db, sid, current_user)

    async def event_stream():
        async for token in rag_pipeline.query(
            question=body.question,
            session_ids=body.session_ids,
            store_id=body.store_id,
        ):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Task 13.2 — Auto-Insight Endpoint
# ---------------------------------------------------------------------------

@router.get("/auto/{session_id}", response_model=AutoInsightResponse)
async def auto_insight(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a structured insight report for a completed session."""
    session = await _verify_session_ownership(db, session_id, current_user)

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session must be completed before generating insights",
        )

    try:
        result = await rag_pipeline.auto_insight(session_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    return result


# ---------------------------------------------------------------------------
# Task 13.3 — Manual Ingestion Trigger
# ---------------------------------------------------------------------------

@router.post("/ingest/{session_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger RAG ingestion for a completed session."""
    session = await _verify_session_ownership(db, session_id, current_user)

    if session.status != SessionStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only completed sessions can be ingested",
        )

    try:
        await ingest(str(session_id), db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return {"message": f"Session {session_id} ingested successfully"}
