"""Database queries (kept separate from routers so they are easy to stub in tests)."""
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models import Product
from app.product_filters import ProductFilters, build_conditions


def count_products(db: Session, filters: ProductFilters | None = None) -> int:
    """Number of products matching `filters` (all products when omitted)."""
    stmt = select(func.count()).select_from(Product)
    if filters is not None:
        stmt = stmt.where(*build_conditions(filters))
    return int(db.scalar(stmt) or 0)


def list_products(db: Session, limit: int, offset: int, filters: ProductFilters | None = None) -> list[Product]:
    """One page of products matching `filters`, ordered by id (stable pagination)."""
    stmt = select(Product)
    if filters is not None:
        stmt = stmt.where(*build_conditions(filters))
    return list(db.scalars(stmt.order_by(Product.id).limit(limit).offset(offset)))


def get_products_by_ids(db: Session, ids: list[int]) -> list[Product]:
    """Products with the given ids, in the order requested; ids that don't exist are simply absent."""
    found = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(ids)))}
    return [found[i] for i in ids if i in found]


def count_embedded(db: Session, model_tag: str) -> int:
    """Products that have an embedding made by `model_tag` (vectors from other models aren't comparable)."""
    stmt = select(func.count()).select_from(Product).where(Product.embedding.is_not(None), Product.embedding_model == model_tag)
    return int(db.scalar(stmt) or 0)


def semantic_search(
    db: Session, query_vector: list[float], model_tag: str, limit: int, filters: ProductFilters | None = None
) -> list[tuple[Product, float]]:
    """Hybrid search: exact SQL filters (price, RAM) first, then rank by cosine distance (pgvector `<=>`).

    Returns (product, distance) pairs, nearest first; distance is 0 for identical meaning, up to 2.
    Ties are broken by id so results are stable.
    """
    distance = Product.embedding.cosine_distance(query_vector).label("distance")
    stmt = select(Product, distance).where(Product.embedding.is_not(None), Product.embedding_model == model_tag)
    if filters is not None:
        stmt = stmt.where(*build_conditions(filters))
    return [(p, float(d)) for p, d in db.execute(stmt.order_by(distance, Product.id).limit(limit))]


def ping(db: Session) -> None:
    db.execute(text("SELECT 1"))


def pgvector_installed(db: Session) -> bool:
    return bool(db.scalar(text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")))
