"""File API routes: upload, detail, and measurements."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_request_id, verify_api_key
from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.db.repository import FileRepository
from app.db.session import get_db
from app.schemas.files import (
    ErrorResponse,
    FileDetailResponse,
    FileUploadResponse,
    MeasurementsResponse,
)
from app.services import file_service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post(
    "/",
    response_model=FileUploadResponse,
    status_code=202,
    responses={
        400: {"model": ErrorResponse},
        413: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_file(
    file: UploadFile = File(...),
    source_crs: str | None = Form(None),
    db: Session = Depends(get_db),
    request_id: str = Depends(get_request_id),
    _auth: None = Depends(verify_api_key),
):
    """Upload a KML file or a ZIP containing a Shapefile for processing."""
    if not file.filename:
        raise AppError(
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "No filename provided.",
        )

    # Read file content with size limit enforcement
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise AppError(
            ErrorCode.UPLOAD_TOO_LARGE,
            f"Upload exceeds maximum size of {settings.max_upload_bytes} bytes.",
        )

    if len(content) == 0:
        raise AppError(
            ErrorCode.INVALID_GEOSPATIAL_FILE,
            "Uploaded file is empty.",
        )

    repo = FileRepository(db)
    result = file_service.handle_upload(
        repo=repo,
        file_content=content,
        filename=file.filename,
        source_crs_override=source_crs,
    )
    return result


@router.get(
    "/{file_id}/",
    response_model=FileDetailResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_file_detail(
    file_id: str,
    db: Session = Depends(get_db),
    request_id: str = Depends(get_request_id),
    _auth: None = Depends(verify_api_key),
):
    """Retrieve file metadata and processing status."""
    repo = FileRepository(db)
    return file_service.get_file_detail(repo, file_id)


@router.get(
    "/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_measurements(
    file_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    request_id: str = Depends(get_request_id),
    _auth: None = Depends(verify_api_key),
):
    """Retrieve paginated feature measurement results."""
    # Clamp limit to configured max
    if limit > settings.max_page_limit:
        limit = settings.max_page_limit

    repo = FileRepository(db)
    return file_service.get_measurements(repo, file_id, limit=limit, offset=offset)
