"""API dependencies: database session and request ID injection."""

from __future__ import annotations

import uuid

from fastapi import Header, Request

from app.core.config import settings
from app.core.errors import AppError, ErrorCode


def get_request_id(request: Request) -> str:
    """Extract or generate a request ID for correlation."""
    req_id = request.headers.get("X-Request-ID")
    if not req_id:
        req_id = f"req_{uuid.uuid4().hex[:12]}"
    # Store in request state for error handlers
    request.state.request_id = req_id
    return req_id


def verify_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> None:
    """Check API key when auth is required (production mode)."""
    if not settings.require_auth:
        return
    if not x_api_key or x_api_key != settings.api_key:
        raise AppError(
            ErrorCode.UNAUTHENTICATED,
            "Valid API key required.",
        )
