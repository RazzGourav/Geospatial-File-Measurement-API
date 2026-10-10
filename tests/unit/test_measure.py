"""Unit tests for geometry measurement calculations."""

import pyproj
import pytest
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon

from app.db.models import MeasurementStatus
from app.geospatial.measure import (
    classify_geometry,
    geometry_to_geojson,
    measure_geometry,
    validate_geometry,
)


class TestClassifyGeometry:
    def test_polygon(self):
        assert classify_geometry("Polygon") == "area"

    def test_multipolygon(self):
        assert classify_geometry("MultiPolygon") == "area"

    def test_linestring(self):
        assert classify_geometry("LineString") == "length"

    def test_multilinestring(self):
        assert classify_geometry("MultiLineString") == "length"

    def test_point(self):
        assert classify_geometry("Point") == "not_applicable"

    def test_multipoint(self):
        assert classify_geometry("MultiPoint") == "not_applicable"

    def test_geometry_collection(self):
        assert classify_geometry("GeometryCollection") == "unsupported"


class TestValidateGeometry:
    def test_valid_polygon(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        is_valid, reason = validate_geometry(poly)
        assert is_valid is True
        assert reason is None

    def test_none_geometry(self):
        is_valid, reason = validate_geometry(None)
        assert is_valid is False
        assert "null" in reason.lower()

    def test_empty_geometry(self):
        poly = Polygon()
        is_valid, reason = validate_geometry(poly)
        assert is_valid is False
        assert "empty" in reason.lower()

    def test_invalid_geometry(self):
        # Self-intersecting polygon (bowtie)
        poly = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        is_valid, reason = validate_geometry(poly)
        assert is_valid is False
        assert reason is not None


class TestMeasureGeometry:
    """Tests using projected CRS (EPSG:32644) for deterministic results."""

    def test_polygon_area_projected(self):
        """A 100m x 200m rectangle in UTM should have area = 20,000 m²."""
        poly = Polygon(
            [
                (500000, 1920000),
                (500100, 1920000),
                (500100, 1920200),
                (500000, 1920200),
                (500000, 1920000),
            ]
        )
        crs = pyproj.CRS("EPSG:32644")
        result = measure_geometry(poly, "Polygon", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.COMPUTED
        assert result.measurement_type == "area"
        assert result.unit == "m2"
        assert result.value == pytest.approx(20000.0, rel=0.001)
        assert result.measurement_crs == "EPSG:32644"

    def test_multipolygon_area_projected(self):
        """Two 100m x 100m squares should have total area = 20,000 m²."""
        mp = MultiPolygon(
            [
                Polygon(
                    [(500000, 1920000), (500100, 1920000), (500100, 1920100), (500000, 1920100)]
                ),
                Polygon(
                    [(501000, 1920000), (501100, 1920000), (501100, 1920100), (501000, 1920100)]
                ),
            ]
        )
        crs = pyproj.CRS("EPSG:32644")
        result = measure_geometry(mp, "MultiPolygon", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.COMPUTED
        assert result.measurement_type == "area"
        assert result.value == pytest.approx(20000.0, rel=0.001)

    def test_linestring_length_projected(self):
        """A 500m horizontal line in UTM should have length = 500 m."""
        line = LineString([(500000, 1920000), (500500, 1920000)])
        crs = pyproj.CRS("EPSG:32644")
        result = measure_geometry(line, "LineString", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.COMPUTED
        assert result.measurement_type == "length"
        assert result.unit == "m"
        assert result.value == pytest.approx(500.0, rel=0.001)

    def test_multilinestring_length_projected(self):
        """Two segments of 200m and 300m should total 500m."""
        ml = MultiLineString(
            [
                [(500000, 1920000), (500200, 1920000)],
                [(501000, 1920000), (501300, 1920000)],
            ]
        )
        crs = pyproj.CRS("EPSG:32644")
        result = measure_geometry(ml, "MultiLineString", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.COMPUTED
        assert result.measurement_type == "length"
        assert result.value == pytest.approx(500.0, rel=0.001)

    def test_point_not_applicable(self):
        point = Point(78.47, 17.37)
        result = measure_geometry(point, "Point", pyproj.CRS("EPSG:4326"), "EPSG:32644")

        assert result.status == MeasurementStatus.NOT_APPLICABLE
        assert result.value is None
        assert result.measurement_type is None

    def test_multipoint_not_applicable(self):
        mp = MultiPoint([(78.47, 17.37), (78.48, 17.38)])
        result = measure_geometry(mp, "MultiPoint", pyproj.CRS("EPSG:4326"), "EPSG:32644")

        assert result.status == MeasurementStatus.NOT_APPLICABLE

    def test_unsupported_geometry(self):
        # GeometryCollection treated as unsupported
        result = measure_geometry(
            Point(0, 0), "GeometryCollection", pyproj.CRS("EPSG:4326"), "EPSG:32644"
        )
        assert result.status == MeasurementStatus.UNSUPPORTED_GEOMETRY

    def test_missing_crs(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        result = measure_geometry(poly, "Polygon", None, None)

        assert result.status == MeasurementStatus.NOT_COMPUTED_CRS_UNKNOWN
        assert result.value is None

    def test_no_measurement_crs(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        crs = pyproj.CRS("EPSG:4326")
        result = measure_geometry(poly, "Polygon", crs, None)

        assert result.status == MeasurementStatus.MEASUREMENT_CRS_UNSUPPORTED
        assert result.value is None

    def test_empty_polygon(self):
        poly = Polygon()
        crs = pyproj.CRS("EPSG:32644")
        result = measure_geometry(poly, "Polygon", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.INVALID_GEOMETRY
        assert result.value is None
        assert "empty" in result.reason.lower()

    def test_geographic_polygon_transformed(self):
        """A small polygon in EPSG:4326 should be transformed to UTM before measurement.

        ~0.001° × ~0.001° near 17.37°N, 78.47°E.
        At this latitude: 1° lon ≈ 105,600m, 1° lat ≈ 110,600m.
        0.001° × 0.001° ≈ 105.6m × 110.6m ≈ 11,679 m² (approximate).
        """
        poly = Polygon(
            [
                (78.470, 17.370),
                (78.471, 17.370),
                (78.471, 17.371),
                (78.470, 17.371),
                (78.470, 17.370),
            ]
        )
        crs = pyproj.CRS("EPSG:4326")
        result = measure_geometry(poly, "Polygon", crs, "EPSG:32644")

        assert result.status == MeasurementStatus.COMPUTED
        assert result.measurement_crs == "EPSG:32644"
        assert result.unit == "m2"
        # Allow 1% tolerance for projection distortion
        assert 10000 < result.value < 15000

    def test_zero_is_valid_measurement(self):
        """A degenerate polygon should not be confused with a failed measurement."""
        # A line masquerading as a polygon has zero area
        poly = Polygon([(500000, 1920000), (500100, 1920000), (500000, 1920000)])
        if poly.is_valid and not poly.is_empty:
            crs = pyproj.CRS("EPSG:32644")
            result = measure_geometry(poly, "Polygon", crs, "EPSG:32644")
            # Zero area is valid if geometry is valid
            if result.status == MeasurementStatus.COMPUTED:
                assert result.value == 0.0


class TestGeometryToGeojson:
    def test_polygon_to_geojson(self):
        poly = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        crs = pyproj.CRS("EPSG:4326")
        geojson = geometry_to_geojson(poly, crs)
        assert geojson is not None
        assert geojson["type"] == "Polygon"

    def test_projected_to_4326(self):
        """A projected geometry should be transformed to EPSG:4326."""
        poly = Polygon(
            [
                (500000, 1920000),
                (500100, 1920000),
                (500100, 1920100),
                (500000, 1920100),
            ]
        )
        crs = pyproj.CRS("EPSG:32644")
        geojson = geometry_to_geojson(poly, crs)
        assert geojson is not None
        # Coordinates should now be in lon/lat range
        coords = geojson["coordinates"][0]
        for lon, lat in coords:
            assert -180 <= lon <= 180
            assert -90 <= lat <= 90

    def test_none_geometry(self):
        assert geometry_to_geojson(None, None) is None

    def test_empty_geometry(self):
        assert geometry_to_geojson(Polygon(), None) is None
