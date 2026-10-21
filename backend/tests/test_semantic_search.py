"""GET /products/semantic-search (Module 3A): fake Titan, stubbed database queries, no AWS calls."""
import io
import json

import pytest
from botocore.exceptions import ClientError
from sqlalchemy.exc import DataError

from app import crud
from app.ai.embeddings import model_tag
from app.config import settings
from app.routers import semantic as semantic_router

TAG = model_tag(settings.embedding_model_id, settings.embedding_dim)


class FakeTitan:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    def invoke_model(self, **kwargs):
        self.calls.append(json.loads(kwargs["body"]))
        if self.error:
            raise self.error
        return {"body": io.BytesIO(json.dumps({"embedding": [0.5] * settings.embedding_dim}).encode())}


@pytest.fixture
def titan(monkeypatch):
    fake = FakeTitan()
    monkeypatch.setattr(semantic_router, "create_bedrock_client", lambda: fake)
    return fake


@pytest.fixture
def db_stub(monkeypatch, make_product):
    state = {"embedded": 41, "searches": [], "rows": None}
    near, far = make_product(id=7, name="QuietBook"), make_product(id=3, name="LoudBook")
    state["rows"] = [(near, 0.1234), (far, 0.6)]

    def fake_search(db, vector, tag, limit, filters=None):
        state["searches"].append({"vector": vector, "tag": tag, "limit": limit, "filters": filters})
        return state["rows"]

    monkeypatch.setattr(crud, "count_embedded", lambda db, tag: state["embedded"] if tag == TAG else 0)
    monkeypatch.setattr(crud, "semantic_search", fake_search)
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: 41)
    return state


def get(client, **params):
    return client.get("/products/semantic-search", params=params)


def test_ranked_results_with_similarity(client, titan, db_stub):
    res = get(client, q="  quiet   laptop for coding ", max_price=1200, min_ram_gb=16, limit=2)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["query"] == "quiet laptop for coding"
    assert [p["name"] for p in body["items"]] == ["QuietBook", "LoudBook"]
    assert body["items"][0]["similarity"] == pytest.approx(0.8766)
    assert body["items"][0]["is_mock"] is True and "price" in body["items"][0]
    assert body["embedding_model"] == TAG and body["embedded_products"] == 41 and body["catalog_products"] == 41
    assert body["message"] is None


def test_query_text_is_embedded_and_filters_reach_sql(client, titan, db_stub):
    get(client, q="travel laptop", min_price=500, max_price=1200, min_ram_gb=16, limit=3)
    assert titan.calls == [{"inputText": "travel laptop", "dimensions": settings.embedding_dim, "normalize": True}]
    search = db_stub["searches"][0]
    assert len(search["vector"]) == settings.embedding_dim and search["tag"] == TAG and search["limit"] == 3
    f = search["filters"]
    assert (f.min_price, f.max_price, f.min_ram_gb, f.q, f.cpu) == (500, 1200, 16, None, None)


@pytest.mark.parametrize(
    "params",
    [{}, {"q": ""}, {"q": "   "}, {"q": "x" * 201}, {"q": "a", "limit": 0}, {"q": "a", "limit": 21},
     {"q": "a", "min_price": 900, "max_price": 100}, {"q": "a", "min_ram_gb": 0}, {"q": "a", "max_price": -1},
     {"q": "a", "max_price": "abc"}, {"q": "a", "max_price": "nan"}, {"q": "a", "max_price": "inf"},
     {"q": "a", "min_ram_gb": "16.5"}, {"q": "a", "maxprice": 500}, {"q": "a", "cpu": "i7"},
     {"q": "a", "max_price": [500, 900]}, {"q": "laptop\x00for kids"}],
    ids=["missing", "empty", "blank", "too-long", "limit-0", "limit-21", "min>max", "ram-0", "negative-price",
         "price-text", "price-nan", "price-inf", "ram-fraction", "unknown-param-typo", "unsupported-param",
         "repeated-param", "control-char"],
)  # fmt: skip
def test_invalid_input_is_rejected_before_aws(client, titan, db_stub, params):
    assert get(client, **params).status_code == 422
    assert titan.calls == [] and db_stub["searches"] == []


def test_not_initialized_returns_503_without_calling_aws(client, titan, db_stub):
    db_stub["embedded"] = 0
    res = get(client, q="laptop")
    assert res.status_code == 503
    detail = res.json()["detail"]
    assert detail["code"] == "embeddings_not_initialized"
    assert "app.migrate_embedding_dim" in detail["message"] and "app.embed" in detail["message"]
    assert titan.calls == [] and db_stub["searches"] == []


def test_bedrock_auth_error_is_mapped(client, titan, db_stub):
    titan.error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "arn:aws:iam::123:user/x"}}, "InvokeModel")
    res = get(client, q="laptop")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "bedrock_access_denied"
    assert "arn:" not in res.text


def test_dimension_mismatch_is_a_controlled_error(client, titan, db_stub, monkeypatch):
    def boom(*args, **kwargs):
        raise DataError("SELECT", {}, Exception("different vector dimensions 1536 and 1024"))

    monkeypatch.setattr(crud, "semantic_search", boom)
    res = get(client, q="laptop")
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "embedding_dimension_mismatch"
    assert "1536" not in res.text


def test_no_results_is_200_and_distinct_from_not_initialized(client, titan, db_stub):
    db_stub["rows"] = []
    res = get(client, q="laptop", max_price=1)
    assert res.status_code == 200
    body = res.json()
    assert body["items"] == [] and body["embedded_products"] == 41
    assert "Relax a filter" in body["message"]


def test_partial_embedding_coverage_is_reported(client, titan, db_stub, monkeypatch):
    db_stub["embedded"] = 30
    body = get(client, q="laptop").json()
    assert (body["embedded_products"], body["catalog_products"]) == (30, 41)


def test_keyword_search_route_is_unchanged(client, monkeypatch, make_product):
    monkeypatch.setattr(crud, "list_products", lambda db, limit, offset, filters=None: [make_product()])
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: 1)
    body = client.get("/products", params={"q": "lenovo"}).json()
    assert body["total"] == 1 and "similarity" not in body["items"][0]
