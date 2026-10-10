"""Pydantic schemas for API request/response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Upload Response ---
class FileUploadResponse(BaseModel):
    id: str
    filename: str
    format: str
    status: str
    feature_count: int | None = None
    source_crs: str | None = None
    created_at: datetime
    status_url: str


# --- File Detail ---
class FileDetailResponse(BaseModel):
    id: str
    filename: str
    format: str
    feature_count: int | None = None
    source_crs: str | None = None
    measurement_crs: str | None = None
    status: str
    warning_count: int | None = None
    created_at: datetime
    completed_at: datetime | None = None


# --- Measurement ---
class MeasurementResult(BaseModel):
    type: str | None = None
    value: float | None = None
    unit: str | None = None
    status: str
    measurement_crs: str | None = None
    reason: str | None = None


class FeatureResult(BaseModel):
    feature_index: int
    source_feature_id: str | None = None
    geometry_type: str
    geometry_crs: str | None = None
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    measurement: MeasurementResult


class MeasurementsResponse(BaseModel):
    file_id: str
    status: str
    total_count: int
    limit: int
    offset: int
    features: list[FeatureResult]


# --- Error ---
class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
