"""CSV -> PostgreSQL import.

    python -m app.ingest                       # import data/laptops.csv
    python -m app.ingest --csv my.csv          # import another file
    python -m app.ingest --reset               # delete all products first

Idempotent: rows are upserted by SKU, so running it twice changes nothing.
Invalid or duplicate rows are reported and skipped; they never abort the import.
(Embeddings are intentionally not generated here - that is Module 2.)
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database import SessionLocal, init_db
from app.models import Product

logger = logging.getLogger(__name__)

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "laptops.csv"


class ProductRow(BaseModel):
    """One validated CSV row."""

    sku: str = Field(min_length=1, max_length=64)
    name: str
    brand: str
    price: float = Field(gt=0)
    cpu: str
    gpu: str
    ram_gb: int = Field(ge=1)
    storage_gb: int = Field(ge=1)
    storage_type: str = "SSD"
    display_size_in: float = Field(gt=0)
    display_resolution: str
    weight_kg: float = Field(gt=0)
    battery_hours: float | None = None
    os: str
    best_for: str = ""
    description: str
    source_name: str
    source_url: str | None = None
    is_mock: bool = True


def read_rows(path: Path) -> tuple[list[ProductRow], list[str]]:
    """Parse and validate a CSV. Returns (valid_rows, error_messages)."""
    rows: list[ProductRow] = []
    errors: list[str] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for line_no, raw in enumerate(csv.DictReader(fh), start=2):
            # Blank cells mean "not provided" so optional fields fall back to their defaults.
            cleaned = {k: v.strip() for k, v in raw.items() if isinstance(k, str) and isinstance(v, str) and v.strip()}
            try:
                row = ProductRow(**cleaned)
            except ValidationError as exc:
                fields = ", ".join(str(e["loc"][0]) for e in exc.errors())
                errors.append(f"line {line_no}: invalid field(s): {fields}")
                continue
            if row.sku in seen:
                errors.append(f"line {line_no}: duplicate sku {row.sku}")
                continue
            seen.add(row.sku)
            rows.append(row)
    return rows, errors


def row_hash(row: ProductRow) -> str:
    return hashlib.sha256(json.dumps(row.model_dump(), sort_keys=True).encode()).hexdigest()


@dataclass
class IngestStats:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[str] = field(default_factory=list)


def ingest(db: Session, csv_path: Path = DEFAULT_CSV, reset: bool = False) -> IngestStats:
    rows, errors = read_rows(csv_path)
    stats = IngestStats(errors=errors)

    if reset:
        db.execute(delete(Product))
        db.flush()

    existing = {p.sku: p for p in db.scalars(select(Product))}
    for row in rows:
        digest = row_hash(row)
        product = existing.get(row.sku)
        if product is None:
            db.add(Product(**row.model_dump(), content_hash=digest))
            stats.inserted += 1
        elif product.content_hash != digest:
            for key, value in row.model_dump().items():
                setattr(product, key, value)
            product.content_hash = digest
            stats.updated += 1
        else:
            stats.unchanged += 1

    db.commit()
    return stats


def needs_ingest(db: Session) -> bool:
    from app.crud import count_products

    return count_products(db) == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Import laptops from a CSV file.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--reset", action="store_true", help="delete all products before importing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_db()
    with SessionLocal() as db:
        stats = ingest(db, args.csv, reset=args.reset)
    logger.info("Import finished: inserted=%d updated=%d unchanged=%d skipped=%d",
                stats.inserted, stats.updated, stats.unchanged, len(stats.errors))
    for err in stats.errors:
        logger.warning("Skipped row - %s", err)


if __name__ == "__main__":
    main()
