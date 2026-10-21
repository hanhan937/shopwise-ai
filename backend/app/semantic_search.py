"""Semantic retrieval shared by GET /products/semantic-search and the agent's semantic_search_products tool.

One implementation of: "are embeddings ready?" -> Titan query embedding -> pgvector ranking with exact
SQL price/RAM filters (crud.semantic_search). Failures raise ChatError with a safe message; callers
decide how to surface them (HTTP error for the route, tool error result for the agent). A failure is
never turned into an empty result.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app import crud
from app.ai.embeddings import TitanEmbedder, model_tag
from app.ai.errors import ChatError
from app.config import settings
from app.models import Product
from app.product_filters import ProductFilters

logger = logging.getLogger(__name__)

NOT_INITIALIZED_MESSAGE = (
    "Semantic search isn't initialized yet: no product embeddings exist for the configured model. "
    "Run `python -m app.migrate_embedding_dim` (once), then `python -m app.embed` "
    "(in Docker: docker compose exec backend ...). Keyword search at /products still works."
)


@dataclass
class SemanticHits:
    rows: list[tuple[Product, float]]  # (product, cosine distance), nearest first
    embedded_products: int
    model_tag: str


def current_model_tag() -> str:
    return model_tag(settings.embedding_model_id, settings.embedding_dim)


def search(db: Session, client: Any, query: str, filters: ProductFilters, limit: int) -> SemanticHits:
    """Rank products by meaning. Raises ChatError (never returns a fake empty result) when it can't run."""
    tag = current_model_tag()
    embedded = crud.count_embedded(db, tag)
    if embedded == 0:  # checked before calling AWS: there is nothing to search yet
        raise ChatError(503, "embeddings_not_initialized", NOT_INITIALIZED_MESSAGE)

    vector = TitanEmbedder(client, settings.embedding_model_id, settings.embedding_dim).embed(query)
    try:
        rows = crud.semantic_search(db, vector, tag, limit, filters)
    except DataError:  # e.g. the column still has another vector size
        logger.error("Semantic search query failed: vector size mismatch between EMBEDDING_DIM and the database column")
        raise ChatError(503, "embedding_dimension_mismatch", "Semantic search is misconfigured on the server.") from None
    return SemanticHits(rows=rows, embedded_products=embedded, model_tag=tag)
