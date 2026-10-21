
"""Bedrock tool use tests: no AWS calls and no PostgreSQL needed."""

from copy import deepcopy

import pytest

from app.ai.agent import ShoppingAgent
from app.ai.tools import parse_search_input, ToolArgumentError


class FakeBedrock:
    def __init__(self):
        self.calls = []

    def converse(self, **kwargs):
        # Preserve a snapshot of each request before the agent
        # modifies its conversation history.
        self.calls.append(deepcopy(kwargs))

        if len(self.calls) == 1:
            return {
                "stopReason": "tool_use",
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "call-1",
                                    "name": "search_products",
                                    "input": {
                                        "query": "lenovo",
                                        "max_price": 1000,
                                        "min_ram_gb": 16,
                                    },
                                }
                            }
                        ],
                    }
                },
            }

        return {
            "stopReason": "end_turn",
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "text": "Found a laptop in the synthetic demo catalog."
                        }
                    ],
                }
            },
        }


def test_tool_roundtrip(make_product):
    fake = FakeBedrock()
    product = make_product()

    def search(args):
        assert args.query == "lenovo"
        assert args.max_price == 1000
        assert args.min_ram_gb == 16
        return [product], 1

    agent = ShoppingAgent(
        client=fake,
        model_id="amazon.nova-lite-v1:0",
        search_fn=search,
    )

    result = agent.run("Find Lenovo under 1000 with 16GB")

    assert result.tools_used == ["search_products"]
    assert result.products[0]["name"] == product.name
    assert len(fake.calls) == 2

    # First request contains the user question.
    first_messages = fake.calls[0]["messages"]
    assert first_messages[0]["role"] == "user"

    # Second request contains the actual tool result.
    second_messages = fake.calls[1]["messages"]
    block = second_messages[-1]["content"][0]["toolResult"]

    assert block["toolUseId"] == "call-1"
    assert "TestBook" in block["content"][0]["text"]


def test_invalid_args():
    with pytest.raises(ToolArgumentError):
        parse_search_input({"max_price": -5})


def test_blank_message(client):
    result = client.post("/chat", json={"message": "   "})
    assert result.status_code == 422
