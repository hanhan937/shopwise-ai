"""The shopping agent: an Amazon Bedrock Converse API tool-use loop.

Protocol (Converse API tool use):
  1. Send the user's message, the system prompt, and `toolConfig` (the search_products toolSpec).
  2. If the model wants a tool it answers with `stopReason == "tool_use"` and an assistant message
     whose content contains one or more `toolUse` blocks: {toolUseId, name, input}.
  3. The assistant message is appended to the conversation VERBATIM (this preserves any reasoning
     blocks the model needs to see again).
  4. Every toolUse is executed here, on the server, and ALL results are returned together in ONE
     user message as `toolResult` blocks that carry the matching `toolUseId`. Every toolUse gets a
     result, even rejected ones (Converse returns a ValidationException otherwise).
  5. Repeat until the model answers with text.

Converse has no "tool_choice: none", so the call limit works differently from other APIs: after
`max_tool_calls` executions, further toolUse requests are answered with an error result, each
tool result reports `calls_remaining`, and the loop is bounded to max_tool_calls + 2 requests.

Standard library plus a duck-typed `client` (anything with `client.converse(**kwargs)`) and
`search_fn`: the whole protocol is unit-testable with a scripted fake and no AWS access.

RAG (Module 3B): with a `semantic_fn` the model also gets `semantic_search_products` (Titan embeddings +
pgvector, price/RAM still exact SQL filters). Both tools return database rows only; `products` in the
result is built from those rows, de-duplicated by id, never from ids the model writes. A semantic search
that can't run (embeddings missing, Titan error) becomes an ERROR tool result telling the model to use
search_products instead, never an empty "no matches" result.
"""
from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ai.errors import ChatError, map_provider_error
from app.ai.prompts import SYSTEM_INSTRUCTIONS
from app.ai.tools import (
    RAG_TOOL_CONFIG,
    SEMANTIC_TOOL_NAME,
    TOOL_CONFIG,
    TOOL_NAME,
    SearchArgs,
    SemanticArgs,
    ToolArgumentError,
    build_semantic_output,
    build_tool_output,
    error_output,
    format_product,
    parse_search_input,
    parse_semantic_input,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS = 3
MAX_REPLY_CHARS = 4_000
MAX_RETURNED_PRODUCTS = 20

SearchFn = Callable[[SearchArgs], "tuple[Sequence[Any], int]"]
# Returns (product_row, cosine_distance) pairs, nearest first; raises ChatError when it can't run.
SemanticFn = Callable[[SemanticArgs], "Sequence[tuple[Any, float]]"]

# Nova models may wrap reasoning in <thinking> tags; it is never shown to users.
_THINKING = re.compile(r"<thinking>.*?(</thinking>|$)", re.DOTALL | re.IGNORECASE)
# Replies are plain text (the UI shows them verbatim), but models still emit **bold** / __bold__ now and then.
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)  # "### Options" -> "Options"
_EXTRA_BLANK_LINES = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)+")  # 3+ line breaks -> one blank line


def supports_tool_result_status(model_id: str) -> bool:
    """`toolResult.status` is documented for Anthropic Claude and Amazon Nova models only."""
    model = model_id.lower()
    return "anthropic." in model or "amazon.nova" in model or ".nova-" in model


@dataclass
class AgentResult:
    reply: str
    products: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)


