"""FastAPI application entry point — app factory, router registration, middleware."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, auth, insights, sessions, stream
from app.config import settings
from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yield
    # Shutdown — dispose DB engine connections
    await engine.dispose()


app = FastAPI(
    title="Supermarket Analytics API",
    description="Backend orchestration service for supermarket foot traffic analytics",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Router Registration
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(sessions.router)
app.include_router(analytics.router)
app.include_router(insights.router)
app.include_router(stream.router)

# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health_check():
    return {"status": "ok"}
