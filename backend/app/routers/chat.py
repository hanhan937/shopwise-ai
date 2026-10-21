"""Bedrock chat API; independent of catalog availability and startup."""
import logging

import boto3
from botocore.config import Config
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import crud
from app import semantic_search as semantic_search_service
from app.ai.agent import ShoppingAgent
from app.ai.errors import ChatError, map_provider_error
from app.ai.tools import SearchArgs, SemanticArgs
from app.config import settings
from app.database import get_db
from app.product_filters import ProductFilters

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str
    products: list[dict]
    tools_used: list[str]


def create_bedrock_client():
    # Boto3's normal credential chain supports AWS profiles/roles and temporary credentials.
    return boto3.client(
        "bedrock-runtime",
        region_name=settings.aws_region,
        config=Config(connect_timeout=5, read_timeout=35, retries={"max_attempts": 2, "mode": "standard"}),
    )


def search_database(db: Session, args: SearchArgs):
    filters = ProductFilters(q=args.query, min_price=args.min_price, max_price=args.max_price, min_ram_gb=args.min_ram_gb)
    return crud.list_products(db, args.limit, 0, filters), crud.count_products(db, filters)


def semantic_database(db: Session, client, args: SemanticArgs):
    """semantic_search_products: same service as GET /products/semantic-search (Titan + pgvector + SQL filters)."""
    filters = ProductFilters(max_price=args.max_price, min_ram_gb=args.min_ram_gb)
    return semantic_search_service.search(db, client, args.query, filters, args.limit).rows


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="Message must not be blank")
    try:
        client = create_bedrock_client()
        agent = ShoppingAgent(client=client, model_id=settings.bedrock_model_id,
                              search_fn=lambda args: search_database(db, args),
                              semantic_fn=lambda args: semantic_database(db, client, args))  # same client for Titan
        result = agent.run(payload.message)
        return ChatResponse(reply=result.reply, products=result.products, tools_used=result.tools_used)
    except ChatError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from None
    except Exception as exc:
        mapped = map_provider_error(exc)
        logger.warning("Chat failed: %s", mapped.code)
        raise HTTPException(status_code=mapped.status_code, detail={"code": mapped.code, "message": mapped.message}) from None