class ShoppingAgent:
    def __init__(
        self,
        client: Any,
        model_id: str,
        search_fn: SearchFn,
        *,
        system_prompt: str = SYSTEM_INSTRUCTIONS,
        max_tool_calls: int = MAX_TOOL_CALLS,
        max_tokens: int = 1024,
        temperature: float = 0.2,
        deadline_s: float = 60.0,
        send_tool_status: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        semantic_fn: SemanticFn | None = None,
    ) -> None:
        self.client = client
        self.model_id = model_id
        self.search_fn = search_fn
        self.semantic_fn = semantic_fn
        self.tool_config = RAG_TOOL_CONFIG if semantic_fn is not None else TOOL_CONFIG
        self.tool_names = [t["toolSpec"]["name"] for t in self.tool_config["tools"]]
        self.system_prompt = system_prompt
        self.max_tool_calls = max_tool_calls
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.deadline_s = deadline_s
        self.send_tool_status = supports_tool_result_status(model_id) if send_tool_status is None else send_tool_status
        self.clock = clock

    # ------------------------------------------------------------------ public
    def run(self, message: str) -> AgentResult:
        started = self.clock()
        messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": message}]}]
        executed = 0  # tool calls handled so far (valid or not); capped at max_tool_calls
        tools_used: list[str] = []
        products: dict[int, dict[str, Any]] = {}  # de-duplicated by id, in first-seen order

        for _ in range(self.max_tool_calls + 2):
            if self.clock() - started > self.deadline_s:
                raise ChatError(504, "ai_timeout", "The AI service took too long to respond. Please try again.")

            response = self._converse(messages)
            assistant = self._assistant_message(response)
            messages.append(assistant)  # preserved verbatim, including any reasoning blocks

            tool_uses = [b["toolUse"] for b in assistant["content"] if isinstance(b, dict) and isinstance(b.get("toolUse"), dict)]
            if not tool_uses:
                return AgentResult(
                    reply=self._final_text(assistant, response.get("stopReason")),
                    products=list(products.values())[:MAX_RETURNED_PRODUCTS],
                    tools_used=tools_used,
                )

            results: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                if executed >= self.max_tool_calls:
                    results.append(self._result_block(tool_use, error_output(
                        "tool_call_limit_reached",
                        ["No more tool calls are allowed for this request. Answer with the results you already have."],
                    ), ok=False))
                else:
                    executed += 1
                    output, ok = self._execute(tool_use, products, tools_used, calls_remaining=self.max_tool_calls - executed)
                    results.append(self._result_block(tool_use, output, ok=ok))
            # ALL toolResult blocks for one assistant turn go into a single user message.
            messages.append({"role": "user", "content": results})

        raise ChatError(502, "ai_no_answer", "The AI service didn't produce an answer. Please try again.")

    # ----------------------------------------------------------------- internals
    def _converse(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            return self.client.converse(
                modelId=self.model_id,
                messages=messages,
                system=[{"text": self.system_prompt}],
                toolConfig=self.tool_config,
                inferenceConfig={"maxTokens": self.max_tokens, "temperature": self.temperature},
            )
        except ChatError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised to a safe ChatError
            raise map_provider_error(exc) from None  # `from None`: never chain provider details

    @staticmethod
    def _assistant_message(response: Any) -> dict[str, Any]:
        try:
            message = response["output"]["message"]
            content = message["content"]
        except (KeyError, TypeError):
            raise ChatError(502, "ai_no_answer", "The AI service didn't produce an answer. Please try again.") from None
        if not isinstance(content, list):
            raise ChatError(502, "ai_no_answer", "The AI service didn't produce an answer. Please try again.")
        return message

    def _result_block(self, tool_use: dict[str, Any], output: str, *, ok: bool) -> dict[str, Any]:
        # Text content (a JSON string) is accepted by every Converse model family; `json` blocks are not.
        block: dict[str, Any] = {"toolUseId": tool_use.get("toolUseId"), "content": [{"text": output}]}
        if self.send_tool_status:
            block["status"] = "success" if ok else "error"
        return {"toolResult": block}

    def _execute(
        self, tool_use: dict[str, Any], products: dict[int, dict[str, Any]], tools_used: list[str], *, calls_remaining: int
    ) -> tuple[str, bool]:
        """Run one toolUse. Returns (output_text, succeeded)."""
        name = tool_use.get("name")
        if name not in self.tool_names:
            logger.warning("Model requested unknown tool %r", str(name)[:40])
            return error_output("unknown_tool", [f"There is no tool with that name. Available tools: {', '.join(self.tool_names)}."]), False
        if name == SEMANTIC_TOOL_NAME:
            return self._execute_semantic(tool_use, products, tools_used, calls_remaining=calls_remaining)

        try:
            args = parse_search_input(tool_use.get("input"))
        except ToolArgumentError as exc:
            logger.info("search_products rejected arguments: %s", "; ".join(exc.problems))
            return error_output("invalid_arguments", exc.problems), False

        rows, total = self.search_fn(args)  # may raise ChatError (e.g. database unavailable)
        formatted = [format_product(r) for r in rows]
        output, included = build_tool_output(args, formatted, total, calls_remaining)
        tools_used.append(TOOL_NAME)
        for product in included:
            products.setdefault(product["id"], product)
        logger.info("search_products ran: total_matches=%d returned=%d", total, len(included))
        return output, True

    def _execute_semantic(
        self, tool_use: dict[str, Any], products: dict[int, dict[str, Any]], tools_used: list[str], *, calls_remaining: int
    ) -> tuple[str, bool]:
        try:
            args = parse_semantic_input(tool_use.get("input"))
        except ToolArgumentError as exc:
            logger.info("%s rejected arguments: %s", SEMANTIC_TOOL_NAME, "; ".join(exc.problems))
            return error_output("invalid_arguments", exc.problems), False

        try:
            rows = self.semantic_fn(args)  # type: ignore[misc] - only reachable when semantic_fn is set
        except ChatError as exc:  # embeddings missing, Titan error, ...: a failure, not "no matches"
            logger.warning("%s unavailable: %s", SEMANTIC_TOOL_NAME, exc.code)
            return error_output("semantic_search_unavailable", [
                f"Semantic search could not run ({exc.code}); this is NOT an empty result.",
                f"Use {TOOL_NAME} with keywords and the stated budget/RAM instead, or tell the user semantic search is unavailable.",
            ]), False  # fmt: skip

        formatted = [{**format_product(p), "similarity": round(1 - float(d), 4)} for p, d in rows]
        output, included = build_semantic_output(args, formatted, calls_remaining)
        tools_used.append(SEMANTIC_TOOL_NAME)
        for product in included:
            products.setdefault(product["id"], product)
        # Counts and filters only: the shopper's query text is not logged.
        logger.info("%s ran: returned=%d max_price=%s min_ram_gb=%s limit=%d query_chars=%d",
                    SEMANTIC_TOOL_NAME, len(included), args.max_price, args.min_ram_gb, args.limit, len(args.query))  # fmt: skip
        return output, True

    @staticmethod
    def _final_text(assistant: dict[str, Any], stop_reason: Any) -> str:
        pieces = [b["text"] for b in assistant["content"] if isinstance(b, dict) and isinstance(b.get("text"), str)]
        text = _THINKING.sub("", "\n".join(pieces))
        text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text).replace("**", "")
        text = _EXTRA_BLANK_LINES.sub("\n\n", _HEADING.sub("", text))
        text = "\n".join(line.rstrip() for line in text.splitlines()).strip()
        if not text:
            if stop_reason in ("content_filtered", "guardrail_intervened"):
                raise ChatError(502, "ai_blocked", "The AI service blocked this response. Try rephrasing your question.")
            if stop_reason == "max_tokens":
                raise ChatError(502, "ai_incomplete", "The AI response was cut off before it finished. Try a shorter question.")
            raise ChatError(502, "ai_no_answer", "The AI service didn't produce an answer. Please try again.")
        return text[:MAX_REPLY_CHARS]
