"""End-to-end check against REAL PostgreSQL + pgvector.

Skipped unless TEST_DATABASE_URL is set. It resets the products table, so point it at
a throwaway database (the name must contain "test"):

    docker compose up -d db
    docker compose exec db createdb -U shopwise shopwise_test
    TEST_DATABASE_URL=postgresql+psycopg://shopwise:shopwise@localhost:5432/shopwise_test pytest tests/test_integration_db.py
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

URL = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    "test" not in URL.rsplit("/", 1)[-1], reason="set TEST_DATABASE_URL to a database whose name contains 'test'"
)


def test_schema_import_and_api_against_real_postgres():
    from app.database import SessionLocal, init_db
    from app.ingest import DEFAULT_CSV, ingest, read_rows
    from app.main import app

    expected = len(read_rows(DEFAULT_CSV)[0])

    init_db()
    init_db()  # idempotent
    with SessionLocal() as db:
        assert db.scalar(text("SELECT count(*) FROM pg_extension WHERE extname='vector'")) == 1
        assert ingest(db, DEFAULT_CSV, reset=True).inserted == expected
        again = ingest(db, DEFAULT_CSV)
        assert (again.inserted, again.updated, again.unchanged) == (0, 0, expected)

    client = TestClient(app)  # no lifespan: startup already done above
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "database": True, "pgvector": True, "products_total": expected}

    page = client.get("/products?limit=5&offset=0").json()
    assert page["total"] == expected and len(page["items"]) == 5
    assert all(p["is_mock"] for p in page["items"])
    assert isinstance(page["items"][0]["price"], float)

    last = client.get(f"/products?limit=100&offset={expected - 3}").json()
    assert len(last["items"]) == 3


# ----------------------------------------------------------------------------
# Module 2A: search & filtering against real PostgreSQL.
#
# Differential test: for each filter combination, the SQL results must equal the
# results of an independent, plain-Python implementation of the documented rules
# applied to the CSV. This catches wrong operators, escaping bugs, AND/OR mistakes
# and pagination errors that mocked tests cannot see.
# ----------------------------------------------------------------------------
SEARCH_FIELDS = ("brand", "name", "cpu", "gpu", "os", "storage_type", "display_resolution", "best_for")


def _expected_skus(rows, q=None, min_price=None, max_price=None, min_ram_gb=None, cpu=None):
    out = set()
    for r in rows:
        ok = all(any(w.lower() in str(getattr(r, f)).lower() for f in SEARCH_FIELDS) for w in (q or "").split())
        ok = ok and all(w.lower() in r.cpu.lower() for w in (cpu or "").split())
        ok = ok and (min_price is None or r.price >= min_price) and (max_price is None or r.price <= max_price)
        ok = ok and (min_ram_gb is None or r.ram_gb >= min_ram_gb)
        if ok:
            out.add(r.sku)
    return out


def _fetch_all(client, **params):
    """Walk every page of /products?... and return (skus_in_order, reported_total)."""
    skus, offset, total = [], 0, None
    while True:
        page = client.get("/products", params={**params, "limit": 7, "offset": offset})
        assert page.status_code == 200, page.text
        body = page.json()
        total = body["total"]
        skus += [p["sku"] for p in body["items"]]
        offset += 7
        if offset >= total:
            return skus, total


@pytest.fixture
def seeded_client():
    from app.database import SessionLocal, init_db
    from app.ingest import DEFAULT_CSV, ingest, read_rows
    from app.main import app

    init_db()
    with SessionLocal() as db:
        ingest(db, DEFAULT_CSV, reset=True)
    return TestClient(app), read_rows(DEFAULT_CSV)[0]


FILTER_CASES = [
    {},
    {"q": "lenovo"},
    {"q": "LENOVO"},  # case-insensitive
    {"q": "ryzen"},  # matches the CPU column
    {"q": "oled"},  # matches display_resolution
    {"q": "programming"},  # matches the use-case tags
    {"q": "dell ryzen"},  # words are ANDed across columns
    {"q": "rtx 4060"},  # GPU, two words
    {"q": "ubuntu"},  # OS
    {"min_price": 800, "max_price": 1000},
    {"max_price": 999},  # inclusive upper bound hits a $999 laptop
    {"min_price": 999, "max_price": 999},  # equal bounds
    {"min_ram_gb": 32},
    {"min_ram_gb": 16, "max_price": 1000},  # the original demo scenario
    {"cpu": "ryzen 7"},
    {"cpu": "i7", "min_ram_gb": 32},
    {"q": "lenovo", "cpu": "ryzen", "min_price": 400, "max_price": 900, "min_ram_gb": 16},
    {"q": "zzz-no-such-laptop"},
    {"min_price": 100000},
]


@pytest.mark.parametrize("params", FILTER_CASES, ids=lambda p: "&".join(f"{k}={v}" for k, v in p.items()) or "no-filters")
def test_search_matches_independent_python_implementation(seeded_client, params):
    client, rows = seeded_client
    expected = _expected_skus(rows, **params)
    skus, total = _fetch_all(client, **params)
    assert set(skus) == expected
    assert total == len(expected)
    assert len(skus) == len(set(skus)), "pagination returned duplicates"
    assert skus == [r.sku for r in rows if r.sku in expected], "results must stay in stable catalog order"


def test_like_wildcards_typed_by_the_user_match_literally(seeded_client):
    client, rows = seeded_client
    for wildcard in ("%", "_", "\\", "%%"):
        body = client.get("/products", params={"q": wildcard}).json()
        assert body["total"] == 0 and body["items"] == [], wildcard
    # A leading wildcard must not turn into "match everything"
    assert client.get("/products", params={"cpu": "%"}).json()["total"] == 0


def test_filtered_page_count_is_correct_and_pages_do_not_overlap(seeded_client):
    client, rows = seeded_client
    expected = _expected_skus(rows, min_ram_gb=16)
    first = client.get("/products", params={"min_ram_gb": 16, "limit": 5, "offset": 0}).json()
    second = client.get("/products", params={"min_ram_gb": 16, "limit": 5, "offset": 5}).json()
    assert first["total"] == second["total"] == len(expected)
    assert len(first["items"]) == 5
    assert not {p["sku"] for p in first["items"]} & {p["sku"] for p in second["items"]}
    assert all(p["ram_gb"] >= 16 for p in first["items"] + second["items"])


def test_invalid_filters_are_rejected_before_touching_the_database(seeded_client):
    client, _ = seeded_client
    r = client.get("/products", params={"min_price": 900, "max_price": 100})
    assert r.status_code == 422 and "min_price" in r.text
    assert client.get("/products", params={"min_ram_gb": 0}).status_code == 422


# ----------------------------------------------------------------------------
# Module 3A: embedding column size and pgvector ranking against real PostgreSQL.
# Vectors are hand-made (no AWS): with unit vectors the cosine distances are known exactly.
# ----------------------------------------------------------------------------
def _column_type(db):
    return db.scalar(text(
        "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='products'::regclass AND attname='embedding'"
    ))  # fmt: skip


def test_migration_command_resizes_only_while_empty_and_is_repeatable(seeded_client):
    from app.config import settings
    from app.database import SessionLocal, engine
    from app.migrate_embedding_dim import migrate

    with SessionLocal() as db:
        assert _column_type(db) == f"vector({settings.embedding_dim})"  # new databases are created at the right size
        db.execute(text("ALTER TABLE products ALTER COLUMN embedding TYPE vector(1536)"))  # like a Module 1 database
        db.commit()

    assert migrate(engine, 1024, check_only=True).status == "would_migrate"
    with SessionLocal() as db:
        assert _column_type(db) == "vector(1536)"  # --check changed nothing

    first = migrate(engine, 1024)
    assert (first.status, first.before, first.after) == ("migrated", "vector(1536)", "vector(1024)")
    assert migrate(engine, 1024).status == "already_done"  # repeatable

    with SessionLocal() as db:
        db.execute(text("ALTER TABLE products ALTER COLUMN embedding TYPE vector(1536)"))
        db.execute(text("UPDATE products SET embedding = array_fill(0.1, ARRAY[1536])::vector WHERE id = (SELECT min(id) FROM products)"))
        db.commit()
    blocked = migrate(engine, 1024)
    assert (blocked.status, blocked.stored_vectors) == ("blocked", 1)
    with SessionLocal() as db:
        assert _column_type(db) == "vector(1536)"  # data present: left alone
        assert db.scalar(text("SELECT count(embedding) FROM products")) == 1
        db.execute(text("UPDATE products SET embedding = NULL"))
        db.commit()
    assert migrate(engine, settings.embedding_dim).status == "migrated"  # restore for the other tests
    with pytest.raises(ValueError):
        migrate(engine, 1536)  # Titan V2 can't produce 1536


def _unit(*weights, dim=1024):
    norm = sum(w * w for w in weights) ** 0.5
    return [w / norm for w in weights] + [0.0] * (dim - len(weights))


def test_semantic_search_ranks_by_cosine_distance_with_sql_filters(seeded_client, monkeypatch):
    import io
    import json

    from app import crud
    from app.ai.embeddings import model_tag
    from app.config import settings
    from app.database import SessionLocal
    from app.models import Product
    from app.product_filters import ProductFilters
    from app.routers import semantic as semantic_router

    client, _ = seeded_client
    tag = model_tag(settings.embedding_model_id, settings.embedding_dim)
    with SessionLocal() as db:
        a, b, c, other = db.scalars(text("SELECT id FROM products ORDER BY price DESC LIMIT 4")).all()
        vectors = {a: _unit(1, 0), b: _unit(1, 1), c: _unit(0, 1), other: _unit(1, 0)}
        for pid, vec in vectors.items():
            p = db.get(Product, pid)
            p.embedding, p.embedding_text = vec, "test"
            p.embedding_model = tag if pid != other else "some-other-model:1024"  # must be ignored
        db.commit()
        price_of_a = float(db.get(Product, a).price)

        rows = crud.semantic_search(db, _unit(1, 0), tag, limit=10)
        assert [p.id for p, _ in rows] == [a, b, c]
        assert [round(d, 4) for _, d in rows] == [0.0, 0.2929, 1.0]
        assert crud.count_embedded(db, tag) == 3

        cheaper = crud.semantic_search(db, _unit(1, 0), tag, 10, ProductFilters(max_price=price_of_a - 0.01))
        assert a not in [p.id for p, _ in cheaper]

    class FakeTitan:
        def invoke_model(self, **kwargs):
            return {"body": io.BytesIO(json.dumps({"embedding": _unit(1, 0)}).encode())}

    monkeypatch.setattr(semantic_router, "create_bedrock_client", lambda: FakeTitan())
    body = client.get("/products/semantic-search", params={"q": "anything", "limit": 2}).json()
    assert [p["id"] for p in body["items"]] == [a, b]
    assert body["items"][0]["similarity"] == 1.0 and body["embedded_products"] == 3
