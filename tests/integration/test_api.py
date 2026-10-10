"""Integration tests for the API and workflows."""

import pytest


def test_health_live(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_health_ready(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_missing_file(client):
    response = client.post("/api/files/")
    assert response.status_code == 422


def test_upload_invalid_extension(client):
    # Try uploading a PDF
    files = {"file": ("test.pdf", b"fake-pdf-content", "application/pdf")}
    response = client.post("/api/files/", files=files)
    assert response.status_code == 415
    data = response.json()
    assert "error" in data
    assert data["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_upload_oversized_file(client, monkeypatch):
    import app.core.config

    monkeypatch.setattr(app.core.config.settings, "max_upload_bytes", 10)

    files = {
        "file": ("test.kml", b"this is more than 10 bytes", "application/vnd.google-earth.kml+xml")
    }
    response = client.post("/api/files/", files=files)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_upload_valid_kml(client, db_session):
    from tests.conftest import FIXTURES_DIR

    kml_path = FIXTURES_DIR / "polygon.kml"

    with open(kml_path, "rb") as f:
        files = {"file": ("polygon.kml", f, "application/vnd.google-earth.kml+xml")}
        response = client.post("/api/files/", files=files)

    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["filename"] == "polygon.kml"
    assert data["format"] == "KML"
    assert data["status"] in ["QUEUED", "PROCESSING", "COMPLETED", "COMPLETED_WITH_WARNINGS"]

    file_id = data["id"]

    # Check detail
    detail_resp = client.get(f"/api/files/{file_id}/")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["status"] == "COMPLETED"
    assert detail_data["feature_count"] == 1
    assert detail_data["source_crs"] == "EPSG:4326"
    assert detail_data["measurement_crs"] == "EPSG:32644"  # Expected UTM zone for Hyderabad

    # Check measurements
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["total_count"] == 1
    assert len(meas_data["features"]) == 1

    feature = meas_data["features"][0]
    assert feature["geometry_type"] == "Polygon"
    assert feature["measurement"]["type"] == "area"
    assert feature["measurement"]["unit"] == "m2"
    assert feature["measurement"]["status"] == "COMPUTED"
    assert feature["measurement"]["value"] > 10000  # Should be ~11,679m2


def test_upload_valid_shapefile(client):
    from tests.conftest import FIXTURES_DIR

    zip_path = FIXTURES_DIR / "valid_shapefile.zip"

    with open(zip_path, "rb") as f:
        files = {"file": ("valid_shapefile.zip", f, "application/zip")}
        response = client.post("/api/files/", files=files)

    assert response.status_code == 202
    file_id = response.json()["id"]

    # Detail
    detail_resp = client.get(f"/api/files/{file_id}/")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["status"] == "COMPLETED"
    assert detail_data["feature_count"] == 1
    # PyProj parse of our PRJ might yield a specific WKT or EPSG.
    assert detail_data["source_crs"] is not None

    # Measurements
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()
    assert meas_data["total_count"] == 1
    feature = meas_data["features"][0]
    assert feature["geometry_type"] == "Polygon"
    assert feature["measurement"]["value"] == pytest.approx(20000.0, rel=0.001)


def test_upload_shapefile_missing_components(client):
    from tests.conftest import FIXTURES_DIR

    zip_path = FIXTURES_DIR / "shapefile_missing_components.zip"

    with open(zip_path, "rb") as f:
        files = {"file": ("bad.zip", f, "application/zip")}
        response = client.post("/api/files/", files=files)

    # The error might happen synchronously or asynchronously depending on implementation.
    # We implemented it synchronously for simplicity in the assignment scope.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MISSING_SHAPEFILE_COMPONENTS"


def test_upload_shapefile_missing_prj_uses_override(client):
    """Test that source_crs is used if .prj is missing."""
    from tests.conftest import FIXTURES_DIR

    zip_path = FIXTURES_DIR / "shapefile_no_prj.zip"

    with open(zip_path, "rb") as f:
        files = {"file": ("no_prj.zip", f, "application/zip")}
        data = {"source_crs": "EPSG:32644"}
        response = client.post("/api/files/", files=files, data=data)

    assert response.status_code == 202
    file_id = response.json()["id"]

    detail = client.get(f"/api/files/{file_id}/").json()
    assert detail["source_crs"] == "EPSG:32644"


def test_upload_mixed_kml_partial_success(client):
    from tests.conftest import FIXTURES_DIR

    kml_path = FIXTURES_DIR / "mixed.kml"

    with open(kml_path, "rb") as f:
        files = {"file": ("mixed.kml", f, "application/vnd.google-earth.kml+xml")}
        response = client.post("/api/files/", files=files)

    assert response.status_code == 202
    file_id = response.json()["id"]

    detail = client.get(f"/api/files/{file_id}/").json()
    assert detail["status"] == "COMPLETED"
    assert detail["feature_count"] == 3
    assert detail["warning_count"] == 0  # The Point is NOT_APPLICABLE, not a warning, wait...
    # Actually, NOT_APPLICABLE might not be counted as a warning in my logic, let's check what I wrote.
    # measure_service.py: if result.status not in (MeasurementStatus.COMPUTED, MeasurementStatus.NOT_APPLICABLE): warning_count += 1
    # So if there are no warnings, it should be COMPLETED. Let's see.
    # The mixed KML has Polygon, LineString, Point.
    assert detail["status"] == "COMPLETED"
    assert detail["warning_count"] == 0

    meas = client.get(f"/api/files/{file_id}/measurements/").json()
    statuses = {f["geometry_type"]: f["measurement"]["status"] for f in meas["features"]}
    assert statuses["Polygon"] == "COMPUTED"
    assert statuses["LineString"] == "COMPUTED"
    assert statuses["Point"] == "NOT_APPLICABLE"


def test_get_measurements_pagination(client, db_session):
    from tests.conftest import FIXTURES_DIR

    kml_path = FIXTURES_DIR / "mixed.kml"

    with open(kml_path, "rb") as f:
        files = {"file": ("mixed.kml", f, "application/vnd.google-earth.kml+xml")}
        file_id = client.post("/api/files/", files=files).json()["id"]

    # Get limit=1, offset=0
    resp1 = client.get(f"/api/files/{file_id}/measurements/?limit=1&offset=0").json()
    assert resp1["total_count"] == 3
    assert len(resp1["features"]) == 1
    assert resp1["features"][0]["feature_index"] == 0

    # Get limit=1, offset=1
    resp2 = client.get(f"/api/files/{file_id}/measurements/?limit=1&offset=1").json()
    assert len(resp2["features"]) == 1
    assert resp2["features"][0]["feature_index"] == 1


def test_upload_corrupt_zip(client):
    from tests.conftest import FIXTURES_DIR

    zip_path = FIXTURES_DIR / "corrupt.zip"
    with open(zip_path, "rb") as f:
        files = {"file": ("corrupt.zip", f, "application/zip")}
        response = client.post("/api/files/", files=files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CORRUPT_ARCHIVE"


def test_upload_path_traversal_zip(client):
    from tests.conftest import FIXTURES_DIR

    zip_path = FIXTURES_DIR / "path_traversal.zip"
    with open(zip_path, "rb") as f:
        files = {"file": ("path_traversal.zip", f, "application/zip")}
        response = client.post("/api/files/", files=files)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSAFE_ARCHIVE"
