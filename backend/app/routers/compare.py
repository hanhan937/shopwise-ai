"""AI comparison API (Module 2C-2). Specs always come from PostgreSQL, never from the request."""
import logging
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy.orm import Session

from app import crud
from app.ai.compare import ComparisonAnalyzer
from app.ai.errors import ChatError, map_provider_error
from app.ai.tools import DATA_NOTICE, format_product
from app.config import settings
from app.database import get_db
from app.routers.chat import create_bedrock_client  # same region, timeouts and credential chain as /chat

logger = logging.getLogger(__name__)
router = APIRouter(tags=["compare"])

ProductId = Annotated[StrictInt, Field(ge=1, le=2_147_483_647)]


class CompareRequest(BaseModel):
    # extra="forbid": the client sends ids only; any attempt to send specs is rejected, not ignored.
    model_config = ConfigDict(extra="forbid")

    product_ids: list[ProductId] = Field(min_length=2, max_length=3)
    use_case: Literal["general", "programming", "student", "gaming", "travel"] = "general"

    @field_validator("product_ids")
    @classmethod
    def _unique(cls, ids: list[int]) -> list[int]:
        if len(set(ids)) != len(ids):
            raise ValueError("product_ids must not contain duplicates")
        return ids


class CompareResponse(BaseModel):
    product_ids: list[int]
    use_case: str
    summary: str
    best_for_budget: int | None
    best_for_performance: int | None
    recommended_product_id: int | None
    recommendation_reason: str
    tradeoffs: list[str]
    assumptions: list[str]
    missing_data: list[str]
    warnings: list[str]
    data_notice: str


@router.post("/compare/analyze", response_model=CompareResponse)
def analyze_comparison(payload: CompareRequest, db: Session = Depends(get_db)):
    rows = crud.get_products_by_ids(db, payload.product_ids)
    missing = sorted(set(payload.product_ids) - {r.id for r in rows})
    if missing:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "products_not_found",
                "message": "One or more selected laptops no longer exist in the catalog. Refresh and select again.",
                "missing_ids": missing,
            },
        )

    products = [format_product(r) for r in rows]
    try:
        analyzer = ComparisonAnalyzer(client=create_bedrock_client(), model_id=settings.bedrock_model_id)
        result = analyzer.analyze(products, payload.use_case)
    except ChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    except Exception as exc:
        mapped = map_provider_error(exc)
        logger.warning("Comparison failed: %s", mapped.code)
        raise HTTPException(status_code=mapped.status_code, detail={"code": mapped.code, "message": mapped.message}) from None

    return CompareResponse(product_ids=payload.product_ids, use_case=payload.use_case, data_notice=DATA_NOTICE, **asdict(result))
