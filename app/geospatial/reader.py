"""Safe reading of KML and Shapefile ZIP archives.

Security policy:
- ZIP members are extracted only into server-generated isolated directories.
- Path traversal entries, symlinks, and encrypted members are rejected.
- Archive expansion is bounded by configured limits.
- KML is parsed with external entity resolution disabled.
- Client filenames are never used as filesystem paths.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from lxml import etree

from app.core.config import settings
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)

# Required Shapefile components
REQUIRED_SHP_EXTENSIONS = {".shp", ".shx", ".dbf"}
OPTIONAL_SHP_EXTENSIONS = {".prj", ".cpg", ".sbn", ".sbx", ".fbn", ".fbx", ".ain", ".aih", ".xml"}


def validate_file_extension(filename: str) -> str:
    """Return the normalized format name ('KML' or 'SHAPEFILE') or raise."""
    ext = Path(filename).suffix.lower()
    if ext == ".kml":
        return "KML"
    if ext == ".zip":
        return "SHAPEFILE"
    raise AppError(
        ErrorCode.UNSUPPORTED_FILE_TYPE,
        "Upload a .kml file or a .zip containing a Shapefile.",
        details={"received_filename": filename},
    )


def _validate_zip_safety(zip_path: Path) -> dict[str, list[str]]:
    """Validate ZIP archive for safety and return grouped member paths by extension.

    Checks: corrupt archive, path traversal, symlinks, encrypted entries, expansion limits.
    """
    try:
        zf = zipfile.ZipFile(zip_path, "r")
    except (zipfile.BadZipFile, Exception) as exc:
        raise AppError(
            ErrorCode.CORRUPT_ARCHIVE,
            "The uploaded ZIP archive is corrupt or cannot be read.",
        ) from exc

    with zf:
        total_uncompressed = 0
        compressed_size = os.path.getsize(zip_path)
        members_by_ext: dict[str, list[str]] = {}

        for info in zf.infolist():
            # Reject encrypted entries
            if info.flag_bits & 0x1:
                raise AppError(
                    ErrorCode.UNSAFE_ARCHIVE,
                    "Encrypted ZIP entries are not supported.",
                )

            # Reject directory traversal
            name = info.filename
            if ".." in name or name.startswith("/") or name.startswith("\\"):
                raise AppError(
                    ErrorCode.UNSAFE_ARCHIVE,
                    "ZIP contains path traversal entries.",
                )

            # Reject symlinks (external_attr check for Unix symlinks)
            if (info.external_attr >> 16) & 0o120000 == 0o120000:
                raise AppError(
                    ErrorCode.UNSAFE_ARCHIVE,
                    "ZIP contains symbolic links.",
                )

            # Track expansion
            total_uncompressed += info.file_size
            if total_uncompressed > settings.max_archive_expansion_bytes:
                raise AppError(
                    ErrorCode.ARCHIVE_EXPANSION_LIMIT,
                    f"Decompressed size exceeds limit of {settings.max_archive_expansion_bytes} bytes.",
                )

            # Check expansion ratio
            if (
                compressed_size > 0
                and total_uncompressed / compressed_size > settings.max_zip_ratio
            ):
                raise AppError(
                    ErrorCode.ARCHIVE_EXPANSION_LIMIT,
                    "ZIP expansion ratio exceeds safety limit.",
                )

            # Group by extension
            ext = Path(name).suffix.lower()
            members_by_ext.setdefault(ext, []).append(name)

        return members_by_ext


def _validate_shapefile_components(members_by_ext: dict[str, list[str]]) -> None:
    """Ensure the ZIP contains the required Shapefile components."""
    present_exts = set(members_by_ext.keys())
    missing = REQUIRED_SHP_EXTENSIONS - present_exts
    if missing:
        raise AppError(
            ErrorCode.MISSING_SHAPEFILE_COMPONENTS,
            f"ZIP is missing required Shapefile components: {', '.join(sorted(missing))}",
            details={"missing": sorted(missing)},
        )


def _extract_zip_safely(zip_path: Path, extract_dir: Path) -> Path:
    """Extract ZIP into a server-controlled directory and return the .shp path."""
    members_by_ext = _validate_zip_safety(zip_path)
    _validate_shapefile_components(members_by_ext)

    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Construct safe output path using only the basename
            safe_name = Path(info.filename).name
            target = extract_dir / safe_name
            with zf.open(info) as source, open(target, "wb") as dest:
                shutil.copyfileobj(source, dest)

    # Find the .shp file
    shp_files = list(extract_dir.glob("*.shp"))
    if not shp_files:
        raise AppError(
            ErrorCode.INVALID_GEOSPATIAL_FILE,
            "No .shp file found after extraction.",
        )
    return shp_files[0]


def _parse_kml_safely(kml_path: Path) -> gpd.GeoDataFrame:
    """Parse a KML file with XML external entity resolution disabled.

    Uses lxml to validate the XML is well-formed, then reads via Fiona/GDAL.
    If GDAL's KML/LIBKML driver is unavailable, falls back to manual parsing.
    """
    # First validate XML safety: no external entities
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
        huge_tree=False,
    )
    try:
        tree = etree.parse(str(kml_path), parser)
    except etree.XMLSyntaxError as exc:
        raise AppError(
            ErrorCode.INVALID_GEOSPATIAL_FILE,
            "KML file contains invalid XML.",
        ) from exc

    # Try reading with GDAL/Fiona KML driver
    try:
        import fiona

        drivers = fiona.supported_drivers
        kml_driver = None
        if "KML" in drivers:
            kml_driver = "KML"
        elif "LIBKML" in drivers:
            kml_driver = "LIBKML"

        if kml_driver:
            gdf = gpd.read_file(str(kml_path), driver=kml_driver)
            if gdf.empty:
                # Try listing layers
                layers = fiona.listlayers(str(kml_path), driver=kml_driver)
                frames = []
                for layer_name in layers:
                    layer_gdf = gpd.read_file(str(kml_path), driver=kml_driver, layer=layer_name)
                    if not layer_gdf.empty:
                        frames.append(layer_gdf)
                if frames:
                    gdf = gpd.GeoDataFrame(__import__("pandas").concat(frames, ignore_index=True))
            return gdf
    except Exception:
        pass

    # Fallback: manual KML parsing using lxml
    return _parse_kml_manual(tree)


def _parse_kml_manual(tree: etree._ElementTree) -> gpd.GeoDataFrame:
    """Parse KML manually when GDAL drivers are unavailable.

    Extracts Placemarks with Point, LineString, Polygon, MultiGeometry elements.
    KML coordinates are always in WGS 84 (lon, lat, [alt]).
    """
    root = tree.getroot()
    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    # Try to detect namespace
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0].lstrip("{")
        ns = {"kml": ns_uri}

    placemarks = root.findall(".//kml:Placemark", ns)
    if not placemarks:
        # Try without namespace
        placemarks = root.findall(".//Placemark")

    features = []
    geometries = []

    for pm in placemarks:
        props: dict[str, Any] = {}

        # Extract name and description
        # Extract name and description
        name_el = pm.find("kml:name", ns)
        if name_el is None:
            name_el = pm.find("name")
        if name_el is not None and name_el.text:
            props["name"] = name_el.text.strip()

        desc_el = pm.find("kml:description", ns)
        if desc_el is None:
            desc_el = pm.find("description")
        if desc_el is not None and desc_el.text:
            props["description"] = desc_el.text.strip()

        # Extract extended data
        for data in pm.findall(".//kml:SimpleData", ns) + pm.findall(".//SimpleData"):
            data_name = data.get("name", "")
            if data_name and data.text:
                props[data_name] = data.text.strip()

        for data in pm.findall(".//kml:Data", ns) + pm.findall(".//Data"):
            data_name = data.get("name", "")
            value_el = data.find("kml:value", ns)
            if value_el is None:
                value_el = data.find("value")
            if data_name and value_el is not None and value_el.text:
                props[data_name] = value_el.text.strip()

        # Extract geometry
        geom = _extract_kml_geometry(pm, ns)
        if geom is not None:
            features.append(props)
            geometries.append(geom)

    if not features and not geometries:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    from shapely.geometry import shape as shapely_shape

    shapely_geoms = []
    for g in geometries:
        try:
            shapely_geoms.append(shapely_shape(g))
        except Exception:
            shapely_geoms.append(None)

    gdf = gpd.GeoDataFrame(features, geometry=shapely_geoms, crs="EPSG:4326")
    return gdf


def _parse_kml_coordinates(coord_text: str) -> list[list[float]]:
    """Parse KML coordinate string 'lon,lat[,alt] lon,lat[,alt] ...' into coordinate tuples."""
    coords = []
    for token in coord_text.strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
                coords.append([lon, lat])
            except ValueError:
                continue
    return coords


def _extract_kml_geometry(placemark, ns: dict) -> dict | None:
    """Extract GeoJSON-style geometry dict from a KML Placemark element."""
    # Point
    for tag in ("kml:Point", "Point"):
        point = placemark.find(f".//{tag}", ns) if ":" in tag else placemark.find(f".//{tag}")
        if point is not None:
            coord_el = point.find(".//kml:coordinates", ns)
            if coord_el is None:
                coord_el = point.find(".//coordinates")
            if coord_el is not None and coord_el.text:
                coords = _parse_kml_coordinates(coord_el.text)
                if coords:
                    return {"type": "Point", "coordinates": coords[0]}

    # LineString
    for tag in ("kml:LineString", "LineString"):
        ls = placemark.find(f".//{tag}", ns) if ":" in tag else placemark.find(f".//{tag}")
        if ls is not None:
            coord_el = ls.find(".//kml:coordinates", ns)
            if coord_el is None:
                coord_el = ls.find(".//coordinates")
            if coord_el is not None and coord_el.text:
                coords = _parse_kml_coordinates(coord_el.text)
                if len(coords) >= 2:
                    return {"type": "LineString", "coordinates": coords}

    # Polygon
    for tag in ("kml:Polygon", "Polygon"):
        poly = placemark.find(f".//{tag}", ns) if ":" in tag else placemark.find(f".//{tag}")
        if poly is not None:
            return _extract_kml_polygon(poly, ns)

    # MultiGeometry
    for tag in ("kml:MultiGeometry", "MultiGeometry"):
        mg = placemark.find(f".//{tag}", ns) if ":" in tag else placemark.find(f".//{tag}")
        if mg is not None:
            return _extract_kml_multi_geometry(mg, ns)

    return None


def _extract_kml_polygon(poly_el, ns: dict) -> dict | None:
    """Extract polygon coordinates from KML Polygon element."""
    rings = []

    # Outer boundary
    outer = poly_el.find(".//kml:outerBoundaryIs//kml:coordinates", ns)
    if outer is None:
        outer = poly_el.find(".//outerBoundaryIs//coordinates")

    if outer is not None and outer.text:
        coords = _parse_kml_coordinates(outer.text)
        if coords:
            rings.append(coords)
    else:
        return None

    # Inner boundaries (holes)
    for inner in poly_el.findall(".//kml:innerBoundaryIs//kml:coordinates", ns) + poly_el.findall(
        ".//innerBoundaryIs//coordinates"
    ):
        if inner.text:
            coords = _parse_kml_coordinates(inner.text)
            if coords:
                rings.append(coords)

    return {"type": "Polygon", "coordinates": rings}


def _extract_kml_multi_geometry(mg_el, ns: dict) -> dict | None:
    """Extract MultiGeometry from KML."""
    geom_types: dict[str, list] = {}

    for child in mg_el:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "Point":
            coord_el = child.find(".//kml:coordinates", ns)
            if coord_el is None:
                coord_el = child.find(".//coordinates")
            if coord_el is not None and coord_el.text:
                coords = _parse_kml_coordinates(coord_el.text)
                if coords:
                    geom_types.setdefault("Point", []).append(coords[0])

        elif tag == "LineString":
            coord_el = child.find(".//kml:coordinates", ns)
            if coord_el is None:
                coord_el = child.find(".//coordinates")
            if coord_el is not None and coord_el.text:
                coords = _parse_kml_coordinates(coord_el.text)
                if len(coords) >= 2:
                    geom_types.setdefault("LineString", []).append(coords)

        elif tag == "Polygon":
            poly_geom = _extract_kml_polygon(child, ns)
            if poly_geom:
                geom_types.setdefault("Polygon", []).append(poly_geom["coordinates"])

    # Convert to appropriate multi or geometry collection
    if len(geom_types) == 1:
        gtype, items = next(iter(geom_types.items()))
        if gtype == "Point" and len(items) > 1:
            return {"type": "MultiPoint", "coordinates": items}
        elif gtype == "Point":
            return {"type": "Point", "coordinates": items[0]}
        elif gtype == "LineString" and len(items) > 1:
            return {"type": "MultiLineString", "coordinates": items}
        elif gtype == "LineString":
            return {"type": "LineString", "coordinates": items[0]}
        elif gtype == "Polygon" and len(items) > 1:
            return {"type": "MultiPolygon", "coordinates": items}
        elif gtype == "Polygon":
            return {"type": "Polygon", "coordinates": items[0]}

    # Mixed types -> GeometryCollection
    if geom_types:
        sub_geoms = []
        for gtype, items in geom_types.items():
            for item in items:
                if gtype == "Point":
                    sub_geoms.append({"type": "Point", "coordinates": item})
                elif gtype == "LineString":
                    sub_geoms.append({"type": "LineString", "coordinates": item})
                elif gtype == "Polygon":
                    sub_geoms.append({"type": "Polygon", "coordinates": item})
        return {"type": "GeometryCollection", "geometries": sub_geoms}

    return None


def read_geospatial_file(file_path: Path, file_format: str, temp_dir: Path) -> gpd.GeoDataFrame:
    """Read a geospatial file and return a GeoDataFrame.

    Args:
        file_path: Path to the uploaded file.
        file_format: 'KML' or 'SHAPEFILE'.
        temp_dir: Server-controlled temporary directory for extraction.

    Returns:
        GeoDataFrame with geometry and attributes.
    """
    try:
        if file_format == "KML":
            return _parse_kml_safely(file_path)
        elif file_format == "SHAPEFILE":
            shp_path = _extract_zip_safely(file_path, temp_dir / "shapefile")
            return gpd.read_file(str(shp_path))
        else:
            raise AppError(
                ErrorCode.UNSUPPORTED_FILE_TYPE,
                f"Unsupported format: {file_format}",
            )
    except AppError:
        raise
    except Exception as exc:
        logger.error("Failed to read geospatial file: %s", exc)
        raise AppError(
            ErrorCode.INVALID_GEOSPATIAL_FILE,
            "The uploaded file could not be read as a valid geospatial dataset.",
        ) from exc
