from sqlalchemy.exc import OperationalError

from app import crud


# ------------------------------------------------------------------ /health
def test_health_ok(client, fake_db, monkeypatch):
    fake_db.scalar.return_value = 1  # pgvector extension present
    monkeypatch.setattr(crud, "count_products", lambda db: 41)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": True, "pgvector": True, "products_total": 41}


def test_health_reports_missing_pgvector(client, fake_db, monkeypatch):
    fake_db.scalar.return_value = 0
    monkeypatch.setattr(crud, "count_products", lambda db: 0)
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json()["status"] == "degraded" and r.json()["pgvector"] is False


def test_health_reports_database_down_without_crashing(client, fake_db):
    fake_db.execute.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))
    r = client.get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "database": False, "pgvector": False, "products_total": 0}


# ---------------------------------------------------------------- /products
def test_products_returns_paginated_envelope(client, monkeypatch, make_product):
    seen = {}

    def fake_list(db, limit, offset, filters=None):
        seen.update(limit=limit, offset=offset)
        return [make_product(price=849), make_product(price=999)]

    monkeypatch.setattr(crud, "list_products", fake_list)
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: 41)

    body = client.get("/products").json()
    assert seen == {"limit": 20, "offset": 0}  # defaults
    assert body["total"] == 41 and body["limit"] == 20 and body["offset"] == 0
    assert [p["price"] for p in body["items"]] == [849.0, 999.0]
    first = body["items"][0]
    assert first["best_for"] == ["programming", "travel"]
    assert first["is_mock"] is True and first["source_name"] == "ShopWise Mock Catalog"


def test_products_passes_pagination_params(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(crud, "list_products", lambda db, limit, offset, filters=None: seen.update(limit=limit, offset=offset) or [])
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: 0)
    body = client.get("/products?limit=5&offset=10").json()
    assert seen == {"limit": 5, "offset": 10}
    assert body == {"items": [], "total": 0, "limit": 5, "offset": 10}


def test_products_rejects_invalid_pagination(client):
    for qs in ("limit=0", "limit=101", "offset=-1", "limit=abc"):
        assert client.get(f"/products?{qs}").status_code == 422, qs


def test_products_returns_503_when_database_is_down(client, monkeypatch):
    def boom(db, limit, offset, filters=None):
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(crud, "list_products", boom)
    r = client.get("/products")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "database_unavailable"
