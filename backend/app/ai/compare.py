"""AI comparison of 2-3 catalog laptops (Module 2C-2): one Bedrock Converse call, structured output.

The backend already holds the selected database rows, so there is no search tool here. Instead the
model is forced (`toolChoice`) to answer through a single `submit_comparison` tool whose input schema
is the response shape: Converse's supported way to get JSON back from Nova. Converse does not
enforce schemas, so `parse_analysis()` validates everything again; recommended IDs that are not
among the selected products are discarded, never replaced with a guess.

Standard library plus a duck-typed `client` (anything with `client.converse(**kwargs)`), so the
whole flow is unit-testable with a scripted fake and no AWS access.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.errors import ChatError, map_provider_error
from app.ai.prompts import COMPARE_INSTRUCTIONS
from app.ai.tools import DATA_NOTICE

logger = logging.getLogger(__name__)

TOOL_NAME = "submit_comparison"
USE_CASES = ("general", "programming", "student", "gaming", "travel")

MAX_SUMMARY_CHARS = 800
MAX_REASON_CHARS = 600
MAX_ITEM_CHARS = 300
MAX_LIST_ITEMS = 6

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-4 sentences comparing the laptops overall."},
        "best_for_budget": {
            "type": "integer",
            "description": "id of the laptop that gives the most for the money. Omit if no clear choice.",
        },
        "best_for_performance": {
            "type": "integer",
            "description": "id of the laptop with the strongest listed hardware. Omit if the data cannot tell.",
        },
        "recommended_product_id": {
            "type": "integer",
            "description": "id of the overall pick for the stated use case. Omit if no clear choice.",
        },
        "recommendation_reason": {"type": "string", "description": "1-3 sentences tied to the listed specs."},
        "tradeoffs": {
            "type": "array", "items": {"type": "string"},
            "description": "2-5 short key differences (price, CPU, GPU, RAM, storage, weight, OS).",
        },
        "assumptions": {
            "type": "array", "items": {"type": "string"},
            "description": "General knowledge you relied on that is NOT in the data. Empty if none.",
        },
        "missing_data": {
            "type": "array", "items": {"type": "string"},
            "description": "Information that would change the answer but is not in the data (e.g. benchmarks).",
        },
    },
    "required": ["summary", "recommendation_reason", "tradeoffs"],
}  # fmt: skip

TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": TOOL_NAME,
                "description": "Submit the structured comparison of the selected laptops.",
                "inputSchema": {"json": _SCHEMA},
            }
        }
    ],
    "toolChoice": {"tool": {"name": TOOL_NAME}},
}

_INVALID_OUTPUT = (502, "ai_invalid_output", "The AI returned its analysis in an unexpected format, so nothing was shown. Please try again.")


@dataclass
class ComparisonAnalysis:
    summary: str
    best_for_budget: int | None
    best_for_performance: int | None
    recommended_product_id: int | None
    recommendation_reason: str
    tradeoffs: list[str]
    assumptions: list[str] = field(default_factory=list)
    missing_data: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # server-side corrections, shown to the user


def build_user_message(products: list[dict[str, Any]], use_case: str) -> str:
    """Product data travels as JSON inside a clearly delimited block the prompt marks as untrusted."""
    data = json.dumps({"data_notice": DATA_NOTICE, "products": products}, separators=(",", ":"))
    return (
        f"Use case: {use_case}\n"
        f"Compare these {len(products)} laptops and call {TOOL_NAME}.\n"
        f"<catalog_data>\n{data}\n</catalog_data>"
    )


class ComparisonAnalyzer:
    def __init__(self, client: Any, model_id: str, *, max_tokens: int = 900, temperature: float = 0.2) -> None:
        self.client = client
        self.model_id = model_id
        self.max_tokens = max_tokens
        self.temperature = temperature

    def analyze(self, products: list[dict[str, Any]], use_case: str = "general") -> ComparisonAnalysis:
        try:
            response = self.client.converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": [{"text": build_user_message(products, use_case)}]}],
                system=[{"text": COMPARE_INSTRUCTIONS}],
                toolConfig=TOOL_CONFIG,
                inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
            )
        except ChatError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised to a safe ChatError
            raise map_provider_error(exc) from None  # `from None`: never chain provider details

        data = extract_payload(response)
        return parse_analysis(data, {int(p["id"]) for p in products})


def extract_payload(response: Any) -> dict[str, Any]:
    """The submit_comparison input, or (fallback) a JSON object the model wrote as plain text."""
    try:
        content = response["output"]["message"]["content"]
    except (KeyError, TypeError):
        raise ChatError(502, "ai_no_answer", "The AI service didn't produce an answer. Please try again.") from None
    if not isinstance(content, list):
        raise ChatError(*_INVALID_OUTPUT)

    for block in content:
        tool_use = block.get("toolUse") if isinstance(block, dict) else None
        if isinstance(tool_use, dict) and tool_use.get("name") == TOOL_NAME and isinstance(tool_use.get("input"), dict):
            return tool_use["input"]

    text = "\n".join(b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

    if response.get("stopReason") in ("content_filtered", "guardrail_intervened"):
        raise ChatError(502, "ai_blocked", "The AI service blocked this response. Please try again.")
    logger.warning("Comparison output unusable (stopReason=%s)", str(response.get("stopReason"))[:30])
    raise ChatError(*_INVALID_OUTPUT)


def _text(value: object, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items = [_text(v, MAX_ITEM_CHARS) for v in value]
    return [v for v in items if v][:MAX_LIST_ITEMS]


def _product_id(value: object, allowed: set[int]) -> tuple[int | None, bool]:
    """(id or None, was_invalid). Omitted/null is a legitimate 'no clear choice', not an error."""
    if value is None:
        return None, False
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value not in allowed:
        return None, True
    return value, False


def parse_analysis(data: dict[str, Any], allowed_ids: set[int]) -> ComparisonAnalysis:
    summary = _text(data.get("summary"), MAX_SUMMARY_CHARS)
    if not summary:
        raise ChatError(*_INVALID_OUTPUT)

    warnings: list[str] = []
    ids: dict[str, int | None] = {}
    for key, label in (
        ("best_for_budget", "budget pick"),
        ("best_for_performance", "performance pick"),
        ("recommended_product_id", "overall recommendation"),
    ):
        ids[key], invalid = _product_id(data.get(key), allowed_ids)
        if invalid:
            logger.warning("Comparison output referenced an unselected product for %s", key)
            warnings.append(f"The AI's {label} referred to a laptop that isn't in this comparison, so it was discarded.")

    reason = _text(data.get("recommendation_reason"), MAX_REASON_CHARS)
    if ids["recommended_product_id"] is None and data.get("recommended_product_id") is not None:
        reason = ""  # the reason explained a discarded pick; showing it would imply a recommendation

    return ComparisonAnalysis(
        summary=summary,
        best_for_budget=ids["best_for_budget"],
        best_for_performance=ids["best_for_performance"],
        recommended_product_id=ids["recommended_product_id"],
        recommendation_reason=reason,
        tradeoffs=_text_list(data.get("tradeoffs")),
        assumptions=_text_list(data.get("assumptions")),
        missing_data=_text_list(data.get("missing_data")),
        warnings=warnings,
    )
