"""The evaluation dataset is valid and its catalog facts are TRUE for data/laptops.csv."""
import json

import pytest

from app.eval.dataset import CATEGORIES, ScenarioError, load_scenarios, validate_scenario, violations
from tests.eval_support import catalog_dict

SCENARIOS = load_scenarios()
CATALOG = catalog_dict()
SKUS = {p["sku"] for p in CATALOG.values()}


def test_dataset_size_and_category_coverage():
    assert 20 <= len(SCENARIOS) <= 30
    assert {s["category"] for s in SCENARIOS} == CATEGORIES
    assert len({s["id"] for s in SCENARIOS}) == len(SCENARIOS)


def test_catalog_basics_used_by_the_scenarios():
    prices = [p["price"] for p in CATALOG.values()]
    assert len(CATALOG) == 41 and min(prices) == 349 and max(prices) == 2999


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s.get("catalog_facts")], ids=lambda s: s["id"])
def test_catalog_facts_are_true(scenario):
    facts, constraints = scenario["catalog_facts"], scenario.get("constraints") or {}
    matching = sorted(p["sku"] for p in CATALOG.values() if not violations(p, constraints))
    if "matching_skus" in facts:
        assert matching == sorted(facts["matching_skus"])
    if "matching_count" in facts:
        assert len(matching) == facts["matching_count"]
    if "zero_with_tag" in facts:
        tag = facts["zero_with_tag"]
        assert matching, "the scenario needs products under the limit that do NOT have the tag"
        assert not [s for s in matching if tag in next(p for p in CATALOG.values() if p["sku"] == s)["best_for"]]


@pytest.mark.parametrize("scenario", [s for s in SCENARIOS if s["endpoint"] == "compare"], ids=lambda s: s["id"])
def test_compare_scenarios_reference_real_skus(scenario):
    assert set(scenario["input"]["skus"]) <= SKUS
    assert all(i not in CATALOG for i in scenario["input"].get("raw_ids", []))  # raw ids are meant to be missing


def test_product_names_in_prompts_exist():
    devbook = [p for p in CATALOG.values() if p["name"] == "DevBook 14 Pro"]
    assert devbook and devbook[0]["price"] == 849  # injection-02 relies on the real price
    assert [p for p in CATALOG.values() if p["name"] == "IdeaSlim 14 OLED"]
    assert not [p for p in CATALOG.values() if "UltraBook Z9" in p["name"]]  # injection-04 product must be invented


@pytest.mark.parametrize(
    "bad, problem",
    [
        ({"id": "x", "category": "nope", "endpoint": "chat", "input": {"message": "hi"}}, "unknown category"),
        ({"id": "x", "category": "exact_search", "endpoint": "chat", "input": {"message": " "}}, "non-empty message"),
        ({"id": "x", "category": "comparison", "endpoint": "compare", "input": {"skus": ["A"]}}, "http_status"),
        ({"id": "x", "category": "exact_search", "endpoint": "chat", "input": {"message": "hi"}, "tools": {"required_any": ["delete_all"]}}, "unknown tool"),
        ({"id": "x", "category": "exact_search", "endpoint": "chat", "input": {"message": "hi"}, "constraints": {"max_ram": 8}}, "unknown constraints"),
    ],
)
def test_invalid_scenarios_are_rejected(bad, problem):
    assert any(problem in p for p in validate_scenario(bad))


def test_duplicate_ids_are_rejected(tmp_path):
    s = {"id": "a", "category": "exact_search", "endpoint": "chat", "input": {"message": "hi"}}
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"scenarios": [s, s]}))
    with pytest.raises(ScenarioError, match="duplicate"):
        load_scenarios(path)
