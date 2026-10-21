"""Generate product embeddings (Module 3A).

    python -m app.embed              # embed products that are new or whose text changed
    python -m app.embed --dry-run    # show what would be embedded; no AWS calls, no writes
    python -m app.embed --force      # re-embed everything

In Docker: docker compose exec backend python -m app.embed

Requires the embedding column to have EMBEDDING_DIM dimensions; on a database created by Module 1 run
`python -m app.migrate_embedding_dim` once first (the command stops with a message otherwise).

Idempotent: a product is skipped when its stored embedding_text and embedding_model already match,
so a second run makes no Bedrock calls. Each product is committed on its own, so an interrupted
run keeps its progress and the next run continues where it stopped.
Not run on startup on purpose: the app must boot (and keyword search must work) without AWS.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import TitanEmbedder, build_embedding_text
from app.models import Product

logger = logging.getLogger(__name__)


@dataclass
class EmbedStats:
    embedded: int = 0
    unchanged: int = 0
    would_embed: int = 0  # --dry-run only


def embed_products(db: Session, embedder: TitanEmbedder, *, force: bool = False, dry_run: bool = False) -> EmbedStats:
    stats = EmbedStats()
    for product in db.scalars(select(Product).order_by(Product.id)):
        text = build_embedding_text(product)
        current = (
            product.embedding is not None and product.embedding_text == text and product.embedding_model == embedder.tag
        )
        if current and not force:
            stats.unchanged += 1
            continue
        if dry_run:
            stats.would_embed += 1
            logger.info("Would embed id=%d: %s", product.id, text)
            continue
        product.embedding = embedder.embed(text)  # raises ChatError on AWS problems; earlier commits are kept
        product.embedding_text = text
        product.embedding_model = embedder.tag
        db.commit()
        stats.embedded += 1
    return stats


def main() -> None:
    from app.ai.errors import ChatError
    from app.config import settings
    from app.database import SessionLocal, engine, init_db
    from app.migrate_embedding_dim import embedding_column_type
    from app.routers.chat import create_bedrock_client  # same region, timeouts and credential chain as /chat

    parser = argparse.ArgumentParser(description="Generate Titan embeddings for the product catalog.")
    parser.add_argument("--force", action="store_true", help="re-embed every product")
    parser.add_argument("--dry-run", action="store_true", help="print the texts; no AWS calls, no writes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    init_db()
    with engine.connect() as conn:
        column = embedding_column_type(conn)
    if column != f"vector({settings.embedding_dim})" and not args.dry_run:
        # Checked before any AWS call: vectors could not be stored anyway.
        logger.error("products.embedding is %s but EMBEDDING_DIM=%d. Run `python -m app.migrate_embedding_dim` first.",
                     column, settings.embedding_dim)  # fmt: skip
        raise SystemExit(1)
    embedder = TitanEmbedder(create_bedrock_client(), settings.embedding_model_id, settings.embedding_dim)
    with SessionLocal() as db:
        try:
            stats = embed_products(db, embedder, force=args.force, dry_run=args.dry_run)
        except ChatError as exc:
            logger.error("Embedding stopped (%s): %s Re-run to continue.", exc.code, exc.message)
            raise SystemExit(1) from None
    logger.info("Embedding finished with %s: embedded=%d unchanged=%d%s", embedder.tag, stats.embedded, stats.unchanged,
                f" would_embed={stats.would_embed}" if args.dry_run else "")  # fmt: skip


if __name__ == "__main__":
    main()
