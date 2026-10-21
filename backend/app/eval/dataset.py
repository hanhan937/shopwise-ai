"""Evaluation scenarios: loading, structural validation, and the constraint rules shared with the checks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")

CATEGORIES = frozenset({
    "exact_search", "semantic_search", "mixed_search", "no_match", "ambiguous",
    "unsupported_claims", "prompt_injection", "out_of_domain", "comparison",
})  # fmt: skip
TOOL_NAMES = frozenset({"search_products", "semantic_search_products"})
CONSTRAINT_KEYS = frozenset({"max_price", "min_price", "min_ram_gb", "brand", "os_contains", "gpu_contains"})
TOOL_KEYS = frozenset({"required_any", "preferred", "forbidden"})
EXPECT_KEYS = frozenset({
    "min_products", "max_products", "disclaimer", "disclaimer_if_products", "no_match", "acknowledge_missing",
    "no_prompt_leak", "forbidden_prices", "forbidden_terms", "decline", "http_status", "error_code",
    "mentions_missing_data",
})  # fmt: skip
ACKNOWLEDGE_TOPICS = frozenset({"benchmark", "stock", "live_price", "battery"})


class ScenarioError(ValueError):
    pass


def load_scenarios(path: Path = SCENARIOS_PATH) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    scenarios = data.get("scenarios") if isinstance(data, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        raise ScenarioError("scenarios.json must contain a non-empty 'scenarios' list")
    problems = [p for s in scenarios for p in validate_scenario(s)]
    ids = [s.get("id") for s in scenarios]
    problems += [f"duplicate id {i!r}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    if problems:
        raise ScenarioError("; ".join(problems))
    return scenarios


def validate_scenario(s: Any) -> list[str]:
    if not isinstance(s, dict) or not isinstance(s.get("id"), str) or not s["id"]:
        return [f"scenario without a valid id: {str(s)[:60]}"]
    sid, out = s["id"], []
    if s.get("category") not in CATEGORIES:
        out.append(f"{sid}: unknown category {s.get('category')!r}")
    endpoint = s.get("endpoint")
    if endpoint == "chat":
        if not isinstance((s.get("input") or {}).get("message"), str) or not s["input"]["message"].strip():
            out.append(f"{sid}: chat input needs a non-empty message")
    elif endpoint == "compare":
        skus = (s.get("input") or {}).get("skus")
        if not isinstance(skus, list) or not all(isinstance(x, str) for x in skus):
            out.append(f"{sid}: compare input needs a list of skus")
        if "http_status" not in (s.get("expect") or {}):
            out.append(f"{sid}: compare scenarios must state expect.http_status")
    else:
        out.append(f"{sid}: endpoint must be 'chat' or 'compare'")
    for key, allowed in (("constraints", CONSTRAINT_KEYS), ("tools", TOOL_KEYS), ("expect", EXPECT_KEYS)):
        unknown = set(s.get(key) or {}) - allowed
        if unknown:
            out.append(f"{sid}: unknown {key} keys {sorted(unknown)}")
    for key in TOOL_KEYS:
        bad = set((s.get("tools") or {}).get(key, [])) - TOOL_NAMES
        if bad:
            out.append(f"{sid}: unknown tool names {sorted(bad)}")
    bad_topics = set((s.get("expect") or {}).get("acknowledge_missing", [])) - ACKNOWLEDGE_TOPICS
    if bad_topics:
        out.append(f"{sid}: unknown acknowledge_missing topics {sorted(bad_topics)}")
    return out


def violations(product: dict[str, Any], constraints: dict[str, Any]) -> list[str]:
    """Which explicit constraints a catalog record breaks (empty list = satisfies all)."""
    out = []
    price, ram = float(product["price"]), int(product["ram_gb"])
    if "max_price" in constraints and price > constraints["max_price"]:
        out.append(f"price ${price:g} > max ${constraints['max_price']:g}")
    if "min_price" in constraints and price < constraints["min_price"]:
        out.append(f"price ${price:g} < min ${constraints['min_price']:g}")
    if "min_ram_gb" in constraints and ram < constraints["min_ram_gb"]:
        out.append(f"RAM {ram} GB < min {constraints['min_ram_gb']} GB")
    if "brand" in constraints and str(product["brand"]).lower() != constraints["brand"].lower():
        out.append(f"brand {product['brand']} != {constraints['brand']}")
    for key, field in (("os_contains", "os"), ("gpu_contains", "gpu")):
        if key in constraints and constraints[key].lower() not in str(product[field]).lower():
            out.append(f"{field} {product[field]!r} lacks {constraints[key]!r}")
    return out
