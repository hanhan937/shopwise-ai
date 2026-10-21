"""The `search_products` tool: Bedrock tool definition, argument validation, and result formatting.

Standard library only. Arguments produced by the model are NEVER trusted: they are validated
here no matter what the JSON schema sent to Bedrock says (Converse does not enforce schemas).
The model cannot supply SQL, column names, or code; it can only fill five typed fields.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

TOOL_NAME = "search_products"

MAX_LIMIT = 10
DEFAULT_LIMIT = 5
MAX_QUERY_CHARS = 100
MAX_QUERY_WORDS = 8
MAX_PRICE = 1_000_000
MAX_RAM_GB = 1024
MAX_ARGUMENT_CHARS = 2_000  # raw JSON string from the model
MAX_TOOL_OUTPUT_CHARS = 12_000  # JSON string handed back to the model

DATA_NOTICE = (
    "Synthetic demonstration data: names, specifications and prices are invented, "
    "are not real-time, and carry no stock or benchmark information."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "A few distinctive keywords, e.g. a brand ('lenovo'), CPU family ('ryzen', 'i7'), GPU "
                "('rtx'), OS, or use-case tag ('programming', 'gaming', 'travel'). Every word must appear "
                "in the product's brand, model, CPU, GPU, OS, display, or tags. Do NOT include filler "
                "words such as 'laptop' or 'for', and do NOT put prices or RAM sizes here. Omit if no keyword."
            ),
        },
        "min_price": {"type": "number", "description": "Minimum price in USD, inclusive. Omit if not stated."},
        "max_price": {"type": "number", "description": "Maximum price in USD, inclusive (the budget). Omit if not stated."},
        "min_ram_gb": {"type": "integer", "description": "Minimum RAM in GB. Omit if not stated."},
        "limit": {
            "type": "integer",
            "description": f"Number of products to return, 1 to {MAX_LIMIT}. Omit for the default ({DEFAULT_LIMIT}).",
        },
    },
    "additionalProperties": False,
}

# Converse `toolConfig`. Every parameter is optional (omit what the user did not state). Models may still
# send null or odd values, so parse_search_input() validates everything again on the server.
TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": TOOL_NAME,
                "description": (
                    "Search the laptop catalog (a PostgreSQL table of SYNTHETIC demo products). Returns up to "
                    "`limit` matching products plus `total_matches`. Call this for any question about which "
                    "laptops exist or about their specs or prices. All filters are combined with AND."
                ),
                "inputSchema": {"json": _SCHEMA},
            }
        }
    ]
}

# Words that never help a catalog search (every query word must match, so filler would cause misses).
_FILLER = frozenset(
    "a an the and or for with in on of to me my i need want find show get give looking good best cheap "
    "laptop laptops notebook notebooks computer computers pc under over below above than at least most "
    "less more around about some any please ram memory".split()
)
_MONEY_OR_MEMORY = re.compile(r"^(\$[\d,.]+k?|\d+(\.\d+)?(gb|tb|g|t|k))$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ALLOWED_ARGS = frozenset({"query", "min_price", "max_price", "min_ram_gb", "limit"})


class ToolArgumentError(ValueError):
    """The model's arguments failed validation. `problems` is safe to show back to the model."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class SearchArgs:
    query: str | None
    min_price: float | None
    max_price: float | None
    min_ram_gb: int | None
    limit: int


# ----------------------------------------------------------------------------- validation
def parse_search_input(data: object) -> SearchArgs:
    """Validate the `input` object of a toolUse block (Bedrock delivers it already JSON-decoded)."""
    if not isinstance(data, dict):
        raise ToolArgumentError(["arguments must be a JSON object"])
    try:
        size = len(json.dumps(data))
    except (TypeError, ValueError):
        raise ToolArgumentError(["arguments must be plain JSON values"]) from None
    if size > MAX_ARGUMENT_CHARS:
        raise ToolArgumentError([f"arguments are too long (max {MAX_ARGUMENT_CHARS} characters)"])

    problems: list[str] = []
    unknown = sorted(str(k)[:30] for k in data if k not in _ALLOWED_ARGS)
    if unknown:
        problems.append(f"unknown argument(s): {', '.join(unknown[:5])}")

    query = _clean_query(data.get("query"), problems)
    min_price = _number(data.get("min_price"), "min_price", 0, MAX_PRICE, problems)
    max_price = _number(data.get("max_price"), "max_price", 0, MAX_PRICE, problems)
    min_ram = _integer(data.get("min_ram_gb"), "min_ram_gb", 1, MAX_RAM_GB, problems)
    limit = _integer(data.get("limit"), "limit", 1, MAX_LIMIT, problems)

    if min_price is not None and max_price is not None and min_price > max_price:
        problems.append("min_price must not be greater than max_price")
    if problems:
        raise ToolArgumentError(problems)
    return SearchArgs(query, min_price, max_price, min_ram, limit if limit is not None else DEFAULT_LIMIT)


