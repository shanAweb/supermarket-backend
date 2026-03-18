"""WebSocket streaming route — relay SSE frames from CV Engine to browser clients."""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.websocket_manager import ws_manager
from app.services.cv_client import CVEngineError, cv_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


@router.websocket("/ws/stream/{cv_job_id}")
async def stream_frames(websocket: WebSocket, cv_job_id: str):
    """Relay processed frames from the CV Engine SSE stream to WebSocket clients.

    Flow:
    1. Accept WebSocket connection and register in WebSocketManager
    2. Open SSE connection to CV Engine /stream/{cv_job_id}
    3. For each SSE event, forward parsed JSON to the WebSocket client
    4. On "done" event, close all connections for this job
    5. On client disconnect, cancel the SSE relay task
    6. Support multiple clients per cv_job_id via WebSocketManager
    """
    await ws_manager.connect(cv_job_id, websocket)
    logger.info(
        "WebSocket connected for job %s (total: %d)",
        cv_job_id,
        ws_manager.get_connection_count(cv_job_id),
    )

    sse_task: asyncio.Task | None = None

    try:
        # Start SSE relay in a background task so we can also listen
        # for client disconnects on the WebSocket side.
        sse_task = asyncio.create_task(_relay_sse(cv_job_id))

        # Keep the connection alive by reading client messages.
        # We don't expect meaningful messages from the client, but
        # this loop will raise WebSocketDisconnect when they leave.
        while True:
            await websocket.receive_text()

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for job %s", cv_job_id)
    except Exception as exc:
        logger.error("WebSocket error for job %s: %s", cv_job_id, exc)
    finally:
        ws_manager.disconnect(cv_job_id, websocket)

        # If this was the last client, cancel the SSE relay
        if ws_manager.get_connection_count(cv_job_id) == 0 and sse_task and not sse_task.done():
            sse_task.cancel()
            try:
                await sse_task
            except asyncio.CancelledError:
                pass
            logger.info("SSE relay cancelled for job %s (no remaining clients)", cv_job_id)


async def _relay_sse(cv_job_id: str) -> None:
    """Open SSE stream from CV Engine and broadcast events to all WebSocket clients."""
    try:
        async for event in cv_client.stream_frames(cv_job_id):
            event_type = event.get("type", "message")
            payload = {
                "type": event_type,
                "data": event.get("data", {}),
            }

            await ws_manager.broadcast(cv_job_id, payload)

            if event_type == "done":
                logger.info("CV job %s completed, closing all WebSocket connections", cv_job_id)
                await ws_manager.close_all(cv_job_id)
                return

            if event_type == "error":
                logger.error("CV job %s error: %s", cv_job_id, event.get("data"))
                await ws_manager.broadcast(cv_job_id, payload)
                await ws_manager.close_all(cv_job_id)
                return

    except CVEngineError as exc:
        logger.error("SSE relay failed for job %s: %s", cv_job_id, exc.message)
        await ws_manager.broadcast(cv_job_id, {
            "type": "error",
            "data": {"message": exc.message},
        })
        await ws_manager.close_all(cv_job_id)

    except asyncio.CancelledError:
        # Client disconnected, relay cancelled — expected behavior
        raise

    except Exception as exc:
        logger.exception("Unexpected error in SSE relay for job %s", cv_job_id)
        await ws_manager.broadcast(cv_job_id, {
            "type": "error",
            "data": {"message": "Internal server error"},
        })
        await ws_manager.close_all(cv_job_id)
