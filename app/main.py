"""FastAPI application entry point and lifecycle management."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes.files import router as files_router
from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger, setup_logging
from app.db.models import Base
from app.db.session import engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    setup_logging()
    logger.info(
        "Starting Geospatial Measurement API (env=%s, auth=%s)",
        settings.app_env,
        settings.require_auth,
    )
    # Create tables if they don't exist (development convenience)
    Base.metadata.create_all(bind=engine)
    yield
    logger.info("Shutting down Geospatial Measurement API")


app = FastAPI(
    title="Geospatial File Measurement API",
    description=(
        "A backend service for ingesting KML and Shapefile archives, "
        "extracting geospatial features, and returning measurement results "
        "with explicit CRS handling."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# --- Error Handlers ---


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Convert AppError to the PRD's error envelope format."""
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code.value,
                "message": exc.message,
                "request_id": request_id,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(Exception)
async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions: log details, return safe message."""
    request_id = getattr(request.state, "request_id", f"req_{uuid.uuid4().hex[:12]}")
    logger.exception("Unhandled exception for request %s", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "request_id": request_id,
                "details": {},
            }
        },
    )


# --- Routes ---

app.include_router(files_router)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect to the API documentation."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/docs")


@app.get("/health/live", tags=["health"])
async def health_live():
    """Liveness probe: process is running."""
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
async def health_ready():
    """Readiness probe: database is accessible."""
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return {"status": "ok", "database": "connected"}
        finally:
            db.close()
    except Exception as exc:
        logger.warning("Readiness check failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "database": "disconnected"},
        )
