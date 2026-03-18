"""Async HTTP client wrapper for the CV Engine (Heatmaps-Generation-CNN)."""

from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import settings


class CVEngineError(Exception):
    """Raised when the CV Engine returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class CVEngineClient:
    """Async client for communicating with the CV Engine API."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or settings.CV_ENGINE_URL).rstrip("/")
        self.timeout = timeout

    def _client(self, **kwargs: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            **kwargs,
        )

    async def submit_job(self, video_path: str) -> str:
        """Submit a video processing job to the CV Engine.

        Returns the job_id assigned by the engine.
        """
        async with self._client() as client:
            try:
                response = await client.post(
                    "/jobs",
                    json={"video_path": video_path},
                )
                response.raise_for_status()
                data = response.json()
                return data["job_id"]
            except httpx.HTTPStatusError as exc:
                raise CVEngineError(
                    f"CV Engine rejected job submission: {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                raise CVEngineError(
                    f"Failed to connect to CV Engine: {exc}"
                ) from exc

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Get the current status and results of a job."""
        async with self._client() as client:
            try:
                response = await client.get(f"/jobs/{job_id}")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise CVEngineError(
                    f"Failed to get job status: {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                raise CVEngineError(
                    f"Failed to connect to CV Engine: {exc}"
                ) from exc

    async def get_heatmap_image(self, job_id: str) -> bytes:
        """Fetch the heatmap image (JPEG) for a completed job."""
        async with self._client() as client:
            try:
                response = await client.get(f"/jobs/{job_id}/heatmap")
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as exc:
                raise CVEngineError(
                    f"Failed to fetch heatmap image: {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                raise CVEngineError(
                    f"Failed to connect to CV Engine: {exc}"
                ) from exc

    async def get_initial_grid_image(self, job_id: str) -> bytes:
        """Fetch the initial grid image (JPEG) for a completed job."""
        async with self._client() as client:
            try:
                response = await client.get(f"/jobs/{job_id}/initial-grid")
                response.raise_for_status()
                return response.content
            except httpx.HTTPStatusError as exc:
                raise CVEngineError(
                    f"Failed to fetch initial grid image: {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                raise CVEngineError(
                    f"Failed to connect to CV Engine: {exc}"
                ) from exc

    async def stream_frames(self, job_id: str) -> AsyncIterator[dict[str, Any]]:
        """Open an SSE connection to stream processed frames from the CV Engine.

        Yields parsed JSON events with keys like:
          - type: "frame" | "ping" | "done" | "error"
          - data: frame payload (base64 JPEG, count, frame_idx) or error info
        """
        import json

        async with self._client(timeout=None) as client:
            try:
                async with client.stream(
                    "GET", f"/stream/{job_id}"
                ) as response:
                    response.raise_for_status()
                    event_type = ""
                    data_buffer = ""

                    async for line in response.aiter_lines():
                        line = line.strip()

                        if not line:
                            # Empty line marks end of an SSE event
                            if data_buffer:
                                try:
                                    parsed = json.loads(data_buffer)
                                except json.JSONDecodeError:
                                    parsed = {"raw": data_buffer}
                                yield {
                                    "type": event_type or "message",
                                    "data": parsed,
                                }
                                event_type = ""
                                data_buffer = ""
                            continue

                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                        elif line.startswith("data:"):
                            data_buffer += line[len("data:"):].strip()

            except httpx.HTTPStatusError as exc:
                raise CVEngineError(
                    f"SSE stream error: {exc.response.text}",
                    status_code=exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                raise CVEngineError(
                    f"Failed to connect to CV Engine stream: {exc}"
                ) from exc


# Module-level singleton for convenience
cv_client = CVEngineClient()
