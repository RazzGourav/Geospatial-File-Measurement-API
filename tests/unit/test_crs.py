"""Unit tests for CRS discovery, validation, and projection selection."""

import pyproj
import pytest

from app.geospatial.crs import (
    discover_crs,
    is_geographic_crs,
    resolve_source_crs,
    select_measurement_crs,
    validate_crs_string,
)


class TestDiscoverCrs:
    def test_discover_from_epsg_int(self):
        crs = pyproj.CRS("EPSG:4326")
        result = discover_crs(crs)
        assert result == "EPSG:4326"

    def test_discover_from_utm_crs(self):
        crs = pyproj.CRS("EPSG:32644")
        result = discover_crs(crs)
        assert result == "EPSG:32644"

    def test_discover_from_none(self):
        assert discover_crs(None) is None

    def test_discover_from_wkt(self):
        wkt = pyproj.CRS("EPSG:4326").to_wkt()
        result = discover_crs(wkt)
        assert result == "EPSG:4326"


class TestValidateCrsString:
    def test_valid_epsg(self):
        crs = validate_crs_string("EPSG:4326")
        assert crs.to_epsg() == 4326

    def test_valid_utm(self):
        crs = validate_crs_string("EPSG:32644")
        assert crs.to_epsg() == 32644

    def test_invalid_crs(self):
        with pytest.raises(ValueError, match="Unrecognized"):
            validate_crs_string("INVALID:99999")


class TestResolveSourceCrs:
    def test_dataset_crs_takes_priority(self):
        """When dataset has CRS, user override is ignored."""
        dataset_crs = pyproj.CRS("EPSG:4326")
        crs_str, crs_obj = resolve_source_crs(dataset_crs, "EPSG:32644")
        assert crs_str == "EPSG:4326"
        assert crs_obj.to_epsg() == 4326

    def test_override_used_when_missing(self):
        """When dataset CRS is missing, override is accepted."""
        crs_str, crs_obj = resolve_source_crs(None, "EPSG:4326")
        assert crs_str == "EPSG:4326"
        assert crs_obj.to_epsg() == 4326

    def test_both_missing(self):
        crs_str, crs_obj = resolve_source_crs(None, None)
        assert crs_str is None
        assert crs_obj is None


class TestIsGeographicCrs:
    def test_4326_is_geographic(self):
        assert is_geographic_crs(pyproj.CRS("EPSG:4326")) is True

    def test_utm_is_not_geographic(self):
        assert is_geographic_crs(pyproj.CRS("EPSG:32644")) is False


class TestSelectMeasurementCrs:
    def test_geographic_local_extent(self):
        """A small local extent near Hyderabad should select UTM zone 44N."""
        crs = pyproj.CRS("EPSG:4326")
        bounds = (78.4, 17.3, 78.6, 17.5)  # Hyderabad area
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs == "EPSG:32644"
        assert reason is None

    def test_geographic_broad_extent_rejected(self):
        """An extent spanning > 12 degrees should be rejected."""
        crs = pyproj.CRS("EPSG:4326")
        bounds = (0.0, 0.0, 90.0, 45.0)  # Global extent
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs is None
        assert "too broad" in reason.lower()

    def test_polar_region_rejected(self):
        """Polar regions beyond UTM coverage should be rejected."""
        crs = pyproj.CRS("EPSG:4326")
        bounds = (10.0, 85.0, 20.0, 89.0)  # Beyond 84°N
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs is None
        assert "polar" in reason.lower()

    def test_projected_crs_passes_through(self):
        """A projected CRS with metre units is used as-is."""
        crs = pyproj.CRS("EPSG:32644")
        bounds = (500000, 1920000, 510000, 1930000)
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs == "EPSG:32644"
        assert reason is None

    def test_southern_hemisphere_utm(self):
        """A location in the southern hemisphere gets the correct UTM zone."""
        crs = pyproj.CRS("EPSG:4326")
        bounds = (28.0, -34.0, 28.5, -33.5)  # Cape Town area
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs == "EPSG:32735"  # UTM zone 35S
        assert reason is None

    def test_antimeridian_crossing(self):
        """Antimeridian crossing should be rejected."""
        crs = pyproj.CRS("EPSG:4326")
        # minx > maxx indicates antimeridian crossing
        bounds = (179.0, -10.0, -179.0, 10.0)
        measurement_crs, reason = select_measurement_crs(crs, bounds)
        assert measurement_crs is None
        assert "antimeridian" in reason.lower()
