"""One-time migration: resize products.embedding to EMBEDDING_DIM (Module 1 created vector(1536)).

    python -m app.migrate_embedding_dim --check   # report what would happen; changes nothing
    python -m app.migrate_embedding_dim           # apply

In Docker: docker compose exec backend python -m app.migrate_embedding_dim

Safe to run any number of times:
* already the right size  -> nothing to do (exit 0)
* any embedding is stored -> STOP without changes (exit 1): vectors of another size can't be converted
* all embeddings are NULL -> ALTER COLUMN ... TYPE vector(N) (exit 0); no row data is touched

The check and the ALTER run in ONE transaction that first takes an exclusive lock on the table, so no
embedding can be written between "all NULL" and the ALTER. Never run automatically; never drops anything.
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.ai.embeddings import SUPPORTED_DIMENSIONS

logger = logging.getLogger(__name__)

COLUMN_TYPE_SQL = text(
    "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
    "WHERE attrelid = to_regclass('products') AND attname = 'embedding' AND NOT attisdropped"
)


def embedding_column_type(conn: Connection) -> str | None:
    """e.g. 'vector(1536)'; None when the products table or the column does not exist."""
    return conn.scalar(COLUMN_TYPE_SQL)


@dataclass(frozen=True)
class MigrationResult:
    status: str  # "already_done" | "would_migrate" | "migrated" | "blocked" | "missing"
    before: str | None
    after: str | None
    stored_vectors: int = 0


def decide(current: str | None, stored_vectors: int, target_dim: int) -> str:
    """Pure decision rule (unit-tested): what to do given the current column type and stored vectors."""
    if current is None:
        return "missing"
    if current == f"vector({target_dim})":
        return "already_done"
    if stored_vectors > 0:
        return "blocked"
    return "migrate"


def migrate(engine: Engine, target_dim: int, *, check_only: bool = False) -> MigrationResult:
    if target_dim not in SUPPORTED_DIMENSIONS:
        raise ValueError(f"EMBEDDING_DIM must be one of {SUPPORTED_DIMENSIONS}, not {target_dim}")

    with engine.begin() as conn:  # one transaction: rolled back on any error
        current = embedding_column_type(conn)
        if current is None:
            return MigrationResult("missing", None, None)
        if not check_only:
            conn.execute(text("LOCK TABLE products IN ACCESS EXCLUSIVE MODE"))  # released at commit/rollback
            current = embedding_column_type(conn)
        stored = int(conn.scalar(text("SELECT count(*) FROM products WHERE embedding IS NOT NULL")) or 0)

        action = decide(current, stored, target_dim)
        if action != "migrate":
            return MigrationResult(action, current, current, stored)
        if check_only:
            return MigrationResult("would_migrate", current, f"vector({target_dim})", stored)
        conn.execute(text(f"ALTER TABLE products ALTER COLUMN embedding TYPE vector({int(target_dim)})"))
        return MigrationResult("migrated", current, embedding_column_type(conn), stored)


MESSAGES = {
    "already_done": "products.embedding is already {after}. Nothing to do.",
    "would_migrate": "products.embedding is {before} and all embeddings are NULL: it can be resized to {after}. "
    "Run without --check to apply.",
    "migrated": "Resized products.embedding from {before} to {after}. No row data was changed.",
    "blocked": "STOPPED: products.embedding is {before} and {stored_vectors} embedding(s) are stored. Nothing was "
    "changed. Vectors of another size can't be converted; to start over, clear them first "
    "(UPDATE products SET embedding = NULL, embedding_text = NULL, embedding_model = NULL), then re-run.",
    "missing": "STOPPED: the products table or its embedding column does not exist. Start the backend once "
    "(it creates the schema), then re-run.",
}


def main() -> None:
    from app.config import settings
    from app.database import engine

    parser = argparse.ArgumentParser(description="Resize products.embedding to EMBEDDING_DIM (only while it is empty).")
    parser.add_argument("--check", action="store_true", help="report only; change nothing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    result = migrate(engine, settings.embedding_dim, check_only=args.check)
    message = MESSAGES[result.status].format(**vars(result))
    if result.status in ("blocked", "missing"):
        logger.error(message)
        sys.exit(1)
    logger.info(message)


if __name__ == "__main__":
    main()
