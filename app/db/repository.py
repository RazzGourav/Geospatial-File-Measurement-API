"""Repository layer for database persistence operations."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import (
    VALID_TRANSITIONS,
    FeatureRecord,
    FileRecord,
    FileStatus,
    MeasurementStatus,
)

logger = get_logger(__name__)


class FileRepository:
    """Encapsulates all database operations for file and feature records."""

    def __init__(self, db: Session):
        self.db = db

    def create_file(
        self,
        *,
        file_id: str,
        filename: str,
        file_format: str,
        source_crs: str | None = None,
    ) -> FileRecord:
        record = FileRecord(
            id=file_id,
            filename=filename,
            format=file_format,
            source_crs=source_crs,
            status=FileStatus.QUEUED,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_file(self, file_id: str) -> FileRecord | None:
        return self.db.query(FileRecord).filter(FileRecord.id == file_id).first()

    def update_status(
        self,
        file_id: str,
        new_status: FileStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
        feature_count: int | None = None,
        warning_count: int | None = None,
        source_crs: str | None = None,
        measurement_crs: str | None = None,
    ) -> FileRecord:
        record = self.get_file(file_id)
        if not record:
            raise ValueError(f"File {file_id} not found")

        # Validate state transition
        current = record.status
        if new_status not in VALID_TRANSITIONS.get(current, set()):
            raise ValueError(f"Invalid transition from {current.value} to {new_status.value}")

        record.status = new_status

        if new_status == FileStatus.PROCESSING:
            record.started_at = datetime.now(UTC)

        if new_status in (
            FileStatus.COMPLETED,
            FileStatus.COMPLETED_WITH_WARNINGS,
            FileStatus.FAILED,
        ):
            record.completed_at = datetime.now(UTC)

        if error_code is not None:
            record.error_code = error_code
        if error_message is not None:
            record.error_message = error_message
        if feature_count is not None:
            record.feature_count = feature_count
        if warning_count is not None:
            record.warning_count = warning_count
        if source_crs is not None:
            record.source_crs = source_crs
        if measurement_crs is not None:
            record.measurement_crs = measurement_crs

        self.db.commit()
        self.db.refresh(record)
        return record

    def create_feature(
        self,
        *,
        file_id: str,
        feature_index: int,
        source_feature_id: str | None,
        geometry_type: str,
        geometry_geojson: dict | None,
        geometry_crs: str | None,
        properties: dict | None,
        measurement_type: str | None,
        measurement_value: float | None,
        measurement_unit: str | None,
        measurement_status: MeasurementStatus,
        measurement_crs: str | None,
        reason: str | None,
    ) -> FeatureRecord:
        record = FeatureRecord(
            file_id=file_id,
            feature_index=feature_index,
            source_feature_id=source_feature_id,
            geometry_type=geometry_type,
            geometry_geojson=json.dumps(geometry_geojson) if geometry_geojson else None,
            geometry_crs=geometry_crs,
            properties_json=json.dumps(properties, default=str) if properties else None,
            measurement_type=measurement_type,
            measurement_value=measurement_value,
            measurement_unit=measurement_unit,
            measurement_status=measurement_status,
            measurement_crs=measurement_crs,
            reason=reason,
        )
        self.db.add(record)
        return record

    def bulk_commit(self) -> None:
        """Commit all pending feature records in a single transaction."""
        self.db.commit()

    def get_features_paginated(
        self, file_id: str, *, limit: int, offset: int
    ) -> list[FeatureRecord]:
        return (
            self.db.query(FeatureRecord)
            .filter(FeatureRecord.file_id == file_id)
            .order_by(FeatureRecord.feature_index)
            .offset(offset)
            .limit(limit)
            .all()
        )

    def count_features(self, file_id: str) -> int:
        return self.db.query(FeatureRecord).filter(FeatureRecord.file_id == file_id).count()
