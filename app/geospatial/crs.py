"""CRS discovery, validation, and projected CRS selection.

Policy (from PRD Section 6.2):
1. Discover source CRS from dataset metadata.
2. Accept source_crs override only when metadata is absent.
3. Never guess a missing CRS.
4. Normalize to EPSG:4326 for extent analysis and GeoJSON output.
5. Select a suitable projected CRS (typically UTM) for local/regional datasets.
6. Reject measurements for global, polar, or antimeridian-crossing extents.
7. Use explicit lon/lat axis ordering.
"""

from __future__ import annotations

import pyproj

from app.core.logging import get_logger

logger = get_logger(__name__)


def discover_crs(dataset_crs: object | None) -> str | None:
    """Extract a CRS identifier string from a dataset's CRS metadata.

    Returns an EPSG string like 'EPSG:4326' or the full WKT/proj string,
    or None if no CRS can be determined.
    """
    if dataset_crs is None:
        return None

    try:
        crs = pyproj.CRS(dataset_crs)
        epsg = crs.to_epsg()
        if epsg:
            return f"EPSG:{epsg}"
        # Fall back to authority code
        auth = crs.to_authority()
        if auth:
            return f"{auth[0]}:{auth[1]}"
        # Use WKT as last resort
        return crs.to_wkt()
    except Exception:
        return None


def validate_crs_string(crs_string: str) -> pyproj.CRS:
    """Validate a user-provided CRS string and return a pyproj.CRS object.

    Raises ValueError if the CRS string is not recognized.
    """
    try:
        crs = pyproj.CRS(crs_string)
        return crs
    except Exception as exc:
        raise ValueError(f"Unrecognized CRS identifier: {crs_string}") from exc


def resolve_source_crs(
    dataset_crs: object | None,
    user_override: str | None,
) -> tuple[str | None, pyproj.CRS | None]:
    """Determine the effective source CRS.

    Returns:
        (crs_string, crs_object) where either or both may be None if CRS is unknown.
        The override is used only when dataset CRS is missing.
    """
    discovered = discover_crs(dataset_crs)

    if discovered:
        crs_obj = pyproj.CRS(discovered)
        crs_str = discovered
        if user_override and user_override != discovered:
            logger.info(
                "Ignoring user CRS override '%s' because dataset has CRS: %s",
                user_override,
                discovered,
            )
        return crs_str, crs_obj

    if user_override:
        crs_obj = validate_crs_string(user_override)
        return user_override, crs_obj

    return None, None


def is_geographic_crs(crs: pyproj.CRS) -> bool:
    """Check if a CRS uses angular (geographic) coordinates."""
    return crs.is_geographic


def select_measurement_crs(
    crs: pyproj.CRS, bounds: tuple[float, float, float, float]
) -> tuple[str | None, str | None]:
    """Select a suitable projected CRS for measurement.

    Args:
        crs: The source CRS.
        bounds: (minx, miny, maxx, maxy) in the source CRS.

    Returns:
        (measurement_crs_string, rejection_reason)
        If a suitable CRS is found, rejection_reason is None.
        If not suitable, measurement_crs_string is None and a reason is provided.
    """
    if not is_geographic_crs(crs):
        # Already projected with presumably linear units
        unit_name = _get_linear_unit(crs)
        if unit_name and "metre" in unit_name.lower() or unit_name and "meter" in unit_name.lower():
            epsg = crs.to_epsg()
            crs_str = f"EPSG:{epsg}" if epsg else crs.to_wkt()
            return crs_str, None
        # Non-metre projected CRS: still usable but note units
        epsg = crs.to_epsg()
        crs_str = f"EPSG:{epsg}" if epsg else crs.to_wkt()
        return crs_str, None

    # Geographic CRS: need to find a suitable UTM zone
    minx, miny, maxx, maxy = bounds

    # Check for antimeridian crossing
    if minx > maxx:
        return None, "Dataset crosses the antimeridian; automatic UTM selection is not supported."

    # Check for polar regions (beyond 84°N or 80°S where UTM is not defined)
    if maxy > 84 or miny < -80:
        return None, "Dataset extends into polar regions where UTM zones are not defined."

    # Check for overly broad extent (spanning more than ~6 degrees of longitude or latitude)
    lon_span = maxx - minx
    lat_span = maxy - miny

    if lon_span > 12 or lat_span > 12:
        return (
            None,
            f"Dataset extent is too broad ({lon_span:.1f}° lon × {lat_span:.1f}° lat) "
            "for a single UTM zone projection.",
        )

    # Calculate centroid for UTM zone selection
    center_lon = (minx + maxx) / 2
    center_lat = (miny + maxy) / 2

    # UTM zone calculation
    zone_number = int((center_lon + 180) / 6) + 1
    zone_number = max(1, min(60, zone_number))

    # Northern or southern hemisphere
    epsg_code = 32600 + zone_number if center_lat >= 0 else 32700 + zone_number

    measurement_crs = f"EPSG:{epsg_code}"

    # Verify the CRS exists
    try:
        pyproj.CRS(measurement_crs)
    except Exception:
        return None, f"Could not construct measurement CRS {measurement_crs}."

    return measurement_crs, None


def _get_linear_unit(crs: pyproj.CRS) -> str | None:
    """Get the linear unit name for a CRS."""
    try:
        cs = crs.coordinate_system
        if cs and cs.axis_list:
            return cs.axis_list[0].unit_name
    except Exception:
        pass
    return None


def get_transformer(
    source_crs: str | pyproj.CRS,
    target_crs: str | pyproj.CRS,
) -> pyproj.Transformer:
    """Create a transformer with explicit axis ordering (lon, lat)."""
    return pyproj.Transformer.from_crs(
        source_crs,
        target_crs,
        always_xy=True,
    )