def _number(value: object, name: str, lo: float, hi: float, problems: list[str]) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{name} must be a number")
        return None
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number) or not lo <= number <= hi:
        problems.append(f"{name} must be between {lo:g} and {hi:g}")
        return None
    return number


def _integer(value: object, name: str, lo: int, hi: int, problems: list[str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        problems.append(f"{name} must be a whole number")
        return None
    if isinstance(value, float) and (not math.isfinite(value) or not value.is_integer()):
        problems.append(f"{name} must be a whole number")
        return None
    number = int(value)
    if not lo <= number <= hi:
        problems.append(f"{name} must be between {lo} and {hi}")
        return None
    return number


def _clean_query(value: object, problems: list[str]) -> str | None:
    """Normalise free text: drop filler and price/RAM tokens, cap length and word count."""
    if value is None:
        return None
    if not isinstance(value, str):
        problems.append("query must be text")
        return None
    if len(value) > MAX_QUERY_CHARS:
        problems.append(f"query must be at most {MAX_QUERY_CHARS} characters")
        return None
    if _CONTROL_CHARS.search(value):
        problems.append("query contains unsupported control characters")
        return None
    words = [w for w in value.lower().split() if w not in _FILLER and not _MONEY_OR_MEMORY.match(w)]
    if len(words) > MAX_QUERY_WORDS:
        problems.append(f"query must have at most {MAX_QUERY_WORDS} keywords")
        return None
    return " ".join(words) or None


# ----------------------------------------------------------------------------- results
def format_product(p: Any) -> dict[str, Any]:
    """JSON-safe product record. Field names and types mirror the `products` table / ProductOut."""
    return {
        "id": int(p.id),
        "sku": str(p.sku),
        "brand": str(p.brand),
        "name": str(p.name),
        "price": float(p.price),
        "cpu": str(p.cpu),
        "gpu": str(p.gpu),
        "ram_gb": int(p.ram_gb),
        "storage_gb": int(p.storage_gb),
        "storage_type": str(p.storage_type),
        "weight_kg": float(p.weight_kg),
        "os": str(p.os),
        "best_for": [t for t in str(p.best_for or "").split(";") if t],
        "source_name": str(p.source_name),
        "is_mock": bool(p.is_mock),
    }


def build_tool_output(
    args: SearchArgs, products: list[dict[str, Any]], total: int, calls_remaining: int | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """Serialise a search result for the model. Returns (json_string, products_actually_included).

    The output is bounded: products are dropped from the end until it fits MAX_TOOL_OUTPUT_CHARS.
    """
    included = list(products)
    payload: dict[str, Any] = {
        "total_matches": total,
        "returned": len(included),
        "applied_filters": {
            "query": args.query,
            "min_price": args.min_price,
            "max_price": args.max_price,
            "min_ram_gb": args.min_ram_gb,
            "limit": args.limit,
        },
        "data_notice": DATA_NOTICE,
        "products": included,
    }
    if calls_remaining is not None:
        payload["calls_remaining"] = calls_remaining
        if calls_remaining <= 0:
            payload["instruction"] = "No more searches are allowed for this question. Answer now using the data above."
    if not included:
        payload["note"] = (
            "No products in the catalog matched these filters. Do not invent alternatives: tell the user "
            "nothing matched and suggest relaxing one constraint."
        )

    def dump() -> str:
        return json.dumps(payload, separators=(",", ":"))

    text = dump()
    while len(text) > MAX_TOOL_OUTPUT_CHARS and included:
        included.pop()
        payload["returned"] = len(included)
        payload["truncated"] = True
        text = dump()
    return text, included


def error_output(code: str, problems: list[str]) -> str:
    """Tool error handed back to the model so it can correct itself or explain."""
    return json.dumps({"error": code, "problems": problems[:6]}, separators=(",", ":"))


# ============================================================================ semantic_search_products (Module 3B)
# Retrieval by meaning (Titan V2 embeddings + pgvector) for fuzzy needs. Price and RAM remain exact SQL
# filters inside the same query, so a vector match can never break a stated budget or RAM minimum.
SEMANTIC_TOOL_NAME = "semantic_search_products"
SEMANTIC_MAX_LIMIT = 5
SEMANTIC_MAX_QUERY_CHARS = 200
_SEMANTIC_ALLOWED_ARGS = frozenset({"query", "max_price", "min_ram_gb", "limit"})

_SEMANTIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": (
                "The shopper's needs in plain words, e.g. 'light quiet laptop for coding on trains' or "
                "'good for a student who edits video'. Describe use cases and preferences; do NOT put the "
                "budget or RAM size here (use max_price and min_ram_gb)."
            ),
        },
        "max_price": {"type": "number", "description": "Maximum price in USD, inclusive (exact filter). Omit if not stated."},
        "min_ram_gb": {"type": "integer", "description": "Minimum RAM in GB (exact filter). Omit if not stated."},
        "limit": {"type": "integer", "description": f"Number of products, 1 to {SEMANTIC_MAX_LIMIT}. Omit for {SEMANTIC_MAX_LIMIT}."},
    },
    "required": ["query"],
    "additionalProperties": False,
}

