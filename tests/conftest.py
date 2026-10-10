"""Shared test configuration and fixtures."""

import os
import sys
from pathlib import Path

import pytest

# Ensure we use a test database
os.environ["DATABASE_URL"] = "sqlite:///./test_geospatial.db"
os.environ["APP_ENV"] = "testing"
os.environ["REQUIRE_AUTH"] = "false"
os.environ["LOG_LEVEL"] = "WARNING"


from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.main import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def generate_fixtures():
    """Generate test fixtures before running the test suite."""
    sys.path.insert(0, str(FIXTURES_DIR))
    from generate_fixtures import (
        create_corrupt_zip,
        create_empty_kml,
        create_linestring_kml,
        create_linestring_shapefile_zip,
        create_malformed_kml,
        create_mixed_geometry_kml,
        create_not_a_zip,
        create_path_traversal_zip,
        create_point_kml,
        create_polygon_kml,
        create_shapefile_missing_components_zip,
        create_shapefile_no_prj_zip,
        create_valid_shapefile_zip,
    )

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


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables for each test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    """Provide a test database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """Provide a synchronous test client."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
