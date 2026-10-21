"""FastAPI application entrypoint (Module 1: health + product catalog)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import SessionLocal, init_db
from app.routers import chat, compare, health, products

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("shopwise")


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        init_db()
        if settings.auto_ingest:
            from app.ingest import DEFAULT_CSV, ingest, needs_ingest

            with SessionLocal() as db:
                if needs_ingest(db):
                    logger.info("Products table is empty - importing %s", DEFAULT_CSV)
                    logger.info("Import result: %s", ingest(db, DEFAULT_CSV))
    except Exception:  # noqa: BLE001 - stay up so /health can report what is wrong
        logger.exception("Startup initialisation failed; /health will report the problem")
    yield


app = FastAPI(
    title="ShopWise AI",
    description="Laptop research assistant. Module 1: product database, health check, catalog API. "
    "All product data is MOCK data for development.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.exception_handler(OperationalError)
async def database_unavailable(_: Request, exc: OperationalError) -> JSONResponse:
    logger.error("Database unavailable: %s", exc.__class__.__name__)
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": "database_unavailable", "message": "The database is not reachable right now."}},
    )


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "Something went wrong on the server."}},
    )


app.include_router(health.router)
app.include_router(products.router)
app.include_router(chat.router)
app.include_router(compare.router)
