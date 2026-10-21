"""Search and filter conditions for the product catalog (Module 2A).

Everything here compiles to SQL ``WHERE`` clauses, so filtering, counting and
pagination all run inside PostgreSQL; the catalog is never loaded into memory.

Semantics
---------
* Keyword search (``q``): the text is split on whitespace. EVERY word must match
  (AND), and a word matches if it appears (case-insensitively, as a substring) in
  ANY of SEARCH_COLUMNS (OR). "lenovo ryzen" therefore means Lenovo laptops with a
  Ryzen CPU, and "i7" also matches "Core i7-1355U".
* ``cpu``: same word logic, but only against the CPU column.
* Price bounds are inclusive. ``min_ram_gb`` means "at least this much RAM".
* All filters combine with AND.
* LIKE wildcards typed by the user (% and _) are escaped, so they match literally.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, or_

from app.models import Product

MAX_TERMS = 8  # words per text field; keeps query size bounded
MAX_PRICE = 1_000_000
MAX_RAM_GB = 1024

# Brand, model, and the specifications a shopper would type. Free-text prose
# (`description`) is deliberately left out: it is marketing copy and adds noise.
SEARCH_COLUMNS = (
    Product.brand,
    Product.name,
    Product.cpu,
    Product.gpu,
    Product.os,
    Product.storage_type,
    Product.display_resolution,
    Product.best_for,  # use-case tags such as "programming;travel"
)


@dataclass(frozen=True)
class ProductFilters:
    q: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_ram_gb: int | None = None
    cpu: str | None = None

    def is_active(self) -> bool:
        return any(v is not None for v in (self.q, self.min_price, self.max_price, self.min_ram_gb, self.cpu))


def split_terms(text: str | None) -> list[str]:
    """Whitespace-separated words; None/blank -> []."""
    return text.split() if text else []


def escape_like(term: str) -> str:
    """Make ``%``, ``_`` and ``\\`` literal inside a LIKE pattern (escape char is backslash)."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _word_matches(term: str, columns: tuple) -> ColumnElement[bool]:
    pattern = f"%{escape_like(term)}%"
    return or_(*(col.ilike(pattern, escape="\\") for col in columns))


def build_conditions(filters: ProductFilters) -> list[ColumnElement[bool]]:
    """SQLAlchemy conditions to AND together (empty list when no filter is set)."""
    conditions: list[ColumnElement[bool]] = []
    conditions += [_word_matches(t, SEARCH_COLUMNS) for t in split_terms(filters.q)]
    conditions += [_word_matches(t, (Product.cpu,)) for t in split_terms(filters.cpu)]
    if filters.min_price is not None:
        conditions.append(Product.price >= filters.min_price)
    if filters.max_price is not None:
        conditions.append(Product.price <= filters.max_price)
    if filters.min_ram_gb is not None:
        conditions.append(Product.ram_gb >= filters.min_ram_gb)
    return conditions
