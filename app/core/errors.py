"""Application error types and centralized error-code mappings."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Machine-readable error codes matching the PRD error catalog."""

    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
    ARCHIVE_EXPANSION_LIMIT = "ARCHIVE_EXPANSION_LIMIT"
    CORRUPT_ARCHIVE = "CORRUPT_ARCHIVE"
    INVALID_GEOSPATIAL_FILE = "INVALID_GEOSPATIAL_FILE"
    INVALID_SOURCE_CRS = "INVALID_SOURCE_CRS"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_NOT_READY = "FILE_NOT_READY"
    INVALID_PAGINATION = "INVALID_PAGINATION"
    MISSING_SHAPEFILE_COMPONENTS = "MISSING_SHAPEFILE_COMPONENTS"
    UNSAFE_ARCHIVE = "UNSAFE_ARCHIVE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    UNAUTHENTICATED = "UNAUTHENTICATED"


# Map error codes to HTTP status codes
ERROR_HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNSUPPORTED_FILE_TYPE: 415,
    ErrorCode.UPLOAD_TOO_LARGE: 413,
    ErrorCode.ARCHIVE_EXPANSION_LIMIT: 413,
    ErrorCode.CORRUPT_ARCHIVE: 400,
    ErrorCode.INVALID_GEOSPATIAL_FILE: 400,
    ErrorCode.INVALID_SOURCE_CRS: 422,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.FILE_NOT_READY: 409,
    ErrorCode.INVALID_PAGINATION: 422,
    ErrorCode.MISSING_SHAPEFILE_COMPONENTS: 400,
    ErrorCode.UNSAFE_ARCHIVE: 400,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.DEPENDENCY_UNAVAILABLE: 503,
    ErrorCode.UNAUTHENTICATED: 401,
}


class AppError(Exception):
    """Base application error that maps to a structured API error response."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    @property
    def status_code(self) -> int:
        return ERROR_HTTP_STATUS.get(self.code, 500)
