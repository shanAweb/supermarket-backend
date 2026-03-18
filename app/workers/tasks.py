"""Celery tasks — video processing, RAG ingestion, nightly aggregation."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Task 9.2 — Process Video
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_video(self, session_id: str):
    """Coordinate video processing through the CV Engine.

    1. Load session from DB, set status to processing
    2. Submit job to CV Engine, save cv_job_id
    3. Poll until completion
    4. Persist results (customer_count, zone_analytics grid)
    5. Chain ingest_session task
    6. On failure: set status to failed
    """
    _run_async(_process_video_async(self, session_id))


async def _process_video_async(task, session_id: str):
    import asyncio as aio

    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models.db.session import Session, SessionStatus
    from app.models.db.zone_analytics import ZoneAnalytics
    from app.services.cv_client import CVEngineError, cv_client

    async with AsyncSessionLocal() as db:
        try:
            # 1. Load session
            result = await db.execute(select(Session).where(Session.id == session_id))
            session = result.scalar_one_or_none()
            if not session:
                logger.error("Session %s not found", session_id)
                return

            # 2. Update status to processing
            session.status = SessionStatus.PROCESSING
            await db.commit()

            # 3. Submit job to CV Engine
            try:
                cv_job_id = await cv_client.submit_job(session.video_path)
            except CVEngineError as exc:
                logger.error("CV Engine submission failed for session %s: %s", session_id, exc)
                session.status = SessionStatus.FAILED
                await db.commit()
                raise task.retry(exc=exc)

            # 4. Save cv_job_id
            session.cv_job_id = cv_job_id
            await db.commit()

            # 5. Poll for completion
            max_polls = 360  # 30 minutes at 5-second intervals
            for _ in range(max_polls):
                try:
                    status_data = await cv_client.get_job_status(cv_job_id)
                except CVEngineError as exc:
                    logger.warning("Poll failed for job %s: %s", cv_job_id, exc)
                    await aio.sleep(5)
                    continue

                job_status = status_data.get("status", "")

                if job_status == "completed":
                    # 6. Extract results
                    customer_count = status_data.get("customer_count", 0)
                    grid_data = status_data.get("grid_data", [])
                    result_dir = status_data.get("result_dir")
                    heatmap_path = status_data.get("heatmap_image_path")
                    initial_grid_path = status_data.get("initial_grid_path")

                    # 7. Write customer_count
                    session.customer_count = customer_count
                    session.result_dir = result_dir
                    session.heatmap_image_path = heatmap_path
                    session.initial_grid_path = initial_grid_path

                    # 8. Write 100 rows to zone_analytics (10x10 grid)
                    for row_idx, row_data in enumerate(grid_data):
                        for col_idx, heat_value in enumerate(row_data):
                            zone = ZoneAnalytics(
                                session_id=session.id,
                                row=row_idx,
                                col=col_idx,
                                heat_value=float(heat_value),
                            )
                            db.add(zone)

                    # 9. Update status to completed
                    session.status = SessionStatus.COMPLETED
                    session.completed_at = datetime.now(timezone.utc)
                    await db.commit()

                    logger.info(
                        "Session %s completed: %d customers, grid %dx%d",
                        session_id,
                        customer_count,
                        len(grid_data),
                        len(grid_data[0]) if grid_data else 0,
                    )

                    # 10. Chain ingest_session task
                    ingest_session.delay(session_id)
                    return

                elif job_status == "failed":
                    error_msg = status_data.get("error", "Unknown error")
                    logger.error("CV job %s failed: %s", cv_job_id, error_msg)
                    session.status = SessionStatus.FAILED
                    await db.commit()
                    return

                # Still processing — wait and poll again
                await aio.sleep(5)

            # Polling timeout
            logger.error("Polling timeout for CV job %s", cv_job_id)
            session.status = SessionStatus.FAILED
            await db.commit()

        except Exception:
            # 11. On any unhandled failure: set status to failed
            try:
                session.status = SessionStatus.FAILED
                await db.commit()
            except Exception:
                logger.exception("Failed to update session status after error")
            raise


# ---------------------------------------------------------------------------
# Task 9.3 — Ingest Session (RAG)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def ingest_session(self, session_id: str):
    """Ingest a completed session into ChromaDB for RAG queries.

    1. Load session + zone_analytics from DB
    2. Build text documents
    3. Embed and store in ChromaDB
    """
    _run_async(_ingest_session_async(self, session_id))


async def _ingest_session_async(task, session_id: str):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.database import AsyncSessionLocal
    from app.models.db.session import Session, SessionStatus

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.zone_analytics))
        )
        session = result.scalar_one_or_none()

        if not session:
            logger.error("Ingest: session %s not found", session_id)
            return

        if session.status != SessionStatus.COMPLETED:
            logger.warning("Ingest: session %s not completed (status=%s)", session_id, session.status)
            return

        try:
            from app.services.rag.ingestion import ingest

            await ingest(session_id, db)
            logger.info("Ingest completed for session %s", session_id)
        except ImportError:
            logger.warning("RAG ingestion module not yet implemented, skipping ingest for session %s", session_id)
        except Exception as exc:
            logger.error("Ingest failed for session %s: %s", session_id, exc)
            raise task.retry(exc=exc)


# ---------------------------------------------------------------------------
# Task 9.4 — Nightly Aggregation
# ---------------------------------------------------------------------------

@celery_app.task
def nightly_aggregation():
    """Aggregate sessions from the past 24 hours.

    Computes rolling zone averages per store for fast dashboard queries.
    """
    _run_async(_nightly_aggregation_async())


async def _nightly_aggregation_async():
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models.db.session import Session, SessionStatus
    from app.models.db.zone_analytics import ZoneAnalytics

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    async with AsyncSessionLocal() as db:
        # Find all sessions completed in the last 24 hours
        result = await db.execute(
            select(func.count())
            .select_from(Session)
            .where(
                Session.status == SessionStatus.COMPLETED,
                Session.completed_at >= cutoff,
            )
        )
        session_count = result.scalar() or 0

        if session_count == 0:
            logger.info("Nightly aggregation: no sessions in last 24h")
            return

        # Compute average heat per zone across recent sessions, grouped by store
        result = await db.execute(
            select(
                Session.store_id,
                ZoneAnalytics.row,
                ZoneAnalytics.col,
                func.avg(ZoneAnalytics.heat_value).label("avg_heat"),
            )
            .join(Session, ZoneAnalytics.session_id == Session.id)
            .where(
                Session.status == SessionStatus.COMPLETED,
                Session.completed_at >= cutoff,
            )
            .group_by(Session.store_id, ZoneAnalytics.row, ZoneAnalytics.col)
        )
        aggregates = result.all()

        logger.info(
            "Nightly aggregation: processed %d sessions, computed %d zone averages",
            session_count,
            len(aggregates),
        )

        # Aggregates are available for future use (e.g. storing in a
        # summary table for fast dashboard loading). For now we log the
        # results; a dedicated summary table can be added when needed.
        await db.commit()
