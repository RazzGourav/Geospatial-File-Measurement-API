"""SQLAlchemy ORM models for file records and feature results."""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class FileStatus(enum.StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


# Valid state transitions: non-terminal states can move forward, terminal states are final.
VALID_TRANSITIONS: dict[FileStatus, set[FileStatus]] = {
    FileStatus.QUEUED: {FileStatus.PROCESSING, FileStatus.FAILED},
    FileStatus.PROCESSING: {
        FileStatus.COMPLETED,
        FileStatus.COMPLETED_WITH_WARNINGS,
        FileStatus.FAILED,
    },
    FileStatus.COMPLETED: set(),
    FileStatus.COMPLETED_WITH_WARNINGS: set(),
    FileStatus.FAILED: set(),
}


class MeasurementStatus(enum.StrEnum):
    COMPUTED = "COMPUTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_COMPUTED_CRS_UNKNOWN = "NOT_COMPUTED_CRS_UNKNOWN"
    MEASUREMENT_CRS_UNSUPPORTED = "MEASUREMENT_CRS_UNSUPPORTED"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> str:
    return str(uuid.uuid4())


class FileRecord(Base):
    __tablename__ = "file_records"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    filename = Column(String(255), nullable=False)
    format = Column(String(20), nullable=False)  # KML or SHAPEFILE
    source_crs = Column(String(100), nullable=True)
    measurement_crs = Column(String(100), nullable=True)
    status = Column(Enum(FileStatus), nullable=False, default=FileStatus.QUEUED)
    feature_count = Column(Integer, nullable=True)
    warning_count = Column(Integer, nullable=True, default=0)
    error_code = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    features = relationship("FeatureRecord", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_file_status_created", "status", "created_at"),)


class FeatureRecord(Base):
    __tablename__ = "feature_records"

    id = Column(String(36), primary_key=True, default=_new_uuid)
    file_id = Column(String(36), ForeignKey("file_records.id"), nullable=False)
    feature_index = Column(Integer, nullable=False)
    source_feature_id = Column(String(255), nullable=True)
    geometry_type = Column(String(50), nullable=False)
    geometry_geojson = Column(Text, nullable=True)  # GeoJSON string in EPSG:4326
    geometry_crs = Column(String(100), nullable=True, default="EPSG:4326")
    properties_json = Column(Text, nullable=True)  # JSON string of feature properties
    measurement_type = Column(String(20), nullable=True)  # "area" or "length" or null
    measurement_value = Column(Float, nullable=True)
    measurement_unit = Column(String(10), nullable=True)  # "m2" or "m" or null
    measurement_status = Column(Enum(MeasurementStatus), nullable=False)
    measurement_crs = Column(String(100), nullable=True)
    reason = Column(Text, nullable=True)

    file = relationship("FileRecord", back_populates="features")

    __table_args__ = (
        UniqueConstraint("file_id", "feature_index", name="uq_file_feature_index"),
        Index("ix_feature_file_id", "file_id"),
    )
