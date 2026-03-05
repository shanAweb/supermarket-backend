# Supermarket Backend — Build Tasks (Ordered)

---

## Phase 1: Project Setup & Configuration

### Task 1.1 — Initialize Project Structure
- Create the full directory tree as per the spec
- `app/`, `app/api/`, `app/api/routes/`, `app/models/`, `app/models/db/`, `app/models/schemas/`, `app/services/`, `app/services/rag/`, `app/workers/`, `app/core/`
- `alembic/`, `tests/`
- Add `__init__.py` files to all packages

### Task 1.2 — Requirements & Dependencies
- Create `requirements.txt` with all production dependencies:
  - `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`
  - `sqlalchemy[asyncio]`, `asyncpg`, `alembic`
  - `celery[redis]`, `redis`
  - `httpx`, `python-multipart`
  - `langchain`, `langchain-anthropic`, `chromadb`, `sentence-transformers`
  - `anthropic`
  - `python-jose[cryptography]`, `passlib[bcrypt]`, `bcrypt`
  - `websockets`
- Create `requirements-dev.txt`:
  - `pytest`, `pytest-asyncio`, `httpx`, `aiosqlite`, `pytest-cov`

### Task 1.3 — Environment Configuration
- Create `.env.example` with all required env vars
- Create `app/config.py` — Pydantic `Settings` class reading from `.env`:
  - `APP_ENV`, `SECRET_KEY`, `CORS_ORIGINS`
  - `CV_ENGINE_URL`
  - `DATABASE_URL`
  - `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
  - `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `CHROMA_PERSIST_DIR`, `EMBEDDING_MODEL`, `RAG_TOP_K`
  - JWT settings: `ACCESS_TOKEN_EXPIRE_MINUTES`, `REFRESH_TOKEN_EXPIRE_DAYS`

### Task 1.4 — Database Engine & Session Factory
- Create `app/database.py`:
  - Async SQLAlchemy engine via `create_async_engine`
  - `AsyncSessionLocal` session factory
  - `get_db` async generator for FastAPI dependency injection

---

## Phase 2: Database Models (ORM)

### Task 2.1 — Base Model
- Create `app/models/db/base.py`:
  - `DeclarativeBase` class
  - Common mixins (UUID primary key, timestamps)

### Task 2.2 — User Model
- Create `app/models/db/user.py`:
  - `id` (UUID, PK)
  - `email` (VARCHAR, unique, indexed)
  - `password_hash` (VARCHAR)
  - `first_name`, `last_name` (VARCHAR)
  - `company` (VARCHAR, nullable)
  - `role` (VARCHAR, default "store_manager")
  - `plan` (VARCHAR, default "free")
  - `is_active` (BOOLEAN, default True)
  - `created_at`, `updated_at` (TIMESTAMP)

### Task 2.3 — Session Model
- Create `app/models/db/session.py`:
  - `id` (UUID, PK)
  - `user_id` (UUID, FK -> users)
  - `cv_job_id` (VARCHAR)
  - `status` (ENUM: queued/processing/completed/failed)
  - `video_filename` (VARCHAR)
  - `video_path` (TEXT)
  - `customer_count` (INTEGER)
  - `result_dir` (TEXT)
  - `heatmap_image_path` (TEXT)
  - `initial_grid_path` (TEXT)
  - `store_id`, `camera_id` (VARCHAR, nullable)
  - `notes` (TEXT, nullable)
  - `created_at`, `completed_at` (TIMESTAMP)

### Task 2.4 — Zone Analytics Model
- Create `app/models/db/zone_analytics.py`:
  - `id` (UUID, PK)
  - `session_id` (UUID, FK -> sessions)
  - `row` (SMALLINT, 0-9)
  - `col` (SMALLINT, 0-9)
  - `heat_value` (FLOAT, 0.0-100.0)

### Task 2.5 — Customer Count Model
- Create `app/models/db/customer_count.py`:
  - `id` (UUID, PK)
  - `session_id` (UUID, FK -> sessions)
  - `count` (INTEGER)
  - `frame_idx` (INTEGER)
  - `recorded_at` (TIMESTAMP)

