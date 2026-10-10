"""Geometry validation and measurement calculations.

All measurements are 2D planimetric. Area is in square metres, length is in metres.
Geometries are transformed to a projected CRS before measurement.
Invalid geometries are not silently repaired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyproj
from shapely import ops
from shapely.geometry import mapping
from shapely.geometry.base import BaseGeometry

from app.core.logging import get_logger
from app.db.models import MeasurementStatus

logger = get_logger(__name__)

# Geometry types that produce area measurements
AREA_TYPES = {"Polygon", "MultiPolygon"}
# Geometry types that produce length measurements
LENGTH_TYPES = {"LineString", "MultiLineString"}
# Geometry types that are explicitly not applicable
NOT_APPLICABLE_TYPES = {"Point", "MultiPoint"}


@dataclass
class MeasurementResult:
    """Result of measuring a single geometry."""

    measurement_type: str | None  # "area", "length", or None
    value: float | None
    unit: str | None  # "m2", "m", or None
    status: MeasurementStatus
    measurement_crs: str | None
    reason: str | None


def classify_geometry(geom_type: str) -> str:
    """Classify a geometry type into measurement category.

    Returns: 'area', 'length', 'not_applicable', or 'unsupported'
    """
    if geom_type in AREA_TYPES:
        return "area"
    elif geom_type in LENGTH_TYPES:
        return "length"
    elif geom_type in NOT_APPLICABLE_TYPES:
        return "not_applicable"
    else:
        return "unsupported"


def validate_geometry(geom: BaseGeometry | None) -> tuple[bool, str | None]:
    """Check if a geometry is valid for measurement.

    Returns (is_valid, reason_if_invalid).
    """
    if geom is None:
        return False, "Geometry is null."
    if geom.is_empty:
        return False, "Geometry is empty."
    if not geom.is_valid:
        from shapely.validation import explain_validity

        return False, f"Geometry is invalid: {explain_validity(geom)}"
    return True, None


def measure_geometry(
    geom: BaseGeometry,
    geom_type: str,
    source_crs: pyproj.CRS | None,
    measurement_crs_str: str | None,
) -> MeasurementResult:
    """Compute the measurement for a geometry.

    Args:
        geom: The Shapely geometry object.
        geom_type: The geometry type string.
        source_crs: The source CRS of the geometry (may be None).
        measurement_crs_str: The selected measurement CRS string (may be None).

    Returns:
        MeasurementResult with the calculated value or appropriate status.
    """
    # Check geometry type classification
    category = classify_geometry(geom_type)

    if category == "not_applicable":
        return MeasurementResult(
            measurement_type=None,
            value=None,
            unit=None,
            status=MeasurementStatus.NOT_APPLICABLE,
            measurement_crs=None,
            reason=f"{geom_type} geometry does not require measurement.",
        )

    if category == "unsupported":
        return MeasurementResult(
            measurement_type=None,
            value=None,
            unit=None,
            status=MeasurementStatus.UNSUPPORTED_GEOMETRY,
            measurement_crs=None,
            reason=f"{geom_type} geometry type is not supported for measurement.",
        )

    # Validate geometry
    is_valid, invalid_reason = validate_geometry(geom)
    if not is_valid:
        return MeasurementResult(
            measurement_type=category,
            value=None,
            unit="m2" if category == "area" else "m",
            status=MeasurementStatus.INVALID_GEOMETRY,
            measurement_crs=None,
            reason=invalid_reason,
        )

    # Check CRS availability
    if source_crs is None:
        return MeasurementResult(
            measurement_type=category,
            value=None,
            unit="m2" if category == "area" else "m",
            status=MeasurementStatus.NOT_COMPUTED_CRS_UNKNOWN,
            measurement_crs=None,
            reason="Source CRS is unknown; cannot compute measurement.",
        )

    if measurement_crs_str is None:
        return MeasurementResult(
            measurement_type=category,
            value=None,
            unit="m2" if category == "area" else "m",
            status=MeasurementStatus.MEASUREMENT_CRS_UNSUPPORTED,
            measurement_crs=None,
            reason="No suitable measurement CRS could be selected for this extent.",
        )

    # Transform geometry to measurement CRS
    try:
        measurement_crs = pyproj.CRS(measurement_crs_str)
        transformer = pyproj.Transformer.from_crs(source_crs, measurement_crs, always_xy=True)
        projected_geom = ops.transform(transformer.transform, geom)
    except Exception as exc:
        logger.warning("CRS transformation failed: %s", exc)
        return MeasurementResult(
            measurement_type=category,
            value=None,
            unit="m2" if category == "area" else "m",
            status=MeasurementStatus.MEASUREMENT_CRS_UNSUPPORTED,
            measurement_crs=measurement_crs_str,
            reason=f"Coordinate transformation failed: {exc}",
        )

    # Calculate measurement
    if category == "area":
        value = projected_geom.area
        unit = "m2"
    else:
        value = projected_geom.length
        unit = "m"

    return MeasurementResult(
        measurement_type=category,
        value=value,
        unit=unit,
        status=MeasurementStatus.COMPUTED,
        measurement_crs=measurement_crs_str,
        reason=None,
    )


def geometry_to_geojson(
    geom: BaseGeometry | None,
    source_crs: pyproj.CRS | None,
) -> dict[str, Any] | None:
    """Convert a geometry to GeoJSON in EPSG:4326 for API output.

    If the source CRS is already EPSG:4326 (or geographic WGS84), no transform needed.
    For projected geometries, transform to EPSG:4326 first.
    """
    if geom is None or geom.is_empty:
        return None

    if source_crs is not None:
        target_crs = pyproj.CRS("EPSG:4326")
        if not source_crs.equals(target_crs):
            try:
                transformer = pyproj.Transformer.from_crs(source_crs, target_crs, always_xy=True)
                geom = ops.transform(transformer.transform, geom)
            except Exception as exc:
                logger.warning("Failed to transform geometry to EPSG:4326: %s", exc)
                # Return in original CRS as fallback
                pass

    return mapping(geom)
