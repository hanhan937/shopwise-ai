"""Database models."""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.database import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand: Mapped[str] = mapped_column(String(80), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    cpu: Mapped[str] = mapped_column(String(120), nullable=False)
    gpu: Mapped[str] = mapped_column(String(120), nullable=False)
    ram_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="SSD")
    display_size_in: Mapped[float] = mapped_column(Float, nullable=False)
    display_resolution: Mapped[str] = mapped_column(String(60), nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    battery_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    os: Mapped[str] = mapped_column(String(60), nullable=False)

    # Semicolon-separated tags, e.g. "programming;travel;students"
    best_for: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Provenance shown in the UI as the "source reference".
    source_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_mock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Change detection for idempotent CSV imports (Module 1).
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Reserved for Module 2 (semantic search). Nullable and unused for now; they are
    # created up front so Module 2 does not need a schema migration.
    embedding_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # B-tree indexes for the filters added in Module 2.
        Index("ix_products_price", "price"),
        Index("ix_products_brand", "brand"),
        Index("ix_products_ram_gb", "ram_gb"),
        Index("ix_products_storage_gb", "storage_gb"),
    )