---

## Phase 3: Alembic Migrations

### Task 3.1 — Initialize Alembic
- Run `alembic init alembic`
- Configure `alembic.ini` with async driver
- Edit `alembic/env.py` for async SQLAlchemy + import all models

### Task 3.2 — Generate Initial Migration
- Auto-generate migration for all 4 tables: `users`, `sessions`, `zone_analytics`, `customer_counts`
- Apply migration: `alembic upgrade head`

---

## Phase 4: Pydantic Schemas (Request/Response Models)

### Task 4.1 — Auth Schemas
- Create `app/models/schemas/auth.py`:
  - `SignupRequest` (first_name, last_name, email, company, password)
  - `LoginRequest` (email, password)
  - `TokenResponse` (access_token, refresh_token, token_type)
  - `RefreshRequest` (refresh_token)
  - `UserResponse` (id, email, first_name, last_name, company, role, plan, created_at)
  - `ForgotPasswordRequest` (email)
  - `ResetPasswordRequest` (token, new_password)

### Task 4.2 — Session Schemas
- Create `app/models/schemas/session.py`:
  - `SessionCreate` (video_path, store_id, camera_id, notes — all optional)
  - `SessionResponse` (id, cv_job_id, status, video_filename, customer_count, grid_data, heatmap_image_url, initial_grid_url, created_at, completed_at, store_id, camera_id, notes)
  - `SessionListResponse` (total, items: list[SessionResponse])

### Task 4.3 — Analytics Schemas
- Create `app/models/schemas/analytics.py`:
  - `ZoneGridResponse` (grid: list[list[float]])
  - `ZoneRanking` (row, col, avg_heat, label)
  - `ZoneRankingsResponse` (rankings: list[ZoneRanking])
  - `CustomerCountData` (session_id, created_at, customer_count)
  - `CustomerCountsResponse` (data: list[CustomerCountData])
  - `ComparisonResponse` (session_a, session_b, delta)

### Task 4.4 — Insights Schemas
- Create `app/models/schemas/insights.py`:
  - `InsightQueryRequest` (question, session_ids, store_id)
  - `AutoInsightResponse` (session_id, summary, hot_zones, cold_zones, recommendations)

---

## Phase 5: Core Utilities

### Task 5.1 — Security Module
- Create `app/core/security.py`:
  - Password hashing (passlib + bcrypt)
  - `hash_password(plain)` -> hashed string
  - `verify_password(plain, hashed)` -> bool
  - JWT creation: `create_access_token(user_id)`, `create_refresh_token(user_id)`
  - JWT decoding: `decode_token(token)` -> payload dict
  - Token expiry settings from config

### Task 5.2 — Auth Dependencies
- Update `app/api/deps.py`:
  - `get_db()` — async DB session generator
  - `get_current_user(token, db)` — extract JWT from `Authorization: Bearer ...`, validate, load user from DB
  - Raise `401 Unauthorized` if token invalid/expired/user not found

### Task 5.3 — WebSocket Manager
- Create `app/core/websocket_manager.py`:
  - In-memory dict of `cv_job_id -> list[WebSocket]`
  - `connect(job_id, websocket)` — register client
  - `disconnect(job_id, websocket)` — remove client
  - `broadcast(job_id, data)` — send JSON to all clients for a job
  - `get_connections(job_id)` — return active clients count

---

## Phase 6: Services Layer

### Task 6.1 — CV Engine Client
- Create `app/services/cv_client.py`:
  - Async `httpx.AsyncClient` wrapper
  - `submit_job(video_path) -> job_id` — POST to CNN `/jobs`
  - `get_job_status(job_id) -> dict` — GET from CNN `/jobs/{job_id}`
  - `get_heatmap_image(job_id) -> bytes` — GET from CNN `/jobs/{job_id}/heatmap`
  - `get_initial_grid_image(job_id) -> bytes` — GET from CNN `/jobs/{job_id}/initial-grid`
  - `stream_frames(job_id) -> AsyncIterator` — SSE stream from CNN `/stream/{job_id}`
  - Error handling for connection failures, timeouts

