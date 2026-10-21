"""Test setup.

Unit tests never touch Postgres: the DB session is a MagicMock and data-access
functions are monkeypatched. Set TEST_DATABASE_URL (a throwaway database whose name
contains "test") to also run tests/test_integration_db.py against real Postgres.
"""
import os

# Must be set before `app` is imported (the engine is created at import time).
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/shopwise_test"
)

from unittest.mock import MagicMock  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Product  # noqa: E402


@pytest.fixture
def make_product():
    counter = {"n": 0}

    def _make(**overrides) -> Product:
        counter["n"] += 1
        n = counter["n"]
        data = dict(
            id=n, sku=f"MOCK-TEST-{n:03d}", name=f"TestBook {n}", brand="Lenovo", price=899,
            cpu="AMD Ryzen 7 7840U", gpu="Integrated Radeon 780M", ram_gb=16, storage_gb=512,
            storage_type="SSD", display_size_in=14.0, display_resolution="1920x1200", weight_kg=1.3,
            battery_hours=12, os="Windows 11", best_for="programming;travel",
            description="A test laptop used only in unit tests.", source_name="ShopWise Mock Catalog",
            source_url="https://example.com/mock-catalog/test", is_mock=True, content_hash="x",
        )
        data.update(overrides)
        return Product(**data)  # transient instance; never added to a session

    return _make


@pytest.fixture
def fake_db():
    return MagicMock()


@pytest.fixture
def client(fake_db):
    app.dependency_overrides[get_db] = lambda: fake_db
    # Deliberately not used as a context manager: skips startup (DB init / auto-import).
    yield TestClient(app)
    app.dependency_overrides.clear()
