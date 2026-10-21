from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.product_filters import MAX_PRICE, MAX_RAM_GB, MAX_TERMS, ProductFilters, split_terms
from app.schemas import ProductList, ProductOut

router = APIRouter(tags=["products"])


def _error(field: str, message: str, value: object) -> dict:
    # Same shape FastAPI/Pydantic use for built-in validation errors, so clients parse one format.
    return {"type": "value_error", "loc": ("query", field), "msg": message, "input": value}


@router.get("/products", response_model=ProductList)
def list_products(
    limit: int = Query(20, ge=1, le=100, description="Page size"),
    offset: int = Query(0, ge=0, description="Rows to skip"),
    q: str | None = Query(
        None,
        max_length=100,
        description="Keyword search over brand, model, CPU, GPU, OS, display, and use-case tags. "
        f"Every word must match (up to {MAX_TERMS} words).",
    ),
    min_price: float | None = Query(None, ge=0, le=MAX_PRICE, description="Minimum price in USD (inclusive)"),
    max_price: float | None = Query(None, ge=0, le=MAX_PRICE, description="Maximum price in USD (inclusive)"),
    min_ram_gb: int | None = Query(None, ge=1, le=MAX_RAM_GB, description="Minimum RAM in GB"),
    cpu: str | None = Query(
        None, max_length=50, description=f"CPU keywords, e.g. 'ryzen 7' or 'i5' (up to {MAX_TERMS} words)"
    ),
    db: Session = Depends(get_db),
) -> ProductList:
    """Paginated catalog listing, ordered by id. All filters are optional and combine with AND."""
    errors: list[dict] = []
    if min_price is not None and max_price is not None and min_price > max_price:
        errors.append(_error("min_price", "min_price must not be greater than max_price.", min_price))
    for name, value in (("q", q), ("cpu", cpu)):
        if len(split_terms(value)) > MAX_TERMS:
            errors.append(_error(name, f"{name} may contain at most {MAX_TERMS} words.", value))
    if errors:
        raise RequestValidationError(errors)

    filters = ProductFilters(
        q=(q or "").strip() or None,
        min_price=min_price,
        max_price=max_price,
        min_ram_gb=min_ram_gb,
        cpu=(cpu or "").strip() or None,
    )
    return ProductList(
        items=[ProductOut.model_validate(p) for p in crud.list_products(db, limit, offset, filters)],
        total=crud.count_products(db, filters),
        limit=limit,
        offset=offset,
    )
