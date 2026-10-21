"""POST /compare/analyze tests (Module 2C-2): Bedrock is always a scripted fake, no AWS calls."""
import json
from copy import deepcopy

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from app import crud
from app.ai.compare import TOOL_NAME, parse_analysis
from app.routers import chat as chat_router
from app.routers import compare as compare_router


def tool_response(payload: dict) -> dict:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "t-1", "name": TOOL_NAME, "input": payload}},
        ]}},
    }  # fmt: skip


def text_response(text: str) -> dict:
    return {"stopReason": "end_turn", "output": {"message": {"role": "assistant", "content": [{"text": text}]}}}


class FakeBedrock:
    def __init__(self, response=None, error: Exception | None = None):
        self.response, self.error, self.calls = response, error, []

    def converse(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if self.error:
            raise self.error
        return self.response


def good_output(**overrides) -> dict:
    data = {
        "summary": "Both are synthetic demo laptops with different trade-offs.",
        "best_for_budget": 1,
        "best_for_performance": 2,
        "recommended_product_id": 2,
        "recommendation_reason": "More RAM for programming workloads.",
        "tradeoffs": ["Laptop 1 is cheaper.", "Laptop 2 has 32 GB RAM."],
        "assumptions": ["General knowledge: more RAM helps with many open tools."],
        "missing_data": ["No CPU benchmarks are available."],
    }
    data.update(overrides)
    return data


@pytest.fixture
def catalog(monkeypatch, make_product):
    products = {
        1: make_product(id=1, name="ValueBook", price=649, ram_gb=16, gpu="Integrated Iris Xe", os="Windows 11"),
        2: make_product(id=2, name="DevBook Pro", price=1349, ram_gb=32, cpu="Intel Core i7-13700H", os="Ubuntu 22.04"),
        3: make_product(id=3, name="AirLite", price=999, weight_kg=0.99, gpu="NVIDIA RTX 4050"),
    }
    seen: list[list[int]] = []

    def fake_lookup(db, ids):
        seen.append(list(ids))
        return [products[i] for i in ids if i in products]

    monkeypatch.setattr(crud, "get_products_by_ids", fake_lookup)
    return seen


@pytest.fixture
def bedrock(monkeypatch):
    fake = FakeBedrock(tool_response(good_output()))
    monkeypatch.setattr(compare_router, "create_bedrock_client", lambda: fake)
    return fake


def post(client, body):
    return client.post("/compare/analyze", json=body)


# ------------------------------------------------------------------ accepted requests
def test_two_products_accepted(client, catalog, bedrock):
    res = post(client, {"product_ids": [1, 2], "use_case": "programming"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["product_ids"] == [1, 2]
    assert body["use_case"] == "programming"
    assert body["recommended_product_id"] == 2
    assert body["best_for_budget"] == 1
    assert body["tradeoffs"] == ["Laptop 1 is cheaper.", "Laptop 2 has 32 GB RAM."]
    assert body["warnings"] == []
    assert "Synthetic" in body["data_notice"]
    assert len(bedrock.calls) == 1


def test_three_products_accepted_and_use_case_optional(client, catalog, bedrock):
    res = post(client, {"product_ids": [3, 1, 2]})
    assert res.status_code == 200, res.text
    assert res.json()["use_case"] == "general"
    assert catalog == [[3, 1, 2]]


# ------------------------------------------------------------------ rejected requests
@pytest.mark.parametrize(
    "body",
    [
        {"product_ids": [1, 1]},  # duplicates
        {"product_ids": [1]},  # fewer than 2
        {"product_ids": []},
        {"product_ids": [1, 2, 3, 4]},  # more than 3
        {"product_ids": [0, 1]},  # invalid ids
        {"product_ids": [-1, 2]},
        {"product_ids": ["1", "2"]},
        {"product_ids": [True, 2]},
        {"product_ids": [1, 2], "use_case": "mining"},
        {},
    ],
    ids=["duplicates", "one", "empty", "four", "zero", "negative", "strings", "bool", "bad-use-case", "missing"],
)
def test_invalid_requests_rejected_without_calling_bedrock(client, catalog, bedrock, body):
    res = post(client, body)
    assert res.status_code == 422
    assert bedrock.calls == []
    assert catalog == []


def test_client_supplied_specs_are_rejected(client, catalog, bedrock):
    res = post(client, {"product_ids": [1, 2], "products": [{"id": 1, "price": 1}]})
    assert res.status_code == 422
    assert bedrock.calls == []


def test_missing_product_returns_404(client, catalog, bedrock):
    res = post(client, {"product_ids": [1, 99]})
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert detail["code"] == "products_not_found"
    assert detail["missing_ids"] == [99]
    assert bedrock.calls == []


# ------------------------------------------------------------------ model input
def test_database_values_are_passed_to_model(client, catalog, bedrock):
    post(client, {"product_ids": [1, 2], "use_case": "travel"})
    call = bedrock.calls[0]
    text = call["messages"][0]["content"][0]["text"]
    assert "Use case: travel" in text
    data = json.loads(text.split("<catalog_data>\n", 1)[1].split("\n</catalog_data>", 1)[0])
    by_id = {p["id"]: p for p in data["products"]}
    assert by_id[1]["price"] == 649 and by_id[1]["gpu"] == "Integrated Iris Xe"
    assert by_id[2]["ram_gb"] == 32 and by_id[2]["cpu"] == "Intel Core i7-13700H" and by_id[2]["os"] == "Ubuntu 22.04"
    assert all(p["is_mock"] for p in data["products"])
    assert "description" not in by_id[1]  # free text is not sent to the model
    assert call["toolConfig"]["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert call["inferenceConfig"]["maxTokens"] <= 1024
    assert "untrusted data" in call["system"][0]["text"]


# ------------------------------------------------------------------ model output
def test_invalid_model_output_returns_safe_error(client, catalog, bedrock):
    bedrock.response = text_response("Sorry, I can't help with that {not json")
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "ai_invalid_output"


def test_output_without_summary_rejected(client, catalog, bedrock):
    bedrock.response = tool_response(good_output(summary="  "))
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "ai_invalid_output"


def test_json_text_fallback_is_validated(client, catalog, bedrock):
    bedrock.response = text_response("Here you go: " + json.dumps(good_output(recommended_product_id=1)))
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 200
    assert res.json()["recommended_product_id"] == 1


def test_invalid_recommended_product_id_is_discarded(client, catalog, bedrock):
    bedrock.response = tool_response(good_output(recommended_product_id=3, best_for_performance=42, best_for_budget="1"))
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 200
    body = res.json()
    assert body["recommended_product_id"] is None  # 3 exists in the DB but was not selected
    assert body["recommendation_reason"] == ""  # the reason belonged to the discarded pick
    assert body["best_for_performance"] is None
    assert body["best_for_budget"] == 1  # numeric string for a selected id is accepted
    assert len(body["warnings"]) == 2


def test_parse_analysis_bounds_and_types():
    result = parse_analysis(
        {"summary": "x" * 5000, "recommended_product_id": True, "tradeoffs": ["a", 5, "", "b"] + ["c"] * 10, "assumptions": "nope"},
        {1, 2},
    )
    assert len(result.summary) == 800
    assert result.recommended_product_id is None and result.warnings
    assert result.tradeoffs[:2] == ["a", "b"] and len(result.tradeoffs) == 6
    assert result.assumptions == []


def test_no_clear_winner_is_allowed(client, catalog, bedrock):
    out = good_output(recommendation_reason="Too close to call with the listed specs.")
    for key in ("best_for_budget", "best_for_performance", "recommended_product_id"):
        out.pop(key)
    bedrock.response = tool_response(out)
    body = post(client, {"product_ids": [1, 2]}).json()
    assert body["recommended_product_id"] is None
    assert body["recommendation_reason"] == "Too close to call with the listed specs."
    assert body["warnings"] == []


# ------------------------------------------------------------------ provider errors
def test_bedrock_authentication_error(client, catalog, bedrock):
    bedrock.error = ClientError(
        {"Error": {"Code": "UnrecognizedClientException", "Message": "secret-ish details arn:aws:iam::123"},
         "ResponseMetadata": {"HTTPStatusCode": 403}},
        "Converse",
    )  # fmt: skip
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 503
    assert res.json()["detail"]["code"] == "aws_credentials_invalid"
    assert "arn:" not in res.text


def test_bedrock_timeout(client, catalog, bedrock):
    bedrock.error = ReadTimeoutError(endpoint_url="https://bedrock-runtime.example")
    res = post(client, {"product_ids": [1, 2]})
    assert res.status_code == 504
    assert res.json()["detail"]["code"] == "ai_timeout"


# ------------------------------------------------------------------ Module 2B unchanged
def test_chat_endpoint_still_uses_search_tool(client, monkeypatch, make_product):
    calls = []

    class ChatFake:
        def converse(self, **kwargs):
            calls.append(deepcopy(kwargs))
            if len(calls) == 1:
                return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": [
                    {"toolUse": {"toolUseId": "c1", "name": "search_products", "input": {"query": "lenovo"}}}]}}}  # fmt: skip
            return text_response("Found one synthetic demo laptop.")

    monkeypatch.setattr(chat_router, "create_bedrock_client", lambda: ChatFake())
    monkeypatch.setattr(crud, "list_products", lambda db, limit, offset, filters=None: [make_product()])
    monkeypatch.setattr(crud, "count_products", lambda db, filters=None: 1)

    res = client.post("/chat", json={"message": "lenovo laptop"})
    assert res.status_code == 200, res.text
    assert res.json()["tools_used"] == ["search_products"]
    assert calls[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "search_products"
    assert "toolChoice" not in calls[0]["toolConfig"]
