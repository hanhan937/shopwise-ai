"""Product/query embeddings with Amazon Titan Text Embeddings V2 (Module 3A).

Titan is called through the same `bedrock-runtime` client the chat agent uses (InvokeModel, not
Converse: embedding models have no Converse support). Request/response format for Titan V2:

    request  {"inputText": "...", "dimensions": 1024, "normalize": true}
    response {"embedding": [1024 floats], "inputTextTokenCount": 42}

`normalize: true` returns unit-length vectors, so cosine distance and inner product rank the same.
Standard library plus a duck-typed `client` (anything with `client.invoke_model(**kwargs)`), so
tests use a fake and never call AWS.
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.ai.errors import ChatError, map_provider_error

MAX_INPUT_CHARS = 8_000  # Titan V2 accepts far more; product texts are ~400 characters
SUPPORTED_DIMENSIONS = (256, 512, 1024)


def build_embedding_text(p: Any) -> str:
    """What a product "means", as one paragraph.

    Price is left out on purpose: embeddings are poor at numbers ($849 and $899 look alike), so
    budget and RAM stay exact SQL filters and the vector only ranks how well a product fits the need.
    """
    tags = ", ".join(t for t in str(p.best_for or "").split(";") if t)
    text = (
        f"{p.brand} {p.name}. "
        f"CPU: {p.cpu}. GPU: {p.gpu}. {p.ram_gb} GB RAM, {p.storage_gb} GB {p.storage_type}. "
        f'{p.display_size_in:g}" {p.display_resolution} display. Weight {p.weight_kg:g} kg. OS: {p.os}.'
    )
    if tags:
        text += f" Good for: {tags}."
    return f"{text} {p.description}".strip()


def model_tag(model_id: str, dimensions: int) -> str:
    """Stored in products.embedding_model; vectors from another model or size are not comparable."""
    return f"{model_id}:{dimensions}"


class TitanEmbedder:
    def __init__(self, client: Any, model_id: str, dimensions: int = 1024) -> None:
        if dimensions not in SUPPORTED_DIMENSIONS:
            raise ValueError(f"Titan V2 supports {SUPPORTED_DIMENSIONS} dimensions, not {dimensions}")
        self.client = client
        self.model_id = model_id
        self.dimensions = dimensions

    @property
    def tag(self) -> str:
        return model_tag(self.model_id, self.dimensions)

    def embed(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text[:MAX_INPUT_CHARS], "dimensions": self.dimensions, "normalize": True})
        try:
            response = self.client.invoke_model(
                modelId=self.model_id, body=body, contentType="application/json", accept="application/json"
            )
            data = json.loads(response["body"].read())
        except ChatError:
            raise
        except Exception as exc:  # noqa: BLE001 - normalised to a safe ChatError
            raise map_provider_error(exc) from None

        vector = data.get("embedding") if isinstance(data, dict) else None
        if (
            not isinstance(vector, list)
            or len(vector) != self.dimensions
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vector)
        ):
            raise ChatError(502, "embedding_invalid", "The embedding service returned an unexpected response.")
        return [float(v) for v in vector]
