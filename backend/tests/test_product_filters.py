"""Unit tests for the SQL that search/filtering generates (no database needed).

Statements are compiled with the PostgreSQL dialect and inspected, which proves the
filtering happens in SQL (WHERE ... ILIKE / >= / <=) rather than in Python.
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import Product
from app.product_filters import (
    SEARCH_COLUMNS,
    ProductFilters,
    build_conditions,
    escape_like,
    split_terms,
)


def compile_where(filters: ProductFilters):
    stmt = select(Product.id).where(*build_conditions(filters))
    compiled = stmt.compile(dialect=postgresql.dialect())
    return str(compiled), list(compiled.params.values())


# --------------------------------------------------------------- pure helpers
def test_split_terms_handles_blank_and_extra_whitespace():
    assert split_terms("  dell   ryzen ") == ["dell", "ryzen"]
    assert split_terms("") == [] and split_terms("   ") == [] and split_terms(None) == []


def test_escape_like_makes_wildcards_literal():
    assert escape_like("100%") == "100\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("back\\slash") == "back\\\\slash"


def test_is_active():
    assert not ProductFilters().is_active()
    assert ProductFilters(min_ram_gb=16).is_active()
    assert ProductFilters(min_price=0).is_active()  # 0 is a real value, not "unset"


# ------------------------------------------------------------ generated SQL
def test_no_filters_means_no_where_clause():
    assert build_conditions(ProductFilters()) == []
    sql, params = compile_where(ProductFilters())
    assert "WHERE" not in sql and params == []


def test_price_and_ram_filters_are_inclusive_comparisons():
    sql, params = compile_where(ProductFilters(min_price=500, max_price=1000, min_ram_gb=16))
    assert "products.price >=" in sql and "products.price <=" in sql and "products.ram_gb >=" in sql
    assert sorted(params) == [16, 500, 1000]


def test_keyword_search_ors_columns_per_word_and_ands_words():
    sql, params = compile_where(ProductFilters(q="dell ryzen"))
    assert sql.count("ILIKE") == 2 * len(SEARCH_COLUMNS)
    assert sql.count(" OR ") == 2 * (len(SEARCH_COLUMNS) - 1)
    assert "AND" in sql  # the two words are ANDed
    assert params.count("%dell%") == len(SEARCH_COLUMNS) and params.count("%ryzen%") == len(SEARCH_COLUMNS)


def test_search_covers_brand_model_and_specs_but_not_description():
    sql, _ = compile_where(ProductFilters(q="x"))
    for column in ("brand", "name", "cpu", "gpu", "os", "storage_type", "display_resolution", "best_for"):
        assert f"products.{column} ILIKE" in sql
    assert "products.description" not in sql


def test_cpu_filter_only_touches_the_cpu_column():
    sql, params = compile_where(ProductFilters(cpu="i7"))
    assert sql.count("ILIKE") == 1 and "products.cpu ILIKE" in sql
    assert params == ["%i7%"]


def test_all_filters_combine():
    sql, params = compile_where(
        ProductFilters(q="lenovo", min_price=400, max_price=900, min_ram_gb=16, cpu="ryzen 7")
    )
    assert sql.count("ILIKE") == len(SEARCH_COLUMNS) + 2  # 'lenovo' on every column + 'ryzen' and '7' on cpu
    assert "products.price >=" in sql and "products.price <=" in sql and "products.ram_gb >=" in sql
    assert "%lenovo%" in params and "%ryzen%" in params and "%7%" in params


def test_user_typed_wildcards_are_escaped_in_the_pattern():
    _, params = compile_where(ProductFilters(q="100%"))
    assert set(params) == {"%100\\%%"}
    assert "ESCAPE" in compile_where(ProductFilters(q="a"))[0]


def test_values_are_bound_parameters_never_inlined():
    sql, _ = compile_where(ProductFilters(q="x'; DROP TABLE products; --"))
    assert "DROP TABLE" not in sql
