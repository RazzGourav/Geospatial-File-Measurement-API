"""Generate small test fixture files for KML and Shapefile formats.

Run this script to create test fixtures in the tests/fixtures/ directory.
"""

import zipfile
from pathlib import Path

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent


def create_polygon_kml():
    """Create a KML file with a simple polygon near Hyderabad, India.

    The polygon is roughly a rectangle in EPSG:4326 coordinates.
    Expected: area measurement in m² after UTM transformation.
    """
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test Polygon</name>
    <Placemark>
      <name>Parcel 01</name>
      <description>Test polygon near Hyderabad</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              78.4744,17.3753,0
              78.4754,17.3753,0
              78.4754,17.3763,0
              78.4744,17.3763,0
              78.4744,17.3753,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    (FIXTURES_DIR / "polygon.kml").write_text(kml, encoding="utf-8")


def create_linestring_kml():
    """Create a KML file with a simple linestring."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test LineString</name>
    <Placemark>
      <name>Road Segment</name>
      <LineString>
        <coordinates>
          78.4744,17.3753,0
          78.4844,17.3753,0
        </coordinates>
      </LineString>
    </Placemark>
  </Document>
</kml>"""
    (FIXTURES_DIR / "linestring.kml").write_text(kml, encoding="utf-8")


def create_point_kml():
    """Create a KML file with a point feature."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Test Point</name>
    <Placemark>
      <name>Control Point</name>
      <Point>
        <coordinates>78.4744,17.3753,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    (FIXTURES_DIR / "point.kml").write_text(kml, encoding="utf-8")


def create_mixed_geometry_kml():
    """Create a KML file with mixed geometry types."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Mixed Geometries</name>
    <Placemark>
      <name>Parcel 01</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              78.4744,17.3753,0
              78.4754,17.3753,0
              78.4754,17.3763,0
              78.4744,17.3763,0
              78.4744,17.3753,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Road Segment</name>
      <LineString>
        <coordinates>
          78.4744,17.3753,0
          78.4844,17.3753,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>Control Point</name>
      <Point>
        <coordinates>78.4744,17.3753,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    (FIXTURES_DIR / "mixed.kml").write_text(kml, encoding="utf-8")


def create_malformed_kml():
    """Create an invalid/malformed KML file."""
    (FIXTURES_DIR / "malformed.kml").write_text("<not-valid-xml><<<", encoding="utf-8")


def create_empty_kml():
    """Create a KML file with no features."""
    kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Empty Document</name>
  </Document>
</kml>"""
    (FIXTURES_DIR / "empty.kml").write_text(kml, encoding="utf-8")


def create_valid_shapefile_zip():
    """Create a minimal valid Shapefile ZIP with a polygon feature."""
    import geopandas as gpd
    from shapely.geometry import Polygon

    # Rectangle: (500000, 1920000) to (500100, 1920200)
    # Width: 100m, Height: 200m, Area: 20,000 m²
    poly = Polygon(
        [
            (500000, 1920000),
            (500100, 1920000),
            (500100, 1920200),
            (500000, 1920200),
            (500000, 1920000),
        ]
    )

    gdf = gpd.GeoDataFrame({"NAME": ["Test Polygon"]}, geometry=[poly], crs="EPSG:32644")

    temp_dir = FIXTURES_DIR / "temp_shp"
    temp_dir.mkdir(exist_ok=True)

    shp_path = temp_dir / "test_polygon.shp"
    gdf.to_file(shp_path)

    zip_path = FIXTURES_DIR / "valid_shapefile.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in temp_dir.glob("test_polygon.*"):
            zf.write(f, f.name)

    # Cleanup
    import shutil

    shutil.rmtree(temp_dir)


def create_shapefile_no_prj_zip():
    """Create a Shapefile ZIP without a .prj file."""
    zip_path = FIXTURES_DIR / "valid_shapefile.zip"
    no_prj_path = FIXTURES_DIR / "shapefile_no_prj.zip"

    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(no_prj_path, "w") as dst:
        for item in src.infolist():
            if not item.filename.endswith(".prj"):
                dst.writestr(item, src.read(item.filename))


def create_shapefile_missing_components_zip():
    """Create a ZIP with only a .shp file."""
    zip_path = FIXTURES_DIR / "valid_shapefile.zip"
    bad_path = FIXTURES_DIR / "shapefile_missing_components.zip"

    with zipfile.ZipFile(zip_path, "r") as src, zipfile.ZipFile(bad_path, "w") as dst:
        for item in src.infolist():
            if item.filename.endswith(".shp"):
                dst.writestr(item, src.read(item.filename))


def create_corrupt_zip():
    """Create a corrupt ZIP file."""
    (FIXTURES_DIR / "corrupt.zip").write_bytes(b"PK\\x03\\x04not-a-real-zip-content")


def create_path_traversal_zip():
    """Create a ZIP with path traversal entries."""
    zip_path = FIXTURES_DIR / "path_traversal.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../etc/passwd", "malicious content")


def create_not_a_zip():
    """Create a file with .zip extension that is not actually a ZIP."""
    (FIXTURES_DIR / "not_a_zip.zip").write_text("This is not a ZIP file", encoding="utf-8")


def create_linestring_shapefile_zip():
    """Create a Shapefile ZIP with a LineString feature in EPSG:32644."""
    import geopandas as gpd
    from shapely.geometry import LineString

    line = LineString([(500000, 1920000), (500500, 1920000)])
    gdf = gpd.GeoDataFrame({"NAME": ["Test Line"]}, geometry=[line], crs="EPSG:32644")

    temp_dir = FIXTURES_DIR / "temp_line_shp"
    temp_dir.mkdir(exist_ok=True)

    shp_path = temp_dir / "test_line.shp"
    gdf.to_file(shp_path)

    zip_path = FIXTURES_DIR / "linestring_shapefile.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in temp_dir.glob("test_line.*"):
            zf.write(f, f.name)

    import shutil

    shutil.rmtree(temp_dir)


if __name__ == "__main__":
    print(f"Generating fixtures in {FIXTURES_DIR}")
    create_polygon_kml()
    create_linestring_kml()
    create_point_kml()
    create_mixed_geometry_kml()
    create_malformed_kml()
    create_empty_kml()
    create_valid_shapefile_zip()
    create_shapefile_no_prj_zip()
    create_shapefile_missing_components_zip()
    create_corrupt_zip()
    create_path_traversal_zip()
    create_not_a_zip()
    create_linestring_shapefile_zip()
    print("Done! All fixtures created.")
