"""Semantic product search (Module 3A). The keyword search at GET /products is unchanged.

Outcomes a client can tell apart:
* 422                            the request is invalid (nothing was searched, AWS was not called)
* 503 embeddings_not_initialized semantic search isn't set up yet (migration / `app.embed` not run)
* 200 with items == []           set up, but no embedded laptop passes the price/RAM filters (`message` says so)
* 200 with items                 ranked results
"""
import logging
import math
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import crud
from app import semantic_search as semantic_search_service
from app.ai.errors import ChatError, map_provider_error
from app.database import get_db
from app.product_filters import MAX_PRICE, MAX_RAM_GB, ProductFilters
from app.routers.chat import create_bedrock_client  # same region, timeouts and credential chain as /chat
from app.schemas import ProductOut

logger = logging.getLogger(__name__)
router = APIRouter(tags=["products"])

MAX_QUERY_CHARS = 200
MAX_RESULTS = 20
ALLOWED_PARAMS = frozenset({"q", "min_price", "max_price", "min_ram_gb", "limit"})
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

NO_RESULTS_MESSAGE = "No laptops with embeddings match these price and RAM filters. Relax a filter and try again."


class SemanticProduct(ProductOut):
    similarity: float  # 1 - cosine distance: 1.0 = same meaning; compare within one query, not across queries


class SemanticSearchResponse(BaseModel):
    query: str
    items: list[SemanticProduct]
    limit: int
    embedding_model: str
    embedded_products: int  # products searchable right now
    catalog_products: int  # all products; larger than embedded_products means `app.embed` should be re-run
    message: str | None = None  # set when items is empty


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _error(field: str, message: str, value: object) -> dict:
    # Same shape FastAPI/Pydantic use for built-in validation errors, so clients parse one format.
    return {"type": "value_error", "loc": ("query", field), "msg": message, "input": value}


@router.get("/products/semantic-search", response_model=SemanticSearchResponse)
def semantic_search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_CHARS, description="What you need, in plain words, e.g. 'quiet laptop for coding on trains'"),
    min_price: float | None = Query(None, ge=0, le=MAX_PRICE, description="Minimum price in USD (inclusive, exact SQL filter)"),
    max_price: float | None = Query(None, ge=0, le=MAX_PRICE, description="Maximum price in USD (inclusive, exact SQL filter)"),
    min_ram_gb: int | None = Query(None, ge=1, le=MAX_RAM_GB, description="Minimum RAM in GB (exact SQL filter)"),
    limit: int = Query(5, ge=1, le=MAX_RESULTS, description="Number of results"),
    db: Session = Depends(get_db),
) -> SemanticSearchResponse:
    """Products ranked by how well their specs and description match `q` in meaning (Titan V2 + pgvector).

    Price and RAM are exact SQL filters applied before ranking: a result never breaks them. Every product
    passing the filters is a candidate, so the closest matches are always returned; check `similarity`.
    """
    # Strict parameters: a typo such as `maxprice` would otherwise be ignored silently and drop a filter.
    errors = [_error(k, f"Unknown parameter '{k}'.", None) for k in sorted(set(request.query_params) - ALLOWED_PARAMS)]
    errors += [_error(k, f"'{k}' may be given only once.", None) for k in sorted(ALLOWED_PARAMS)
               if len(request.query_params.getlist(k)) > 1]  # fmt: skip
    query = " ".join(q.split())  # collapse whitespace
    if not query:
        errors.append(_error("q", "q must not be blank.", q))
    elif _CONTROL_CHARS.search(q.replace("\t", " ")):
        errors.append(_error("q", "q contains unsupported control characters.", None))
    for name, value in (("min_price", min_price), ("max_price", max_price)):
        if value is not None and not math.isfinite(value):
            errors.append(_error(name, f"{name} must be a finite number.", str(value)))
    if min_price is not None and max_price is not None and min_price > max_price:
        errors.append(_error("min_price", "min_price must not be greater than max_price.", min_price))
    if errors:
        raise RequestValidationError(errors)

    filters = ProductFilters(min_price=min_price, max_price=max_price, min_ram_gb=min_ram_gb)
    try:
        hits = semantic_search_service.search(db, create_bedrock_client(), query, filters, limit)
    except ChatError as exc:
        raise _http_error(exc.status_code, exc.code, exc.message) from None
    except Exception as exc:
        mapped = map_provider_error(exc)
        logger.warning("Query embedding failed: %s", mapped.code)
        raise _http_error(mapped.status_code, mapped.code, mapped.message) from None

    items = [
        SemanticProduct(**ProductOut.model_validate(p).model_dump(), similarity=round(1 - distance, 4)) for p, distance in hits.rows
    ]
    return SemanticSearchResponse(
        query=query, items=items, limit=limit, embedding_model=hits.model_tag, embedded_products=hits.embedded_products,
        catalog_products=crud.count_products(db), message=None if items else NO_RESULTS_MESSAGE,
    )  # fmt: skip