SEMANTIC_TOOL_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": SEMANTIC_TOOL_NAME,
        "description": (
            "Find laptops in the SYNTHETIC demo catalog whose specs, use-case tags and descriptions best match "
            "a natural-language need (portability, quietness, 'good for students', etc.), ranked by similarity. "
            "Budget and RAM are applied as exact filters. Use search_products instead for exact brands, model "
            "names or purely numeric requirements."
        ),
        "inputSchema": {"json": _SEMANTIC_SCHEMA},
    }
}

# Both tools; the search_products definition is the same object as in TOOL_CONFIG.
RAG_TOOL_CONFIG: dict[str, Any] = {"tools": [*TOOL_CONFIG["tools"], SEMANTIC_TOOL_SPEC]}


@dataclass(frozen=True)
class SemanticArgs:
    query: str
    max_price: float | None
    min_ram_gb: int | None
    limit: int


def parse_semantic_input(data: object) -> SemanticArgs:
    """Validate a semantic_search_products toolUse `input`. Raises ToolArgumentError (safe to show the model)."""
    if not isinstance(data, dict):
        raise ToolArgumentError(["arguments must be a JSON object"])
    try:
        size = len(json.dumps(data))
    except (TypeError, ValueError):
        raise ToolArgumentError(["arguments must be plain JSON values"]) from None
    if size > MAX_ARGUMENT_CHARS:
        raise ToolArgumentError([f"arguments are too long (max {MAX_ARGUMENT_CHARS} characters)"])

    problems: list[str] = []
    unknown = sorted(str(k)[:30] for k in data if k not in _SEMANTIC_ALLOWED_ARGS)
    if unknown:
        problems.append(f"unknown argument(s): {', '.join(unknown[:5])}")

    raw = data.get("query")
    query = " ".join(raw.split()) if isinstance(raw, str) else ""
    if not isinstance(raw, str):
        problems.append("query is required and must be text")
    elif not query:
        problems.append("query must not be blank")
    elif len(query) > SEMANTIC_MAX_QUERY_CHARS:
        problems.append(f"query must be at most {SEMANTIC_MAX_QUERY_CHARS} characters")
    elif _CONTROL_CHARS.search(raw):
        problems.append("query contains unsupported control characters")

    max_price = _number(data.get("max_price"), "max_price", 0, MAX_PRICE, problems)
    min_ram = _integer(data.get("min_ram_gb"), "min_ram_gb", 1, MAX_RAM_GB, problems)
    limit = _integer(data.get("limit"), "limit", 1, SEMANTIC_MAX_LIMIT, problems)
    if problems:
        raise ToolArgumentError(problems)
    return SemanticArgs(query, max_price, min_ram, limit if limit is not None else SEMANTIC_MAX_LIMIT)


def build_semantic_output(
    args: SemanticArgs, products: list[dict[str, Any]], calls_remaining: int | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """Serialise semantic results for the model (same bounds as build_tool_output).

    The query text is deliberately not echoed back; products carry `similarity` (1 = same meaning).
    """
    included = list(products)
    payload: dict[str, Any] = {
        "returned": len(included),
        "applied_filters": {"max_price": args.max_price, "min_ram_gb": args.min_ram_gb, "limit": args.limit},
        "ranking": "by similarity to the shopper's need; similarity is relative within this result only",
        "data_notice": DATA_NOTICE,
        "products": included,
    }
    if calls_remaining is not None:
        payload["calls_remaining"] = calls_remaining
        if calls_remaining <= 0:
            payload["instruction"] = "No more searches are allowed for this question. Answer now using the data above."
    if not included:
        payload["note"] = (
            "No products in the catalog passed the price/RAM filters. Do not invent alternatives: tell the user "
            "nothing matched and suggest relaxing one constraint."
        )

    def dump() -> str:
        return json.dumps(payload, separators=(",", ":"))

    text = dump()
    while len(text) > MAX_TOOL_OUTPUT_CHARS and included:
        included.pop()
        payload["returned"] = len(included)
        payload["truncated"] = True
        text = dump()
    return text, included