### Task 6.2 — Analytics Service
- Create `app/services/analytics.py`:
  - `get_zone_averages(db, filters) -> 10x10 grid` — AVG heat per cell across sessions
  - `get_zone_rankings(db, filters) -> list` — zones sorted by avg heat desc
  - `get_customer_counts(db, filters) -> list` — time-series data
  - `get_peak_zones(db, top_n) -> list` — top N hottest zones
  - `get_session_comparison(db, session_a_id, session_b_id) -> dict` — two grids + delta

---

## Phase 7: Authentication Routes

### Task 7.1 — Signup Endpoint
- Create `app/api/routes/auth.py`:
  - `POST /api/v1/auth/signup`
  - Validate email uniqueness
  - Hash password
  - Create user row in DB
  - Return JWT tokens + user data

### Task 7.2 — Login Endpoint
- `POST /api/v1/auth/login`
  - Find user by email
  - Verify password
  - Return JWT tokens + user data
  - Return 401 if invalid credentials

### Task 7.3 — Token Refresh Endpoint
- `POST /api/v1/auth/refresh`
  - Validate refresh token
  - Issue new access + refresh token pair

### Task 7.4 — Get Current User Endpoint
- `GET /api/v1/auth/me`
  - Protected route (requires valid JWT)
  - Return full user profile

### Task 7.5 — OAuth Endpoints (Google & GitHub)
- `POST /api/v1/auth/oauth/google` — exchange Google auth code for user
- `POST /api/v1/auth/oauth/github` — exchange GitHub auth code for user
- Create or link user account, return JWT tokens

### Task 7.6 — Password Reset Endpoints
- `POST /api/v1/auth/forgot-password` — generate reset token, send email (or return token in dev)
- `POST /api/v1/auth/reset-password` — validate reset token, update password

---

## Phase 8: Session Routes

### Task 8.1 — Create Session
- Create `app/api/routes/sessions.py`:
  - `POST /api/v1/sessions` (protected)
  - Accept multipart file upload OR `video_path` string
  - Create session row in DB (status=queued, user_id from JWT)
  - Dispatch `process_video` Celery task
  - Return 202 with session data

### Task 8.2 — List Sessions
- `GET /api/v1/sessions` (protected)
  - Filter by status, store_id
  - Pagination: limit/offset
  - Only return sessions belonging to current user

### Task 8.3 — Get Session Detail
- `GET /api/v1/sessions/{id}` (protected)
  - Load session with zone_analytics grid data
  - Reconstruct 10x10 grid from zone_analytics rows
  - Include heatmap_image_url and initial_grid_url
  - Verify session belongs to current user

### Task 8.4 — Proxy Heatmap Image
- `GET /api/v1/sessions/{id}/heatmap` (protected)
  - Look up cv_job_id from session
  - Fetch JPEG from CV engine via cv_client
  - Return as `image/jpeg`

### Task 8.5 — Proxy Initial Grid Image
- `GET /api/v1/sessions/{id}/initial-grid` (protected)
  - Same pattern as 8.4 but for initial grid

### Task 8.6 — Delete Session
- `DELETE /api/v1/sessions/{id}` (protected)
  - Soft-delete (set a `deleted_at` timestamp or `is_deleted` flag)
  - Verify ownership

---

## Phase 9: Celery Workers

### Task 9.1 — Celery App Configuration
- Create `app/workers/celery_app.py`:
  - Celery instance with Redis broker
  - Config from env vars
  - Task autodiscovery

### Task 9.2 — Process Video Task
- Create `app/workers/tasks.py`:
  - `process_video(session_id: str)`:
    1. Load session from DB
    2. Update status to `processing`
    3. Call `cv_client.submit_job(video_path)` -> get `cv_job_id`
    4. Save `cv_job_id` to session
    5. Poll `cv_client.get_job_status(cv_job_id)` every 5 seconds
    6. On completion: extract `customer_count`, `grid_data`
    7. Write `customer_count` to sessions table
    8. Write 100 rows to `zone_analytics` table (10x10 grid)
    9. Update session status to `completed`, set `completed_at`
    10. Chain `ingest_session` task
    11. On failure: set status to `failed`

