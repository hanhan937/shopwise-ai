"""GET /products search & filter parameters (database stubbed out)."""
from app import crud
from app.product_filters import ProductFilters


class Spy:
    """Records what the router passes to crud and returns canned data."""

    def __init__(self, monkeypatch, make_product, total=12):
        self.list_calls, self.count_calls = [], []
        self.items = [make_product(price=849), make_product(price=999)]

        def fake_list(db, limit, offset, filters=None):
            self.list_calls.append((limit, offset, filters))
            return self.items

        def fake_count(db, filters=None):
            self.count_calls.append(filters)
            return total

        monkeypatch.setattr(crud, "list_products", fake_list)
        monkeypatch.setattr(crud, "count_products", fake_count)


# ----------------------------------------------------------- happy paths
def test_no_filters_passes_an_inactive_filter_object(client, monkeypatch, make_product):
    spy = Spy(monkeypatch, make_product)
    assert client.get("/products").status_code == 200
    limit, offset, filters = spy.list_calls[0]
    assert (limit, offset) == (20, 0)
    assert filters == ProductFilters() and not filters.is_active()


def test_every_filter_is_parsed_and_passed_to_the_query_layer(client, monkeypatch, make_product):
    spy = Spy(monkeypatch, make_product)
    r = client.get("/products", params={"q": "dell", "min_price": 500, "max_price": 1000, "min_ram_gb": 16, "cpu": "i7"})
    assert r.status_code == 200
    expected = ProductFilters(q="dell", min_price=500, max_price=1000, min_ram_gb=16, cpu="i7")
    assert spy.list_calls[0][2] == expected
    assert spy.count_calls[0] == expected  # total is counted with the SAME filters


def test_response_shape_is_unchanged_and_total_reflects_filtered_count(client, monkeypatch, make_product):
    Spy(monkeypatch, make_product, total=12)
    body = client.get("/products?q=lenovo").json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert body["total"] == 12 and len(body["items"]) == 2


def test_filters_work_together_with_pagination(client, monkeypatch, make_product):
    spy = Spy(monkeypatch, make_product, total=12)
    body = client.get("/products?q=lenovo&min_ram_gb=16&limit=5&offset=5").json()
    limit, offset, filters = spy.list_calls[0]
    assert (limit, offset) == (5, 5)
    assert filters == ProductFilters(q="lenovo", min_ram_gb=16)
    assert (body["limit"], body["offset"], body["total"]) == (5, 5, 12)


def test_text_is_trimmed_and_blank_text_is_ignored(client, monkeypatch, make_product):
    spy = Spy(monkeypatch, make_product)
    client.get("/products", params={"q": "  dell  ", "cpu": "   "})
    assert spy.list_calls[0][2] == ProductFilters(q="dell")


def test_zero_price_and_boundary_values_are_accepted(client, monkeypatch, make_product):
    spy = Spy(monkeypatch, make_product)
    assert client.get("/products?min_price=0&max_price=0&min_ram_gb=1").status_code == 200
    assert spy.list_calls[0][2] == ProductFilters(min_price=0, max_price=0, min_ram_gb=1)
    assert client.get("/products?min_price=500&max_price=500").status_code == 200  # equal bounds are valid


# --------------------------------------------------------- validation errors
def test_min_price_above_max_price_is_a_clear_422(client, monkeypatch, make_product):
    Spy(monkeypatch, make_product)
    r = client.get("/products?min_price=1000&max_price=500")
    assert r.status_code == 422
    (err,) = r.json()["detail"]
    assert err["loc"] == ["query", "min_price"]
    assert "min_price must not be greater than max_price" in err["msg"]


def test_invalid_numbers_are_rejected_with_the_field_name(client, monkeypatch, make_product):
    Spy(monkeypatch, make_product)
    cases = {
        "min_price=-1": "min_price",
        "max_price=-5": "max_price",
        "min_price=abc": "min_price",
        "max_price=1e9": "max_price",  # absurdly large
        "min_ram_gb=0": "min_ram_gb",
        "min_ram_gb=-8": "min_ram_gb",
        "min_ram_gb=2000": "min_ram_gb",
        "min_ram_gb=16.5": "min_ram_gb",
        "min_ram_gb=lots": "min_ram_gb",
    }
    for qs, field in cases.items():
        r = client.get(f"/products?{qs}")
        assert r.status_code == 422, qs
        assert field in [part for e in r.json()["detail"] for part in e["loc"]], qs


def test_text_length_and_word_limits(client, monkeypatch, make_product):
    Spy(monkeypatch, make_product)
    assert client.get("/products", params={"q": "x" * 101}).status_code == 422
    assert client.get("/products", params={"cpu": "x" * 51}).status_code == 422
    too_many = client.get("/products", params={"q": "a b c d e f g h i"})
    assert too_many.status_code == 422
    assert "at most 8 words" in too_many.json()["detail"][0]["msg"]
    assert client.get("/products", params={"q": "a b c d e f g h"}).status_code == 200  # exactly 8 is fine


def test_all_problems_are_reported_together(client, monkeypatch, make_product):
    Spy(monkeypatch, make_product)
    r = client.get("/products", params={"min_price": 900, "max_price": 100, "q": "a b c d e f g h i"})
    assert r.status_code == 422
    assert {e["loc"][1] for e in r.json()["detail"]} == {"min_price", "q"}


def test_pagination_validation_still_applies_with_filters(client):
    for qs in ("q=dell&limit=0", "q=dell&limit=101", "q=dell&offset=-1"):
        assert client.get(f"/products?{qs}").status_code == 422, qs


def test_filter_queries_still_report_a_down_database_as_503(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    def boom(db, limit, offset, filters=None):
        raise OperationalError("SELECT", {}, Exception("connection refused"))

    monkeypatch.setattr(crud, "list_products", boom)
    r = client.get("/products?q=dell")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "database_unavailable"
