"""File upload and processing service.

Coordinates file validation, geospatial reading, CRS selection, measurement,
and result persistence. This is the main orchestrator, independent of HTTP routing.
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.db.models import FileStatus, MeasurementStatus
from app.db.repository import FileRepository
from app.geospatial import crs as crs_service
from app.geospatial import measure as measure_service
from app.geospatial.reader import read_geospatial_file, validate_file_extension

logger = get_logger(__name__)


def handle_upload(
    repo: FileRepository,
    file_content: bytes,
    filename: str,
    source_crs_override: str | None = None,
) -> dict[str, Any]:
    """Process an uploaded file: validate, persist metadata, and process features.

    Args:
        repo: Database repository.
        file_content: Raw file bytes.
        filename: Original client filename (used for format detection only).
        source_crs_override: Optional CRS string from the caller.

    Returns:
        Dict matching FileUploadResponse schema.
    """
    # Validate file extension
    file_format = validate_file_extension(filename)

    # Validate file size
    if len(file_content) > settings.max_upload_bytes:
        raise AppError(
            ErrorCode.UPLOAD_TOO_LARGE,
            f"Upload exceeds maximum size of {settings.max_upload_bytes} bytes.",
        )

    # Validate source CRS override if provided
    if source_crs_override:
        try:
            crs_service.validate_crs_string(source_crs_override)
        except ValueError as err:
            raise AppError(
                ErrorCode.INVALID_SOURCE_CRS,
                f"Unrecognized CRS identifier: {source_crs_override}",
                details={"source_crs": source_crs_override},
            ) from err

    # Generate server-side ID and safe storage path
    file_id = str(uuid.uuid4())

    # Create file record in QUEUED state
    record = repo.create_file(
        file_id=file_id,
        filename=filename,
        file_format=file_format,
    )

    # Process synchronously (documented development mode; not a durable queue)
    temp_dir = None
    try:
        # Create isolated temporary directory
        temp_dir = Path(tempfile.mkdtemp(prefix=f"geo_{file_id}_"))

        # Write file to temp directory with safe name
        safe_ext = ".kml" if file_format == "KML" else ".zip"
        temp_file = temp_dir / f"upload{safe_ext}"
        temp_file.write_bytes(file_content)

        # Transition to PROCESSING
        repo.update_status(file_id, FileStatus.PROCESSING)

        # Process the file
        _process_file(repo, file_id, temp_file, file_format, source_crs_override, temp_dir)

    except AppError:
        # Processing failed with a known error
        with contextlib.suppress(Exception):
            repo.update_status(
                file_id,
                FileStatus.FAILED,
                error_code=ErrorCode.INVALID_GEOSPATIAL_FILE.value,
                error_message="File processing failed.",
            )
        raise
    except Exception as exc:
        logger.exception("Unexpected error processing file %s", file_id)
        with contextlib.suppress(Exception):
            repo.update_status(
                file_id,
                FileStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                error_message="An internal error occurred during processing.",
            )
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred during file processing.",
        ) from exc
    finally:
        # Clean up temporary files
        if temp_dir and temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_exc:
                logger.warning("Failed to clean up temp dir %s: %s", temp_dir, cleanup_exc)

    # Re-fetch the record after processing
    record = repo.get_file(file_id)

    return {
        "id": record.id,
        "filename": record.filename,
        "format": record.format,
        "status": record.status.value,
        "feature_count": record.feature_count,
        "source_crs": record.source_crs,
        "created_at": record.created_at,
        "status_url": f"/api/files/{record.id}/",
    }


def _process_file(
    repo: FileRepository,
    file_id: str,
    file_path: Path,
    file_format: str,
    source_crs_override: str | None,
    temp_dir: Path,
) -> None:
    """Core processing: read file, extract features, measure, and persist results."""
    logger.info("Processing file %s (format=%s)", file_id, file_format)

    # Read geospatial data
    gdf = read_geospatial_file(file_path, file_format, temp_dir)

    if gdf.empty or len(gdf) == 0:
        repo.update_status(
            file_id,
            FileStatus.COMPLETED,
            feature_count=0,
            warning_count=0,
        )
        return

    # Enforce feature count limit
    if len(gdf) > settings.max_feature_count:
        raise AppError(
            ErrorCode.UPLOAD_TOO_LARGE,
            f"File contains {len(gdf)} features, exceeding the limit of {settings.max_feature_count}.",
        )

    # Determine source CRS
    crs_str, crs_obj = crs_service.resolve_source_crs(gdf.crs, source_crs_override)
    logger.info("File %s: source CRS = %s", file_id, crs_str)

    # Select measurement CRS
    measurement_crs_str = None
    measurement_rejection = None

    if crs_obj is not None:
        if crs_service.is_geographic_crs(crs_obj):
            # Need to select a projected CRS
            bounds = gdf.total_bounds  # (minx, miny, maxx, maxy)
            measurement_crs_str, measurement_rejection = crs_service.select_measurement_crs(
                crs_obj, tuple(bounds)
            )
        else:
            # Already projected
            measurement_crs_str, measurement_rejection = crs_service.select_measurement_crs(
                crs_obj, tuple(gdf.total_bounds)
            )

    if measurement_rejection:
        logger.warning("File %s: measurement CRS rejection: %s", file_id, measurement_rejection)

    # Process each feature
    warning_count = 0
    for idx, row in gdf.iterrows():
        feature_index = int(idx) if isinstance(idx, (int, float)) else int(gdf.index.get_loc(idx))
        geom = row.geometry

        # Extract feature properties (exclude geometry column)
        props = {}
        for col in gdf.columns:
            if col == "geometry":
                continue
            val = row[col]
            # Convert non-serializable types
            if hasattr(val, "item"):  # numpy types
                val = val.item()
            if val is not None and not isinstance(val, (str, int, float, bool)):
                val = str(val)
            props[col] = val

        # Determine geometry type
        geom_type = geom.geom_type if geom is not None else "Unknown"

        # Try to extract a source feature ID from common attribute names
        source_feature_id = None
        for id_field in ("id", "Id", "ID", "fid", "FID", "Name", "name", "OBJECTID"):
            if id_field in props and props[id_field] is not None:
                source_feature_id = str(props[id_field])
                break

        # Compute measurement
        result = measure_service.measure_geometry(
            geom=geom,
            geom_type=geom_type,
            source_crs=crs_obj,
            measurement_crs_str=measurement_crs_str if measurement_rejection is None else None,
        )

        # If there was a file-level CRS rejection, apply it to measurable features
        if measurement_rejection and result.status == MeasurementStatus.MEASUREMENT_CRS_UNSUPPORTED:
            result = measure_service.MeasurementResult(
                measurement_type=result.measurement_type,
                value=None,
                unit=result.unit,
                status=MeasurementStatus.MEASUREMENT_CRS_UNSUPPORTED,
                measurement_crs=None,
                reason=measurement_rejection,
            )

        # Convert geometry to GeoJSON in EPSG:4326
        geojson = measure_service.geometry_to_geojson(geom, crs_obj)

        # Track warnings
        if result.status not in (MeasurementStatus.COMPUTED, MeasurementStatus.NOT_APPLICABLE):
            warning_count += 1

        # Persist feature result
        repo.create_feature(
            file_id=file_id,
            feature_index=feature_index,
            source_feature_id=source_feature_id,
            geometry_type=geom_type,
            geometry_geojson=geojson,
            geometry_crs="EPSG:4326" if geojson else None,
            properties=props,
            measurement_type=result.measurement_type,
            measurement_value=result.value,
            measurement_unit=result.unit,
            measurement_status=result.status,
            measurement_crs=result.measurement_crs,
            reason=result.reason,
        )

    # Commit all features in a single transaction
    repo.bulk_commit()

    # Determine final status
    final_status = FileStatus.COMPLETED_WITH_WARNINGS if warning_count > 0 else FileStatus.COMPLETED

    repo.update_status(
        file_id,
        final_status,
        feature_count=len(gdf),
        warning_count=warning_count,
        source_crs=crs_str,
        measurement_crs=measurement_crs_str,
    )

    logger.info(
        "File %s processing complete: %d features, %d warnings, status=%s",
        file_id,
        len(gdf),
        warning_count,
        final_status.value,
    )


def get_file_detail(repo: FileRepository, file_id: str) -> dict[str, Any]:
    """Retrieve file metadata."""
    record = repo.get_file(file_id)
    if not record:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found.")

    return {
        "id": record.id,
        "filename": record.filename,
        "format": record.format,
        "feature_count": record.feature_count,
        "source_crs": record.source_crs,
        "measurement_crs": record.measurement_crs,
        "status": record.status.value,
        "warning_count": record.warning_count,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
    }


def get_measurements(
    repo: FileRepository,
    file_id: str,
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Retrieve paginated feature measurement results."""
    record = repo.get_file(file_id)
    if not record:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "File not found.")

    # Check if file is ready
    if record.status in (FileStatus.QUEUED, FileStatus.PROCESSING):
        raise AppError(
            ErrorCode.FILE_NOT_READY,
            "File processing is not yet complete.",
        )

    total = repo.count_features(file_id)
    features = repo.get_features_paginated(file_id, limit=limit, offset=offset)

    feature_results = []
    for f in features:
        geojson = json.loads(f.geometry_geojson) if f.geometry_geojson else None
        props = json.loads(f.properties_json) if f.properties_json else None

        measurement = {
            "type": f.measurement_type,
            "value": f.measurement_value,
            "unit": f.measurement_unit,
            "status": f.measurement_status.value,
            "measurement_crs": f.measurement_crs,
            "reason": f.reason,
        }

        feature_results.append(
            {
                "feature_index": f.feature_index,
                "source_feature_id": f.source_feature_id,
                "geometry_type": f.geometry_type,
                "geometry_crs": f.geometry_crs,
                "geometry": geojson,
                "properties": props,
                "measurement": measurement,
            }
        )

    return {
        "file_id": file_id,
        "status": record.status.value,
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "features": feature_results,
    }
