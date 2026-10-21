import logging

from fastapi import APIRouter, Depends, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health(response: Response, db: Session = Depends(get_db)) -> HealthResponse:
    """Liveness + dependency check. Returns 503 when the database or pgvector is unavailable."""
    try:
        crud.ping(db)
        has_vector = crud.pgvector_installed(db)
        total = crud.count_products(db)
    except SQLAlchemyError:
        logger.exception("Health check could not query the database")
        response.status_code = 503
        return HealthResponse(status="degraded", database=False, pgvector=False, products_total=0)

    if not has_vector:
        response.status_code = 503
    return HealthResponse(
        status="ok" if has_vector else "degraded",
        database=True,
        pgvector=has_vector,
        products_total=total,
    )
