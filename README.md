# Supermarket Analytics — Backend API

The central orchestration layer for the supermarket intelligence platform. This service sits between the CV Engine (heatmap generation) and the Next.js frontend dashboard. It handles session management, analytics persistence, RAG-powered insights, real-time WebSocket streaming, and async job dispatching via a task queue.

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [How This Repo Connects to the Other Repos](#2-how-this-repo-connects-to-the-other-repos)
3. [Tech Stack](#3-tech-stack)
4. [Directory Structure](#4-directory-structure)
5. [Database Schema](#5-database-schema)
6. [API Reference](#6-api-reference)
7. [RAG Pipeline](#7-rag-pipeline)
8. [WebSocket Streaming](#8-websocket-streaming)
9. [Celery Task Queue](#9-celery-task-queue)
10. [Environment Variables](#10-environment-variables)
11. [Docker Compose Services](#11-docker-compose-services)
12. [Running Locally](#12-running-locally)
13. [Running with Docker](#13-running-with-docker)
14. [Development Workflow](#14-development-workflow)
15. [Testing](#15-testing)

---

## 1. System Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    FRONTEND  (Next.js — separate repo)               │
│                                                                      │
│   Dashboard  │  Live Heatmap  │  Zone Grid  │  RAG Insights Page    │
└────────────────────────┬─────────────────────────────────────────────┘
                         │  REST (HTTP/JSON) + WebSocket
                         │
┌────────────────────────▼─────────────────────────────────────────────┐
│                    BACKEND  (this repo — port 8001)                  │
│                                                                      │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────────┐   │
│  │  FastAPI App  │  │  Celery Workers  │  │     RAG Pipeline      │   │
│  │              │  │                 │  │                      │   │
│  │  REST routes │  │  dispatch jobs  │  │  LangChain           │   │
│  │  WebSocket   │  │  to CV engine   │  │  ChromaDB            │   │
│  │  relay       │  │  poll results   │  │  Claude API          │   │
│  └──────┬───────┘  └────────┬────────┘  └──────────────────────┘   │
│         │                   │                                        │
│  ┌──────▼───────┐  ┌────────▼────────┐  ┌──────────────────────┐   │
│  │  PostgreSQL  │  │      Redis      │  │      ChromaDB        │   │
│  │              │  │                 │  │                      │   │
│  │  sessions    │  │  Celery broker  │  │  vector embeddings   │   │
│  │  analytics   │  │  result cache   │  │  of heatmap data     │   │
│  │  zone data   │  │  WS pub/sub     │  │  for RAG queries     │   │
│  └──────────────┘  └─────────────────┘  └──────────────────────┘   │
└────────────────────────┬─────────────────────────────────────────────┘
                         │  HTTP  (internal Docker network)
                         │
┌────────────────────────▼─────────────────────────────────────────────┐
│                CV ENGINE  (Heatmaps-Generation-CNN — port 8000)      │
│                                                                      │
│   POST /jobs  →  GET /jobs/{id}  →  GET /stream/{id}  (SSE)         │
│   YOLOv8 + DeepSORT + HeatmapEngine + GridVisualizer                │
└──────────────────────────────────────────────────────────────────────┘
```

**Data flow for a single session:**

```
Frontend uploads video
        │
        ▼
Backend POST /api/v1/sessions
        │  creates DB session row (status=queued)
        │  pushes Celery task
        ▼
Celery worker calls CV Engine POST /jobs
        │  gets back job_id
        │  polls CV Engine GET /jobs/{id} until completed
        │  writes results (customer_count, grid_data) to PostgreSQL
        │  triggers RAG ingestion for the session
        ▼
Frontend GET /api/v1/sessions/{id}
        │  returns full session with analytics
        ▼
Frontend WebSocket /ws/stream/{job_id}
        │  backend relays SSE frames from CV engine over WebSocket
        ▼
Frontend POST /api/v1/insights/query
        │  RAG query against stored heatmap embeddings
        │  Claude streams back recommendations
```

---

## 2. How This Repo Connects to the Other Repos

| Repo | Role | Connection Method |
|------|------|------------------|
| `Heatmaps-Generation-CNN` | CV Engine | HTTP calls to `CV_ENGINE_URL` env var |
| `supermarket-backend` (this) | Orchestration + RAG + DB | — |
| `supermarket-frontend` | Dashboard UI | This backend's REST + WebSocket |

**This repo never imports Python code from the CNN repo.** The only link is the URL. In `docker-compose.yml` the CV engine runs as a named service (`cv-engine`) on the shared Docker network, so `CV_ENGINE_URL=http://cv-engine:8000` just works.

---

## 3. Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Web framework | FastAPI | Async REST API + WebSocket |
| Task queue | Celery + Redis | Async video job dispatch |
| Database ORM | SQLAlchemy (async) + asyncpg | PostgreSQL async queries |
| Migrations | Alembic | Schema versioning |
| RAG framework | LangChain | Orchestration of retrieval + generation |
| Vector store | ChromaDB | Embedding storage for heatmap data |
| LLM | Claude API (`claude-sonnet-4-6`) | Insight generation + streaming |
| Embeddings | `sentence-transformers` | Text embedding for RAG |
| HTTP client | `httpx` | Async calls to CV engine |
| Settings | `pydantic-settings` | `.env` file management |
| Cache | Redis | API response caching |
| Containerisation | Docker + Docker Compose | Local and production runtime |
| Testing | Pytest + `httpx` async client | Unit + integration tests |

---

## 4. Directory Structure

```
supermarket-backend/
│
├── app/
│   ├── main.py                      # FastAPI app factory, router registration
│   ├── config.py                    # All settings via pydantic-settings
│   ├── database.py                  # Async SQLAlchemy engine + session factory
│   │
│   ├── api/
│   │   ├── deps.py                  # Shared FastAPI dependencies (DB session, etc.)
│   │   └── routes/
│   │       ├── sessions.py          # /api/v1/sessions  — CRUD + job trigger
│   │       ├── analytics.py         # /api/v1/analytics — zone, count, peak queries
│   │       ├── insights.py          # /api/v1/insights  — RAG query + auto-insights
│   │       └── stream.py            # /ws/stream/{job_id} — WebSocket relay
│   │
│   ├── models/
│   │   ├── db/                      # SQLAlchemy ORM table definitions
│   │   │   ├── base.py              # DeclarativeBase
│   │   │   ├── session.py           # Session table
│   │   │   ├── zone_analytics.py    # Per-cell heatmap values table
│   │   │   └── customer_count.py    # Customer count records table
│   │   └── schemas/                 # Pydantic request/response models
│   │       ├── session.py
│   │       ├── analytics.py
│   │       └── insights.py
│   │
│   ├── services/
│   │   ├── cv_client.py             # Async HTTP client wrapping CV engine API
│   │   ├── analytics.py             # Analytics aggregation + zone ranking logic
│   │   └── rag/
│   │       ├── pipeline.py          # LangChain RAG chain (retrieval + generation)
│   │       ├── ingestion.py         # Converts session results → RAG documents
│   │       └── vectorstore.py       # ChromaDB client + collection management
│   │
│   ├── workers/
│   │   ├── celery_app.py            # Celery instance (broker=Redis)
│   │   └── tasks.py                 # Task definitions: process_video, ingest_session
│   │
│   └── core/
│       └── websocket_manager.py     # Connection registry for WebSocket clients
│
├── alembic/
│   ├── env.py                       # Alembic async config
│   └── versions/                    # Auto-generated migration files
│
├── tests/
│   ├── conftest.py                  # Pytest fixtures (test DB, test client)
│   ├── test_sessions.py
│   ├── test_analytics.py
│   └── test_rag.py
│
├── docker-compose.yml               # Full stack (all services)
├── docker-compose.dev.yml           # Dev overrides (hot reload, no SSL)
├── Dockerfile
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt
├── .env.example
└── README.md
```

---

## 5. Database Schema

### `sessions` table
Represents one video processing run (one camera feed, one time window).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Session identifier |
| `cv_job_id` | VARCHAR | Job ID returned by the CV engine |
| `status` | ENUM | `queued / processing / completed / failed` |
| `video_filename` | VARCHAR | Original uploaded filename |
| `video_path` | TEXT | Path on the CV engine container |
| `customer_count` | INTEGER | Total unique persons tracked |
| `result_dir` | TEXT | CV engine result directory path |
| `heatmap_image_path` | TEXT | Path to final heatmap grid JPEG |
| `initial_grid_path` | TEXT | Path to initial floor grid JPEG |
| `created_at` | TIMESTAMP | When the session was created |
| `completed_at` | TIMESTAMP | When processing finished |
| `store_id` | VARCHAR | For multi-store support (nullable) |
| `camera_id` | VARCHAR | Camera identifier (nullable) |
| `notes` | TEXT | Free-text label for the session |

### `zone_analytics` table
Stores the 10×10 heatmap grid for each session as individual cell rows — makes SQL queries on specific zones possible.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Row identifier |
| `session_id` | UUID (FK → sessions) | Parent session |
| `row` | SMALLINT | Grid row index (0–9) |
| `col` | SMALLINT | Grid column index (0–9) |
| `heat_value` | FLOAT | Heat percentage (0.0 – 100.0) |

> Each session produces 100 zone_analytics rows (10×10 grid).

### `customer_counts` table
Allows storing multiple count checkpoints within a session (e.g. every N frames).

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID (PK) | Row identifier |
| `session_id` | UUID (FK → sessions) | Parent session |
| `count` | INTEGER | Unique persons at this checkpoint |
| `frame_idx` | INTEGER | Frame number at checkpoint |
| `recorded_at` | TIMESTAMP | Wall-clock time of checkpoint |

---

## 6. API Reference

Base URL: `http://localhost:8001/api/v1`

Interactive docs: `http://localhost:8001/docs`

---

### Sessions

#### `POST /sessions`
Start a new processing session. Uploads video to CV engine and dispatches a Celery task.

**Request** — `multipart/form-data`
```
file         (file, optional)   — video file upload
video_path   (string, optional) — path already on the server
store_id     (string, optional) — store identifier
camera_id    (string, optional) — camera identifier
notes        (string, optional) — free-text label
```

**Response** `202 Accepted`
```json
{
  "id": "a1b2c3d4-...",
  "cv_job_id": "e5f6g7h8-...",
  "status": "queued",
  "video_filename": "aisle3_morning.mp4",
  "created_at": "2026-02-23T10:00:00Z"
}
```

---

#### `GET /sessions`
List all sessions. Supports pagination and filtering.

**Query params**
```
status       queued | processing | completed | failed
store_id     filter by store
limit        default 20, max 100
offset       default 0
```

**Response** `200 OK`
```json
{
  "total": 42,
  "items": [ { ...session... }, ... ]
}
```

---

#### `GET /sessions/{id}`
Full session detail including zone grid and customer count.

**Response** `200 OK`
```json
{
  "id": "a1b2c3d4-...",
  "status": "completed",
  "customer_count": 37,
  "grid_data": [
    [0.0, 0.0, 1.3, 0.0, ...],
    ...
  ],
  "heatmap_image_url": "/api/v1/sessions/a1b2c3d4/heatmap",
  "initial_grid_url": "/api/v1/sessions/a1b2c3d4/initial-grid",
  "created_at": "2026-02-23T10:00:00Z",
  "completed_at": "2026-02-23T10:08:43Z"
}
```

---

#### `GET /sessions/{id}/heatmap`
Proxies the heatmap JPEG from the CV engine.

**Response** — `image/jpeg`

---

#### `GET /sessions/{id}/initial-grid`
Proxies the initial floor grid JPEG from the CV engine.

**Response** — `image/jpeg`

---

#### `DELETE /sessions/{id}`
Soft-delete a session record.

---

### Analytics

#### `GET /analytics/zones`
Returns average heat per zone across all (or filtered) sessions. Useful for store-level heatmap trends.

**Query params**
```
store_id       filter by store
from_date      ISO 8601
to_date        ISO 8601
session_ids    comma-separated UUIDs
```

**Response**
```json
{
  "grid": [
    [4.2, 1.1, 0.0, 12.5, ...],
    ...
  ]
}
```

---

#### `GET /analytics/zone-rankings`
Zones ranked by average heat value, highest first.

**Response**
```json
{
  "rankings": [
    { "row": 9, "col": 4, "avg_heat": 10.7, "label": "Zone 9-5" },
    { "row": 7, "col": 0, "avg_heat": 12.2, "label": "Zone 7-1" },
    ...
  ]
}
```

---

#### `GET /analytics/customer-counts`
Time-series of customer counts across sessions.

**Response**
```json
{
  "data": [
    { "session_id": "...", "created_at": "...", "customer_count": 37 },
    ...
  ]
}
```

---

#### `GET /analytics/peak-zones`
Top N hottest zones by average traffic across all sessions.

**Query params**
```
top_n    default 5
```

---

#### `GET /analytics/comparison`
Side-by-side grid comparison between two sessions (e.g. before and after a shelf rearrangement).

**Query params**
```
session_a    UUID
session_b    UUID
```

**Response**
```json
{
  "session_a": { "id": "...", "grid": [[...], ...] },
  "session_b": { "id": "...", "grid": [[...], ...] },
  "delta":     [[+2.1, -0.5, ...], ...]
}
```

---

### Insights (RAG)

#### `POST /insights/query`
Ask a natural language question about the store analytics. Response streams token-by-token.

**Request** `application/json`
```json
{
  "question": "Which aisles are underperforming and what should I change?",
  "session_ids": ["a1b2c3d4", "e5f6g7h8"],
  "store_id": "store-001"
}
```

**Response** — `text/event-stream` (streamed Claude tokens)
```
data: {"token": "Based"}
data: {"token": " on"}
data: {"token": " the"}
...
data: {"done": true}
```

---

#### `GET /insights/auto/{session_id}`
Auto-generates a structured insight report for a completed session. No question required — the pipeline builds a prompt from the raw grid data.

**Response**
```json
{
  "session_id": "...",
  "summary": "...",
  "hot_zones": ["Zone 9-5", "Zone 7-1"],
  "cold_zones": ["Zone 1-1", "Zone 2-3"],
  "recommendations": [
    "Consider relocating high-margin products to Zone 9-5 (highest traffic).",
    "Zone 1-1 sees near-zero traffic — evaluate signage or lighting."
  ]
}
```

---

#### `POST /insights/ingest/{session_id}`
Manually trigger RAG ingestion for a session. (Normally called automatically by the Celery task after processing completes.)

---

### WebSocket

#### `WS /ws/stream/{cv_job_id}`
Relays live heatmap frames from the CV engine's SSE stream over WebSocket to the frontend.

**Messages sent to client**
```json
{ "type": "frame",  "frame": "<base64 JPEG>", "count": 12, "frame_idx": 240 }
{ "type": "ping" }
{ "type": "done" }
{ "type": "error", "detail": "CV engine job not found." }
```

The backend opens an SSE connection to `CV_ENGINE_URL/stream/{cv_job_id}` and re-emits each frame as a WebSocket JSON message. This lets the frontend use a single clean WebSocket instead of dealing with SSE directly or worrying about CORS.

---

## 7. RAG Pipeline

The RAG pipeline enables natural language querying of historical analytics data.

### How it works

```
Session completes
      │
      ▼
ingestion.py — builds text documents from session data:
  "Session 2026-02-23: 37 customers.
   Hottest zone: row=9 col=4 (10.7%).
   Cold zones: row=1 col=1 (0.0%)..."
      │
      ▼
sentence-transformers embeds the documents
      │
      ▼
ChromaDB stores vectors in collection "sessions"
      │
      ▼ (at query time)
User asks: "Which aisle needs attention?"
      │
      ▼
RAG retrieves top-k most relevant session documents
      │
      ▼
LangChain builds prompt:
  [System] You are a supermarket analytics expert...
  [Context] {retrieved documents}
  [User] Which aisle needs attention?
      │
      ▼
Claude claude-sonnet-4-6 streams response back
```

### ChromaDB Collections

| Collection | Contents | Metadata per doc |
|-----------|---------|-----------------|
| `sessions` | One document per session summarising grid + counts | `session_id`, `store_id`, `created_at` |
| `zone_insights` | One document per hot/cold zone event | `session_id`, `row`, `col`, `heat_value` |

---

## 8. WebSocket Streaming

The `WebSocketManager` in `app/core/websocket_manager.py` maintains an in-memory registry of active connections keyed by `cv_job_id`. When a client connects:

1. Backend opens `GET CV_ENGINE_URL/stream/{cv_job_id}` (SSE) with `httpx.AsyncClient`.
2. For each SSE `data:` event, the frame JSON is forwarded to all WebSocket clients subscribed to that job.
3. On `event: done`, all connections for that job are closed cleanly.
4. If the client disconnects early, the SSE connection is cancelled.

Multiple frontend tabs can subscribe to the same `cv_job_id` — they all receive the same frames.

---

## 9. Celery Task Queue

Two tasks defined in `app/workers/tasks.py`:

### `process_video(session_id: str)`
1. Load session record from DB.
2. Call `CV_ENGINE_URL/jobs` with the video path.
3. Poll `CV_ENGINE_URL/jobs/{cv_job_id}` every 5 seconds.
4. On completion, write `customer_count` and `grid_data` to DB.
5. Update session status to `completed`.
6. Trigger `ingest_session` task.

### `ingest_session(session_id: str)`
1. Load completed session from DB.
2. Build text documents from grid data and analytics.
3. Embed and store in ChromaDB.

### Scheduling
Celery Beat runs a periodic task every night at midnight:
- Aggregate all sessions from the past 24 hours.
- Compute rolling zone averages.
- Store summary in PostgreSQL for fast dashboard queries.

---

## 10. Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
# ── Application ──────────────────────────────────────────────────────
APP_ENV=development                      # development | production
SECRET_KEY=change-me-to-a-random-string
CORS_ORIGINS=http://localhost:3000       # comma-separated

# ── CV Engine ─────────────────────────────────────────────────────────
CV_ENGINE_URL=http://cv-engine:8000      # Docker service name in Compose
                                         # Use http://localhost:8000 for local dev

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://supermarket:password@postgres:5432/supermarket_db

# ── Redis ─────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# ── RAG / LLM ─────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-6
CHROMA_PERSIST_DIR=./chroma_db          # Local disk path inside container
EMBEDDING_MODEL=all-MiniLM-L6-v2        # sentence-transformers model name
RAG_TOP_K=5                             # Number of documents retrieved per query
```

---

## 11. Docker Compose Services

```yaml
# docker-compose.yml (overview — full file in repo root)

services:

  backend:          # This FastAPI app — port 8001
  celery-worker:    # Same image, different command (celery worker)
  celery-beat:      # Periodic task scheduler
  cv-engine:        # CNN repo image — port 8000 (internal only)
  postgres:         # PostgreSQL 16 — port 5432 (internal only)
  redis:            # Redis 7 — port 6379 (internal only)
```

Only `backend` exposes a port to the host (`8001:8001`). All other services communicate over the internal `supermarket-net` Docker network.

The CV engine image is built from the `Heatmaps-Generation-CNN` repo. In `docker-compose.yml` you point it at either:
- A local path: `build: { context: ../Heatmaps-Generation-CNN }`
- A registry image: `image: your-registry/cv-engine:latest`

---

## 12. Running Locally (without Docker)

Requires: Python 3.11+, PostgreSQL, Redis, and the CV engine running on port 8000.

```bash
# 1. Create and activate virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy and fill in environment variables
cp .env.example .env
# edit .env — set DATABASE_URL, REDIS_URL, CV_ENGINE_URL, ANTHROPIC_API_KEY

# 4. Run database migrations
alembic upgrade head

# 5. Start FastAPI server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

# 6. In a separate terminal — start Celery worker
celery -A app.workers.celery_app worker --loglevel=info

# 7. In a separate terminal — start Celery Beat (scheduler)
celery -A app.workers.celery_app beat --loglevel=info
```

---

## 13. Running with Docker

```bash
# Build and start all services
docker compose up --build

# Run DB migrations inside the backend container
docker compose exec backend alembic upgrade head

# Tail logs
docker compose logs -f backend
docker compose logs -f celery-worker
```

The full stack (backend + CV engine + postgres + redis) starts together. The frontend connects to `http://localhost:8001`.

---

## 14. Development Workflow

### Adding a new API endpoint
1. Create (or add to) a route file in `app/api/routes/`.
2. Register the router in `app/main.py`.
3. Add the corresponding Pydantic schema in `app/models/schemas/`.
4. Add a DB model in `app/models/db/` if new table needed.
5. Generate migration: `alembic revision --autogenerate -m "add xyz"`
6. Apply: `alembic upgrade head`
7. Write tests in `tests/`.

### Changing the CV engine API contract
The only file to update is `app/services/cv_client.py`. All CV engine calls are isolated there — no other file imports the CV engine URL directly.

### Adding a new RAG document type
1. Add a builder function in `app/services/rag/ingestion.py`.
2. Call it from the `ingest_session` Celery task.
3. ChromaDB will pick it up in the next query cycle automatically.

---

## 15. Testing

```bash
# Install dev dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=term-missing

# Run a specific test file
pytest tests/test_sessions.py -v
```

Tests use an in-memory SQLite database (via `aiosqlite`) and a mock CV engine client — no real PostgreSQL, Redis, or CV engine required to run the test suite.