### Task 9.3 — Ingest Session Task
- `ingest_session(session_id: str)`:
  1. Load completed session + zone_analytics from DB
  2. Build text documents (session summary + per-zone details)
  3. Embed via sentence-transformers
  4. Store in ChromaDB (`sessions` and `zone_insights` collections)

### Task 9.4 — Celery Beat Periodic Task
- Nightly aggregation task (midnight):
  - Aggregate all sessions from past 24 hours
  - Compute rolling zone averages
  - Store summary in PostgreSQL for fast dashboard queries

---

## Phase 10: Analytics Routes

### Task 10.1 — Zone Averages
- Create `app/api/routes/analytics.py`:
  - `GET /api/v1/analytics/zones` (protected)
  - Accepts: store_id, from_date, to_date, session_ids
  - Returns 10x10 grid of average heat values

### Task 10.2 — Zone Rankings
- `GET /api/v1/analytics/zone-rankings` (protected)
  - Zones ranked by avg heat, highest first
  - Include row, col, avg_heat, label

### Task 10.3 — Customer Counts
- `GET /api/v1/analytics/customer-counts` (protected)
  - Time-series: session_id, created_at, customer_count

### Task 10.4 — Peak Zones
- `GET /api/v1/analytics/peak-zones` (protected)
  - Top N (default 5) hottest zones

### Task 10.5 — Session Comparison
- `GET /api/v1/analytics/comparison` (protected)
  - Two session UUIDs in query params
  - Return both grids + computed delta grid

---

## Phase 11: WebSocket Streaming

### Task 11.1 — WebSocket Stream Route
- Create `app/api/routes/stream.py`:
  - `WS /ws/stream/{cv_job_id}`
  - On connect: register in WebSocketManager
  - Open SSE connection to CV engine `/stream/{cv_job_id}` via httpx
  - For each SSE event: parse frame JSON, forward to WebSocket client
  - Message types: `frame` (base64 JPEG + count + frame_idx), `ping`, `done`, `error`
  - On `done`: close all WebSocket connections for that job
  - On client disconnect: cancel SSE connection
  - Support multiple clients per job_id

---

## Phase 12: RAG Pipeline

### Task 12.1 — ChromaDB Vector Store Setup
- Create `app/services/rag/vectorstore.py`:
  - Initialize ChromaDB persistent client
  - Create/get collections: `sessions`, `zone_insights`
  - `add_documents(collection, docs, metadatas, ids)` wrapper
  - `query(collection, query_text, top_k)` wrapper

### Task 12.2 — Session Ingestion
- Create `app/services/rag/ingestion.py`:
  - `build_session_document(session, grid_data)` — text summary of session
  - `build_zone_documents(session, grid_data)` — per hot/cold zone text chunks
  - `ingest(session_id, db)` — orchestrate doc building + embedding + storage
  - Embeds using `sentence-transformers` (model from config: `all-MiniLM-L6-v2`)

### Task 12.3 — RAG Query Pipeline
- Create `app/services/rag/pipeline.py`:
  - LangChain chain: retriever -> prompt template -> Claude LLM -> streaming output
  - System prompt: "You are a supermarket analytics expert..."
  - Retrieve top-k docs from ChromaDB filtered by session_ids/store_id
  - Stream Claude response tokens
  - `query(question, session_ids, store_id)` -> async token generator
  - `auto_insight(session_id)` -> structured JSON (summary, hot_zones, cold_zones, recommendations)

---

## Phase 13: Insights Routes

### Task 13.1 — RAG Query Endpoint
- Create `app/api/routes/insights.py`:
  - `POST /api/v1/insights/query` (protected)
  - Accept: question, session_ids, store_id
  - Return: `text/event-stream` (SSE) with streamed Claude tokens

### Task 13.2 — Auto-Insight Endpoint
- `GET /api/v1/insights/auto/{session_id}` (protected)
  - Generate structured insight report for a completed session
  - Return JSON: summary, hot_zones, cold_zones, recommendations

