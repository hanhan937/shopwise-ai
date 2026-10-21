"""Shared helpers for the offline evaluation tests (no AWS, no PostgreSQL)."""
from __future__ import annotations

import time

from app.eval.checks import Outcome
from app.ingest import DEFAULT_CSV, read_rows
from app.models import Product
from app.schemas import ProductOut


def catalog_products() -> list[Product]:
    """The real seed catalog (data/laptops.csv) as transient Product rows with ids 1..41."""
    rows, errors = read_rows(DEFAULT_CSV)
    assert not errors
    return [Product(id=i, content_hash="x", **r.model_dump()) for i, r in enumerate(rows, 1)]


def catalog_dict() -> dict[int, dict]:
    """Same shape the live runner gets from GET /products."""
    return {p.id: ProductOut.model_validate(p).model_dump() for p in catalog_products()}


def by_sku(catalog: dict[int, dict], sku: str) -> dict:
    return next(p for p in catalog.values() if p["sku"] == sku)


def chat_ok(reply: str, products: list[dict] | None = None, tools: list[str] | None = None) -> Outcome:
    return Outcome("ok", 200, {"reply": reply, "products": products or [], "tools_used": tools or []}, latency_s=0.1)


class TestClientTransport:
    """Runner transport backed by FastAPI's TestClient: the real routes, in-process."""

    __test__ = False  # not a pytest test class

    def __init__(self, client):
        self.client = client

    def request(self, method, path, payload=None):
        started = time.monotonic()
        res = self.client.request(method, path, json=payload)
        try:
            body = res.json()
        except ValueError:
            return Outcome("malformed", res.status_code, error="response is not JSON")
        return Outcome("ok" if res.status_code < 400 else "http_error", res.status_code, body, latency_s=time.monotonic() - started)