### Task 13.3 — Manual Ingestion Trigger
- `POST /api/v1/insights/ingest/{session_id}` (protected)
  - Trigger RAG ingestion manually for a session

---

## Phase 14: FastAPI App Assembly

### Task 14.1 — App Factory
- Create `app/main.py`:
  - Create FastAPI app instance
  - Register all routers:
    - `/api/v1/auth` — auth routes
    - `/api/v1/sessions` — session routes
    - `/api/v1/analytics` — analytics routes
    - `/api/v1/insights` — insights routes
    - `/ws` — WebSocket routes
  - Add CORS middleware (origins from config)
  - Add startup/shutdown events (DB engine init/dispose)
  - Health check endpoint: `GET /health`

---

## Phase 15: Docker & Deployment

### Task 15.1 — Dockerfile
- Create `Dockerfile`:
  - Python 3.12 slim base
  - Install dependencies
  - Copy app code
  - Expose port 8001
  - CMD: uvicorn app.main:app

### Task 15.2 — Docker Compose
- Create `docker-compose.yml` with 6 services:
  - `backend` — FastAPI app, port 8001:8001
  - `celery-worker` — same image, celery worker command
  - `celery-beat` — same image, celery beat command
  - `cv-engine` — build from ../Heatmaps-Generation-CNN, port 8000 (internal)
  - `postgres` — PostgreSQL 16, port 5432 (internal), volume for data persistence
  - `redis` — Redis 7, port 6379 (internal)
- Create `docker-compose.dev.yml` — dev overrides (hot reload, exposed debug ports)
- Internal network: `supermarket-net`

### Task 15.3 — Alembic Config for Docker
- Update `alembic.ini` to read DATABASE_URL from env
- Ensure migrations run inside container context

---

## Phase 16: Testing

### Task 16.1 — Test Fixtures
- Create `tests/conftest.py`:
  - In-memory SQLite async DB (aiosqlite)
  - Test FastAPI client (httpx.AsyncClient)
  - Mock CV engine client (return fixtures)
  - Test user factory (pre-authenticated)

### Task 16.2 — Auth Tests
- Create `tests/test_auth.py`:
  - Test signup (success, duplicate email)
  - Test login (success, wrong password, nonexistent user)
  - Test token refresh
  - Test protected route without token (401)

### Task 16.3 — Session Tests
- Create `tests/test_sessions.py`:
  - Test create session (job dispatched)
  - Test list sessions (pagination, filtering)
  - Test get session detail (grid data reconstructed)
  - Test delete session (soft delete)
  - Test ownership enforcement (can't see other user's sessions)

### Task 16.4 — Analytics Tests
- Create `tests/test_analytics.py`:
  - Test zone averages (correct aggregation)
  - Test zone rankings (sorted correctly)
  - Test customer counts (time-series format)
  - Test comparison (delta computed correctly)

### Task 16.5 — RAG Tests
- Create `tests/test_rag.py`:
  - Test ingestion (documents stored in ChromaDB)
  - Test query (retriever returns relevant docs)
  - Test auto-insight (structured response format)

---

## Summary

| Phase | Tasks | What it delivers |
|-------|-------|-----------------|
| 1. Setup | 4 | Project skeleton, config, DB engine |
| 2. DB Models | 5 | All ORM tables |
| 3. Migrations | 2 | Schema versioning |
| 4. Schemas | 4 | Request/response validation |
| 5. Core | 3 | Security, auth deps, WS manager |
| 6. Services | 2 | CV client, analytics logic |
| 7. Auth | 6 | Full auth flow |
| 8. Sessions | 6 | Session CRUD + job dispatch |
| 9. Workers | 4 | Celery tasks |
| 10. Analytics | 5 | Analytics endpoints |
| 11. WebSocket | 1 | Live streaming relay |
| 12. RAG | 3 | Vector store + ingestion + pipeline |
| 13. Insights | 3 | RAG endpoints |
| 14. Assembly | 1 | App factory + router wiring |
| 15. Docker | 3 | Containerization |
| 16. Testing | 5 | Full test suite |
| **Total** | **57 tasks** | |
